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

"""CommitHandlers that build and save revisions & their inventories."""


from bzrlib import (
    errors,
    generate_ids,
    inventory,
    osutils,
    revision,
    )
from bzrlib.plugins.fastimport import helpers, processor


class GenericCommitHandler(processor.CommitHandler):
    """Base class for Bazaar CommitHandlers."""

    def __init__(self, command, cache_mgr, rev_store, verbose=False):
        super(GenericCommitHandler, self).__init__(command)
        self.cache_mgr = cache_mgr
        self.rev_store = rev_store
        self.verbose = verbose

    def pre_process_files(self):
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        # cache of texts for this commit, indexed by file-id
        self.lines_for_commit = {}
        if self.rev_store.expects_rich_root():
            self.lines_for_commit[inventory.ROOT_ID] = []

        # Track the heads and get the real parent list
        parents = self.cache_mgr.track_heads(self.command)

        # Convert the parent commit-ids to bzr revision-ids
        if parents:
            self.parents = [self.cache_mgr.revision_ids[p]
                for p in parents]
        else:
            self.parents = []
        self.debug("%s id: %s, parents: %s", self.command.id,
            self.revision_id, str(self.parents))

    def build_revision(self):
        rev_props = {}
        committer = self.command.committer
        who = "%s <%s>" % (committer[0],committer[1])
        author = self.command.author
        if author is not None:
            author_id = "%s <%s>" % (author[0],author[1])
            if author_id != who:
                rev_props['author'] = author_id
        return revision.Revision(
           timestamp=committer[2],
           timezone=committer[3],
           committer=who,
           message=helpers.escape_commit_message(self.command.message),
           revision_id=self.revision_id,
           properties=rev_props,
           parent_ids=self.parents)

    def bzr_file_id_and_new(self, path):
        """Get a Bazaar file identifier and new flag for a path.
        
        :return: file_id, is_new where
          is_new = True if the file_id is newly created
        """
        try:
            id = self.cache_mgr.file_ids[path]
            return id, False
        except KeyError:
            id = generate_ids.gen_file_id(path)
            self.cache_mgr.file_ids[path] = id
            self.debug("Generated new file id %s for '%s'", id, path)
            return id, True

    def bzr_file_id(self, path):
        """Get a Bazaar file identifier for a path."""
        return self.bzr_file_id_and_new(path)[0]

    def gen_revision_id(self):
        """Generate a revision id.

        Subclasses may override this to produce deterministic ids say.
        """
        committer = self.command.committer
        # Perhaps 'who' being the person running the import is ok? If so,
        # it might be a bit quicker and give slightly better compression?
        who = "%s <%s>" % (committer[0],committer[1])
        timestamp = committer[2]
        return generate_ids.gen_revision_id(who, timestamp)

    def get_inventory(self, revision_id):
        """Get the inventory for a revision id."""
        try:
            inv = self.cache_mgr.inventories[revision_id]
        except KeyError:
            if self.verbose:
                self.note("get_inventory cache miss for %s", revision_id)
            # Not cached so reconstruct from the RevisionStore
            inv = self.rev_store.get_inventory(revision_id)
            self.cache_mgr.inventories[revision_id] = inv
        return inv

    def _warn_unless_in_merges(self, fileid, path):
        if len(self.parents) <= 1:
            return
        for parent in self.parents[1:]:
            if fileid in self.get_inventory(parent):
                return
        self.warning("ignoring delete of %s as not in parent inventories", path)


