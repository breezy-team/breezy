# Copyright (C) 2026 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for merging git branches."""

import os

from ...merge import Merge3Merger
from ...tests import TestCaseWithTransport


class GitRenameMergeTests(TestCaseWithTransport):
    """Cover the case where THIS renames a file that OTHER modifies.

    Git's ``iter_changes`` attaches a synthetic ``file_id`` derived from
    BASE/OTHER's path, not THIS's. Routing trans_id resolution through
    that synthetic id picks up the wrong path on path-based trees:
    ``trans_id_file_id(b'git:a.txt')`` resolves to a phantom trans_id at
    ``"a.txt"`` even though THIS has the file at ``"b.txt"``. The merge
    then fails with ``MalformedTransform: unversioned executability``.

    ``_compute_transform`` must therefore key directly off
    ``paths3[2]`` (THIS's path) for path-based trees, not the iterator's
    synthetic file_id.
    """

    def _make_branch_with_long_file(self, name):
        wt = self.make_branch_and_tree(name, format="git")
        # Long content so dulwich's RenameDetector triggers across the
        # rename — this is what makes ``find_previous_path`` return
        # ``"b.txt"`` rather than ``None``.
        content = b"\n".join(f"line{i}".encode() for i in range(50)) + b"\n"
        self.build_tree_contents([(name + "/a.txt", content)])
        wt.add(["a.txt"])
        wt.commit("base")
        return wt, content

    def test_rename_in_this_modify_in_other(self):
        wt, content = self._make_branch_with_long_file("local")
        base_rev = wt.last_revision()

        # THIS renames a.txt -> b.txt.
        os.rename(wt.abspath("a.txt"), wt.abspath("b.txt"))
        wt.remove(["a.txt"])
        wt.add(["b.txt"])
        wt.commit("rename")

        # OTHER modifies a.txt at the original path.
        other_cd = wt.branch.controldir.sprout("other", revision_id=base_rev)
        other_wt = other_cd.open_workingtree()
        self.build_tree_contents([("other/a.txt", content + b"appended\n")])
        other_rev = other_wt.commit("modify")

        base_tree = wt.branch.repository.revision_tree(base_rev)
        other_tree = other_cd.open_branch().repository.revision_tree(other_rev)

        merger = Merge3Merger(
            working_tree=wt,
            this_tree=wt,
            base_tree=base_tree,
            other_tree=other_tree,
            do_merge=False,
        )
        # Used to raise ``MalformedTransform: unversioned executability``
        # because trans_id resolution went through the synthetic file_id
        # ``b'git:a.txt'`` (phantom path) instead of ``paths3[2]`` =
        # ``"b.txt"`` (where THIS actually has the file).
        merger.do_merge()
        self.assertEqual([], list(merger.cooked_conflicts))
        # Rename was preserved; OTHER's modification landed at b.txt.
        self.assertFalse(os.path.exists(wt.abspath("a.txt")))
        with open(wt.abspath("b.txt"), "rb") as f:
            merged = f.read()
        self.assertEqual(content + b"appended\n", merged)
