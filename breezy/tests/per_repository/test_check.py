# Copyright (C) 2007-2011 Canonical Ltd
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


"""Test operations that check the repository for corruption."""

from breezy import revision as _mod_revision
from breezy.bzr.inventorytree import InventoryTreeChange
from breezy.tests.per_repository import TestCaseWithRepository


class TestCleanRepository(TestCaseWithRepository):
    def test_new_repo(self):
        branch = self.make_branch("foo")
        branch.lock_write()
        self.addCleanup(branch.unlock)
        self.overrideEnv("BRZ_EMAIL", "foo@sample.com")
        builder = branch.get_commit_builder([], branch.get_config_stack())
        list(
            builder.record_iter_changes(
                None,
                _mod_revision.NULL_REVISION,
                [
                    InventoryTreeChange(
                        b"TREE_ROOT",
                        (None, ""),
                        True,
                        (False, True),
                        (None, None),
                        (None, ""),
                        (None, "directory"),
                        (None, False),
                    )
                ],
            )
        )
        builder.finish_inventory()
        builder.commit("first post")
        result = branch.repository.check(None, check_repo=True)
        result.report_results(True)
        log = self.get_log()
        self.assertFalse("Missing" in log, "Something was missing in {!r}".format(log))