class InventoryCommitHandler(GenericCommitHandler):
    """A CommitHandler that builds and saves full inventories."""

    def pre_process_files(self):
        super(InventoryCommitHandler, self).pre_process_files()

        # Seed the inventory from the previous one
        if len(self.parents) == 0:
            self.inventory = self.gen_initial_inventory()
        else:
            # use the bzr_revision_id to lookup the inv cache
            inv = self.get_inventory(self.parents[0])
            # TODO: Shallow copy - deep inventory copying is expensive
            self.inventory = inv.copy()
        if self.rev_store.expects_rich_root():
            self.inventory.revision_id = self.revision_id
        else:
            # In this revision store, root entries have no knit or weave.
            # When serializing out to disk and back in, root.revision is
            # always the new revision_id.
            self.inventory.root.revision = self.revision_id

        # directory-path -> inventory-entry for current inventory
        self.directory_entries = dict(self.inventory.directories())

    def gen_initial_inventory(self):
        """Generate an inventory for a parentless revision."""
        inv = inventory.Inventory(revision_id=self.revision_id)
        if self.rev_store.expects_rich_root():
            # The very first root needs to have the right revision
            inv.root.revision = self.revision_id
        return inv

    def post_process_files(self):
        """Save the revision."""
        self.cache_mgr.inventories[self.revision_id] = self.inventory
        rev = self.build_revision()
        self.rev_store.load(rev, self.inventory, None,
            lambda file_id: self._get_lines(file_id),
            lambda revision_ids: self._get_inventories(revision_ids))

    def _get_lines(self, file_id):
        """Get the lines for a file-id."""
        return self.lines_for_commit[file_id]

    def _get_inventories(self, revision_ids):
        """Get the inventories for revision-ids.
        
        This is a callback used by the RepositoryLoader to
        speed up inventory reconstruction.
        """
        present = []
        inventories = []
        # If an inventory is in the cache, we assume it was
        # successfully loaded into the revision store
        for revision_id in revision_ids:
            try:
                inv = self.cache_mgr.inventories[revision_id]
                present.append(revision_id)
            except KeyError:
                if self.verbose:
                    self.note("get_inventories cache miss for %s", revision_id)
                # Not cached so reconstruct from the revision store
                try:
                    inv = self.get_inventory(revision_id)
                    present.append(revision_id)
                except:
                    inv = self.gen_initial_inventory()
                self.cache_mgr.inventories[revision_id] = inv
            inventories.append(inv)
        return present, inventories

    def modify_handler(self, filecmd):
        if filecmd.dataref is not None:
            data = self.cache_mgr.fetch_blob(filecmd.dataref)
        else:
            data = filecmd.data
        self.debug("modifying %s", filecmd.path)
        self._modify_inventory(filecmd.path, filecmd.kind,
            filecmd.is_executable, data)

    def delete_handler(self, filecmd):
        self._delete_recursive(filecmd.path)

    def _delete_recursive(self, path):
        self.debug("deleting %s", path)
        fileid = self.bzr_file_id(path)
        dirname, basename = osutils.split(path)
        if (fileid in self.inventory and
            isinstance(self.inventory[fileid], inventory.InventoryDirectory)):
            for child_path in self.inventory[fileid].children.keys():
                self._delete_recursive(osutils.pathjoin(path, child_path))
        try:
            if self.inventory.id2path(fileid) == path:
                del self.inventory[fileid]
            else:
                # already added by some other name?
                if dirname in self.cache_mgr.file_ids:
                    parent_id = self.cache_mgr.file_ids[dirname]
                    del self.inventory[parent_id].children[basename]
        except KeyError:
            self._warn_unless_in_merges(fileid, path)
        except errors.NoSuchId:
            self._warn_unless_in_merges(fileid, path)
        except AttributeError, ex:
            if ex.args[0] == 'children':
                # A directory has changed into a file and then one
                # of it's children is being deleted!
                self._warn_unless_in_merges(fileid, path)
            else:
                raise
        try:
            self.cache_mgr.delete_path(path)
        except KeyError:
            pass

    def copy_handler(self, filecmd):
        src_path = filecmd.src_path
        dest_path = filecmd.dest_path
        self.debug("copying %s to %s", src_path, dest_path)
        if not self.parents:
            self.warning("ignoring copy of %s to %s - no parent revisions",
                src_path, dest_path)
            return
        file_id = self.inventory.path2id(src_path)
        if file_id is None:
            self.warning("ignoring copy of %s to %s - source does not exist",
                src_path, dest_path)
            return
        ie = self.inventory[file_id]
        kind = ie.kind
        if kind == 'file':
            content = self.rev_store.get_file_text(self.parents[0], file_id)
            self._modify_inventory(dest_path, kind, ie.executable, content)
        elif kind == 'symlink':
            self._modify_inventory(dest_path, kind, False, ie.symlink_target)
        else:
            self.warning("ignoring copy of %s %s - feature not yet supported",
                kind, path)

    def rename_handler(self, filecmd):
        old_path = filecmd.old_path
        new_path = filecmd.new_path
        self.debug("renaming %s to %s", old_path, new_path)
        file_id = self.bzr_file_id(old_path)
        basename, new_parent_ie = self._ensure_directory(new_path)
        new_parent_id = new_parent_ie.file_id
        existing_id = self.inventory.path2id(new_path)
        if existing_id is not None:
            self.inventory.remove_recursive_id(existing_id)
        ie = self.inventory[file_id]
        lines = self.rev_store._get_lines(file_id, ie.revision)
        self.lines_for_commit[file_id] = lines
        self.inventory.rename(file_id, new_parent_id, basename)
        self.cache_mgr.rename_path(old_path, new_path)
        self.inventory[file_id].revision = self.revision_id

    def deleteall_handler(self, filecmd):
        self.debug("deleting all files (and also all directories)")
        # Would be nice to have an inventory.clear() method here
        root_items = [ie for (name, ie) in
            self.inventory.root.children.iteritems()]
        for root_item in root_items:
            self.inventory.remove_recursive_id(root_item.file_id)

    def _modify_inventory(self, path, kind, is_executable, data):
        """Add to or change an item in the inventory."""
        # Create the new InventoryEntry
        basename, parent_ie = self._ensure_directory(path)
        file_id = self.bzr_file_id(path)
        ie = inventory.make_entry(kind, basename, parent_ie.file_id, file_id)
        ie.revision = self.revision_id
        if isinstance(ie, inventory.InventoryFile):
            ie.executable = is_executable
            lines = osutils.split_lines(data)
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            self.lines_for_commit[file_id] = lines
        elif isinstance(ie, inventory.InventoryLink):
            ie.symlink_target = data.encode('utf8')
            # There are no lines stored for a symlink so
            # make sure the cache used by get_lines knows that
            self.lines_for_commit[file_id] = []
        else:
            raise errors.BzrError("Cannot import items of kind '%s' yet" %
                (kind,))

        # Record this new inventory entry
        if file_id in self.inventory:
            # HACK: no API for this (del+add does more than it needs to)
            self.inventory._byid[file_id] = ie
            parent_ie.children[basename] = ie
        else:
            self.inventory.add(ie)

    def _ensure_directory(self, path):
        """Ensure that the containing directory exists for 'path'"""
        dirname, basename = osutils.split(path)
        if dirname == '':
            # the root node doesn't get updated
            return basename, self.inventory.root
        try:
            ie = self.directory_entries[dirname]
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
        self.directory_entries[dirname] = ie
        # There are no lines stored for a directory so
        # make sure the cache used by get_lines knows that
        self.lines_for_commit[dir_file_id] = []
        #print "adding dir for %s" % path
        self.inventory.add(ie)
        return basename, ie
