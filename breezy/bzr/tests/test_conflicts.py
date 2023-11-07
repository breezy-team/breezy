# Copyright (C) 2005-2011 Canonical Ltd
# Copyright (C) 2018-2020 Breezy Developers
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

import os

from ... import tests
from ...conflicts import resolve
from ...tests import scenarios
from ...tests.test_conflicts import vary_by_conflicts
from .. import conflicts as bzr_conflicts

load_tests = scenarios.load_tests_apply_scenarios


class TestPerConflict(tests.TestCase):
    scenarios = scenarios.multiply_scenarios(vary_by_conflicts())

    def test_stringification(self):
        text = str(self.conflict)
        self.assertContainsString(text, self.conflict.path)
        self.assertContainsString(text.lower(), "conflict")
        self.assertContainsString(repr(self.conflict), self.conflict.__class__.__name__)

    def test_stanza_roundtrip(self):
        p = self.conflict
        o = bzr_conflicts.Conflict.factory(**p.as_stanza().as_dict())
        self.assertEqual(o, p)

        self.assertIsInstance(o.path, str)

        if o.file_id is not None:
            self.assertIsInstance(o.file_id, bytes)

        conflict_path = getattr(o, "conflict_path", None)
        if conflict_path is not None:
            self.assertIsInstance(conflict_path, str)

        conflict_file_id = getattr(o, "conflict_file_id", None)
        if conflict_file_id is not None:
            self.assertIsInstance(conflict_file_id, bytes)

    def test_stanzification(self):
        stanza = self.conflict.as_stanza()
        if "file_id" in stanza:
            # In Stanza form, the file_id has to be unicode.
            self.assertStartsWith(stanza.get("file_id"), "\xeed")
        self.assertStartsWith(stanza.get("path"), "p\xe5th")
        if "conflict_path" in stanza:
            self.assertStartsWith(stanza.get("conflict_path"), "p\xe5th")
        if "conflict_file_id" in stanza:
            self.assertStartsWith(stanza.get("conflict_file_id"), "\xeed")


class TestConflicts(tests.TestCaseWithTransport):
    def test_resolve_conflict_dir(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("hello", b"hello world4"),
                ("hello.THIS", b"hello world2"),
                ("hello.BASE", b"hello world1"),
            ]
        )
        os.mkdir("hello.OTHER")
        tree.add("hello", ids=b"q")
        l = bzr_conflicts.ConflictList([bzr_conflicts.TextConflict("hello")])
        l.remove_files(tree)

    def test_select_conflicts(self):
        tree = self.make_branch_and_tree(".")
        clist = bzr_conflicts.ConflictList

        def check_select(not_selected, selected, paths, **kwargs):
            self.assertEqual(
                (not_selected, selected),
                tree_conflicts.select_conflicts(tree, paths, **kwargs),
            )

        foo = bzr_conflicts.ContentsConflict("foo")
        bar = bzr_conflicts.ContentsConflict("bar")
        tree_conflicts = clist([foo, bar])

        check_select(clist([bar]), clist([foo]), ["foo"])
        check_select(clist(), tree_conflicts, [""], ignore_misses=True, recurse=True)

        foobaz = bzr_conflicts.ContentsConflict("foo/baz")
        tree_conflicts = clist([foobaz, bar])

        check_select(
            clist([bar]), clist([foobaz]), ["foo"], ignore_misses=True, recurse=True
        )

        qux = bzr_conflicts.PathConflict("qux", "foo/baz")
        tree_conflicts = clist([qux])

        check_select(clist(), tree_conflicts, ["foo"], ignore_misses=True, recurse=True)
        check_select(tree_conflicts, clist(), ["foo"], ignore_misses=True)

    def test_resolve_conflicts_recursive(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["dir/", "dir/hello"])
        tree.add(["dir", "dir/hello"])

        dirhello = [bzr_conflicts.TextConflict("dir/hello")]
        tree.set_conflicts(dirhello)

        resolve(tree, ["dir"], recursive=False, ignore_misses=True)
        self.assertEqual(dirhello, tree.conflicts())

        resolve(tree, ["dir"], recursive=True, ignore_misses=True)
        self.assertEqual(bzr_conflicts.ConflictList([]), tree.conflicts())
