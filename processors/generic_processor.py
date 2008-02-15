# Copyright (C) 2008 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Import processor that supports all Bazaar repository formats."""


from bzrlib import (
    errors,
    generate_ids,
    inventory,
    lru_cache,
    osutils,
    revision,
    revisiontree,
    )
from bzrlib.trace import (
    note,
    warning,
    )
from bzrlib.plugins.fastimport import (
    processor,
    revisionloader,
    )


class GenericProcessor(processor.ImportProcessor):
    """An import processor that handles basic imports.

    Current features supported:

    * timestamped progress reporting
    * blobs are cached in memory until used
    * TODO: commit handling
    * LATER: branch support
    * checkpoints and tags are ignored
    * some basic statistics are dumped on completion.
    """

    def pre_process(self):
        # Statistics
        self._revision_count = 0
        self._branch_count = 0
        self._tag_count = 0

        # dataref -> data. datref is either :mark or the sha-1.
        # Once a blob is used, it should be deleted from here.
        self.blob_cache = {}

    def post_process(self):
        # Dump statistics
        note("Imported %d revisions into %d branches with %d tags.",
            self._revision_count, self._branch_count, self._tag_count)
        #note("%d files, %d directories, %d symlinks.",
        #    self._file_count, self._dir_count, self._symlink_count)

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        if cmd.mark is not None:
            dataref = ":%s" % (cmd.mark,)
        else:
            dataref = osutils.sha_strings(cmd.data)
        self.blob_cache[dataref] = cmd.data

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        warning("ignoring checkpoint")

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        handler = GenericCommitHandler(cmd, self.target, self.blob_cache)
        handler.process()
        self._revision_count += 1

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        note("%s progress %s" % (self._time_of_day(), cmd.message))

    def _time_of_day(self):
        """Time of day as a string."""
        # Note: this is a separate method so tests can patch in a fixed value
        return datetime.datetime.now().strftime("%H:%M:%s")

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        warning("multiple branches are not supported yet"
            " - ignoring branch '%s'", cmd.ref)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        warning("tags are not supported yet - ignoring tag '%s'", cmd.id)


