# Copyright (C) 2026 Breezy Developers
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

import os

from ....branch import Branch
from ....tests import TestCaseWithTransport
from ....tests.features import ExecutableFeature
from ..cmds import summarize_unmerged


class SummarizeUnmergedTests(TestCaseWithTransport):
    _test_needs_features = [ExecutableFeature("git")]

    def commit(self, tree, message):
        return tree.commit(
            message, committer="Joe <joe@example.com>", timestamp=1700000000, timezone=0
        )

    def open_remote(self, path):
        url = "git://{}/".format(os.path.abspath(path))
        self.permit_url(url)
        return Branch.open(url)

    def summarize(self, prerequisite=None):
        return summarize_unmerged(
            self.local.branch,
            self.open_remote("fork"),
            self.open_remote("target"),
            None if prerequisite is None else self.open_remote(prerequisite),
        )

    def setUp(self):
        super().setUp()
        self.target = self.make_branch_and_tree("target", format="git")
        self.commit(self.target, "Base")
        self.local = self.target.controldir.sprout("local").open_workingtree()
        self.commit(self.local, "Fix something")
        self.local.branch.controldir.sprout("prerequisite")
        self.commit(self.local, "Fix more")
        self.local.branch.controldir.sprout("fork")
        self.commit(self.local, "Not pushed yet")
        self.local.branch.get_config_stack().set("log_format", "line")

    def test_remote_git_branches(self):
        self.assertEqual(
            "2: Joe 2023-11-14 Fix something\n3: Joe 2023-11-14 Fix more\n",
            self.summarize(),
        )

    def test_target_moved_on(self):
        self.commit(self.target, "Upstream change")
        self.assertEqual(
            "2: Joe 2023-11-14 Fix something\n3: Joe 2023-11-14 Fix more\n",
            self.summarize(),
        )

    def test_prerequisite(self):
        self.assertEqual(
            "3: Joe 2023-11-14 Fix more\n", self.summarize(prerequisite="prerequisite")
        )
