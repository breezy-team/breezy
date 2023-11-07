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

"""Tests for locking/unlocking a repository with external references."""

from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
)


class TestUnlock(TestCaseWithExternalReferenceRepository):
    def create_stacked_branch(self):
        builder = self.make_branch_builder("source", format=self.bzrdir_format)
        builder.start_series()
        repo = builder.get_branch().repository
        if not repo._format.supports_external_lookups:
            raise tests.TestNotApplicable("format does not support stacking")
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"contents\n")),
            ],
            revision_id=b"A-id",
        )
        builder.build_snapshot(
            [b"A-id"], [("modify", ("file", b"new-content\n"))], revision_id=b"B-id"
        )
        builder.build_snapshot(
            [b"B-id"],
            [("modify", ("file", b"yet more content\n"))],
            revision_id=b"C-id",
        )
        builder.finish_series()
        source_b = builder.get_branch()
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        base = self.make_branch("base")
        base.pull(source_b, stop_revision=b"B-id")
        stacked = self.make_branch("stacked")
        stacked.set_stacked_on_url("../base")
        stacked.pull(source_b, stop_revision=b"C-id")

        return base, stacked

    def test_unlock_unlocks_fallback(self):
        self.make_branch("base")
        stacked = self.make_branch("stacked")
        repo = stacked.repository
        stacked.set_stacked_on_url("../base")
        self.assertEqual(1, len(repo._fallback_repositories))
        fallback_repo = repo._fallback_repositories[0]
        self.assertFalse(repo.is_locked())
        self.assertFalse(fallback_repo.is_locked())
        repo.lock_read()
        self.assertTrue(repo.is_locked())
        self.assertTrue(fallback_repo.is_locked())
        repo.unlock()
        self.assertFalse(repo.is_locked())
        self.assertFalse(fallback_repo.is_locked())
        repo.lock_write()
        self.assertTrue(repo.is_locked())
        self.assertTrue(fallback_repo.is_locked())
        repo.unlock()
        self.assertFalse(repo.is_locked())
        self.assertFalse(fallback_repo.is_locked())
