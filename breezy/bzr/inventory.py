# Copyright (C) 2005-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# FIXME: This refactoring of the workingtree code doesn't seem to keep
# the WorkingTree's copy of the inventory in sync with the branch.  The
# branch modifies its working inventory when it does a commit to make
# missing files permanently removed.

# TODO: Maybe also keep the full path of the entry, and the children?
# But those depend on its position within a particular inventory, and
# it would be nice not to need to hold the backpointer here.

# This should really be an id randomly assigned when the tree is
# created, but it's not for now.
ROOT_ID = b"TREE_ROOT"

from collections import deque
from typing import Iterable, Optional, Union

from .. import errors, lazy_regex, osutils, trace
from . import chk_map


FileId = bytes


class InvalidEntryName(errors.InternalBzrError):
    _fmt = "Invalid entry name: %(name)s"

    def __init__(self, name):
        errors.BzrError.__init__(self)
        self.name = name


class DuplicateFileId(errors.BzrError):
    _fmt = "File id {%(file_id)s} already exists in inventory as %(entry)s"

    def __init__(self, file_id, entry):
        errors.BzrError.__init__(self)
        self.file_id = file_id
        self.entry = entry


class InventoryEntry:
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
    b'TREE_ROOT'
    >>> i.add(InventoryDirectory(b'123', 'src', ROOT_ID))
    InventoryDirectory(b'123', 'src', parent_id=b'TREE_ROOT', revision=None)
    >>> i.add(InventoryFile(b'2323', 'hello.c', parent_id=b'123'))
    InventoryFile(b'2323', 'hello.c', parent_id=b'123', sha1=None, len=None, revision=None)
    >>> shouldbe = {0: '', 1: 'src', 2: 'src/hello.c'}
    >>> for ix, j in enumerate(i.iter_entries()):
    ...   print(j[0] == shouldbe[ix], j[1])
    ...
    True InventoryDirectory(b'TREE_ROOT', '', parent_id=None, revision=None)
    True InventoryDirectory(b'123', 'src', parent_id=b'TREE_ROOT', revision=None)
    True InventoryFile(b'2323', 'hello.c', parent_id=b'123', sha1=None, len=None, revision=None)
    >>> i.add(InventoryFile(b'2324', 'bye.c', b'123'))
    InventoryFile(b'2324', 'bye.c', parent_id=b'123', sha1=None, len=None, revision=None)
    >>> i.add(InventoryDirectory(b'2325', 'wibble', b'123'))
    InventoryDirectory(b'2325', 'wibble', parent_id=b'123', revision=None)
    >>> i.path2id('src/wibble')
    b'2325'
    >>> i.add(InventoryFile(b'2326', 'wibble.c', b'2325'))
    InventoryFile(b'2326', 'wibble.c', parent_id=b'2325', sha1=None, len=None, revision=None)
    >>> i.get_entry(b'2326')
    InventoryFile(b'2326', 'wibble.c', parent_id=b'2325', sha1=None, len=None, revision=None)
    >>> for path, entry in i.iter_entries():
    ...     print(path)
    ...
    <BLANKLINE>
    src
    src/bye.c
    src/hello.c
    src/wibble
    src/wibble/wibble.c
    >>> i.id2path(b'2326')
    'src/wibble/wibble.c'
    """

    # Constants returned by describe_change()
    #
    # TODO: These should probably move to some kind of FileChangeDescription
    # class; that's like what's inside a TreeDelta but we want to be able to
    # generate them just for one file at a time.
    RENAMED = "renamed"
    MODIFIED_AND_RENAMED = "modified and renamed"

    __slots__ = ["file_id", "name", "parent_id", "revision"]

    # Attributes that all InventoryEntry instances are expected to have, but
    # that don't vary for all kinds of entry.  (e.g. symlink_target is only
    # relevant to InventoryLink, so there's no reason to make every
    # InventoryFile instance allocate space to hold a value for it.)
    # Attributes that only vary for files: executable, text_sha1, text_size,
    # text_id
    executable = False
    text_sha1 = None
    text_size = None
    text_id = None
    # Attributes that only vary for symlinks: symlink_target
    symlink_target = None
    # Attributes that only vary for tree-references: reference_revision
    reference_revision = None

    def detect_changes(self, old_entry):
        """Return a (text_modified, meta_modified) from this to old_entry.

        _read_tree_state must have been called on self and old_entry prior to
        calling detect_changes.
        """
        return False, False

    def _diff(
        self,
        text_diff,
        from_label,
        tree,
        to_label,
        to_entry,
        to_tree,
        output_to,
        reverse=False,
    ):
        """Perform a diff between two entries of the same kind."""

    def parent_candidates(self, previous_inventories):
        """Find possible per-file graph parents.

        This is currently defined by:
         - Select the last changed revision in the parent inventory.
         - Do deal with a short lived bug in bzr 0.8's development two entries
           that have the same last changed but different 'x' bit settings are
           changed in-place.
        """
        # revision:ie mapping for each ie found in previous_inventories.
        candidates = {}
        # identify candidate head revision ids.
        for inv in previous_inventories:
            try:
                ie = inv.get_entry(self.file_id)
            except errors.NoSuchId:
                pass
            else:
                if ie.revision in candidates:
                    # same revision value in two different inventories:
                    # correct possible inconsistencies:
                    #     * there was a bug in revision updates with 'x' bit
                    #       support.
                    try:
                        if candidates[ie.revision].executable != ie.executable:
                            candidates[ie.revision].executable = False
                            ie.executable = False
                    except AttributeError:
                        pass
                else:
                    # add this revision as a candidate.
                    candidates[ie.revision] = ie
        return candidates

    def has_text(self):
        """Return true if the object this entry represents has textual data.

        Note that textual data includes binary content.

        Also note that all entries get weave files created for them.
        This attribute is primarily used when upgrading from old trees that
        did not have the weave index for all inventory entries.
        """
        return False

    def __init__(self, file_id, name, parent_id):
        """Create an InventoryEntry.

        The filename must be a single component, relative to the
        parent directory; it cannot be a whole path or relative name.

        >>> e = InventoryFile(b'123', 'hello.c', ROOT_ID)
        >>> e.name
        'hello.c'
        >>> e.file_id
        b'123'
        >>> e = InventoryFile(b'123', 'src/hello.c', ROOT_ID)
        Traceback (most recent call last):
        breezy.bzr.inventory.InvalidEntryName: Invalid entry name: src/hello.c
        """
        if "/" in name:
            raise InvalidEntryName(name=name)
        if not isinstance(file_id, bytes):
            raise TypeError(file_id)
        self.file_id = file_id
        self.revision = None
        self.name = name
        self.parent_id = parent_id

    def kind_character(self):
        """Return a short kind indicator useful for appending to names."""
        raise errors.BzrError("unknown kind {!r}".format(self.kind))

    known_kinds = ("file", "directory", "symlink")

    @staticmethod
    def versionable_kind(kind):
        return kind in ("file", "directory", "symlink", "tree-reference")

    def check(self, checker, rev_id, inv):
        """Check this inventory entry is intact.

        This is a template method, override _check for kind specific
        tests.

        :param checker: Check object providing context for the checks;
             can be used to find out what parts of the repository have already
             been checked.
        :param rev_id: Revision id from which this InventoryEntry was loaded.
             Not necessarily the last-changed revision for this file.
        :param inv: Inventory from which the entry was loaded.
        """
        if self.parent_id is not None:
            if not inv.has_id(self.parent_id):
                raise errors.BzrCheckError(
                    "missing parent {{{}}} in inventory for revision {{{}}}".format(
                        self.parent_id, rev_id
                    )
                )
        checker._add_entry_to_text_key_references(inv, self)
        self._check(checker, rev_id)

    def _check(self, checker, rev_id):
        """Check this inventory entry for kind specific errors."""
        checker._report_items.append(
            "unknown entry kind {!r} in revision {{{}}}".format(self.kind, rev_id)
        )

    def copy(self):
        """Clone this inventory entry."""
        raise NotImplementedError

    @staticmethod
    def describe_change(old_entry, new_entry):
        """Describe the change between old_entry and this.

        This smells of being an InterInventoryEntry situation, but as its
        the first one, we're making it a static method for now.

        An entry with a different parent, or different name is considered
        to be renamed. Reparenting is an internal detail.
        Note that renaming the parent does not trigger a rename for the
        child entry itself.
        """
        # TODO: Perhaps return an object rather than just a string
        if old_entry is new_entry:
            # also the case of both being None
            return "unchanged"
        elif old_entry is None:
            return "added"
        elif new_entry is None:
            return "removed"
        if old_entry.kind != new_entry.kind:
            return "modified"
        text_modified, meta_modified = new_entry.detect_changes(old_entry)
        if text_modified or meta_modified:
            modified = True
        else:
            modified = False
        # TODO 20060511 (mbp, rbc) factor out 'detect_rename' here.
        if old_entry.parent_id != new_entry.parent_id:
            renamed = True
        elif old_entry.name != new_entry.name:
            renamed = True
        else:
            renamed = False
        if renamed and not modified:
            return InventoryEntry.RENAMED
        if modified and not renamed:
            return "modified"
        if modified and renamed:
            return InventoryEntry.MODIFIED_AND_RENAMED
        return "unchanged"

    def __repr__(self):
        return "{}({!r}, {!r}, parent_id={!r}, revision={!r})".format(
            self.__class__.__name__,
            self.file_id,
            self.name,
            self.parent_id,
            self.revision,
        )

    def is_unmodified(self, other):
        other_revision = getattr(other, "revision", None)
        if other_revision is None:
            return False
        return self.revision == other.revision

    def __eq__(self, other):
        if other is self:
            # For the case when objects are cached
            return True
        if not isinstance(other, InventoryEntry):
            return NotImplemented

        return (
            (self.file_id == other.file_id)
            and (self.name == other.name)
            and (other.symlink_target == self.symlink_target)
            and (self.text_sha1 == other.text_sha1)
            and (self.text_size == other.text_size)
            and (self.text_id == other.text_id)
            and (self.parent_id == other.parent_id)
            and (self.kind == other.kind)
            and (self.revision == other.revision)
            and (self.executable == other.executable)
            and (self.reference_revision == other.reference_revision)
        )

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        raise ValueError("not hashable")

    def _unchanged(self, previous_ie):
        """Has this entry changed relative to previous_ie.

        This method should be overridden in child classes.
        """
        compatible = True
        # different inv parent
        if previous_ie.parent_id != self.parent_id:
            compatible = False
        # renamed
        elif previous_ie.name != self.name:
            compatible = False
        elif previous_ie.kind != self.kind:
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
        pass  # nothing to do by default

    def _forget_tree_state(self):
        pass


class InventoryDirectory(InventoryEntry):
    """A directory in an inventory."""

    __slots__ = ["children"]

    kind = "directory"

    def _check(self, checker, rev_id):
        """See InventoryEntry._check."""
        # In non rich root repositories we do not expect a file graph for the
        # root.
        if self.name == "" and not checker.rich_roots:
            return
        # Directories are stored as an empty file, but the file should exist
        # to provide a per-fileid log. The hash of every directory content is
        # "da..." below (the sha1sum of '').
        checker.add_pending_item(
            rev_id,
            ("texts", self.file_id, self.revision),
            b"text",
            b"da39a3ee5e6b4b0d3255bfef95601890afd80709",
        )

    def copy(self):
        other = InventoryDirectory(self.file_id, self.name, self.parent_id)
        other.revision = self.revision
        # note that children are *not* copied; they're pulled across when
        # others are added
        return other

    def __init__(self, file_id, name, parent_id):
        super().__init__(file_id, name, parent_id)
        self.children = {}

    def sorted_children(self):
        return sorted(self.children.items())

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return "/"


class InventoryFile(InventoryEntry):
    """A file in an inventory."""

    __slots__ = ["executable", "text_id", "text_sha1", "text_size"]

    kind = "file"

    def __init__(self, file_id, name, parent_id):
        super().__init__(file_id, name, parent_id)
        self.text_sha1 = None
        self.text_size = None
        self.text_id = None
        self.executable = False

    def _check(self, checker, tree_revision_id):
        """See InventoryEntry._check."""
        # TODO: check size too.
        checker.add_pending_item(
            tree_revision_id,
            ("texts", self.file_id, self.revision),
            b"text",
            self.text_sha1,
        )
        if self.text_size is None:
            checker._report_items.append(
                "fileid {{{}}} in {{{}}} has None for text_size".format(
                    self.file_id, tree_revision_id
                )
            )

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
        text_modified = self.text_sha1 != old_entry.text_sha1
        meta_modified = self.executable != old_entry.executable
        return text_modified, meta_modified

    def _diff(
        self,
        text_diff,
        from_label,
        tree,
        to_label,
        to_entry,
        to_tree,
        output_to,
        reverse=False,
    ):
        """See InventoryEntry._diff."""
        from breezy.diff import DiffText

        from_file_id = self.file_id
        if to_entry:
            to_file_id = to_entry.file_id
            to_path = to_tree.id2path(to_file_id)
        else:
            to_file_id = None
            to_path = None
        if from_file_id is not None:
            from_path = tree.id2path(from_file_id)
        else:
            from_path = None
        if reverse:
            to_file_id, from_file_id = from_file_id, to_file_id
            tree, to_tree = to_tree, tree
            from_label, to_label = to_label, from_label
        differ = DiffText(tree, to_tree, output_to, "utf-8", "", "", text_diff)
        return differ.diff_text(
            from_path, to_path, from_label, to_label, from_file_id, to_file_id
        )

    def has_text(self):
        """See InventoryEntry.has_text."""
        return True

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ""

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.text_sha1 = work_tree.get_file_sha1(path)
        # FIXME: 20050930 probe for the text size when getting sha1
        # in _read_tree_state
        self.executable = work_tree.is_executable(path)

    def __repr__(self):
        return "{}({!r}, {!r}, parent_id={!r}, sha1={!r}, len={}, revision={})".format(
            self.__class__.__name__,
            self.file_id,
            self.name,
            self.parent_id,
            self.text_sha1,
            self.text_size,
            self.revision,
        )

    def _forget_tree_state(self):
        self.text_sha1 = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super()._unchanged(previous_ie)
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

    __slots__ = ["symlink_target"]

    kind = "symlink"

    def __init__(self, file_id, name, parent_id):
        super().__init__(file_id, name, parent_id)
        self.symlink_target = None

    def _check(self, checker, tree_revision_id):
        """See InventoryEntry._check."""
        if self.symlink_target is None:
            checker._report_items.append(
                "symlink {{{}}} has no target in revision {{{}}}".format(
                    self.file_id, tree_revision_id
                )
            )
        # Symlinks are stored as ''
        checker.add_pending_item(
            tree_revision_id,
            ("texts", self.file_id, self.revision),
            b"text",
            b"da39a3ee5e6b4b0d3255bfef95601890afd80709",
        )

    def copy(self):
        other = InventoryLink(self.file_id, self.name, self.parent_id)
        other.symlink_target = self.symlink_target
        other.revision = self.revision
        return other

    def detect_changes(self, old_entry):
        """See InventoryEntry.detect_changes."""
        # FIXME: which _modified field should we use ? RBC 20051003
        text_modified = self.symlink_target != old_entry.symlink_target
        if text_modified:
            trace.mutter("    symlink target changed")
        meta_modified = False
        return text_modified, meta_modified

    def _diff(
        self,
        text_diff,
        from_label,
        tree,
        to_label,
        to_entry,
        to_tree,
        output_to,
        reverse=False,
    ):
        """See InventoryEntry._diff."""
        from breezy.diff import DiffSymlink

        old_target = self.symlink_target
        if to_entry is not None:
            new_target = to_entry.symlink_target
        else:
            new_target = None
        if not reverse:
            old_tree = tree
            new_tree = to_tree
        else:
            old_tree = to_tree
            new_tree = tree
            new_target, old_target = old_target, new_target
        differ = DiffSymlink(old_tree, new_tree, output_to)
        return differ.diff_symlink(old_target, new_target)

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ""

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.symlink_target = work_tree.get_symlink_target(
            work_tree.id2path(self.file_id), self.file_id
        )

    def _forget_tree_state(self):
        self.symlink_target = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super()._unchanged(previous_ie)
        if self.symlink_target != previous_ie.symlink_target:
            compatible = False
        return compatible


class TreeReference(InventoryEntry):
    __slots__ = ["reference_revision"]

    kind = "tree-reference"

    def __init__(
        self, file_id, name, parent_id, revision=None, reference_revision=None
    ):
        InventoryEntry.__init__(self, file_id, name, parent_id)
        self.revision = revision
        self.reference_revision = reference_revision

    def copy(self):
        return TreeReference(
            self.file_id,
            self.name,
            self.parent_id,
            self.revision,
            self.reference_revision,
        )

    def _read_tree_state(self, path, work_tree):
        """Populate fields in the inventory entry from the given tree."""
        self.reference_revision = work_tree.get_reference_revision(path, self.file_id)

    def _forget_tree_state(self):
        self.reference_revision = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super()._unchanged(previous_ie)
        if self.reference_revision != previous_ie.reference_revision:
            compatible = False
        return compatible

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return "+"


class CommonInventory:
    """Basic inventory logic, defined in terms of primitives like has_id.

    An inventory is the metadata about the contents of a tree.

    This is broadly a map from file_id to entries such as directories, files,
    symlinks and tree references. Each entry maintains its own metadata like
    SHA1 and length for files, or children for a directory.

    Entries can be looked up either by path or by file_id.

    InventoryEntry objects must not be modified after they are
    inserted, other than through the Inventory API.
    """

    def has_filename(self, filename):
        return bool(self.path2id(filename))

    def id2path(self, file_id):
        """Return as a string the path to file_id.

        >>> i = Inventory()
        >>> e = i.add(InventoryDirectory(b'src-id', 'src', ROOT_ID))
        >>> e = i.add(InventoryFile(b'foo-id', 'foo.c', parent_id=b'src-id'))
        >>> print(i.id2path(b'foo-id'))
        src/foo.c

        :raises NoSuchId: If file_id is not present in the inventory.
        """
        # get all names, skipping root
        return "/".join(
            reversed(
                [parent.name for parent in self._iter_file_id_parents(file_id)][:-1]
            )
        )

    def iter_entries(self, from_dir=None, recursive=True):
        """Return (path, entry) pairs, in order by name.

        :param from_dir: if None, start from the root,
          otherwise start from this directory (either file-id or entry)
        :param recursive: recurse into directories or not
        """
        if from_dir is None:
            if self.root is None:
                return
            from_dir = self.root
            yield "", self.root
        elif isinstance(from_dir, bytes):
            from_dir = self.get_entry(from_dir)

        # unrolling the recursive called changed the time from
        # 440ms/663ms (inline/total) to 116ms/116ms
        children = sorted(from_dir.children.items())
        if not recursive:
            yield from children
            return
        children = deque(children)
        stack = [("", children)]
        while stack:
            from_dir_relpath, children = stack[-1]

            while children:
                name, ie = children.popleft()

                # we know that from_dir_relpath never ends in a slash
                # and 'f' doesn't begin with one, we can do a string op, rather
                # than the checks of pathjoin(), though this means that all paths
                # start with a slash
                path = from_dir_relpath + "/" + name

                yield path[1:], ie

                if ie.kind != "directory":
                    continue

                # But do this child first
                new_children = sorted(ie.children.items())
                new_children = deque(new_children)
                stack.append((path, new_children))
                # Break out of inner loop, so that we start outer loop with child
                break
            else:
                # if we finished all children, pop it off the stack
                stack.pop()

    def _preload_cache(self):
        """Populate any caches, we are about to access all items.

        The default implementation does nothing, because CommonInventory doesn't
        have a cache.
        """
        pass

    def iter_entries_by_dir(self, from_dir=None, specific_file_ids=None):
        """Iterate over the entries in a directory first order.

        This returns all entries for a directory before returning
        the entries for children of a directory. This is not
        lexicographically sorted order, and is a hybrid between
        depth-first and breadth-first.

        :return: This yields (path, entry) pairs
        """
        if specific_file_ids and not isinstance(specific_file_ids, set):
            specific_file_ids = set(specific_file_ids)
        # TODO? Perhaps this should return the from_dir so that the root is
        # yielded? or maybe an option?
        if from_dir is None and specific_file_ids is None:
            # They are iterating from the root, and have not specified any
            # specific entries to look at. All current callers fully consume the
            # iterator, so we can safely assume we are accessing all entries
            self._preload_cache()
        if from_dir is None:
            if self.root is None:
                return
            # Optimize a common case
            if specific_file_ids is not None and len(specific_file_ids) == 1:
                file_id = list(specific_file_ids)[0]
                if file_id is not None:
                    try:
                        path = self.id2path(file_id)
                    except errors.NoSuchId:
                        pass
                    else:
                        yield path, self.get_entry(file_id)
                return
            from_dir = self.root
            if specific_file_ids is None or self.root.file_id in specific_file_ids:
                yield "", self.root
        elif isinstance(from_dir, bytes):
            from_dir = self.get_entry(from_dir)
        else:
            raise TypeError(from_dir)

        if specific_file_ids is not None:
            # TODO: jam 20070302 This could really be done as a loop rather
            #       than a bunch of recursive calls.
            parents = set()
            byid = self

            def add_ancestors(file_id):
                if not byid.has_id(file_id):
                    return
                parent_id = byid.get_entry(file_id).parent_id
                if parent_id is None:
                    return
                if parent_id not in parents:
                    parents.add(parent_id)
                    add_ancestors(parent_id)

            for file_id in specific_file_ids:
                add_ancestors(file_id)
        else:
            parents = None

        stack = [("", from_dir)]
        while stack:
            cur_relpath, cur_dir = stack.pop()

            child_dirs = []
            for child_name, child_ie in sorted(cur_dir.children.items()):
                child_relpath = cur_relpath + child_name

                if specific_file_ids is None or child_ie.file_id in specific_file_ids:
                    yield child_relpath, child_ie

                if child_ie.kind == "directory":
                    if parents is None or child_ie.file_id in parents:
                        child_dirs.append((child_relpath + "/", child_ie))
            stack.extend(reversed(child_dirs))

    def _make_delta(self, old):
        """Make an inventory delta from two inventories."""
        old_ids = set(old.iter_all_ids())
        new_ids = set(self.iter_all_ids())
        adds = new_ids - old_ids
        deletes = old_ids - new_ids
        common = old_ids.intersection(new_ids)
        delta = []
        for file_id in deletes:
            delta.append((old.id2path(file_id), None, file_id, None))
        for file_id in adds:
            delta.append(
                (None, self.id2path(file_id), file_id, self.get_entry(file_id))
            )
        for file_id in common:
            if old.get_entry(file_id) != self.get_entry(file_id):
                delta.append(
                    (
                        old.id2path(file_id),
                        self.id2path(file_id),
                        file_id,
                        self.get_entry(file_id),
                    )
                )
        return delta

    def make_entry(self, kind, name, parent_id, file_id=None):
        """Simple thunk to breezy.bzr.inventory.make_entry."""
        return make_entry(kind, name, parent_id, file_id)

    def entries(self):
        """Return list of (path, ie) for all entries except the root.

        This may be faster than iter_entries.
        """
        accum = []

        def descend(dir_ie, dir_path):
            kids = sorted(dir_ie.children.items())
            for name, ie in kids:
                child_path = osutils.pathjoin(dir_path, name)
                accum.append((child_path, ie))
                if ie.kind == "directory":
                    descend(ie, child_path)

        if self.root is not None:
            descend(self.root, "")
        return accum

    def get_entry_by_path_partial(self, relpath):
        """Like get_entry_by_path, but return TreeReference objects.

        :param relpath: Path to resolve, either as string with / as separators,
            or as list of elements.
        :return: tuple with ie, resolved elements and elements left to resolve
        """
        if isinstance(relpath, str):
            names = osutils.splitpath(relpath)
        else:
            names = relpath

        try:
            parent = self.root
        except errors.NoSuchId:
            # root doesn't exist yet so nothing else can
            return None, None, None
        if parent is None:
            return None, None, None
        for i, f in enumerate(names):
            try:
                children = getattr(parent, "children", None)
                if children is None:
                    return None, None, None
                cie = children[f]
                if cie.kind == "tree-reference":
                    return cie, names[: i + 1], names[i + 1 :]
                parent = cie
            except KeyError:
                # or raise an error?
                return None, None, None
        return parent, names, []

    def get_entry_by_path(self, relpath):
        """Return an inventory entry by path.

        :param relpath: may be either a list of path components, or a single
            string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.

        Returns None IFF the path is not found.
        """
        if isinstance(relpath, str):
            names = osutils.splitpath(relpath)
        else:
            names = relpath

        try:
            parent = self.root
        except errors.NoSuchId:
            # root doesn't exist yet so nothing else can
            return None
        if parent is None:
            return None
        for f in names:
            try:
                children = getattr(parent, "children", None)
                if children is None:
                    return None
                cie = children[f]
                parent = cie
            except KeyError:
                # or raise an error?
                return None
        return parent

    def path2id(self, relpath):
        """Walk down through directories to return entry of last component.

        :param relpath: may be either a list of path components, or a single
            string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.

        Returns None IFF the path is not found.
        """
        ie = self.get_entry_by_path(relpath)
        if ie is None:
            return None
        return ie.file_id

    def filter(self, specific_fileids):
        """Get an inventory view filtered against a set of file-ids.

        Children of directories and parents are included.

        The result may or may not reference the underlying inventory
        so it should be treated as immutable.
        """
        interesting_parents = set()
        for fileid in specific_fileids:
            try:
                interesting_parents.update(self.get_idpath(fileid))
            except errors.NoSuchId:
                # This fileid is not in the inventory - that's ok
                pass
        entries = self.iter_entries()
        if self.root is None:
            return Inventory(root_id=None)
        other = Inventory(next(entries)[1].file_id)
        other.root.revision = self.root.revision
        other.revision_id = self.revision_id
        directories_to_expand = set()
        for _path, entry in entries:
            file_id = entry.file_id
            if file_id in specific_fileids or entry.parent_id in directories_to_expand:
                if entry.kind == "directory":
                    directories_to_expand.add(file_id)
            elif file_id not in interesting_parents:
                continue
            other.add(entry.copy())
        return other

    def get_idpath(self, file_id: FileId) -> list[FileId]:
        """Return a list of file_ids for the path to an entry.

        The list contains one element for each directory followed by
        the id of the file itself.  So the length of the returned list
        is equal to the depth of the file in the tree, counting the
        root directory as depth 1.
        """
        raise NotImplementedError(self.get_idpath)


class Inventory(CommonInventory):
    """Mutable dict based in-memory inventory.

    We never store the full path to a file, because renaming a directory
    implicitly moves all of its contents.  This class internally maintains a
    lookup tree that allows the children under a directory to be
    returned quickly.

    >>> inv = Inventory()
    >>> inv.add(InventoryFile(b'123-123', 'hello.c', ROOT_ID))
    InventoryFile(b'123-123', 'hello.c', parent_id=b'TREE_ROOT', sha1=None, len=None, revision=None)
    >>> inv.get_entry(b'123-123').name
    'hello.c'

    Id's may be looked up from paths:

    >>> inv.path2id('hello.c')
    b'123-123'
    >>> inv.has_id(b'123-123')
    True

    There are iterators over the contents:

    >>> [entry[0] for entry in inv.iter_entries()]
    ['', 'hello.c']
    """

    def __init__(self, root_id=ROOT_ID, revision_id=None):
        """Create or read an inventory.

        If a working directory is specified, the inventory is read
        from there.  If the file is specified, read from that. If not,
        the inventory is created empty.

        The inventory is created with a default root directory, with
        an id of None.
        """
        if root_id is not None:
            self._set_root(InventoryDirectory(root_id, "", None))
        else:
            self.root = None
            self._byid = {}
        self.revision_id = revision_id

    def __repr__(self):
        # More than one page of ouput is not useful anymore to debug
        max_len = 2048
        closing = "...}"
        contents = repr(self._byid)
        if len(contents) > max_len:
            contents = contents[: (max_len - len(closing))] + closing
        return "<Inventory object at {:x}, contents={!r}>".format(id(self), contents)

    def apply_delta(self, delta):
        """Apply a delta to this inventory.

        See the inventory developers documentation for the theory behind
        inventory deltas.

        If delta application fails the inventory is left in an indeterminate
        state and must not be used.

        :param delta: A list of changes to apply. After all the changes are
            applied the final inventory must be internally consistent, but it
            is ok to supply changes which, if only half-applied would have an
            invalid result - such as supplying two changes which rename two
            files, 'A' and 'B' with each other : [('A', 'B', b'A-id', a_entry),
            ('B', 'A', b'B-id', b_entry)].

            Each change is a tuple, of the form (old_path, new_path, file_id,
            new_entry).

            When new_path is None, the change indicates the removal of an entry
            from the inventory and new_entry will be ignored (using None is
            appropriate). If new_path is not None, then new_entry must be an
            InventoryEntry instance, which will be incorporated into the
            inventory (and replace any existing entry with the same file id).

            When old_path is None, the change indicates the addition of
            a new entry to the inventory.

            When neither new_path nor old_path are None, the change is a
            modification to an entry, such as a rename, reparent, kind change
            etc.

            The children attribute of new_entry is ignored. This is because
            this method preserves children automatically across alterations to
            the parent of the children, and cases where the parent id of a
            child is changing require the child to be passed in as a separate
            change regardless. E.g. in the recursive deletion of a directory -
            the directory's children must be included in the delta, or the
            final inventory will be invalid.

            Note that a file_id must only appear once within a given delta.
            An AssertionError is raised otherwise.
        """
        # Check that the delta is legal. It would be nice if this could be
        # done within the loops below but it's safer to validate the delta
        # before starting to mutate the inventory, as there isn't a rollback
        # facility.
        list(
            _check_delta_unique_ids(
                _check_delta_unique_new_paths(
                    _check_delta_unique_old_paths(
                        _check_delta_ids_match_entry(
                            _check_delta_ids_are_valid(
                                _check_delta_new_path_entry_both_or_None(delta)
                            )
                        )
                    )
                )
            )
        )

        children = {}
        # Remove all affected items which were in the original inventory,
        # starting with the longest paths, thus ensuring parents are examined
        # after their children, which means that everything we examine has no
        # modified children remaining by the time we examine it.
        for old_path, file_id in sorted(
            ((op, f) for op, np, f, e in delta if op is not None), reverse=True
        ):
            # Preserve unaltered children of file_id for later reinsertion.
            file_id_children = getattr(self.get_entry(file_id), "children", {})
            if len(file_id_children):
                children[file_id] = file_id_children
            if self.id2path(file_id) != old_path:
                raise errors.InconsistentDelta(
                    old_path,
                    file_id,
                    "Entry was at wrong other path {!r}.".format(self.id2path(file_id)),
                )
            # Remove file_id and the unaltered children. If file_id is not
            # being deleted it will be reinserted back later.
            self.remove_recursive_id(file_id)
        # Insert all affected which should be in the new inventory, reattaching
        # their children if they had any. This is done from shortest path to
        # longest, ensuring that items which were modified and whose parents in
        # the resulting inventory were also modified, are inserted after their
        # parents.
        for new_path, _f, new_entry in sorted(
            (np, f, e) for op, np, f, e in delta if np is not None
        ):
            if new_entry.kind == "directory":
                # Pop the child which to allow detection of children whose
                # parents were deleted and which were not reattached to a new
                # parent.
                replacement = InventoryDirectory(
                    new_entry.file_id, new_entry.name, new_entry.parent_id
                )
                replacement.revision = new_entry.revision
                replacement.children = children.pop(replacement.file_id, {})
                new_entry = replacement
            try:
                self.add(new_entry)
            except DuplicateFileId as e:
                raise errors.InconsistentDelta(
                    new_path, new_entry.file_id, "New id is already present in target."
                ) from e
            except AttributeError as e:
                raise errors.InconsistentDelta(
                    new_path, new_entry.file_id, "Parent is not a directory."
                ) from e
            if self.id2path(new_entry.file_id) != new_path:
                raise errors.InconsistentDelta(
                    new_path,
                    new_entry.file_id,
                    "New path is not consistent with parent path.",
                )
        if len(children):
            # Get the parent id that was deleted
            parent_id, children = children.popitem()
            raise errors.InconsistentDelta(
                "<deleted>",
                parent_id,
                "The file id was deleted but its children were not deleted.",
            )

    def create_by_apply_delta(
        self, inventory_delta, new_revision_id, propagate_caches=False
    ):
        """See CHKInventory.create_by_apply_delta()."""
        new_inv = self.copy()
        new_inv.apply_delta(inventory_delta)
        new_inv.revision_id = new_revision_id
        return new_inv

    def _set_root(self, ie):
        self.root = ie
        self._byid = {self.root.file_id: self.root}

    def copy(self):
        # TODO: jam 20051218 Should copy also copy the revision_id?
        entries = self.iter_entries()
        if self.root is None:
            return Inventory(root_id=None)
        other = Inventory(next(entries)[1].file_id)
        other.root.revision = self.root.revision
        # copy recursively so we know directories will be added before
        # their children.  There are more efficient ways than this...
        for _path, entry in entries:
            other.add(entry.copy())
        return other

    def get_idpath(self, file_id: FileId) -> list[FileId]:
        """Return a list of file_ids for the path to an entry.

        The list contains one element for each directory followed by
        the id of the file itself.  So the length of the returned list
        is equal to the depth of the file in the tree, counting the
        root directory as depth 1.
        """
        p: list[FileId] = []
        for parent in self._iter_file_id_parents(file_id):
            p.insert(0, parent.file_id)
        return p

    def iter_all_ids(self):
        """Iterate over all file-ids."""
        return iter(self._byid)

    def iter_just_entries(self):
        """Iterate over all entries.

        Unlike iter_entries(), just the entries are returned (not (path, ie))
        and the order of entries is undefined.

        XXX: We may not want to merge this into bzr.dev.
        """
        if self.root is None:
            return ()
        return self._byid.values()

    def __len__(self):
        """Returns number of entries."""
        return len(self._byid)

    def get_entry(self, file_id):
        """Return the entry for given file_id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile(b'123123', 'hello.c', ROOT_ID))
        InventoryFile(b'123123', 'hello.c', parent_id=b'TREE_ROOT', sha1=None, len=None, revision=None)
        >>> inv.get_entry(b'123123').name
        'hello.c'
        """
        if not isinstance(file_id, bytes):
            raise TypeError(file_id)
        try:
            return self._byid[file_id]
        except KeyError as e:
            # really we're passing an inventory, not a tree...
            raise errors.NoSuchId(self, file_id) from e

    def get_file_kind(self, file_id):
        return self._byid[file_id].kind

    def get_child(self, parent_id, filename):
        return self.get_entry(parent_id).children.get(filename)

    def _add_child(self, entry):
        """Add an entry to the inventory, without adding it to its parent."""
        if entry.file_id in self._byid:
            raise errors.BzrError(
                "inventory already contains entry with id {{{}}}".format(entry.file_id)
            )
        self._byid[entry.file_id] = entry
        children = getattr(entry, "children", {})
        if children is not None:
            for child in children.values():
                self._add_child(child)
        return entry

    def add(self, entry):
        """Add entry to inventory.

        :return: entry
        """
        if entry.file_id in self._byid:
            raise DuplicateFileId(entry.file_id, self._byid[entry.file_id])
        if entry.parent_id is None:
            self.root = entry
        else:
            try:
                parent = self._byid[entry.parent_id]
            except KeyError as e:
                raise errors.InconsistentDelta(
                    "<unknown>", entry.parent_id, "Parent not in inventory."
                ) from e
            if entry.name in parent.children:
                raise errors.InconsistentDelta(
                    self.id2path(parent.children[entry.name].file_id),
                    entry.file_id,
                    "Path already versioned",
                )
            parent.children[entry.name] = entry
        return self._add_child(entry)

    def add_path(self, relpath, kind, file_id=None, parent_id=None):
        """Add entry from a path.

        The immediate parent must already be versioned.

        Returns the new entry object.
        """
        parts = osutils.splitpath(relpath)

        if len(parts) == 0:
            if file_id is None:
                from . import generate_ids

                file_id = generate_ids.gen_root_id()
            self.root = InventoryDirectory(file_id, "", None)
            self._byid = {self.root.file_id: self.root}
            return self.root
        else:
            parent_path = parts[:-1]
            parent_id = self.path2id(parent_path)
            if parent_id is None:
                raise errors.NotVersionedError(path=parent_path)
        ie = make_entry(kind, parts[-1], parent_id, file_id)
        return self.add(ie)

    def delete(self, file_id):
        """Remove entry by id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile(b'123', 'foo.c', ROOT_ID))
        InventoryFile(b'123', 'foo.c', parent_id=b'TREE_ROOT', sha1=None, len=None, revision=None)
        >>> inv.has_id(b'123')
        True
        >>> inv.delete(b'123')
        >>> inv.has_id(b'123')
        False
        """
        ie = self.get_entry(file_id)
        del self._byid[file_id]
        if ie.parent_id is not None:
            del self.get_entry(ie.parent_id).children[ie.name]

    def __eq__(self, other):
        """Compare two sets by comparing their contents.

        >>> i1 = Inventory()
        >>> i2 = Inventory()
        >>> i1 == i2
        True
        >>> i1.add(InventoryFile(b'123', 'foo', ROOT_ID))
        InventoryFile(b'123', 'foo', parent_id=b'TREE_ROOT', sha1=None, len=None, revision=None)
        >>> i1 == i2
        False
        >>> i2.add(InventoryFile(b'123', 'foo', ROOT_ID))
        InventoryFile(b'123', 'foo', parent_id=b'TREE_ROOT', sha1=None, len=None, revision=None)
        >>> i1 == i2
        True
        """
        if not isinstance(other, Inventory):
            return NotImplemented

        return self._byid == other._byid

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        raise ValueError("not hashable")

    def _iter_file_id_parents(self, file_id):
        """Yield the parents of file_id up to the root."""
        while file_id is not None:
            try:
                ie = self._byid[file_id]
            except KeyError as e:
                raise errors.NoSuchId(tree=None, file_id=file_id) from e
            yield ie
            file_id = ie.parent_id

    def has_id(self, file_id):
        return file_id in self._byid

    def _make_delta(self, old):
        """Make an inventory delta from two inventories."""
        old_getter = old.get_entry
        new_getter = self.get_entry
        old_ids = set(old.iter_all_ids())
        new_ids = set(self.iter_all_ids())
        adds = new_ids - old_ids
        deletes = old_ids - new_ids
        if not adds and not deletes:
            common = new_ids
        else:
            common = old_ids.intersection(new_ids)
        delta = []
        for file_id in deletes:
            delta.append((old.id2path(file_id), None, file_id, None))
        for file_id in adds:
            delta.append(
                (None, self.id2path(file_id), file_id, self.get_entry(file_id))
            )
        for file_id in common:
            new_ie = new_getter(file_id)
            old_ie = old_getter(file_id)
            # If xml_serializer returns the cached InventoryEntries (rather
            # than always doing .copy()), inlining the 'is' check saves 2.7M
            # calls to __eq__.  Under lsprof this saves 20s => 6s.
            # It is a minor improvement without lsprof.
            if old_ie is new_ie or old_ie == new_ie:
                continue
            else:
                delta.append(
                    (old.id2path(file_id), self.id2path(file_id), file_id, new_ie)
                )
        return delta

    def remove_recursive_id(self, file_id):
        """Remove file_id, and children, from the inventory.

        :param file_id: A file_id to remove.
        """
        to_find_delete = [self._byid[file_id]]
        to_delete = []
        while to_find_delete:
            ie = to_find_delete.pop()
            to_delete.append(ie.file_id)
            if ie.kind == "directory":
                to_find_delete.extend(ie.children.values())
        for file_id in reversed(to_delete):
            ie = self.get_entry(file_id)
            del self._byid[file_id]
        if ie.parent_id is not None:
            del self.get_entry(ie.parent_id).children[ie.name]
        else:
            self.root = None

    def rename(self, file_id, new_parent_id, new_name):
        """Move a file within the inventory.

        This can change either the name, or the parent, or both.

        This does not move the working file.
        """
        new_name = ensure_normalized_name(new_name)
        if not is_valid_name(new_name):
            raise errors.BzrError("not an acceptable filename: {!r}".format(new_name))

        new_parent = self._byid[new_parent_id]
        if new_name in new_parent.children:
            raise errors.BzrError(
                "{!r} already exists in {!r}".format(
                    new_name, self.id2path(new_parent_id)
                )
            )

        new_parent_idpath = self.get_idpath(new_parent_id)
        if file_id in new_parent_idpath:
            raise errors.BzrError(
                "cannot move directory {!r} into a subdirectory of itself, {!r}".format(
                    self.id2path(file_id), self.id2path(new_parent_id)
                )
            )

        file_ie = self._byid[file_id]
        old_parent = self._byid[file_ie.parent_id]

        # TODO: Don't leave things messed up if this fails

        del old_parent.children[file_ie.name]
        new_parent.children[new_name] = file_ie

        file_ie.name = new_name
        file_ie.parent_id = new_parent_id

    def is_root(self, file_id):
        return self.root is not None and file_id == self.root.file_id


class CHKInventory(CommonInventory):
    """An inventory persisted in a CHK store.

    By design, a CHKInventory is immutable so many of the methods
    supported by Inventory - add, rename, apply_delta, etc - are *not*
    supported. To create a new CHKInventory, use create_by_apply_delta()
    or from_inventory(), say.

    Internally, a CHKInventory has one or two CHKMaps:

    * id_to_entry - a map from (file_id,) => InventoryEntry as bytes
    * parent_id_basename_to_file_id - a map from (parent_id, basename_utf8)
        => file_id as bytes

    The second map is optional and not present in early CHkRepository's.

    No caching is performed: every method call or item access will perform
    requests to the storage layer. As such, keep references to objects you
    want to reuse.
    """

    id_to_entry: chk_map.CHKMap

    def __init__(self, search_key_name):
        CommonInventory.__init__(self)
        self._fileid_to_entry_cache = {}
        self._fully_cached = False
        self._path_to_fileid_cache = {}
        self._search_key_name = search_key_name
        self.root_id = None

    def __eq__(self, other):
        """Compare two sets by comparing their contents."""
        if not isinstance(other, CHKInventory):
            return NotImplemented

        this_key = self.id_to_entry.key()
        other_key = other.id_to_entry.key()
        this_pid_key = self.parent_id_basename_to_file_id.key()
        other_pid_key = other.parent_id_basename_to_file_id.key()
        if None in (this_key, this_pid_key, other_key, other_pid_key):
            return False
        return this_key == other_key and this_pid_key == other_pid_key

    def _entry_to_bytes(self, entry):
        r"""Serialise entry as a single bytestring.

        :param Entry: An inventory entry.
        :return: A bytestring for the entry.

        The BNF:
        ENTRY ::= FILE | DIR | SYMLINK | TREE
        FILE ::= "file: " COMMON SEP SHA SEP SIZE SEP EXECUTABLE
        DIR ::= "dir: " COMMON
        SYMLINK ::= "symlink: " COMMON SEP TARGET_UTF8
        TREE ::= "tree: " COMMON REFERENCE_REVISION
        COMMON ::= FILE_ID SEP PARENT_ID SEP NAME_UTF8 SEP REVISION
        SEP ::= "\n"
        """
        if entry.parent_id is not None:
            parent_str = entry.parent_id
        else:
            parent_str = b""
        name_str = entry.name.encode("utf8")
        if entry.kind == "file":
            if entry.executable:
                exec_str = b"Y"
            else:
                exec_str = b"N"
            return b"file: %s\n%s\n%s\n%s\n%s\n%d\n%s" % (
                entry.file_id,
                parent_str,
                name_str,
                entry.revision,
                entry.text_sha1,
                entry.text_size,
                exec_str,
            )
        elif entry.kind == "directory":
            return b"dir: %s\n%s\n%s\n%s" % (
                entry.file_id,
                parent_str,
                name_str,
                entry.revision,
            )
        elif entry.kind == "symlink":
            return b"symlink: %s\n%s\n%s\n%s\n%s" % (
                entry.file_id,
                parent_str,
                name_str,
                entry.revision,
                entry.symlink_target.encode("utf8"),
            )
        elif entry.kind == "tree-reference":
            return b"tree: %s\n%s\n%s\n%s\n%s" % (
                entry.file_id,
                parent_str,
                name_str,
                entry.revision,
                entry.reference_revision,
            )
        else:
            raise ValueError("unknown kind {!r}".format(entry.kind))

    def _expand_fileids_to_parents_and_children(self, file_ids):
        """Give a more wholistic view starting with the given file_ids.

        For any file_id which maps to a directory, we will include all children
        of that directory. We will also include all directories which are
        parents of the given file_ids, but we will not include their children.

        eg:
          /     # TREE_ROOT
          foo/  # foo-id
            baz # baz-id
            frob/ # frob-id
              fringle # fringle-id
          bar/  # bar-id
            bing # bing-id

        if given [foo-id] we will include
            TREE_ROOT as interesting parents
        and
            foo-id, baz-id, frob-id, fringle-id
        As interesting ids.
        """
        interesting = set()
        # TODO: Pre-pass over the list of fileids to see if anything is already
        #       deserialized in self._fileid_to_entry_cache

        directories_to_expand = set()
        children_of_parent_id = {}
        # It is okay if some of the fileids are missing
        for entry in self._getitems(file_ids):
            if entry.kind == "directory":
                directories_to_expand.add(entry.file_id)
            interesting.add(entry.parent_id)
            children_of_parent_id.setdefault(entry.parent_id, set()).add(entry.file_id)

        # Now, interesting has all of the direct parents, but not the
        # parents of those parents. It also may have some duplicates with
        # specific_fileids
        remaining_parents = interesting.difference(file_ids)
        # When we hit the TREE_ROOT, we'll get an interesting parent of None,
        # but we don't actually want to recurse into that
        interesting.add(None)  # this will auto-filter it in the loop
        remaining_parents.discard(None)
        while remaining_parents:
            next_parents = set()
            for entry in self._getitems(remaining_parents):
                next_parents.add(entry.parent_id)
                children_of_parent_id.setdefault(entry.parent_id, set()).add(
                    entry.file_id
                )
            # Remove any search tips we've already processed
            remaining_parents = next_parents.difference(interesting)
            interesting.update(remaining_parents)
            # We should probably also .difference(directories_to_expand)
        interesting.update(file_ids)
        interesting.discard(None)
        while directories_to_expand:
            # Expand directories by looking in the
            # parent_id_basename_to_file_id map
            keys = [(f,) for f in directories_to_expand]
            directories_to_expand = set()
            items = self.parent_id_basename_to_file_id.iteritems(keys)
            next_file_ids = {item[1] for item in items}
            next_file_ids = next_file_ids.difference(interesting)
            interesting.update(next_file_ids)
            for entry in self._getitems(next_file_ids):
                if entry.kind == "directory":
                    directories_to_expand.add(entry.file_id)
                children_of_parent_id.setdefault(entry.parent_id, set()).add(
                    entry.file_id
                )
        return interesting, children_of_parent_id

    def filter(self, specific_fileids):
        """Get an inventory view filtered against a set of file-ids.

        Children of directories and parents are included.

        The result may or may not reference the underlying inventory
        so it should be treated as immutable.
        """
        (interesting, parent_to_children) = (
            self._expand_fileids_to_parents_and_children(specific_fileids)
        )
        # There is some overlap here, but we assume that all interesting items
        # are in the _fileid_to_entry_cache because we had to read them to
        # determine if they were a dir we wanted to recurse, or just a file
        # This should give us all the entries we'll want to add, so start
        # adding
        other = Inventory(self.root_id)
        other.root.revision = self.root.revision
        other.revision_id = self.revision_id
        if not interesting or not parent_to_children:
            # empty filter, or filtering entrys that don't exist
            # (if even 1 existed, then we would have populated
            # parent_to_children with at least the tree root.)
            return other
        cache = self._fileid_to_entry_cache
        remaining_children = deque(parent_to_children[self.root_id])
        while remaining_children:
            file_id = remaining_children.popleft()
            ie = cache[file_id]
            if ie.kind == "directory":
                ie = ie.copy()  # We create a copy to depopulate the .children attribute
            # TODO: depending on the uses of 'other' we should probably alwyas
            #       '.copy()' to prevent someone from mutating other and
            #       invaliding our internal cache
            other.add(ie)
            if file_id in parent_to_children:
                remaining_children.extend(parent_to_children[file_id])
        return other

    @staticmethod
    def _bytes_to_utf8name_key(data):
        """Get the file_id, revision_id key out of data."""
        # We don't normally care about name, except for times when we want
        # to filter out empty names because of non rich-root...
        sections = data.split(b"\n")
        kind, file_id = sections[0].split(b": ")
        return (sections[2], file_id, sections[3])

    def _bytes_to_entry(self, bytes):
        """Deserialise a serialised entry."""
        sections = bytes.split(b"\n")
        if sections[0].startswith(b"file: "):
            result = InventoryFile(
                sections[0][6:], sections[2].decode("utf8"), sections[1]
            )
            result.text_sha1 = sections[4]
            result.text_size = int(sections[5])
            result.executable = sections[6] == b"Y"
        elif sections[0].startswith(b"dir: "):
            result = CHKInventoryDirectory(
                sections[0][5:], sections[2].decode("utf8"), sections[1], self
            )
        elif sections[0].startswith(b"symlink: "):
            result = InventoryLink(
                sections[0][9:], sections[2].decode("utf8"), sections[1]
            )
            result.symlink_target = sections[4].decode("utf8")
        elif sections[0].startswith(b"tree: "):
            result = TreeReference(
                sections[0][6:], sections[2].decode("utf8"), sections[1]
            )
            result.reference_revision = sections[4]
        else:
            raise ValueError("Not a serialised entry {!r}".format(bytes))
        result.file_id = result.file_id
        result.revision = sections[3]
        if result.parent_id == b"":
            result.parent_id = None
        self._fileid_to_entry_cache[result.file_id] = result
        return result

    def create_by_apply_delta(
        self, inventory_delta, new_revision_id, propagate_caches=False
    ):
        """Create a new CHKInventory by applying inventory_delta to this one.

        See the inventory developers documentation for the theory behind
        inventory deltas.

        :param inventory_delta: The inventory delta to apply. See
            Inventory.apply_delta for details.
        :param new_revision_id: The revision id of the resulting CHKInventory.
        :param propagate_caches: If True, the caches for this inventory are
          copied to and updated for the result.
        :return: The new CHKInventory.
        """
        split = osutils.split
        result = CHKInventory(self._search_key_name)
        if propagate_caches:
            # Just propagate the path-to-fileid cache for now
            result._path_to_fileid_cache = self._path_to_fileid_cache.copy()
        search_key_func = chk_map.search_key_registry.get(self._search_key_name)
        self.id_to_entry._ensure_root()
        maximum_size = self.id_to_entry._root_node.maximum_size
        result.revision_id = new_revision_id
        result.id_to_entry = chk_map.CHKMap(
            self.id_to_entry._store,
            self.id_to_entry.key(),
            search_key_func=search_key_func,
        )
        result.id_to_entry._ensure_root()
        result.id_to_entry._root_node.set_maximum_size(maximum_size)
        # Change to apply to the parent_id_basename delta. The dict maps
        # (parent_id, basename) -> (old_key, new_value). We use a dict because
        # when a path has its id replaced (e.g. the root is changed, or someone
        # does bzr mv a b, bzr mv c a, we should output a single change to this
        # map rather than two.
        parent_id_basename_delta = {}
        if self.parent_id_basename_to_file_id is not None:
            result.parent_id_basename_to_file_id = chk_map.CHKMap(
                self.parent_id_basename_to_file_id._store,
                self.parent_id_basename_to_file_id.key(),
                search_key_func=search_key_func,
            )
            result.parent_id_basename_to_file_id._ensure_root()
            self.parent_id_basename_to_file_id._ensure_root()
            result_p_id_root = result.parent_id_basename_to_file_id._root_node
            p_id_root = self.parent_id_basename_to_file_id._root_node
            result_p_id_root.set_maximum_size(p_id_root.maximum_size)
            result_p_id_root._key_width = p_id_root._key_width
        else:
            result.parent_id_basename_to_file_id = None
        result.root_id = self.root_id
        id_to_entry_delta = []
        # inventory_delta is only traversed once, so we just update the
        # variable.
        # Check for repeated file ids
        inventory_delta = _check_delta_unique_ids(inventory_delta)
        # Repeated old paths
        inventory_delta = _check_delta_unique_old_paths(inventory_delta)
        # Check for repeated new paths
        inventory_delta = _check_delta_unique_new_paths(inventory_delta)
        # Check for entries that don't match the fileid
        inventory_delta = _check_delta_ids_match_entry(inventory_delta)
        # Check for nonsense fileids
        inventory_delta = _check_delta_ids_are_valid(inventory_delta)
        # Check for new_path <-> entry consistency
        inventory_delta = _check_delta_new_path_entry_both_or_None(inventory_delta)
        # All changed entries need to have their parents be directories and be
        # at the right path. This set contains (path, id) tuples.
        parents = set()
        # When we delete an item, all the children of it must be either deleted
        # or altered in their own right. As we batch process the change via
        # CHKMap.apply_delta, we build a set of things to use to validate the
        # delta.
        deletes = set()
        altered = set()
        for old_path, new_path, file_id, entry in inventory_delta:
            # file id changes
            if new_path == "":
                result.root_id = file_id
            if new_path is None:
                # Make a delete:
                new_key = None
                new_value = None
                # Update caches
                if propagate_caches:
                    try:
                        del result._path_to_fileid_cache[old_path]
                    except KeyError:
                        pass
                deletes.add(file_id)
            else:
                new_key = (file_id,)
                new_value = result._entry_to_bytes(entry)
                # Update caches. It's worth doing this whether
                # we're propagating the old caches or not.
                result._path_to_fileid_cache[new_path] = file_id
                parents.add((split(new_path)[0], entry.parent_id))
            if old_path is None:
                old_key = None
            else:
                old_key = (file_id,)
                if self.id2path(file_id) != old_path:
                    raise errors.InconsistentDelta(
                        old_path,
                        file_id,
                        "Entry was at wrong other path {!r}.".format(
                            self.id2path(file_id)
                        ),
                    )
                altered.add(file_id)
            id_to_entry_delta.append((old_key, new_key, new_value))
            if result.parent_id_basename_to_file_id is not None:
                # parent_id, basename changes
                if old_path is None:
                    old_key = None
                else:
                    old_entry = self.get_entry(file_id)
                    old_key = self._parent_id_basename_key(old_entry)
                if new_path is None:
                    new_key = None
                    new_value = None
                else:
                    new_key = self._parent_id_basename_key(entry)
                    new_value = file_id
                # If the two keys are the same, the value will be unchanged
                # as its always the file id for this entry.
                if old_key != new_key:
                    # Transform a change into explicit delete/add preserving
                    # a possible match on the key from a different file id.
                    if old_key is not None:
                        parent_id_basename_delta.setdefault(old_key, [None, None])[
                            0
                        ] = old_key
                    if new_key is not None:
                        parent_id_basename_delta.setdefault(new_key, [None, None])[
                            1
                        ] = new_value
        # validate that deletes are complete.
        for file_id in deletes:
            entry = self.get_entry(file_id)
            if entry.kind != "directory":
                continue
            # This loop could potentially be better by using the id_basename
            # map to just get the child file ids.
            for child in entry.children.values():
                if child.file_id not in altered:
                    raise errors.InconsistentDelta(
                        self.id2path(child.file_id),
                        child.file_id,
                        "Child not deleted or reparented when parent deleted.",
                    )
        result.id_to_entry.apply_delta(id_to_entry_delta)
        if parent_id_basename_delta:
            # Transform the parent_id_basename delta data into a linear delta
            # with only one record for a given key. Optimally this would allow
            # re-keying, but its simpler to just output that as a delete+add
            # to spend less time calculating the delta.
            delta_list = []
            for key, (old_key, value) in parent_id_basename_delta.items():
                if value is not None:
                    delta_list.append((old_key, key, value))
                else:
                    delta_list.append((old_key, None, None))
            result.parent_id_basename_to_file_id.apply_delta(delta_list)
        parents.discard(("", None))
        for parent_path, parent in parents:
            try:
                if result.get_entry(parent).kind != "directory":
                    raise errors.InconsistentDelta(
                        result.id2path(parent),
                        parent,
                        "Not a directory, but given children",
                    )
            except errors.NoSuchId as e:
                raise errors.InconsistentDelta(
                    "<unknown>", parent, "Parent is not present in resulting inventory."
                ) from e
            if result.path2id(parent_path) != parent:
                raise errors.InconsistentDelta(
                    parent_path,
                    parent,
                    "Parent has wrong path {!r}.".format(result.path2id(parent_path)),
                )
        return result

    @classmethod
    def deserialise(klass, chk_store, lines, expected_revision_id):
        """Deserialise a CHKInventory.

        :param chk_store: A CHK capable VersionedFiles instance.
        :param bytes: The serialised bytes.
        :param expected_revision_id: The revision ID we think this inventory is
            for.
        :return: A CHKInventory
        """
        if not lines[-1].endswith(b"\n"):
            raise ValueError("last line should have trailing eol\n")
        if lines[0] != b"chkinventory:\n":
            raise ValueError("not a serialised CHKInventory: {!r}".format(bytes))
        info = {}
        allowed_keys = frozenset(
            (
                b"root_id",
                b"revision_id",
                b"parent_id_basename_to_file_id",
                b"search_key_name",
                b"id_to_entry",
            )
        )
        for line in lines[1:]:
            key, value = line.rstrip(b"\n").split(b": ", 1)
            if key not in allowed_keys:
                raise errors.BzrError(
                    "Unknown key in inventory: {!r}\n{!r}".format(key, bytes)
                )
            if key in info:
                raise errors.BzrError(
                    "Duplicate key in inventory: {!r}\n{!r}".format(key, bytes)
                )
            info[key] = value
        revision_id = info[b"revision_id"]
        root_id = info[b"root_id"]
        search_key_name = info.get(b"search_key_name", b"plain")
        parent_id_basename_to_file_id = info.get(b"parent_id_basename_to_file_id")
        if not parent_id_basename_to_file_id.startswith(b"sha1:"):
            raise ValueError(
                "parent_id_basename_to_file_id should be a sha1 key not {!r}".format(
                    parent_id_basename_to_file_id
                )
            )
        id_to_entry = info[b"id_to_entry"]
        if not id_to_entry.startswith(b"sha1:"):
            raise ValueError(
                "id_to_entry should be a sha1 key not {!r}".format(id_to_entry)
            )

        result = CHKInventory(search_key_name)
        result.revision_id = revision_id
        result.root_id = root_id
        search_key_func = chk_map.search_key_registry.get(result._search_key_name)
        if parent_id_basename_to_file_id is not None:
            result.parent_id_basename_to_file_id = chk_map.CHKMap(
                chk_store,
                (parent_id_basename_to_file_id,),
                search_key_func=search_key_func,
            )
        else:
            result.parent_id_basename_to_file_id = None

        result.id_to_entry = chk_map.CHKMap(
            chk_store,
            (id_to_entry,),
            search_key_func=search_key_func,
        )
        if (result.revision_id,) != expected_revision_id:
            raise ValueError(
                "Mismatched revision id and expected: {!r}, {!r}".format(
                    result.revision_id, expected_revision_id
                )
            )
        return result

    @classmethod
    def from_inventory(
        klass, chk_store, inventory, maximum_size=0, search_key_name=b"plain"
    ):
        """Create a CHKInventory from an existing inventory.

        The content of inventory is copied into the chk_store, and a
        CHKInventory referencing that is returned.

        :param chk_store: A CHK capable VersionedFiles instance.
        :param inventory: The inventory to copy.
        :param maximum_size: The CHKMap node size limit.
        :param search_key_name: The identifier for the search key function
        """
        result = klass(search_key_name)
        result.revision_id = inventory.revision_id
        result.root_id = inventory.root.file_id

        entry_to_bytes = result._entry_to_bytes
        parent_id_basename_key = result._parent_id_basename_key
        id_to_entry_dict = {}
        parent_id_basename_dict = {}
        for _path, entry in inventory.iter_entries():
            key = (entry.file_id,)
            id_to_entry_dict[key] = entry_to_bytes(entry)
            p_id_key = parent_id_basename_key(entry)
            parent_id_basename_dict[p_id_key] = entry.file_id

        result._populate_from_dicts(
            chk_store,
            id_to_entry_dict,
            parent_id_basename_dict,
            maximum_size=maximum_size,
        )
        return result

    def _populate_from_dicts(
        self, chk_store, id_to_entry_dict, parent_id_basename_dict, maximum_size
    ):
        search_key_func = chk_map.search_key_registry.get(self._search_key_name)
        root_key = chk_map.CHKMap.from_dict(
            chk_store,
            id_to_entry_dict,
            maximum_size=maximum_size,
            key_width=1,
            search_key_func=search_key_func,
        )
        self.id_to_entry = chk_map.CHKMap(chk_store, root_key, search_key_func)
        root_key = chk_map.CHKMap.from_dict(
            chk_store,
            parent_id_basename_dict,
            maximum_size=maximum_size,
            key_width=2,
            search_key_func=search_key_func,
        )
        self.parent_id_basename_to_file_id = chk_map.CHKMap(
            chk_store, root_key, search_key_func
        )

    def _parent_id_basename_key(self, entry):
        """Create a key for a entry in a parent_id_basename_to_file_id index."""
        if entry.parent_id is not None:
            parent_id = entry.parent_id
        else:
            parent_id = b""
        return (parent_id, entry.name.encode("utf8"))

    def get_entry(self, file_id):
        """Map a single file_id -> InventoryEntry."""
        if file_id is None:
            raise errors.NoSuchId(self, file_id)
        result = self._fileid_to_entry_cache.get(file_id, None)
        if result is not None:
            return result
        try:
            return self._bytes_to_entry(
                next(self.id_to_entry.iteritems([(file_id,)]))[1]
            )
        except StopIteration as e:
            # really we're passing an inventory, not a tree...
            raise errors.NoSuchId(self, file_id) from e

    def _getitems(self, file_ids: Iterable[FileId]) -> list[InventoryEntry]:
        """Similar to get_entry, but lets you query for multiple.

        The returned order is undefined. And currently if an item doesn't
        exist, it isn't included in the output.
        """
        result: list[InventoryEntry] = []
        remaining: list[FileId] = []
        for file_id in file_ids:
            entry = self._fileid_to_entry_cache.get(file_id, None)
            if entry is None:
                remaining.append(file_id)
            else:
                result.append(entry)
        file_keys: list[chk_map.Key] = [(f,) for f in remaining]
        for _file_key, value in self.id_to_entry.iteritems(file_keys):
            entry = self._bytes_to_entry(value)
            result.append(entry)
            self._fileid_to_entry_cache[entry.file_id] = entry
        return result

    def has_id(self, file_id):
        # Perhaps have an explicit 'contains' method on CHKMap ?
        if self._fileid_to_entry_cache.get(file_id, None) is not None:
            return True
        return len(list(self.id_to_entry.iteritems([(file_id,)]))) == 1

    def is_root(self, file_id):
        return file_id == self.root_id

    def _iter_file_id_parents(self, file_id):
        """Yield the parents of file_id up to the root."""
        while file_id is not None:
            try:
                ie = self.get_entry(file_id)
            except KeyError as e:
                raise errors.NoSuchId(tree=self, file_id=file_id) from e
            yield ie
            file_id = ie.parent_id

    def iter_all_ids(self):
        """Iterate over all file-ids."""
        for key, _ in self.id_to_entry.iteritems():
            yield key[-1]

    def iter_just_entries(self):
        """Iterate over all entries.

        Unlike iter_entries(), just the entries are returned (not (path, ie))
        and the order of entries is undefined.

        XXX: We may not want to merge this into bzr.dev.
        """
        for key, entry in self.id_to_entry.iteritems():
            file_id = key[0]
            ie = self._fileid_to_entry_cache.get(file_id, None)
            if ie is None:
                ie = self._bytes_to_entry(entry)
                self._fileid_to_entry_cache[file_id] = ie
            yield ie

    def _preload_cache(self):
        """Make sure all file-ids are in _fileid_to_entry_cache."""
        if self._fully_cached:
            return  # No need to do it again
        # The optimal sort order is to use iteritems() directly
        cache = self._fileid_to_entry_cache
        for key, entry in self.id_to_entry.iteritems():
            file_id = key[0]
            if file_id not in cache:
                ie = self._bytes_to_entry(entry)
                cache[file_id] = ie
            else:
                ie = cache[file_id]
        last_parent_id = last_parent_ie = None
        pid_items = self.parent_id_basename_to_file_id.iteritems()
        for key, child_file_id in pid_items:
            if key == (b"", b""):  # This is the root
                if child_file_id != self.root_id:
                    raise ValueError(
                        "Data inconsistency detected."
                        ' We expected data with key ("","") to match'
                        " the root id, but {} != {}".format(child_file_id, self.root_id)
                    )
                continue
            parent_id, basename = key
            ie = cache[child_file_id]
            parent_ie: InventoryEntry
            if parent_id == last_parent_id:
                if last_parent_ie is None:
                    raise AssertionError("last_parent_ie should not be None")
                parent_ie = last_parent_ie
            else:
                parent_ie = cache[parent_id]
            if parent_ie.kind != "directory":
                raise ValueError(
                    "Data inconsistency detected."
                    " An entry in the parent_id_basename_to_file_id map"
                    " has parent_id {{{}}} but the kind of that object"
                    ' is {!r} not "directory"'.format(parent_id, parent_ie.kind)
                )
            if parent_ie._children is None:
                parent_ie._children = {}
            basename = basename.decode("utf-8")
            if basename in parent_ie._children:
                existing_ie = parent_ie._children[basename]
                if existing_ie != ie:
                    raise ValueError(
                        "Data inconsistency detected."
                        f" Two entries with basename {basename!r} were found"
                        f" in the parent entry {{{parent_id!r}}}"
                    )
            if basename != ie.name:
                raise ValueError(
                    "Data inconsistency detected."
                    " In the parent_id_basename_to_file_id map, file_id"
                    " {{{}}} is listed as having basename {!r}, but in the"
                    " id_to_entry map it is {!r}".format(
                        child_file_id, basename, ie.name
                    )
                )
            parent_ie._children[basename] = ie
        self._fully_cached = True

    def iter_changes(self, basis):
        """Generate a Tree.iter_changes change list between this and basis.

        :param basis: Another CHKInventory.
        :return: An iterator over the changes between self and basis, as per
            tree.iter_changes().
        """
        # We want: (file_id, (path_in_source, path_in_target),
        # changed_content, versioned, parent, name, kind,
        # executable)
        for key, basis_value, self_value in self.id_to_entry.iter_changes(
            basis.id_to_entry
        ):
            file_id = key[0]
            if basis_value is not None:
                basis_entry = basis._bytes_to_entry(basis_value)
                path_in_source = basis.id2path(file_id)
                basis_parent = basis_entry.parent_id
                basis_name = basis_entry.name
                basis_executable = basis_entry.executable
            else:
                path_in_source = None
                basis_parent = None
                basis_name = None
                basis_executable = None
            if self_value is not None:
                self_entry = self._bytes_to_entry(self_value)
                path_in_target = self.id2path(file_id)
                self_parent = self_entry.parent_id
                self_name = self_entry.name
                self_executable = self_entry.executable
            else:
                path_in_target = None
                self_parent = None
                self_name = None
                self_executable = None
            if basis_value is None:
                # add
                kind = (None, self_entry.kind)
                versioned = (False, True)
            elif self_value is None:
                # delete
                kind = (basis_entry.kind, None)
                versioned = (True, False)
            else:
                kind = (basis_entry.kind, self_entry.kind)
                versioned = (True, True)
            changed_content = False
            if kind[0] != kind[1]:
                changed_content = True
            elif kind[0] == "file":
                if (
                    self_entry.text_size != basis_entry.text_size
                    or self_entry.text_sha1 != basis_entry.text_sha1
                ):
                    changed_content = True
            elif kind[0] == "symlink":
                if self_entry.symlink_target != basis_entry.symlink_target:
                    changed_content = True
            elif kind[0] == "tree-reference":
                if self_entry.reference_revision != basis_entry.reference_revision:
                    changed_content = True
            parent = (basis_parent, self_parent)
            name = (basis_name, self_name)
            executable = (basis_executable, self_executable)
            if (
                not changed_content
                and parent[0] == parent[1]
                and name[0] == name[1]
                and executable[0] == executable[1]
            ):
                # Could happen when only the revision changed for a directory
                # for instance.
                continue
            yield (
                file_id,
                (path_in_source, path_in_target),
                changed_content,
                versioned,
                parent,
                name,
                kind,
                executable,
            )

    def __len__(self) -> int:
        """Return the number of entries in the inventory."""
        return len(self.id_to_entry)

    def _make_delta(self, old):
        """Make an inventory delta from two inventories."""
        if not isinstance(old, CHKInventory):
            return CommonInventory._make_delta(self, old)
        delta = []
        for key, old_value, self_value in self.id_to_entry.iter_changes(
            old.id_to_entry
        ):
            file_id = key[0]
            if old_value is not None:
                old_path = old.id2path(file_id)
            else:
                old_path = None
            if self_value is not None:
                entry = self._bytes_to_entry(self_value)
                self._fileid_to_entry_cache[file_id] = entry
                new_path = self.id2path(file_id)
            else:
                entry = None
                new_path = None
            delta.append((old_path, new_path, file_id, entry))
        return delta

    def path2id(self, relpath: Union[str, list[str]]) -> Optional[FileId]:
        """See CommonInventory.path2id()."""
        # TODO: perhaps support negative hits?
        if isinstance(relpath, str):
            names = osutils.splitpath(relpath)
        else:
            names = relpath
            if relpath == []:
                relpath = [""]
            relpath = osutils.pathjoin(*relpath)
        result = self._path_to_fileid_cache.get(relpath, None)
        if result is not None:
            return result
        current_id = self.root_id
        if current_id is None:
            return None
        parent_id_index = self.parent_id_basename_to_file_id
        cur_path = None
        for basename in names:
            if cur_path is None:
                cur_path = basename
            else:
                cur_path = cur_path + "/" + basename
            basename_utf8 = basename.encode("utf8")
            file_id = self._path_to_fileid_cache.get(cur_path, None)
            if file_id is None:
                key_filter = [(current_id, basename_utf8)]
                items = parent_id_index.iteritems(key_filter)
                for (parent_id, name_utf8), file_id in items:  # noqa: B007
                    if parent_id != current_id or name_utf8 != basename_utf8:
                        raise errors.BzrError(
                            "corrupt inventory lookup! {!r} {!r} {!r} {!r}".format(
                                parent_id, current_id, name_utf8, basename_utf8
                            )
                        )
                if file_id is None:
                    return None
                else:
                    self._path_to_fileid_cache[cur_path] = file_id
            current_id = file_id
        return current_id

    def to_lines(self):
        """Serialise the inventory to lines."""
        lines = [b"chkinventory:\n"]
        if self._search_key_name != b"plain":
            # custom ordering grouping things that don't change together
            lines.append(b"search_key_name: %s\n" % (self._search_key_name))
            lines.append(b"root_id: %s\n" % self.root_id)
            lines.append(
                b"parent_id_basename_to_file_id: %s\n"
                % (self.parent_id_basename_to_file_id.key()[0],)
            )
            lines.append(b"revision_id: %s\n" % self.revision_id)
            lines.append(b"id_to_entry: %s\n" % (self.id_to_entry.key()[0],))
        else:
            lines.append(b"revision_id: %s\n" % self.revision_id)
            lines.append(b"root_id: %s\n" % self.root_id)
            if self.parent_id_basename_to_file_id is not None:
                lines.append(
                    b"parent_id_basename_to_file_id: %s\n"
                    % (self.parent_id_basename_to_file_id.key()[0],)
                )
            lines.append(b"id_to_entry: %s\n" % (self.id_to_entry.key()[0],))
        return lines

    @property
    def root(self):
        """Get the root entry."""
        return self.get_entry(self.root_id)


class CHKInventoryDirectory(InventoryDirectory):
    """A directory in an inventory."""

    __slots__ = ["_children", "_chk_inventory"]

    def __init__(self, file_id, name, parent_id, chk_inventory):
        # Don't call InventoryDirectory.__init__ - it isn't right for this
        # class.
        InventoryEntry.__init__(self, file_id, name, parent_id)
        self._children = None
        self._chk_inventory = chk_inventory

    @property
    def children(self):
        """Access the list of children of this directory.

        With a parent_id_basename_to_file_id index, loads all the children,
        without loads the entire index. Without is bad. A more sophisticated
        proxy object might be nice, to allow partial loading of children as
        well when specific names are accessed. (So path traversal can be
        written in the obvious way but not examine siblings.).
        """
        if self._children is not None:
            return self._children
        # No longer supported
        if self._chk_inventory.parent_id_basename_to_file_id is None:
            raise AssertionError(
                "Inventories without"
                " parent_id_basename_to_file_id are no longer supported"
            )
        result = {}
        # XXX: Todo - use proxy objects for the children rather than loading
        # all when the attribute is referenced.
        parent_id_index = self._chk_inventory.parent_id_basename_to_file_id
        child_keys = set()
        for (_parent_id, _name_utf8), file_id in parent_id_index.iteritems(
            key_filter=[(self.file_id,)]
        ):
            child_keys.add((file_id,))
        cached = set()
        for file_id_key in child_keys:
            entry = self._chk_inventory._fileid_to_entry_cache.get(file_id_key[0], None)
            if entry is not None:
                result[entry.name] = entry
                cached.add(file_id_key)
        child_keys.difference_update(cached)
        # populate; todo: do by name
        id_to_entry = self._chk_inventory.id_to_entry
        for file_id_key, bytes in id_to_entry.iteritems(child_keys):
            entry = self._chk_inventory._bytes_to_entry(bytes)
            result[entry.name] = entry
            self._chk_inventory._fileid_to_entry_cache[file_id_key[0]] = entry
        self._children = result
        return result


entry_factory = {
    "directory": InventoryDirectory,
    "file": InventoryFile,
    "symlink": InventoryLink,
    "tree-reference": TreeReference,
}


def make_entry(kind, name, parent_id, file_id=None):
    """Create an inventory entry.

    :param kind: the type of inventory entry to create.
    :param name: the basename of the entry.
    :param parent_id: the parent_id of the entry.
    :param file_id: the file_id to use. if None, one will be created.
    """
    if file_id is None:
        from . import generate_ids

        file_id = generate_ids.gen_file_id(name)
    name = ensure_normalized_name(name)
    try:
        factory = entry_factory[kind]
    except KeyError as e:
        raise errors.BadFileKindError(name, kind) from e
    return factory(file_id, name, parent_id)


def ensure_normalized_name(name):
    """Normalize name.

    :raises InvalidNormalization: When name is not normalized, and cannot be
        accessed on this platform by the normalized path.
    :return: The NFC normalised version of name.
    """
    # ------- This has been copied to breezy.dirstate.DirState.add, please
    # keep them synchronised.
    # we dont import normalized_filename directly because we want to be
    # able to change the implementation at runtime for tests.
    norm_name, can_access = osutils.normalized_filename(name)
    if norm_name != name:
        if can_access:
            return norm_name
        else:
            # TODO: jam 20060701 This would probably be more useful
            #       if the error was raised with the full path
            raise errors.InvalidNormalization(name)
    return name


_NAME_RE = lazy_regex.lazy_compile(r"^[^/\\]+$")


def is_valid_name(name):
    return bool(_NAME_RE.match(name))


def _check_delta_unique_ids(delta):
    """Decorate a delta and check that the file ids in it are unique.

    :return: A generator over delta.
    """
    ids = set()
    for item in delta:
        length = len(ids) + 1
        ids.add(item[2])
        if len(ids) != length:
            raise errors.InconsistentDelta(
                item[0] or item[1], item[2], "repeated file_id"
            )
        yield item


def _check_delta_unique_new_paths(delta):
    """Decorate a delta and check that the new paths in it are unique.

    :return: A generator over delta.
    """
    paths = set()
    for item in delta:
        length = len(paths) + 1
        path = item[1]
        if path is not None:
            paths.add(path)
            if len(paths) != length:
                raise errors.InconsistentDelta(path, item[2], "repeated path")
        yield item


def _check_delta_unique_old_paths(delta):
    """Decorate a delta and check that the old paths in it are unique.

    :return: A generator over delta.
    """
    paths = set()
    for item in delta:
        length = len(paths) + 1
        path = item[0]
        if path is not None:
            paths.add(path)
            if len(paths) != length:
                raise errors.InconsistentDelta(path, item[2], "repeated path")
        yield item


def _check_delta_ids_are_valid(delta):
    """Decorate a delta and check that the ids in it are valid.

    :return: A generator over delta.
    """
    for item in delta:
        entry = item[3]
        if item[2] is None:
            raise errors.InconsistentDelta(
                item[0] or item[1],
                item[2],
                "entry with file_id None {!r}".format(entry),
            )
        if not isinstance(item[2], bytes):
            raise errors.InconsistentDelta(
                item[0] or item[1],
                item[2],
                "entry with non bytes file_id {!r}".format(entry),
            )
        yield item


def _check_delta_ids_match_entry(delta):
    """Decorate a delta and check that the ids in it match the entry.file_id.

    :return: A generator over delta.
    """
    for item in delta:
        entry = item[3]
        if entry is not None:
            if entry.file_id != item[2]:
                raise errors.InconsistentDelta(
                    item[0] or item[1], item[2], "mismatched id with {!r}".format(entry)
                )
        yield item


def _check_delta_new_path_entry_both_or_None(delta):
    """Decorate a delta and check that the new_path and entry are paired.

    :return: A generator over delta.
    """
    for item in delta:
        new_path = item[1]
        entry = item[3]
        if new_path is None and entry is not None:
            raise errors.InconsistentDelta(item[0], item[1], "Entry with no new_path")
        if new_path is not None and entry is None:
            raise errors.InconsistentDelta(new_path, item[1], "new_path with no entry")
        yield item


def mutable_inventory_from_tree(tree):
    """Create a new inventory that has the same contents as a specified tree.

    :param tree: Revision tree to create inventory from
    """
    entries = tree.iter_entries_by_dir()
    inv = Inventory(None, tree.get_revision_id())
    for _path, inv_entry in entries:
        inv.add(inv_entry.copy())
    return inv
