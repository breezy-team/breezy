# Copyright (C) 2006-2009, 2011 Canonical Ltd
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

"""Tests for InterRepository implementastions."""

import sys

import breezy
import breezy.errors as errors
import breezy.gpg
from breezy.bzr.inventory import Inventory
from breezy.repository import WriteGroup
from breezy.revision import NULL_REVISION
from breezy.tests import TestNotApplicable, TestSkipped
from breezy.tests.matchers import MatchesAncestry
from breezy.tests.per_interrepository import TestCaseWithInterRepository
from breezy.workingtree import WorkingTree


def check_repo_format_for_funky_id_on_win32(repo):
    if not repo._format.supports_funky_characters and sys.platform == "win32":
        raise TestSkipped(
            "funky chars not allowed on this platform in repository {}".format(
                repo.__class__.__name__
            )
        )


class TestInterRepository(TestCaseWithInterRepository):
    def test_interrepository_get_returns_correct_optimiser(self):
        # we assume the optimising code paths are triggered
        # by the type of the repo not the transport - at this point.
        # we may need to update this test if this changes.
        #
        # XXX: This code tests that we get an InterRepository when we try to
        # convert between the two repositories that it wants to be tested with
        # -- but that's not necessarily correct.  So for now this is disabled.
        # mbp 20070206
        ## source_repo = self.make_repository("source")
        ## target_repo = self.make_to_repository("target")
        ## interrepo = repository.InterRepository.get(source_repo, target_repo)
        ## self.assertEqual(self.interrepo_class, interrepo.__class__)
        pass


