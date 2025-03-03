# Copyright (C) 2010 Canonical Ltd
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

"""Matchers for breezy.

Primarily test support, Matchers are used by self.assertThat in the breezy
test suite. A matcher is a stateful test helper which can be used to determine
if a passed object 'matches', much like a regex. If the object does not match
the mismatch can be described in a human readable fashion. assertThat then
raises if a mismatch occurs, showing the description as the assertion error.

Matchers are designed to be more reusable and composable than layered
assertions in Test Case objects, so they are recommended for new testing work.
"""

__all__ = [
    "HasLayout",
    "HasPathRelations",
    "MatchesAncestry",
    "MatchesTreeChanges",
    "ReturnsUnlockable",
    "RevisionHistoryMatches",
]

from testtools.matchers import Equals, Matcher, Mismatch

from .. import osutils
from .. import revision as _mod_revision
from ..tree import InterTree, TreeChange


class ReturnsUnlockable(Matcher):
    """Check that a method returns an object with an unlock method.

    A matcher that checks for the pattern we want lock* methods to have:

    They should return an object with an unlock() method.
    Calling that method should unlock the original object.

    :ivar lockable_thing: The object which can be locked that will be
        inspected.
    """

    def __init__(self, lockable_thing):
        Matcher.__init__(self)
        self.lockable_thing = lockable_thing

    def __str__(self):
        return "ReturnsUnlockable(lockable_thing={})".format(self.lockable_thing)

    def match(self, lock_method):
        lock_method().unlock()
        if self.lockable_thing.is_locked():
            return _IsLocked(self.lockable_thing)
        return None


class _IsLocked(Mismatch):
    """Something is locked."""

    def __init__(self, lockable_thing):
        self.lockable_thing = lockable_thing

    def describe(self):
        return "{} is locked".format(self.lockable_thing)


class _AncestryMismatch(Mismatch):
    """Ancestry matching mismatch."""

    def __init__(self, tip_revision, got, expected):
        self.tip_revision = tip_revision
        self.got = got
        self.expected = expected

    def describe(self):
        return "mismatched ancestry for revision {!r} was {!r}, expected {!r}".format(
            self.tip_revision, self.got, self.expected
        )


class MatchesAncestry(Matcher):
    """A matcher that checks the ancestry of a particular revision.

    :ivar graph: Graph in which to check the ancestry
    :ivar revision_id: Revision id of the revision
    """

    def __init__(self, repository, revision_id):
        Matcher.__init__(self)
        self.repository = repository
        self.revision_id = revision_id

    def __str__(self):
        return "MatchesAncestry(repository={!r}, revision_id={!r})".format(
            self.repository, self.revision_id
        )

    def match(self, expected):
        with self.repository.lock_read():
            graph = self.repository.get_graph()
            got = [r for r, p in graph.iter_ancestry([self.revision_id])]
            if _mod_revision.NULL_REVISION in got:
                got.remove(_mod_revision.NULL_REVISION)
        if sorted(got) != sorted(expected):
            return _AncestryMismatch(self.revision_id, sorted(got), sorted(expected))


class HasLayout(Matcher):
    """A matcher that checks if a tree has a specific layout.

    :ivar entries: List of expected entries, as (path, file_id) pairs.
    """

    def __init__(self, entries):
        Matcher.__init__(self)
        self.entries = entries

    def get_tree_layout(self, tree, include_file_ids):
        """Get the (path, file_id) pairs for the current tree."""
        with tree.lock_read():
            for path, ie in tree.iter_entries_by_dir():
                if path != "":
                    path += ie.kind_character()
                if include_file_ids:
                    yield (path, ie.file_id)
                else:
                    yield path

    @staticmethod
    def _strip_unreferenced_directories(entries):
        """Strip all directories that don't (in)directly contain any files.

        :param entries: List of path strings or (path, ie) tuples to process
        """
        directories = []
        for entry in entries:
            if isinstance(entry, str):
                path = entry
            else:
                path = entry[0]
            if not path or path[-1] == "/":
                # directory
                directories.append((path, entry))
            else:
                # Yield the referenced parent directories
                for dirpath, direntry in directories:
                    if osutils.is_inside(dirpath, path):
                        yield direntry
                directories = []
                yield entry

    def __str__(self):
        return "HasLayout({!r})".format(self.entries)

    def match(self, tree):
        include_file_ids = self.entries and not isinstance(self.entries[0], str)
        actual = list(self.get_tree_layout(tree, include_file_ids=include_file_ids))
        if not tree.has_versioned_directories():
            entries = list(self._strip_unreferenced_directories(self.entries))
        else:
            entries = self.entries
        return Equals(entries).match(actual)


