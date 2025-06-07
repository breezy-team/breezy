# Copyright (C) 2009 Canonical Ltd
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

"""Tests for how merge directives interact with various repository formats.

Bundles contain the serialized form, so changes in serialization based on
repository effects the final bundle.
"""

from breezy import merge_directive
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
)
from bzrformats import chk_map

from ....tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestMergeDirective(TestCaseWithRepository):
    scenarios = all_repository_vf_format_scenarios()

    def make_two_branches(self):
        builder = self.make_branch_builder("source")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("f", b"f-id", "file", b"initial content\n")),
            ],
            revision_id=b"A",
        )
        builder.build_snapshot(
            [b"A"],
            [
                ("modify", ("f", b"new content\n")),
            ],
            revision_id=b"B",
        )
        builder.finish_series()
        b1 = builder.get_branch()
        b2 = b1.controldir.sprout("target", revision_id=b"A").open_branch()
        return b1, b2

    def create_merge_directive(self, source_branch, submit_url):
        return merge_directive.MergeDirective2.from_objects(
            repository=source_branch.repository,
            revision_id=source_branch.last_revision(),
            time=1247775710,
            timezone=0,
            target_branch=submit_url,
        )

    def test_create_merge_directive(self):
        source_branch, target_branch = self.make_two_branches()
        directive = self.create_merge_directive(source_branch, target_branch.base)
        self.assertIsInstance(directive, merge_directive.MergeDirective2)

    def test_create_and_install_directive(self):
        source_branch, target_branch = self.make_two_branches()
        directive = self.create_merge_directive(source_branch, target_branch.base)
        chk_map.clear_cache()
        directive.install_revisions(target_branch.repository)
        rt = target_branch.repository.revision_tree(b"B")
        with rt.lock_read():
            self.assertEqualDiff(b"new content\n", rt.get_file_text("f"))
