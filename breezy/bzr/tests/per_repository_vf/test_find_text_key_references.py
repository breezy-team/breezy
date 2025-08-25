# Copyright (C) 2007 Canonical Ltd
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


"""Test the find_text_key_references API."""

from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)

from ....tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestFindTextKeyReferences(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def test_empty(self):
        repo = self.make_repository(".")
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual({}, repo.find_text_key_references())