class TestCaseWithComplexRepository(TestCaseWithInterRepository):
    def setUp(self):
        super().setUp()
        tree_a = self.make_branch_and_tree("a")
        self.controldir = tree_a.branch.controldir
        # add a corrupt inventory 'orphan'
        with (
            tree_a.branch.repository.lock_write(),
            WriteGroup(tree_a.branch.repository),
        ):
            if tree_a.branch.repository._format.supports_ghosts:
                inv_file = tree_a.branch.repository.inventories
                inv_file.add_lines((b"orphan",), [], [])
        # add a real revision 'rev1'
        self.rev1 = tree_a.commit("rev1", allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        self.rev2 = tree_a.commit("rev2", allow_pointless=True)

    def test_search_missing_revision_ids(self):
        # revision ids in repository A but not B are returned, fake ones
        # are stripped. (fake meaning no revision object, but an inventory
        # as some formats keyed off inventory data in the past.)
        # make a repository to compare against that claims to have rev1
        repo_b = self.make_to_repository("rev1_only")
        repo_a = self.controldir.open_repository()
        try:
            repo_b.fetch(repo_a, self.rev1)
        except errors.NoRoundtrippingSupport:
            raise TestNotApplicable("roundtripping not supported")
        # check the test will be valid
        self.assertFalse(repo_b.has_revision(self.rev2))
        result = repo_b.search_missing_revision_ids(repo_a)
        self.assertEqual({self.rev2}, result.get_keys())
        self.assertEqual(("search", {self.rev2}, {self.rev1}, 1), result.get_recipe())

    def test_absent_requested_raises(self):
        # Asking for missing revisions with a tip that is itself absent in the
        # source raises NoSuchRevision.
        repo_b = self.make_to_repository("target")
        repo_a = self.controldir.open_repository()
        # No pizza revisions anywhere
        self.assertFalse(repo_a.has_revision(b"pizza"))
        self.assertFalse(repo_b.has_revision(b"pizza"))
        # Asking specifically for an absent revision errors.
        self.assertRaises(
            errors.NoSuchRevision,
            repo_b.search_missing_revision_ids,
            repo_a,
            revision_ids=[b"pizza"],
            find_ghosts=True,
        )
        self.assertRaises(
            errors.NoSuchRevision,
            repo_b.search_missing_revision_ids,
            repo_a,
            revision_ids=[b"pizza"],
            find_ghosts=False,
        )

    def test_search_missing_rev_limited(self):
        # revision ids in repository A that are not referenced by the
        # requested revision are not returned.
        # make a repository to compare against that is empty
        repo_b = self.make_to_repository("empty")
        repo_a = self.controldir.open_repository()
        result = repo_b.search_missing_revision_ids(repo_a, revision_ids=[self.rev1])
        self.assertEqual({self.rev1}, result.get_keys())
        self.assertEqual(
            ("search", {self.rev1}, {NULL_REVISION}, 1), result.get_recipe()
        )

    def test_search_missing_revision_ids_limit(self):
        # The limit= argument makes fetch() limit
        # the results to the first X topo-sorted revisions.
        repo_b = self.make_to_repository("rev1_only")
        repo_a = self.controldir.open_repository()
        # check the test will be valid
        self.assertFalse(repo_b.has_revision(self.rev2))
        try:
            result = repo_b.search_missing_revision_ids(repo_a, limit=1)
        except errors.FetchLimitUnsupported:
            raise TestNotApplicable("interrepo does not support limited fetches")
        self.assertEqual(("search", {self.rev1}, {b"null:"}, 1), result.get_recipe())

    def test_fetch_fetches_signatures_too(self):
        if not self.repository_format.supports_revision_signatures:
            raise TestNotApplicable("from repository does not support signatures")
        if not self.repository_format_to.supports_revision_signatures:
            raise TestNotApplicable("to repository does not support signatures")
        # and sign 'rev2'
        tree_a = WorkingTree.open("a")
        with (
            tree_a.branch.repository.lock_write(),
            WriteGroup(tree_a.branch.repository),
        ):
            tree_a.branch.repository.sign_revision(
                self.rev2, breezy.gpg.LoopbackGPGStrategy(None)
            )

        from_repo = self.controldir.open_repository()
        from_signature = from_repo.get_signature_text(self.rev2)
        to_repo = self.make_to_repository("target")
        try:
            to_repo.fetch(from_repo)
        except errors.NoRoundtrippingSupport:
            raise TestNotApplicable("interrepo does not support roundtripping")
        to_signature = to_repo.get_signature_text(self.rev2)
        self.assertEqual(from_signature, to_signature)


class TestCaseWithGhosts(TestCaseWithInterRepository):
    def test_fetch_all_fixes_up_ghost(self):
        # we want two repositories at this point:
        # one with a revision that is a ghost in the other
        # repository.
        # 'ghost' is present in has_ghost, 'ghost' is absent in 'missing_ghost'.
        # 'references' is present in both repositories, and 'tip' is present
        # just in has_ghost.
        # has_ghost       missing_ghost
        # ------------------------------
        # 'ghost'             -
        # 'references'    'references'
        # 'tip'               -
        # In this test we fetch 'tip' which should not fetch 'ghost'
        has_ghost = self.make_repository("has_ghost")
        missing_ghost = self.make_repository("missing_ghost")
        if [repo._format.supports_ghosts for repo in (has_ghost, missing_ghost)] != [
            True,
            True,
        ]:
            raise TestNotApplicable("Need ghost support.")

        def add_commit(repo, revision_id, parent_ids):
            repo.lock_write()
            repo.start_write_group()
            inv = Inventory(revision_id=revision_id)
            inv.root.revision = revision_id
            root_id = inv.root.file_id
            sha1 = repo.add_inventory(revision_id, inv, parent_ids)
            repo.texts.add_lines((root_id, revision_id), [], [])
            rev = breezy.revision.Revision(
                timestamp=0,
                timezone=None,
                committer="Foo Bar <foo@example.com>",
                message="Message",
                inventory_sha1=sha1,
                revision_id=revision_id,
            )
            rev.parent_ids = parent_ids
            repo.add_revision(revision_id, rev)
            repo.commit_write_group()
            repo.unlock()

        add_commit(has_ghost, b"ghost", [])
        add_commit(has_ghost, b"references", [b"ghost"])
        add_commit(missing_ghost, b"references", [b"ghost"])
        add_commit(has_ghost, b"tip", [b"references"])
        missing_ghost.fetch(has_ghost, b"tip", find_ghosts=True)
        # missing ghost now has tip and ghost.
        missing_ghost.get_revision(b"tip")
        missing_ghost.get_inventory(b"tip")
        missing_ghost.get_revision(b"ghost")
        missing_ghost.get_inventory(b"ghost")
        # rev must not be corrupt now
        self.assertThat(
            [b"ghost", b"references", b"tip"], MatchesAncestry(missing_ghost, b"tip")
        )
