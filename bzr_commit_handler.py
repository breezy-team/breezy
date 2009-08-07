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
    serializer,
    )
from bzrlib.plugins.fastimport import helpers, processor


_serializer_handles_escaping = hasattr(serializer.Serializer,
    'squashes_xml_invalid_characters')


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
        self.branch_ref = command.ref

    def pre_process_files(self):
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        # cache of texts for this commit, indexed by file-id
        self.lines_for_commit = {}
        #if self.rev_store.expects_rich_root():
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

        # Tell the RevisionStore we're starting a new commit
        self.revision = self.build_revision()
        parent_invs = [self.get_inventory(p) for p in self.parents]
        self.rev_store.start_new_revision(self.revision, self.parents,
            parent_invs)

        # cache of per-file parents for this commit, indexed by file-id
        self.per_file_parents_for_commit = {}
        if self.rev_store.expects_rich_root():
            self.per_file_parents_for_commit[inventory.ROOT_ID] = ()

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
        self.directory_entries = {}

    def _init_inventory(self):
        return self.rev_store.init_inventory(self.revision_id)

    def get_inventory(self, revision_id):
        """Get the inventory for a revision id."""
        try:
            inv = self.cache_mgr.inventories[revision_id]
        except KeyError:
            if self.verbose:
                self.mutter("get_inventory cache miss for %s", revision_id)
            # Not cached so reconstruct from the RevisionStore
            inv = self.rev_store.get_inventory(revision_id)
            self.cache_mgr.inventories[revision_id] = inv
        return inv

    def _get_lines(self, file_id):
        """Get the lines for a file-id."""
        return self.lines_for_commit[file_id]

    def _get_per_file_parents(self, file_id):
        """Get the lines for a file-id."""
        return self.per_file_parents_for_commit[file_id]

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
            id = self.cache_mgr.fetch_file_id(self.branch_ref, path)
            return id, False
        except KeyError:
            # Not in the cache, try the inventory
            id = self.basis_inventory.path2id(path)
            if id is None:
                # Doesn't exist yet so create it
                id = generate_ids.gen_file_id(path)
                self.debug("Generated new file id %s for '%s' in '%s'",
                    id, path, self.branch_ref)
            self.cache_mgr.store_file_id(self.branch_ref, path, id)
            return id, True

    def bzr_file_id(self, path):
        """Get a Bazaar file identifier for a path."""
        return self.bzr_file_id_and_new(path)[0]

    def _format_name_email(self, name, email):
        """Format name & email as a string."""
        if email:
            return "%s <%s>" % (name, email)
        else:
            return name

    def gen_revision_id(self):
        """Generate a revision id.

        Subclasses may override this to produce deterministic ids say.
        """
        committer = self.command.committer
        # Perhaps 'who' being the person running the import is ok? If so,
        # it might be a bit quicker and give slightly better compression?
        who = self._format_name_email(committer[0], committer[1])
        timestamp = committer[2]
        return generate_ids.gen_revision_id(who, timestamp)

    def build_revision(self):
        rev_props = {}
        committer = self.command.committer
        who = self._format_name_email(committer[0], committer[1])
        author = self.command.author
        if author is not None:
            author_id = self._format_name_email(author[0], author[1])
            if author_id != who:
                rev_props['author'] = author_id
        message = self.command.message
        if not _serializer_handles_escaping:
            # We need to assume the bad ol' days
            message = helpers.escape_commit_message(message)
        return revision.Revision(
           timestamp=committer[2],
           timezone=committer[3],
           committer=who,
           message=message,
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
            try:
                self.record_new(path, ie)
            except:
                print "failed to add path '%s' with entry '%s' in command %s" \
                    % (path, ie, self.command.id)
                print "parent's children are:\n%r\n" % (ie.parent_id.children,)
                raise

    def _ensure_directory(self, path, inv):
        """Ensure that the containing directory exists for 'path'"""
        dirname, basename = osutils.split(path)
        if dirname == '':
            # the root node doesn't get updated
            return basename, self.inventory_root_id
        try:
            ie = self._get_directory_entry(inv, dirname)
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

    def _get_directory_entry(self, inv, dirname):
        """Get the inventory entry for a directory.
        
        Raises KeyError if dirname is not a directory in inv.
        """
        result = self.directory_entries.get(dirname)
        if result is None:
            try:
                file_id = inv.path2id(dirname)
            except errors.NoSuchId:
                # In a CHKInventory, this is raised if there's no root yet
                raise KeyError
            if file_id is None:
                raise KeyError
            result = inv[file_id]
            # dirname must be a directory for us to return it
            if result.kind == 'directory':
                self.directory_entries[dirname] = result
            else:
                raise KeyError
        return result

    def _delete_item(self, path, inv):
        file_id = inv.path2id(path)
        if file_id is None:
            self.mutter("ignoring delete of %s as not in inventory", path)
            return
        try:
            ie = inv[file_id]
        except errors.NoSuchId:
            self.mutter("ignoring delete of %s as not in inventory", path)
        else:
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
        if file_id is None:
            self.warning(
                "ignoring rename of %s to %s - old path does not exist" %
                (old_path, new_path))
            return
        ie = inv[file_id]
        rev_id = ie.revision
        new_file_id = inv.path2id(new_path)
        if new_file_id is not None:
            self.record_delete(new_path, inv[new_file_id])
        self.record_rename(old_path, new_path, file_id, ie)
        self.cache_mgr.rename_path(self.branch_ref, old_path, new_path)

        # The revision-id for this entry will be/has been updated and
        # that means the loader then needs to know what the "new" text is.
        # We therefore must go back to the revision store to get it.
        lines = self.rev_store.get_file_lines(rev_id, file_id)
        self.lines_for_commit[file_id] = lines

    def _delete_all_items(self, inv):
        for name, root_item in inv.root.children.iteritems():
            inv.remove_recursive_id(root_item.file_id)

    def _warn_unless_in_merges(self, fileid, path):
        if len(self.parents) <= 1:
            return
        for parent in self.parents[1:]:
            if fileid in self.get_inventory(parent):
                return
        self.warning("ignoring delete of %s as not in parent inventories", path)


class InventoryCommitHandler(GenericCommitHandler):
    """A CommitHandler that builds and saves Inventory objects."""

    def pre_process_files(self):
        super(InventoryCommitHandler, self).pre_process_files()

        # Seed the inventory from the previous one. Note that
        # the parent class version of pre_process_files() has
        # already set the right basis_inventory for this branch
        # but we need to copy it in order to mutate it safely
        # without corrupting the cached inventory value.
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
        self.rev_store.load(self.revision, self.inventory, None,
            lambda file_id: self._get_lines(file_id),
            lambda file_id: self._get_per_file_parents(file_id),
            lambda revision_ids: self._get_inventories(revision_ids))

    def record_new(self, path, ie):
        try:
            # If this is a merge, the file was most likely added already.
            # The per-file parent(s) must therefore be calculated and
            # we can't assume there are none.
            per_file_parents, ie.revision = \
                self.rev_store.get_parents_and_revision_for_entry(ie)
            self.per_file_parents_for_commit[ie.file_id] = per_file_parents
            self.inventory.add(ie)
        except errors.DuplicateFileId:
            # Directory already exists as a file or symlink
            del self.inventory[ie.file_id]
            # Try again
            self.inventory.add(ie)

    def record_changed(self, path, ie, parent_id):
        # HACK: no API for this (del+add does more than it needs to)
        per_file_parents, ie.revision = \
            self.rev_store.get_parents_and_revision_for_entry(ie)
        self.per_file_parents_for_commit[ie.file_id] = per_file_parents
        self.inventory._byid[ie.file_id] = ie
        parent_ie = self.inventory._byid[parent_id]
        parent_ie.children[ie.name] = ie

    def record_delete(self, path, ie):
        self.inventory.remove_recursive_id(ie.file_id)

    def record_rename(self, old_path, new_path, file_id, ie):
        # For a rename, the revision-id is always the new one so
        # no need to change/set it here
        ie.revision = self.revision_id
        per_file_parents, _ = \
            self.rev_store.get_parents_and_revision_for_entry(ie)
        self.per_file_parents_for_commit[file_id] = per_file_parents
        new_basename, new_parent_id = self._ensure_directory(new_path,
            self.inventory)
        self.inventory.rename(file_id, new_parent_id, new_basename)

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
            # We need to clean this out of the directory entries as well
            try:
                del self.directory_entries[path]
            except KeyError:
                pass
        try:
            if self.inventory.id2path(fileid) == path:
                del inv[fileid]
            else:
                # already added by some other name?
                try:
                    parent_id = self.cache_mgr.fetch_file_id(self.branch_ref,
                        dirname)
                except KeyError:
                    pass
                else:
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
            self.cache_mgr.delete_path(self.branch_ref, path)
        except KeyError:
            pass

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


class InventoryDeltaCommitHandler(GenericCommitHandler):
    """A CommitHandler that builds Inventories by applying a delta."""

    def pre_process_files(self):
        super(InventoryDeltaCommitHandler, self).pre_process_files()
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
            root_ie = inventory.InventoryDirectory(root_id, u'', None)
            root_ie.revision = self.revision_id
            self._add_entry((old_path, '', root_id, root_ie))

    def post_process_files(self):
        """Save the revision."""
        delta = list(self._delta_entries_by_fileid.values())
        #print "delta:\n%s\n\n" % "\n".join([str(de) for de in delta])
        inv = self.rev_store.load_using_delta(self.revision,
            self.basis_inventory, delta, None,
            lambda file_id: self._get_lines(file_id),
            lambda file_id: self._get_per_file_parents(file_id),
            lambda revision_ids: self._get_inventories(revision_ids))
        self.cache_mgr.inventories[self.revision_id] = inv
        #print "committed %s" % self.revision_id

    def _add_entry(self, entry):
        # We need to combine the data if multiple entries have the same file-id.
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
        old_path = entry[0]
        new_path = entry[1]
        file_id = entry[2]
        ie = entry[3]
        existing = self._delta_entries_by_fileid.get(file_id, None)
        if existing is not None:
            old_path = existing[0]
            entry = (old_path, new_path, file_id, ie)
        self._delta_entries_by_fileid[file_id] = entry

        # Calculate the per-file parents, if not already done
        if file_id in self.per_file_parents_for_commit:
            return
        if old_path is None:
            # add
            # If this is a merge, the file was most likely added already.
            # The per-file parent(s) must therefore be calculated and
            # we can't assume there are none.
            per_file_parents, ie.revision = \
                self.rev_store.get_parents_and_revision_for_entry(ie)
            self.per_file_parents_for_commit[file_id] = per_file_parents
        elif new_path is None:
            # delete
            pass
        elif old_path != new_path:
            # rename
            per_file_parents, _ = \
                self.rev_store.get_parents_and_revision_for_entry(ie)
            self.per_file_parents_for_commit[file_id] = per_file_parents
        else:
            # modify
            per_file_parents, ie.revision = \
                self.rev_store.get_parents_and_revision_for_entry(ie)
            self.per_file_parents_for_commit[file_id] = per_file_parents

    def record_new(self, path, ie):
        self._add_entry((None, path, ie.file_id, ie))

    def record_changed(self, path, ie, parent_id=None):
        self._add_entry((path, path, ie.file_id, ie))

    def record_delete(self, path, ie):
        self._add_entry((path, None, ie.file_id, None))
        if ie.kind == 'directory':
            for child_relpath, entry in \
                self.basis_inventory.iter_entries_by_dir(from_dir=ie):
                child_path = osutils.pathjoin(path, child_relpath)
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
