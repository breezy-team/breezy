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


def copy_inventory(inv):
    # This currently breaks revision-id matching
    #if hasattr(inv, "_get_mutable_inventory"):
    #    # TODO: Make this a public API on inventory
    #    return inv._get_mutable_inventory()

    # TODO: Shallow copy - deep inventory copying is expensive
    return inv.copy()


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

        # Keep the basis inventory. This needs to be treated as read-only.
        if len(self.parents) == 0:
            self.basis_inventory = self._init_inventory()
        else:
            self.basis_inventory = self.get_inventory(self.parents[0])
        if hasattr(self.basis_inventory, "root_id"):
            self.inventory_root_id = self.basis_inventory.root_id
        else:
            self.inventory_root_id = self.basis_inventory.root.file_id

        # directory-path -> inventory-entry for current inventory
        if self.parents:
            self.directory_entries = dict(self.basis_inventory.directories())
        else:
            self.directory_entries = {}

    def _init_inventory(self):
        return self.rev_store.init_inventory(self.revision_id)

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

    def _get_lines(self, file_id):
        """Get the lines for a file-id."""
        return self.lines_for_commit[file_id]

    def _get_inventories(self, revision_ids):
        """Get the inventories for revision-ids.
        
        This is a callback used by the RepositoryStore to
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
                    inv = self._init_inventory()
                self.cache_mgr.inventories[revision_id] = inv
            inventories.append(inv)
        return present, inventories

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

    def _modify_item(self, path, kind, is_executable, data, inv):
        """Add to or change an item in the inventory."""
        # Create the new InventoryEntry
        basename, parent_id = self._ensure_directory(path, inv)
        file_id = self.bzr_file_id(path)
        ie = inventory.make_entry(kind, basename, parent_id, file_id)
        ie.revision = self.revision_id
        if kind == 'file':
            ie.executable = is_executable
            lines = osutils.split_lines(data)
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            self.lines_for_commit[file_id] = lines
        elif kind == 'symlink':
            ie.symlink_target = data.encode('utf8')
            # There are no lines stored for a symlink so
            # make sure the cache used by get_lines knows that
            self.lines_for_commit[file_id] = []
        else:
            raise errors.BzrError("Cannot import items of kind '%s' yet" %
                (kind,))
        # Record it
        if file_id in inv:
            old_ie = inv[file_id]
            if old_ie.kind == 'directory':
                self.record_delete(path, old_ie)
            self.record_changed(path, ie, parent_id)
        else:
            self.record_new(path, ie)

    def _ensure_directory(self, path, inv):
        """Ensure that the containing directory exists for 'path'"""
        dirname, basename = osutils.split(path)
        if dirname == '':
            # the root node doesn't get updated
            return basename, self.inventory_root_id
        try:
            ie = self.directory_entries[dirname]
        except KeyError:
            # We will create this entry, since it doesn't exist
            pass
        else:
            return basename, ie.file_id

        # No directory existed, we will just create one, first, make sure
        # the parent exists
        dir_basename, parent_id = self._ensure_directory(dirname, inv)
        dir_file_id = self.bzr_file_id(dirname)
        ie = inventory.entry_factory['directory'](dir_file_id,
            dir_basename, parent_id)
        ie.revision = self.revision_id
        self.directory_entries[dirname] = ie
        # There are no lines stored for a directory so
        # make sure the cache used by get_lines knows that
        self.lines_for_commit[dir_file_id] = []

        # It's possible that a file or symlink with that file-id
        # already exists. If it does, we need to delete it.
        if dir_file_id in inv:
            self.record_delete(dirname, ie)
        self.record_new(dirname, ie)
        return basename, ie.file_id

    def _delete_item(self, path, inv):
        file_id = inv.path2id(path)
        #print "**** deleting %s with file-id %s" % (path, file_id)
        ie = inv[file_id]
        self.record_delete(path, ie)

    def _copy_item(self, src_path, dest_path, inv):
        if not self.parents:
            self.warning("ignoring copy of %s to %s - no parent revisions",
                src_path, dest_path)
            return
        file_id = inv.path2id(src_path)
        if file_id is None:
            self.warning("ignoring copy of %s to %s - source does not exist",
                src_path, dest_path)
            return
        ie = inv[file_id]
        kind = ie.kind
        if kind == 'file':
            content = self.rev_store.get_file_text(self.parents[0], file_id)
            self._modify_item(dest_path, kind, ie.executable, content, inv)
        elif kind == 'symlink':
            self._modify_item(dest_path, kind, False, ie.symlink_target, inv)
        else:
            self.warning("ignoring copy of %s %s - feature not yet supported",
                kind, path)

    def _rename_item(self, old_path, new_path, inv):
        file_id = inv.path2id(old_path)
        ie = inv[file_id]
        rev_id = ie.revision
        new_file_id = inv.path2id(new_path)
        if new_file_id is not None:
            self.record_delete(new_path, inv[new_file_id])
        self.record_rename(old_path, new_path, file_id, ie)
        self.cache_mgr.rename_path(old_path, new_path)

        # The revision-id for this entry will be/has been updated and
        # that means the loader then needs to know what the "new" text is.
        # We therefore must go back to the revision store to get it.
        lines = self.rev_store.get_file_lines(rev_id, file_id)
        self.lines_for_commit[file_id] = lines

    def _delete_all_items(self, inv):
        for name, root_item in inv.root.children.iteritems():
            inv.remove_recursive_id(root_item.file_id)


class InventoryCommitHandler(GenericCommitHandler):
    """A CommitHandler that builds and saves Inventory objects."""

    def pre_process_files(self):
        super(InventoryCommitHandler, self).pre_process_files()

        # Seed the inventory from the previous one
        if len(self.parents) == 0:
            self.inventory = self.basis_inventory
        else:
            self.inventory = copy_inventory(self.basis_inventory)
        self.inventory_root = self.inventory.root

        # directory-path -> inventory-entry for current inventory
        self.directory_entries = dict(self.inventory.directories())

        # Initialise the inventory revision info as required
        if self.rev_store.expects_rich_root():
            self.inventory.revision_id = self.revision_id
        else:
            # In this revision store, root entries have no knit or weave.
            # When serializing out to disk and back in, root.revision is
            # always the new revision_id.
            self.inventory.root.revision = self.revision_id

    def post_process_files(self):
        """Save the revision."""
        self.cache_mgr.inventories[self.revision_id] = self.inventory
        rev = self.build_revision()
        self.rev_store.load(rev, self.inventory, None,
            lambda file_id: self._get_lines(file_id),
            lambda revision_ids: self._get_inventories(revision_ids))

    def record_new(self, path, ie):
        try:
            self.inventory.add(ie)
        except errors.DuplicateFileId:
            # Directory already exists as a file or symlink
            del self.inventory[ie.file_id]
            # Try again
            self.inventory.add(ie)

    def record_changed(self, path, ie, parent_id):
        # HACK: no API for this (del+add does more than it needs to)
        self.inventory._byid[ie.file_id] = ie
        parent_ie = self.inventory._byid[parent_id]
        parent_ie.children[ie.name] = ie

    def record_delete(self, path, ie):
        self.inventory.remove_recursive_id(ie.file_id)

    def record_rename(self, old_path, new_path, file_id, ie):
        new_basename, new_parent_id = self._ensure_directory(new_path,
            self.inventory)
        self.inventory.rename(file_id, new_parent_id, new_basename)
        self.inventory[file_id].revision = self.revision_id

    def _delete_item(self, path, inv):
        # NOTE: I'm retaining this method for now, instead of using the
        # one in the superclass, because it's taken quite a lot of tweaking
        # to cover all the edge cases seen in the wild. Long term, it can
        # probably go once the higher level method does "warn_unless_in_merges"
        # and handles all the various special cases ...
        fileid = self.bzr_file_id(path)
        dirname, basename = osutils.split(path)
        if (fileid in inv and
            isinstance(inv[fileid], inventory.InventoryDirectory)):
            for child_path in inv[fileid].children.keys():
                self._delete_item(osutils.pathjoin(path, child_path), inv)
        try:
            if self.inventory.id2path(fileid) == path:
                del inv[fileid]
            else:
                # already added by some other name?
                if dirname in self.cache_mgr.file_ids:
                    parent_id = self.cache_mgr.file_ids[dirname]
                    del inv[parent_id].children[basename]
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

    def _warn_unless_in_merges(self, fileid, path):
        if len(self.parents) <= 1:
            return
        for parent in self.parents[1:]:
            if fileid in self.get_inventory(parent):
                return
        self.warning("ignoring delete of %s as not in parent inventories", path)

    def modify_handler(self, filecmd):
        if filecmd.dataref is not None:
            data = self.cache_mgr.fetch_blob(filecmd.dataref)
        else:
            data = filecmd.data
        self.debug("modifying %s", filecmd.path)
        self._modify_item(filecmd.path, filecmd.kind,
            filecmd.is_executable, data, self.inventory)

    def delete_handler(self, filecmd):
        self.debug("deleting %s", filecmd.path)
        self._delete_item(filecmd.path, self.inventory)

    def copy_handler(self, filecmd):
        src_path = filecmd.src_path
        dest_path = filecmd.dest_path
        self.debug("copying %s to %s", src_path, dest_path)
        self._copy_item(src_path, dest_path, self.inventory)

    def rename_handler(self, filecmd):
        old_path = filecmd.old_path
        new_path = filecmd.new_path
        self.debug("renaming %s to %s", old_path, new_path)
        self._rename_item(old_path, new_path, self.inventory)

    def deleteall_handler(self, filecmd):
        self.debug("deleting all files (and also all directories)")
        self._delete_all_items(self.inventory)


class CHKInventoryCommitHandler(GenericCommitHandler):
    """A CommitHandler that builds and saves CHKInventory objects."""

    def pre_process_files(self):
        super(CHKInventoryCommitHandler, self).pre_process_files()
        # A given file-id can only appear once so we accumulate
        # the entries in a dict then build the actual delta at the end
        self._delta_entries_by_fileid = {}
        if len(self.parents) == 0 or not self.rev_store.expects_rich_root():
            if self.parents:
                old_path = ''
            else:
                old_path = None
            # Need to explicitly add the root entry for the first revision
            # and for non rich-root inventories
            root_id = inventory.ROOT_ID
            # XXX: We *could* make this a CHKInventoryDirectory but it
            # seems that deltas ought to use normal InventoryDirectory's
            # because they simply don't know the chk_inventory that they
            # are about to become a part of.
            root_ie = inventory.InventoryDirectory(root_id, u'', None)
            root_ie.revision = self.revision_id
            self._add_entry((old_path, '', root_id, root_ie))

    def post_process_files(self):
        """Save the revision."""
        delta = list(self._delta_entries_by_fileid.values())
        #print "delta:\n%s\n\n" % "\n".join([str(de) for de in delta])
        rev = self.build_revision()
        inv = self.rev_store.chk_load(rev, self.basis_inventory, delta, None,
            lambda file_id: self._get_lines(file_id),
            lambda revision_ids: self._get_inventories(revision_ids))
        self.cache_mgr.inventories[self.revision_id] = inv
        #print "committed %s" % self.revision_id

    def _add_entry(self, entry):
        # We need to combine the data if multiple entries have the same fileid.
        # For example, a rename followed by a modification looks like:
        #
        # (x, y, f, e) & (y, y, f, g) => (x, y, f, g)
        #
        # Likewise, a modification followed by a rename looks like:
        #
        # (x, x, f, e) & (x, y, f, g) => (x, y, f, g)
        #
        # Here's a rename followed by a delete and a modification followed by
        # a delete:
        #
        # (x, y, f, e) & (y, None, f, None) => (x, None, f, None)
        # (x, x, f, e) & (x, None, f, None) => (x, None, f, None)
        #
        # In summary, we use the original old-path, new new-path and new ie
        # when combining entries.
        file_id = entry[2]
        existing = self._delta_entries_by_fileid.get(file_id, None)
        if existing is not None:
            entry = (existing[0], entry[1], file_id, entry[3])
        self._delta_entries_by_fileid[file_id] = entry

    def record_new(self, path, ie):
        self._add_entry((None, path, ie.file_id, ie))

    def record_changed(self, path, ie, parent_id=None):
        self._add_entry((path, path, ie.file_id, ie))

    def record_delete(self, path, ie):
        self._add_entry((path, None, ie.file_id, None))
        if ie.kind == 'directory':
            for child_path, entry in \
                self.basis_inventory.iter_entries_by_dir(from_dir=ie):
                #print "deleting child %s" % child_path
                self._add_entry((child_path, None, entry.file_id, None))

    def record_rename(self, old_path, new_path, file_id, old_ie):
        new_ie = old_ie.copy()
        new_basename, new_parent_id = self._ensure_directory(new_path,
            self.basis_inventory)
        new_ie.name = new_basename
        new_ie.parent_id = new_parent_id
        new_ie.revision = self.revision_id
        self._add_entry((old_path, new_path, file_id, new_ie))

    def modify_handler(self, filecmd):
        if filecmd.dataref is not None:
            data = self.cache_mgr.fetch_blob(filecmd.dataref)
        else:
            data = filecmd.data
        self.debug("modifying %s", filecmd.path)
        self._modify_item(filecmd.path, filecmd.kind,
            filecmd.is_executable, data, self.basis_inventory)

    def delete_handler(self, filecmd):
        self.debug("deleting %s", filecmd.path)
        self._delete_item(filecmd.path, self.basis_inventory)

    def copy_handler(self, filecmd):
        src_path = filecmd.src_path
        dest_path = filecmd.dest_path
        self.debug("copying %s to %s", src_path, dest_path)
        self._copy_item(src_path, dest_path, self.basis_inventory)

    def rename_handler(self, filecmd):
        old_path = filecmd.old_path
        new_path = filecmd.new_path
        self.debug("renaming %s to %s", old_path, new_path)
        self._rename_item(old_path, new_path, self.basis_inventory)

    def deleteall_handler(self, filecmd):
        self.debug("deleting all files (and also all directories)")
        # I'm not 100% sure this will work in the delta case.
        # But clearing out the basis inventory so that everything
        # is added sounds ok in theory ...
        # We grab a copy as the basis is likely to be cached and
        # we don't want to destroy the cached version
        self.basis_inventory = copy_inventory(self.basis_inventory)
        self._delete_all_items(self.basis_inventory)