class GenericCommitHandler(processor.CommitHandler):

    def __init__(self, command, repo, blob_cache, inventory_cache_size=100):
        processor.CommitHandler.__init__(self, command)
        self.repo = repo
        # cache of blobs until they are referenced
        self.blob_cache = blob_cache
        # revision-id -> Inventory cache
        self.inventory_cache = lru_cache.LRUCache(inventory_cache_size)
        # smart loader that uses this cache
        self.loader = revisionloader.RevisionLoader(repo,
            lambda revision_ids: self._get_inventories(revision_ids))
        # directory-path -> inventory-entry lookup table
        self._directory_entries = {}
        # import-ref to revision-id lookup table
        self.revision_id_by_import_ref = {}

    def pre_process_files(self):
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        self.inv_delta = []
        # cache of texts for this commit, indexed by file-id
        self.text_for_commit = {}

    def post_process_files(self):
        """Save the revision."""
        rev = revision.Revision(self.revision_id)
        committer = self.command.committer
        rev.committer = "%s <%s>" % (committer[0],committer[1])
        rev.timestamp = committer[2]
        rev.timezone = committer[3]
        print "loading revision %r" % (rev,)

        # Derive the inventory from the previous one
        parents = self.command.parents
        if len(parents) == 0:
            new_inventory = inventory.Inventory()
        else:
            # use the bzr_revision_id to lookup the inv cache
            parent_id = self.revision_id_by_import_ref[parents[0]]
            new_inventory = self.get_inventory(parent_id).copy()
        new_inventory.apply_delta(self.inv_delta)
        self.revision_id_by_import_ref[self.command.ref] = new_inventory

        # debug trace ...
        print "applied inventory delta ..."
        for entry in self.inv_delta:
            print "  %r" % (entry,)
        print "creating inventory ..."
        for entry in new_inventory:
            print "  %r" % (entry,)

        ## Uncomment once the rest is working
        # self.loader.load(revision, new_inventory, None,
        #     lambda file_id: self._get_text(file_id))

    def modify_handler(self, filecmd):
        if filecmd.dataref is not None:
            data = self.blob_cache[filecmd.dataref]
            # Conserve memory, assuming blobs aren't referenced twice
            del self.blob_cache[filecmd.dataref]
        else:
            data = filecmd.data
        self._modify_inventory(filecmd.path, filecmd.kind,
            filecmd.is_executable, data)

    def delete_handler(self, filecmd):
        path = filecmd.path
        self.inv_delta.append((path, None, self.bzr_file_id(path), None))

    def copy_handler(self, filecmd):
        raise NotImplementedError(self.copy_handler)

    def rename_handler(self, filecmd):
        # TODO: add a suitable entry to the inventory delta
        raise NotImplementedError(self.rename_handler)

    def deleteall_handler(self, filecmd):
        raise NotImplementedError(self.deleteall_handler)

    def bzr_file_id(self, path):
        """Generate a Bazaar file identifier for a path."""
        # TODO: Search the current inventory instead of generating every time
        return generate_ids.gen_file_id(path)

    def gen_revision_id(self):
        """Generate a revision id.

        Subclasses may override this to produce deterministic ids say.
        """
        committer = self.command.committer
        who = "%s <%s>" % (committer[0],committer[1])
        timestamp = committer[2]
        return generate_ids.gen_revision_id(who, timestamp)

    def _get_inventories(self, revision_ids):
        """Get the inventories for revision-ids.
        
        This is a callback used by the RepositoryLoader to
        speed up inventory reconstruction."""
        present = []
        inventories = []
        # If an inventoy is in the cache, we assume it was
        # successfully loaded into the repsoitory
        for revision_id in revision_ids:
            try:
                inv = self.inventory_cache[revision_id]
                present.append(revision_id)
            except KeyError:
                # TODO: count misses and/or inform the user about the miss?
                # Not cached so reconstruct from repository
                if self.repo.has_revision(revision_id):
                    rev_tree = self.repo.revision_tree(revision_id)
                    present.append(revision_id)
                else:
                    rev_tree = self.repo.revision_tree(None)
                inv = rev_tree.inventory
                self.inventory_cache[revision_id] = inv
        inventories.append(inv)
        return present, inventories

    def _get_text(self, file_id):
        """Get the text for a file-id."""
        return self.text_for_commit[file_id]

    def _modify_inventory(self, path, kind, is_executable, data):
        """Add to or change an item in the inventory."""
        # Create the new InventoryEntry
        basename, parent_ie = self._ensure_directory(path)
        file_id = self.bzr_file_id(path)
        ie = inventory.make_entry(kind, basename, parent_ie, file_id)
        if isinstance(ie, inventory.InventoryFile):
            ie.text_sha1 = osutils.sha_strings(data)
            ie.text_size = len(data)
            ie.executable = is_executable
            self.text_for_commit[file_id] = data
        elif isinstance(ie, inventory.InventoryLnk):
            ie.symlink_target = data
        else:
            raise errors.BzrError("Cannot import items of kind '%s' yet" %
                (kind,))

        # Record this new inventory entry. As the import stream doesn't
        # repeat all files every time, we build an entry delta.
        # HACK: We also assume that inventory.apply_delta handles the
        # 'add' case cleanly when asked to change a non-existent entry.
        # This saves time vs explicitly detecting add vs change.
        old_path = path
        self.inv_delta.append((old_path, path, file_id, ie))

    def _ensure_directory(self, path):
        """Ensure that the containing directory exists for 'path'"""
        dirname, basename = osutils.split(path)
        if dirname == '':
            # the root node doesn't get updated
            return basename, inventory.ROOT_ID
        try:
            ie = self._directory_entries[dirname]
        except KeyError:
            # We will create this entry, since it doesn't exist
            pass
        else:
            return basename, ie

        # No directory existed, we will just create one, first, make sure
        # the parent exists
        dir_basename, parent_ie = self._ensure_directory(dirname)
        dir_file_id = self.bzr_file_id(dirname)
        ie = inventory.entry_factory['directory'](dir_file_id,
                                                  dir_basename,
                                                  parent_ie.file_id)
        ie.revision = self.revision_id
        self._directory_entries[dirname] = ie
        self.inv_delta.append((None, path, dir_file_id, ie))
        return basename, ie