class HasPathRelations(Matcher):
    """Matcher verifies that paths have a relation to those in another tree.

    :ivar previous_tree: tree to compare to
    :ivar previous_entries: List of expected entries, as (path, previous_path) pairs.
    """

    def __init__(self, previous_tree, previous_entries):
        Matcher.__init__(self)
        self.previous_tree = previous_tree
        self.previous_entries = previous_entries

    def get_path_map(self, tree):
        """Get the (path, previous_path) pairs for the current tree."""
        previous_intertree = InterTree.get(self.previous_tree, tree)
        with tree.lock_read(), self.previous_tree.lock_read():
            for path, ie in tree.iter_entries_by_dir():
                if tree.supports_rename_tracking():
                    previous_path = previous_intertree.find_source_path(path)
                else:
                    if self.previous_tree.is_versioned(path):
                        previous_path = path
                    else:
                        previous_path = None
                if previous_path:
                    kind = self.previous_tree.kind(previous_path)
                    if kind == "directory":
                        previous_path += "/"
                if path == "":
                    yield ("", previous_path)
                else:
                    yield (path + ie.kind_character(), previous_path)

    @staticmethod
    def _strip_unreferenced_directories(entries):
        """Strip all directories that don't (in)directly contain any files.

        :param entries: List of path strings or (path, previous_path) tuples to process
        """
        directory_used = set()
        directories = []
        for path, previous_path in entries:
            if not path or path[-1] == "/":
                # directory
                directories.append((path, previous_path))
            else:
                # Yield the referenced parent directories
                for direntry in directories:
                    if osutils.is_inside(direntry[0], path):
                        directory_used.add(direntry[0])
        for path, previous_path in entries:
            if (not path.endswith("/")) or path in directory_used:
                yield (path, previous_path)

    def __str__(self):
        return "HasPathRelations({!r}, {!r})".format(
            self.previous_tree, self.previous_entries
        )

    def match(self, tree):
        actual = list(self.get_path_map(tree))
        if not tree.has_versioned_directories():
            entries = list(self._strip_unreferenced_directories(self.previous_entries))
        else:
            entries = self.previous_entries
        if not tree.supports_rename_tracking():
            entries = [
                (path, path if self.previous_tree.is_versioned(path) else None)
                for (path, previous_path) in entries
            ]
        return Equals(entries).match(actual)


class RevisionHistoryMatches(Matcher):
    """A matcher that checks if a branch has a specific revision history.

    :ivar history: Revision history, as list of revisions. Oldest first.
    """

    def __init__(self, history):
        Matcher.__init__(self)
        self.expected = history

    def __str__(self):
        return "RevisionHistoryMatches({!r})".format(self.expected)

    def match(self, branch):
        with branch.lock_read():
            graph = branch.repository.get_graph()
            history = list(
                graph.iter_lefthand_ancestry(
                    branch.last_revision(), [_mod_revision.NULL_REVISION]
                )
            )
            history.reverse()
        return Equals(self.expected).match(history)


class MatchesTreeChanges(Matcher):
    """A matcher that checks that tree changes match expected contents."""

    def __init__(self, old_tree, new_tree, expected):
        Matcher.__init__(self)
        expected = [TreeChange(*x) if isinstance(x, tuple) else x for x in expected]
        self.use_inventory_tree_changes = (
            old_tree.supports_file_ids and new_tree.supports_file_ids
        )
        self.expected = expected
        self.old_tree = old_tree
        self.new_tree = new_tree

    @staticmethod
    def _convert_to_inventory_tree_changes(old_tree, new_tree, expected):
        from ..bzr.inventorytree import InventoryTreeChange

        rich_expected = []

        def get_parent_id(t, p):
            if p:
                return t.path2id(osutils.dirname(p))
            else:
                return None

        for c in expected:
            if c.path[0] is not None:
                file_id = old_tree.path2id(c.path[0])
            else:
                file_id = new_tree.path2id(c.path[1])
            old_parent_id = get_parent_id(old_tree, c.path[0])
            new_parent_id = get_parent_id(new_tree, c.path[1])
            rich_expected.append(
                InventoryTreeChange(
                    file_id=file_id,
                    parent_id=(old_parent_id, new_parent_id),
                    path=c.path,
                    changed_content=c.changed_content,
                    versioned=c.versioned,
                    name=c.name,
                    kind=c.kind,
                    executable=c.executable,
                    copied=c.copied,
                )
            )
        return rich_expected

    def __str__(self):
        return "<MatchesTreeChanges({!r})>".format(self.expected)

    def match(self, actual):
        from ..bzr.inventorytree import InventoryTreeChange

        actual = list(actual)
        if self.use_inventory_tree_changes or (
            actual and isinstance(actual[0], InventoryTreeChange)
        ):
            expected = self._convert_to_inventory_tree_changes(
                self.old_tree, self.new_tree, self.expected
            )
        else:
            expected = self.expected
        if self.use_inventory_tree_changes:
            actual = self._convert_to_inventory_tree_changes(
                self.old_tree, self.new_tree, actual
            )
        return Equals(expected).match(actual)
