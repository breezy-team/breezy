# (C) 2005 Canonical Ltd
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

# FIXME: This refactoring of the workingtree code doesn't seem to keep 
# the WorkingTree's copy of the inventory in sync with the branch.  The
# branch modifies its working inventory when it does a commit to make
# missing files permanently removed.

# TODO: Maybe also keep the full path of the entry, and the children?
# But those depend on its position within a particular inventory, and
# it would be nice not to need to hold the backpointer here.

# This should really be an id randomly assigned when the tree is
# created, but it's not for now.
ROOT_ID = "TREE_ROOT"


import os.path
import re
import sys
import tarfile
import types

import bzrlib
from bzrlib.osutils import (pumpfile, quotefn, splitpath, joinpath,
                            pathjoin, sha_strings)
from bzrlib.trace import mutter
from bzrlib.errors import (NotVersionedError, InvalidEntryName,
                           BzrError, BzrCheckError)


class InventoryEntry(object):
    """Description of a versioned file.

    An InventoryEntry has the following fields, which are also
    present in the XML inventory-entry element:

    file_id

    name
        (within the parent directory)

    parent_id
        file_id of the parent directory, or ROOT_ID

    revision
        the revision_id in which this variation of this file was 
        introduced.

    executable
        Indicates that this file should be executable on systems
        that support it.

    text_sha1
        sha-1 of the text of the file
        
    text_size
        size in bytes of the text of the file
        
    (reading a version 4 tree created a text_id field.)

    >>> i = Inventory()
    >>> i.path2id('')
    'TREE_ROOT'
    >>> i.add(InventoryDirectory('123', 'src', ROOT_ID))
    InventoryDirectory('123', 'src', parent_id='TREE_ROOT')
    >>> i.add(InventoryFile('2323', 'hello.c', parent_id='123'))
    InventoryFile('2323', 'hello.c', parent_id='123')
    >>> shouldbe = {0: 'src', 1: pathjoin('src','hello.c')}
    >>> for ix, j in enumerate(i.iter_entries()):
    ...   print (j[0] == shouldbe[ix], j[1])
    ... 
    (True, InventoryDirectory('123', 'src', parent_id='TREE_ROOT'))
    (True, InventoryFile('2323', 'hello.c', parent_id='123'))
    >>> i.add(InventoryFile('2323', 'bye.c', '123'))
    Traceback (most recent call last):
    ...
    BzrError: inventory already contains entry with id {2323}
    >>> i.add(InventoryFile('2324', 'bye.c', '123'))
    InventoryFile('2324', 'bye.c', parent_id='123')
    >>> i.add(InventoryDirectory('2325', 'wibble', '123'))
    InventoryDirectory('2325', 'wibble', parent_id='123')
    >>> i.path2id('src/wibble')
    '2325'
    >>> '2325' in i
    True
    >>> i.add(InventoryFile('2326', 'wibble.c', '2325'))
    InventoryFile('2326', 'wibble.c', parent_id='2325')
    >>> i['2326']
    InventoryFile('2326', 'wibble.c', parent_id='2325')
    >>> for path, entry in i.iter_entries():
    ...     print path
    ...     assert i.path2id(path)
    ... 
    src
    src/bye.c
    src/hello.c
    src/wibble
    src/wibble/wibble.c
    >>> i.id2path('2326')
    'src/wibble/wibble.c'
    """
    
    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable', 
                 'revision']

    def _add_text_to_weave(self, new_lines, parents, weave_store, transaction):
        versionedfile = weave_store.get_weave(self.file_id, transaction)
        versionedfile.add_lines(self.revision, parents, new_lines)

    def detect_changes(self, old_entry):
        """Return a (text_modified, meta_modified) from this to old_entry.
        
        _read_tree_state must have been called on self and old_entry prior to 
        calling detect_changes.
        """
        return False, False

    def diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """Perform a diff from this to to_entry.

        text_diff will be used for textual difference calculation.
        This is a template method, override _diff in child classes.
        """
        self._read_tree_state(tree.id2path(self.file_id), tree)
        if to_entry:
            # cannot diff from one kind to another - you must do a removal
            # and an addif they do not match.
            assert self.kind == to_entry.kind
            to_entry._read_tree_state(to_tree.id2path(to_entry.file_id),
                                      to_tree)
        self._diff(text_diff, from_label, tree, to_label, to_entry, to_tree,
                   output_to, reverse)

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """Perform a diff between two entries of the same kind."""

    def find_previous_heads(self, previous_inventories, entry_weave):
        """Return the revisions and entries that directly preceed this.

        Returned as a map from revision to inventory entry.

        This is a map containing the file revisions in all parents
        for which the file exists, and its revision is not a parent of
        any other. If the file is new, the set will be empty.
        """
        def get_ancestors(weave, entry):
            return set(map(weave.idx_to_name,
                           weave.inclusions([weave.lookup(entry.revision)])))
        heads = {}
        head_ancestors = {}
        for inv in previous_inventories:
            if self.file_id in inv:
                ie = inv[self.file_id]
                assert ie.file_id == self.file_id
                if ie.revision in heads:
                    # fixup logic, there was a bug in revision updates.
                    # with x bit support.
                    try:
                        if heads[ie.revision].executable != ie.executable:
                            heads[ie.revision].executable = False
                            ie.executable = False
                    except AttributeError:
                        pass
                    assert heads[ie.revision] == ie
                else:
                    # may want to add it.
                    # may already be covered:
                    already_present = 0 != len(
                        [head for head in heads 
                         if ie.revision in head_ancestors[head]])
                    if already_present:
                        # an ancestor of a known head.
                        continue
                    # definately a head:
                    ancestors = get_ancestors(entry_weave, ie)
                    # may knock something else out:
                    check_heads = list(heads.keys())
                    for head in check_heads:
                        if head in ancestors:
                            # this head is not really a head
                            heads.pop(head)
                    head_ancestors[ie.revision] = ancestors
                    heads[ie.revision] = ie
        return heads

    def get_tar_item(self, root, dp, now, tree):
        """Get a tarfile item and a file stream for its content."""
        item = tarfile.TarInfo(pathjoin(root, dp))
        # TODO: would be cool to actually set it to the timestamp of the
        # revision it was last changed
        item.mtime = now
        fileobj = self._put_in_tar(item, tree)
        return item, fileobj

    def has_text(self):
        """Return true if the object this entry represents has textual data.

        Note that textual data includes binary content.

        Also note that all entries get weave files created for them.
        This attribute is primarily used when upgrading from old trees that
        did not have the weave index for all inventory entries.
        """
        return False

    def __init__(self, file_id, name, parent_id, text_id=None):
        """Create an InventoryEntry
        
        The filename must be a single component, relative to the
        parent directory; it cannot be a whole path or relative name.

        >>> e = InventoryFile('123', 'hello.c', ROOT_ID)
        >>> e.name
        'hello.c'
        >>> e.file_id
        '123'
        >>> e = InventoryFile('123', 'src/hello.c', ROOT_ID)
        Traceback (most recent call last):
        InvalidEntryName: Invalid entry name: src/hello.c
        """
        assert isinstance(name, basestring), name
        if '/' in name or '\\' in name:
            raise InvalidEntryName(name=name)
        self.executable = False
        self.revision = None
        self.text_sha1 = None
        self.text_size = None
        self.file_id = file_id
        self.name = name
        self.text_id = text_id
        self.parent_id = parent_id
        self.symlink_target = None

    def kind_character(self):
        """Return a short kind indicator useful for appending to names."""
        raise BzrError('unknown kind %r' % self.kind)

    known_kinds = ('file', 'directory', 'symlink', 'root_directory')

    def _put_in_tar(self, item, tree):
        """populate item for stashing in a tar, and return the content stream.

        If no content is available, return None.
        """
        raise BzrError("don't know how to export {%s} of kind %r" %
                       (self.file_id, self.kind))

    def put_on_disk(self, dest, dp, tree):
        """Create a representation of self on disk in the prefix dest.
        
        This is a template method - implement _put_on_disk in subclasses.
        """
        fullpath = pathjoin(dest, dp)
        self._put_on_disk(fullpath, tree)
        mutter("  export {%s} kind %s to %s", self.file_id,
                self.kind, fullpath)

    def _put_on_disk(self, fullpath, tree):
        """Put this entry onto disk at fullpath, from tree tree."""
        raise BzrError("don't know how to export {%s} of kind %r" % (self.file_id, self.kind))

    def sorted_children(self):
        l = self.children.items()
        l.sort()
        return l

    @staticmethod
    def versionable_kind(kind):
        return kind in ('file', 'directory', 'symlink')

    def check(self, checker, rev_id, inv, tree):
        """Check this inventory entry is intact.

        This is a template method, override _check for kind specific
        tests.
        """
        if self.parent_id != None:
            if not inv.has_id(self.parent_id):
                raise BzrCheckError('missing parent {%s} in inventory for revision {%s}'
                        % (self.parent_id, rev_id))
        self._check(checker, rev_id, tree)

    def _check(self, checker, rev_id, tree):
        """Check this inventory entry for kind specific errors."""
        raise BzrCheckError('unknown entry kind %r in revision {%s}' % 
                            (self.kind, rev_id))


    def copy(self):
        """Clone this inventory entry."""
        raise NotImplementedError

    def _get_snapshot_change(self, previous_entries):
        if len(previous_entries) > 1:
            return 'merged'
        elif len(previous_entries) == 0:
            return 'added'
        else:
            return 'modified/renamed/reparented'

    def __repr__(self):
        return ("%s(%r, %r, parent_id=%r)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.parent_id))

    def snapshot(self, revision, path, previous_entries,
                 work_tree, weave_store, transaction):
        """Make a snapshot of this entry which may or may not have changed.
        
        This means that all its fields are populated, that it has its
        text stored in the text store or weave.
        """
        mutter('new parents of %s are %r', path, previous_entries)
        self._read_tree_state(path, work_tree)
        if len(previous_entries) == 1:
            # cannot be unchanged unless there is only one parent file rev.
            parent_ie = previous_entries.values()[0]
            if self._unchanged(parent_ie):
                mutter("found unchanged entry")
                self.revision = parent_ie.revision
                return "unchanged"
        return self.snapshot_revision(revision, previous_entries, 
                                      work_tree, weave_store, transaction)

    def snapshot_revision(self, revision, previous_entries, work_tree,
                          weave_store, transaction):
        """Record this revision unconditionally."""
        mutter('new revision for {%s}', self.file_id)
        self.revision = revision
        change = self._get_snapshot_change(previous_entries)
        self._snapshot_text(previous_entries, work_tree, weave_store,
                            transaction)
        return change

    def _snapshot_text(self, file_parents, work_tree, weave_store, transaction): 
        """Record the 'text' of this entry, whatever form that takes.
        
        This default implementation simply adds an empty text.
        """
        mutter('storing file {%s} in revision {%s}',
               self.file_id, self.revision)
        self._add_text_to_weave([], file_parents, weave_store, transaction)

    def __eq__(self, other):
        if not isinstance(other, InventoryEntry):
            return NotImplemented

        return ((self.file_id == other.file_id)
                and (self.name == other.name)
                and (other.symlink_target == self.symlink_target)
                and (self.text_sha1 == other.text_sha1)
                and (self.text_size == other.text_size)
                and (self.text_id == other.text_id)
                and (self.parent_id == other.parent_id)
                and (self.kind == other.kind)
                and (self.revision == other.revision)
                and (self.executable == other.executable)
                )

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        raise ValueError('not hashable')

    def _unchanged(self, previous_ie):
        """Has this entry changed relative to previous_ie.

        This method should be overriden in child classes.
        """
        compatible = True
        # different inv parent
        if previous_ie.parent_id != self.parent_id:
            compatible = False
        # renamed
        elif previous_ie.name != self.name:
            compatible = False
        return compatible

    def _read_tree_state(self, path, work_tree):
        """Populate fields in the inventory entry from the given tree.
        
        Note that this should be modified to be a noop on virtual trees
        as all entries created there are prepopulated.
        """
        # TODO: Rather than running this manually, we should check the 
        # working sha1 and other expensive properties when they're
        # first requested, or preload them if they're already known
        pass            # nothing to do by default

    def _forget_tree_state(self):
        pass


class RootEntry(InventoryEntry):

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""

    def __init__(self, file_id):
        self.file_id = file_id
        self.children = {}
        self.kind = 'root_directory'
        self.parent_id = None
        self.name = u''

    def __eq__(self, other):
        if not isinstance(other, RootEntry):
            return NotImplemented
        
        return (self.file_id == other.file_id) \
               and (self.children == other.children)


class InventoryDirectory(InventoryEntry):
    """A directory in an inventory."""

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""
        if self.text_sha1 != None or self.text_size != None or self.text_id != None:
            raise BzrCheckError('directory {%s} has text in revision {%s}'
                                % (self.file_id, rev_id))

    def copy(self):
        other = InventoryDirectory(self.file_id, self.name, self.parent_id)
        other.revision = self.revision
        # note that children are *not* copied; they're pulled across when
        # others are added
        return other

    def __init__(self, file_id, name, parent_id):
        super(InventoryDirectory, self).__init__(file_id, name, parent_id)
        self.children = {}
        self.kind = 'directory'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return '/'

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.DIRTYPE
        fileobj = None
        item.name += '/'
        item.size = 0
        item.mode = 0755
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        os.mkdir(fullpath)


class InventoryFile(InventoryEntry):
    """A file in an inventory."""

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""
        revision = self.revision
        t = (self.file_id, revision)
        if t in checker.checked_texts:
            prev_sha = checker.checked_texts[t] 
            if prev_sha != self.text_sha1:
                raise BzrCheckError('mismatched sha1 on {%s} in {%s}' %
                                    (self.file_id, rev_id))
            else:
                checker.repeated_text_cnt += 1
                return

        if self.file_id not in checker.checked_weaves:
            mutter('check weave {%s}', self.file_id)
            w = tree.get_weave(self.file_id)
            # Not passing a progress bar, because it creates a new
            # progress, which overwrites the current progress,
            # and doesn't look nice
            w.check()
            checker.checked_weaves[self.file_id] = True
        else:
            w = tree.get_weave_prelude(self.file_id)

        mutter('check version {%s} of {%s}', rev_id, self.file_id)
        checker.checked_text_cnt += 1 
        # We can't check the length, because Weave doesn't store that
        # information, and the whole point of looking at the weave's
        # sha1sum is that we don't have to extract the text.
        if self.text_sha1 != w.get_sha1(self.revision):
            raise BzrCheckError('text {%s} version {%s} wrong sha1' 
                                % (self.file_id, self.revision))
        checker.checked_texts[t] = self.text_sha1

    def copy(self):
        other = InventoryFile(self.file_id, self.name, self.parent_id)
        other.executable = self.executable
        other.text_id = self.text_id
        other.text_sha1 = self.text_sha1
        other.text_size = self.text_size
        other.revision = self.revision
        return other

    def detect_changes(self, old_entry):
        """See InventoryEntry.detect_changes."""
        assert self.text_sha1 != None
        assert old_entry.text_sha1 != None
        text_modified = (self.text_sha1 != old_entry.text_sha1)
        meta_modified = (self.executable != old_entry.executable)
        return text_modified, meta_modified

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """See InventoryEntry._diff."""
        from_text = tree.get_file(self.file_id).readlines()
        if to_entry:
            to_text = to_tree.get_file(to_entry.file_id).readlines()
        else:
            to_text = []
        if not reverse:
            text_diff(from_label, from_text,
                      to_label, to_text, output_to)
        else:
            text_diff(to_label, to_text,
                      from_label, from_text, output_to)

    def has_text(self):
        """See InventoryEntry.has_text."""
        return True

    def __init__(self, file_id, name, parent_id):
        super(InventoryFile, self).__init__(file_id, name, parent_id)
        self.kind = 'file'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.REGTYPE
        fileobj = tree.get_file(self.file_id)
        item.size = self.text_size
        if tree.is_executable(self.file_id):
            item.mode = 0755
        else:
            item.mode = 0644
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        pumpfile(tree.get_file(self.file_id), file(fullpath, 'wb'))
        if tree.is_executable(self.file_id):
            os.chmod(fullpath, 0755)

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.text_sha1 = work_tree.get_file_sha1(self.file_id)
        self.executable = work_tree.is_executable(self.file_id)

    def _forget_tree_state(self):
        self.text_sha1 = None
        self.executable = None

    def _snapshot_text(self, file_parents, work_tree, weave_store, transaction):
        """See InventoryEntry._snapshot_text."""
        mutter('storing file {%s} in revision {%s}',
               self.file_id, self.revision)
        # special case to avoid diffing on renames or 
        # reparenting
        if (len(file_parents) == 1
            and self.text_sha1 == file_parents.values()[0].text_sha1
            and self.text_size == file_parents.values()[0].text_size):
            previous_ie = file_parents.values()[0]
            versionedfile = weave_store.get_weave(self.file_id, transaction)
            versionedfile.clone_text(self.revision, previous_ie.revision, file_parents)
        else:
            new_lines = work_tree.get_file(self.file_id).readlines()
            self._add_text_to_weave(new_lines, file_parents, weave_store,
                                    transaction)
            self.text_sha1 = sha_strings(new_lines)
            self.text_size = sum(map(len, new_lines))


    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(InventoryFile, self)._unchanged(previous_ie)
        if self.text_sha1 != previous_ie.text_sha1:
            compatible = False
        else:
            # FIXME: 20050930 probe for the text size when getting sha1
            # in _read_tree_state
            self.text_size = previous_ie.text_size
        if self.executable != previous_ie.executable:
            compatible = False
        return compatible


class InventoryLink(InventoryEntry):
    """A file in an inventory."""

    __slots__ = ['symlink_target']

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""
        if self.text_sha1 != None or self.text_size != None or self.text_id != None:
            raise BzrCheckError('symlink {%s} has text in revision {%s}'
                    % (self.file_id, rev_id))
        if self.symlink_target == None:
            raise BzrCheckError('symlink {%s} has no target in revision {%s}'
                    % (self.file_id, rev_id))

    def copy(self):
        other = InventoryLink(self.file_id, self.name, self.parent_id)
        other.symlink_target = self.symlink_target
        other.revision = self.revision
        return other

    def detect_changes(self, old_entry):
        """See InventoryEntry.detect_changes."""
        # FIXME: which _modified field should we use ? RBC 20051003
        text_modified = (self.symlink_target != old_entry.symlink_target)
        if text_modified:
            mutter("    symlink target changed")
        meta_modified = False
        return text_modified, meta_modified

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """See InventoryEntry._diff."""
        from_text = self.symlink_target
        if to_entry is not None:
            to_text = to_entry.symlink_target
            if reverse:
                temp = from_text
                from_text = to_text
                to_text = temp
            print >>output_to, '=== target changed %r => %r' % (from_text, to_text)
        else:
            if not reverse:
                print >>output_to, '=== target was %r' % self.symlink_target
            else:
                print >>output_to, '=== target is %r' % self.symlink_target

    def __init__(self, file_id, name, parent_id):
        super(InventoryLink, self).__init__(file_id, name, parent_id)
        self.kind = 'symlink'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.SYMTYPE
        fileobj = None
        item.size = 0
        item.mode = 0755
        item.linkname = self.symlink_target
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        try:
            os.symlink(self.symlink_target, fullpath)
        except OSError,e:
            raise BzrError("Failed to create symlink %r -> %r, error: %s" % (fullpath, self.symlink_target, e))

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.symlink_target = work_tree.get_symlink_target(self.file_id)

    def _forget_tree_state(self):
        self.symlink_target = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(InventoryLink, self)._unchanged(previous_ie)
        if self.symlink_target != previous_ie.symlink_target:
            compatible = False
        return compatible


class Inventory(object):
    """Inventory of versioned files in a tree.

    This describes which file_id is present at each point in the tree,
    and possibly the SHA-1 or other information about the file.
    Entries can be looked up either by path or by file_id.

    The inventory represents a typical unix file tree, with
    directories containing files and subdirectories.  We never store
    the full path to a file, because renaming a directory implicitly
    moves all of its contents.  This class internally maintains a
    lookup tree that allows the children under a directory to be
    returned quickly.

    InventoryEntry objects must not be modified after they are
    inserted, other than through the Inventory API.

    >>> inv = Inventory()
    >>> inv.add(InventoryFile('123-123', 'hello.c', ROOT_ID))
    InventoryFile('123-123', 'hello.c', parent_id='TREE_ROOT')
    >>> inv['123-123'].name
    'hello.c'

    May be treated as an iterator or set to look up file ids:
    
    >>> bool(inv.path2id('hello.c'))
    True
    >>> '123-123' in inv
    True

    May also look up by name:

    >>> [x[0] for x in inv.iter_entries()]
    ['hello.c']
    >>> inv = Inventory('TREE_ROOT-12345678-12345678')
    >>> inv.add(InventoryFile('123-123', 'hello.c', ROOT_ID))
    InventoryFile('123-123', 'hello.c', parent_id='TREE_ROOT-12345678-12345678')
    """
    def __init__(self, root_id=ROOT_ID):
        """Create or read an inventory.

        If a working directory is specified, the inventory is read
        from there.  If the file is specified, read from that. If not,
        the inventory is created empty.

        The inventory is created with a default root directory, with
        an id of None.
        """
        # We are letting Branch.create() create a unique inventory
        # root id. Rather than generating a random one here.
        #if root_id is None:
        #    root_id = bzrlib.branch.gen_file_id('TREE_ROOT')
        self.root = RootEntry(root_id)
        self._byid = {self.root.file_id: self.root}


    def copy(self):
        other = Inventory(self.root.file_id)
        # copy recursively so we know directories will be added before
        # their children.  There are more efficient ways than this...
        for path, entry in self.iter_entries():
            if entry == self.root:
                continue
            other.add(entry.copy())
        return other


    def __iter__(self):
        return iter(self._byid)


    def __len__(self):
        """Returns number of entries."""
        return len(self._byid)


    def iter_entries(self, from_dir=None):
        """Return (path, entry) pairs, in order by name."""
        if from_dir == None:
            assert self.root
            from_dir = self.root
        elif isinstance(from_dir, basestring):
            from_dir = self._byid[from_dir]
            
        kids = from_dir.children.items()
        kids.sort()
        for name, ie in kids:
            yield name, ie
            if ie.kind == 'directory':
                for cn, cie in self.iter_entries(from_dir=ie.file_id):
                    yield pathjoin(name, cn), cie


    def entries(self):
        """Return list of (path, ie) for all entries except the root.

        This may be faster than iter_entries.
        """
        accum = []
        def descend(dir_ie, dir_path):
            kids = dir_ie.children.items()
            kids.sort()
            for name, ie in kids:
                child_path = pathjoin(dir_path, name)
                accum.append((child_path, ie))
                if ie.kind == 'directory':
                    descend(ie, child_path)

        descend(self.root, u'')
        return accum


    def directories(self):
        """Return (path, entry) pairs for all directories, including the root.
        """
        accum = []
        def descend(parent_ie, parent_path):
            accum.append((parent_path, parent_ie))
            
            kids = [(ie.name, ie) for ie in parent_ie.children.itervalues() if ie.kind == 'directory']
            kids.sort()

            for name, child_ie in kids:
                child_path = pathjoin(parent_path, name)
                descend(child_ie, child_path)
        descend(self.root, u'')
        return accum
        


    def __contains__(self, file_id):
        """True if this entry contains a file with given id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123', 'foo.c', ROOT_ID))
        InventoryFile('123', 'foo.c', parent_id='TREE_ROOT')
        >>> '123' in inv
        True
        >>> '456' in inv
        False
        """
        return file_id in self._byid


    def __getitem__(self, file_id):
        """Return the entry for given file_id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123123', 'hello.c', ROOT_ID))
        InventoryFile('123123', 'hello.c', parent_id='TREE_ROOT')
        >>> inv['123123'].name
        'hello.c'
        """
        try:
            return self._byid[file_id]
        except KeyError:
            if file_id == None:
                raise BzrError("can't look up file_id None")
            else:
                raise BzrError("file_id {%s} not in inventory" % file_id)


    def get_file_kind(self, file_id):
        return self._byid[file_id].kind

    def get_child(self, parent_id, filename):
        return self[parent_id].children.get(filename)


    def add(self, entry):
        """Add entry to inventory.

        To add  a file to a branch ready to be committed, use Branch.add,
        which calls this.

        Returns the new entry object.
        """
        if entry.file_id in self._byid:
            raise BzrError("inventory already contains entry with id {%s}" % entry.file_id)

        if entry.parent_id == ROOT_ID or entry.parent_id is None:
            entry.parent_id = self.root.file_id

        try:
            parent = self._byid[entry.parent_id]
        except KeyError:
            raise BzrError("parent_id {%s} not in inventory" % entry.parent_id)

        if parent.children.has_key(entry.name):
            raise BzrError("%s is already versioned" %
                    pathjoin(self.id2path(parent.file_id), entry.name))

        self._byid[entry.file_id] = entry
        parent.children[entry.name] = entry
        return entry


    def add_path(self, relpath, kind, file_id=None):
        """Add entry from a path.

        The immediate parent must already be versioned.

        Returns the new entry object."""
        from bzrlib.workingtree import gen_file_id
        
        parts = bzrlib.osutils.splitpath(relpath)

        if file_id == None:
            file_id = gen_file_id(relpath)

        if len(parts) == 0:
            self.root = RootEntry(file_id)
            self._byid = {self.root.file_id: self.root}
            return
        else:
            parent_path = parts[:-1]
            parent_id = self.path2id(parent_path)
            if parent_id == None:
                raise NotVersionedError(path=parent_path)
        if kind == 'directory':
            ie = InventoryDirectory(file_id, parts[-1], parent_id)
        elif kind == 'file':
            ie = InventoryFile(file_id, parts[-1], parent_id)
        elif kind == 'symlink':
            ie = InventoryLink(file_id, parts[-1], parent_id)
        else:
            raise BzrError("unknown kind %r" % kind)
        return self.add(ie)


    def __delitem__(self, file_id):
        """Remove entry by id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123', 'foo.c', ROOT_ID))
        InventoryFile('123', 'foo.c', parent_id='TREE_ROOT')
        >>> '123' in inv
        True
        >>> del inv['123']
        >>> '123' in inv
        False
        """
        ie = self[file_id]

        assert ie.parent_id is None or \
            self[ie.parent_id].children[ie.name] == ie
        
        del self._byid[file_id]
        if ie.parent_id is not None:
            del self[ie.parent_id].children[ie.name]


    def __eq__(self, other):
        """Compare two sets by comparing their contents.

        >>> i1 = Inventory()
        >>> i2 = Inventory()
        >>> i1 == i2
        True
        >>> i1.add(InventoryFile('123', 'foo', ROOT_ID))
        InventoryFile('123', 'foo', parent_id='TREE_ROOT')
        >>> i1 == i2
        False
        >>> i2.add(InventoryFile('123', 'foo', ROOT_ID))
        InventoryFile('123', 'foo', parent_id='TREE_ROOT')
        >>> i1 == i2
        True
        """
        if not isinstance(other, Inventory):
            return NotImplemented

        if len(self._byid) != len(other._byid):
            # shortcut: obviously not the same
            return False

        return self._byid == other._byid


    def __ne__(self, other):
        return not self.__eq__(other)


    def __hash__(self):
        raise ValueError('not hashable')


    def get_idpath(self, file_id):
        """Return a list of file_ids for the path to an entry.

        The list contains one element for each directory followed by
        the id of the file itself.  So the length of the returned list
        is equal to the depth of the file in the tree, counting the
        root directory as depth 1.
        """
        p = []
        while file_id != None:
            try:
                ie = self._byid[file_id]
            except KeyError:
                raise BzrError("file_id {%s} not found in inventory" % file_id)
            p.insert(0, ie.file_id)
            file_id = ie.parent_id
        return p


    def id2path(self, file_id):
        """Return as a list the path to file_id.
        
        >>> i = Inventory()
        >>> e = i.add(InventoryDirectory('src-id', 'src', ROOT_ID))
        >>> e = i.add(InventoryFile('foo-id', 'foo.c', parent_id='src-id'))
        >>> print i.id2path('foo-id')
        src/foo.c
        """
        # get all names, skipping root
        p = [self._byid[fid].name for fid in self.get_idpath(file_id)[1:]]
        if p:
            return pathjoin(*p)
        else:
            return ''
            


    def path2id(self, name):
        """Walk down through directories to return entry of last component.

        names may be either a list of path components, or a single
        string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.

        Returns None iff the path is not found.
        """
        if isinstance(name, types.StringTypes):
            name = splitpath(name)

        mutter("lookup path %r" % name)

        parent = self.root
        for f in name:
            try:
                cie = parent.children[f]
                assert cie.name == f
                assert cie.parent_id == parent.file_id
                parent = cie
            except KeyError:
                # or raise an error?
                return None

        return parent.file_id


    def has_filename(self, names):
        return bool(self.path2id(names))


    def has_id(self, file_id):
        return self._byid.has_key(file_id)


    def rename(self, file_id, new_parent_id, new_name):
        """Move a file within the inventory.

        This can change either the name, or the parent, or both.

        This does not move the working file."""
        if not is_valid_name(new_name):
            raise BzrError("not an acceptable filename: %r" % new_name)

        new_parent = self._byid[new_parent_id]
        if new_name in new_parent.children:
            raise BzrError("%r already exists in %r" % (new_name, self.id2path(new_parent_id)))

        new_parent_idpath = self.get_idpath(new_parent_id)
        if file_id in new_parent_idpath:
            raise BzrError("cannot move directory %r into a subdirectory of itself, %r"
                    % (self.id2path(file_id), self.id2path(new_parent_id)))

        file_ie = self._byid[file_id]
        old_parent = self._byid[file_ie.parent_id]

        # TODO: Don't leave things messed up if this fails

        del old_parent.children[file_ie.name]
        new_parent.children[new_name] = file_ie
        
        file_ie.name = new_name
        file_ie.parent_id = new_parent_id




_NAME_RE = None

def is_valid_name(name):
    global _NAME_RE
    if _NAME_RE == None:
        _NAME_RE = re.compile(r'^[^/\\]+$')
        
    return bool(_NAME_RE.match(name))
