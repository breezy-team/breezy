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


import time
from bzrlib import (
    delta,
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


def _single_plural(n, single, plural):
    """Return a single or plural form of a noun based on number."""
    if n == 1:
        return single
    else:
        return plural


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
        self.cache_mgr = GenericCacheManager()
        self.active_branch = self.branch
        self.init_stats()
        # mapping of tag name to revision_id
        self.tags = {}

    def post_process(self):
        self.dump_stats()
        # Update the branches, assuming the last revision is the head
        note("Updating branch information ...")
        # TODO - loop over the branches created/modified
        last_rev_id = self.cache_mgr.last_revision_ids[self.branch]
        revno = len(list(self.repo.iter_reverse_revision_history(last_rev_id)))
        self.branch.set_last_revision_info(revno, last_rev_id)
        if self.tags:
            self.branch.tags._set_tag_dict(self.tags)
        # Update the working tree, if any
        if self.working_tree:
            self.working_tree.update(delta._ChangeReporter())

    def init_stats(self):
        self._revision_count = 0
        self._branch_count = 1
        self._tag_count = 0

    def dump_stats(self):
        rc = self._revision_count
        bc = self._branch_count
        tc = self._tag_count
        note("Imported %d %s into %d %s with %d %s.",
            rc, _single_plural(rc, "revision", "revisions"),
            bc, _single_plural(bc, "branch", "branches"),
            tc, _single_plural(tc, "tag", "tags"))

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        if cmd.mark is not None:
            dataref = ":%s" % (cmd.mark,)
        else:
            dataref = osutils.sha_strings(cmd.data)
        self.cache_mgr.blobs[dataref] = cmd.data

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        warning("ignoring checkpoint")

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        handler = GenericCommitHandler(cmd, self.repo, self.cache_mgr,
            self.active_branch, self.verbose)
        # For now, put a write group around every commit. In the future,
        # we might only start/commit one every N to sppeed things up
        self.repo.start_write_group()
        try:
            handler.process()
            self.cache_mgr.revision_ids[cmd.ref] = handler.revision_id
            self.cache_mgr.last_revision_ids[self.active_branch] = \
                handler.revision_id
            self._revision_count += 1
        except:
            self.repo.abort_write_group()
            raise
        else:
            self.repo.commit_write_group()

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        # We could use a progress bar here but timestamped messages
        # is more useful for determining when things might complete
        note("%s progress %s" % (self._time_of_day(), cmd.message))

    def _time_of_day(self):
        """Time of day as a string."""
        # Note: this is a separate method so tests can patch in a fixed value
        return time.localtime().strftime("%H:%M:%s")

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        if cmd.ref.startswith('refs/tags/'):
            self._set_tag(cmd.ref[len('refs/tags/'):], cmd.from_)
        else:
            warning("multiple branches are not supported yet"
                " - ignoring branch '%s'", cmd.ref)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        self._set_tag(cmd.id, cmd.from_)

    def _set_tag(self, name, from_):
        """Define a tag given a name an import 'from' reference."""
        bzr_tag_name = name.decode('utf-8', 'replace')
        bzr_rev_id = self.cache_mgr.revision_ids[from_]
        self.tags[bzr_tag_name] = bzr_rev_id
        self._tag_count += 1


class GenericCacheManager(object):
    """A manager of caches for the GenericProcessor."""

    def __init__(self, inventory_cache_size=100):
        # dataref -> data. datref is either :mark or the sha-1.
        # Once a blob is used, it should be deleted from here.
        self.blobs = {}

        # revision-id -> Inventory cache
        # these are large and we probably don't need too many as
        # most parents are recent in history
        self.inventories = lru_cache.LRUCache(inventory_cache_size)

        # directory-path -> inventory-entry lookup table
        # we need to keep all of these but they are small
        self.directory_entries = {}

        # import-ref -> revision-id lookup table
        # we need to keep all of these but they are small
        self.revision_ids = {}

        # branch -> last revision-id lookup table
        self.last_revision_ids = {}

        # path -> file-ids
        self.file_ids = {}

class GenericCommitHandler(processor.CommitHandler):

    def __init__(self, command, repo, cache_mgr, active_branch, verbose=False):
        processor.CommitHandler.__init__(self, command)
        self.repo = repo
        self.cache_mgr = cache_mgr
        self.active_branch = active_branch
        self.verbose = verbose
        # smart loader that uses these caches
        self.loader = revisionloader.RevisionLoader(repo,
            lambda revision_ids: self._get_inventories(revision_ids))

    def pre_process_files(self):
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        self.inv_delta = []
        # cache of texts for this commit, indexed by file-id
        self.lines_for_commit = {}

        # Get the parent inventories
        if self.command.parents:
            self.parents = [self.cache_mgr.revision_ids[ref]
                for ref in self.command.parents]
        else:
            # if no parents are given, the last revision on
            # the current branch is assumed according to the spec
            last_rev = self.cache_mgr.last_revision_ids.get(
                    self.active_branch)
            if last_rev:
                self.parents = [last_rev]
            else:
                self.parents = []

        # Seed the inventory from the previous one
        if len(self.parents) == 0:
            self.inventory = self.gen_initial_inventory()
        else:
            # use the bzr_revision_id to lookup the inv cache
            self.inventory = self.get_inventory(self.parents[0]).copy()
        if not self.repo.supports_rich_root():
            # In this repository, root entries have no knit or weave. When
            # serializing out to disk and back in, root.revision is always
            # the new revision_id.
            self.inventory.root.revision = self.revision_id

    def post_process_files(self):
        """Save the revision."""
        if self.verbose:
            print "applied inventory delta ..."
            for entry in self.inv_delta:
                print "  %r" % (entry,)
        self.inventory.apply_delta(self.inv_delta)
        self.cache_mgr.inventories[self.command.ref] = self.inventory
        if self.verbose:
            print "creating inventory ..."
            for entry in self.inventory:
                print "  %r" % (entry,)

        # Load the revision into the repository
        committer = self.command.committer
        who = "%s <%s>" % (committer[0],committer[1])
        rev = revision.Revision(self.revision_id)
        rev = revision.Revision(
           timestamp=committer[2],
           timezone=committer[3],
           committer=who,
           message=self.escape_commit_message(self.command.message),
           revision_id=self.revision_id)
        rev.parent_ids = self.parents
        self.loader.load(rev, self.inventory, None,
            lambda file_id: self._get_lines(file_id))
        print "loaded revision %r" % (rev,)

    def escape_commit_message(self, msg):
        # It's crap that we need to do this at this level (but we do)
        # TODO
        return msg

    def modify_handler(self, filecmd):
        if filecmd.dataref is not None:
            data = self.cache_mgr.blobs[filecmd.dataref]
            # Conserve memory, assuming blobs aren't referenced twice
            del self.cache_mgr.blobs[filecmd.dataref]
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
        """Get a Bazaar file identifier for a path."""
        try:
            return self.cache_mgr.file_ids[path]
        except KeyError:
            id = generate_ids.gen_file_id(path)
            self.cache_mgr.file_ids[path] = id
            return id

    def gen_initial_inventory(self):
        """Generate an inventory for a parentless revision."""
        inv = inventory.Inventory(revision_id=self.revision_id)
        return inv

    def gen_revision_id(self):
        """Generate a revision id.

        Subclasses may override this to produce deterministic ids say.
        """
        committer = self.command.committer
        who = "%s <%s>" % (committer[0],committer[1])
        timestamp = committer[2]
        return generate_ids.gen_revision_id(who, timestamp)

    def get_inventory(self, revision_id):
        """Get the inventory for a revision id."""
        try:
            inv = self.cache_mgr.inventories[revision_id]
        except KeyError:
            # TODO: count misses and/or inform the user about the miss?
            # Not cached so reconstruct from repository
            inv = self.repo.revision_tree(revision_id).inventory
            self.cache_mgr.inventories[revision_id] = inv
        return inv

    def _get_inventories(self, revision_ids):
        """Get the inventories for revision-ids.
        
        This is a callback used by the RepositoryLoader to
        speed up inventory reconstruction."""
        present = []
        inventories = []
        # If an inventory is in the cache, we assume it was
        # successfully loaded into the repsoitory
        for revision_id in revision_ids:
            try:
                inv = self.cache_mgr.inventories[revision_id]
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
                self.cache_mgr.inventories[revision_id] = inv
            inventories.append(inv)
        return present, inventories

    def _get_lines(self, file_id):
        """Get the lines for a file-id."""
        return self.lines_for_commit[file_id]

    def _modify_inventory(self, path, kind, is_executable, data):
        """Add to or change an item in the inventory."""
        # Create the new InventoryEntry
        basename, parent_ie = self._ensure_directory(path)
        file_id = self.bzr_file_id(path)
        ie = inventory.make_entry(kind, basename, parent_ie, file_id)
        ie.revision = self.revision_id
        if isinstance(ie, inventory.InventoryFile):
            ie.executable = is_executable
            lines = osutils.split_lines(data)
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            self.lines_for_commit[file_id] = lines
        elif isinstance(ie, inventory.InventoryLnk):
            ie.symlink_target = data
        else:
            raise errors.BzrError("Cannot import items of kind '%s' yet" %
                (kind,))

        # Record this new inventory entry. As the import stream doesn't
        # repeat all files every time, we build an inventory delta.
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
            ie = self.cache_mgr.directory_entries[dirname]
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
        self.cache_mgr.directory_entries[dirname] = ie
        self.inv_delta.append((None, path, dir_file_id, ie))
        return basename, ie
