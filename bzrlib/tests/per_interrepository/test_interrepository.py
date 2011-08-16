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

import bzrlib
import bzrlib.errors as errors
import bzrlib.gpg
from bzrlib.inventory import Inventory
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import (
    TestNotApplicable,
    TestSkipped,
    )
from bzrlib.tests.matchers import MatchesAncestry
from bzrlib.tests.per_interrepository import (
    TestCaseWithInterRepository,
    )


def check_repo_format_for_funky_id_on_win32(repo):
    if not repo._format.supports_funky_characters and sys.platform == 'win32':
        raise TestSkipped("funky chars not allowed on this platform in repository"
                          " %s" % repo.__class__.__name__)


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
        super(TestCaseWithComplexRepository, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.bzrdir = tree_a.branch.bzrdir
        # add a corrupt inventory 'orphan'
        tree_a.branch.repository.lock_write()
        tree_a.branch.repository.start_write_group()
        inv_file = tree_a.branch.repository.inventories
        inv_file.add_lines(('orphan',), [], [])
        tree_a.branch.repository.commit_write_group()
        tree_a.branch.repository.unlock()
        # add a real revision 'rev1'
        tree_a.commit('rev1', rev_id='rev1', allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit('rev2', rev_id='rev2', allow_pointless=True)
        # and sign 'rev2'
        tree_a.branch.repository.lock_write()
        tree_a.branch.repository.start_write_group()
        tree_a.branch.repository.sign_revision('rev2',
            bzrlib.gpg.LoopbackGPGStrategy(None))
        tree_a.branch.repository.commit_write_group()
        tree_a.branch.repository.unlock()

    def test_search_missing_revision_ids(self):
        # revision ids in repository A but not B are returned, fake ones
        # are stripped. (fake meaning no revision object, but an inventory
        # as some formats keyed off inventory data in the past.)
        # make a repository to compare against that claims to have rev1
        repo_b = self.make_to_repository('rev1_only')
        repo_a = self.bzrdir.open_repository()
        repo_b.fetch(repo_a, 'rev1')
        # check the test will be valid
        self.assertFalse(repo_b.has_revision('rev2'))
        result = repo_b.search_missing_revision_ids(repo_a)
        self.assertEqual(set(['rev2']), result.get_keys())
        self.assertEqual(('search', set(['rev2']), set(['rev1']), 1),
            result.get_recipe())

    def test_search_missing_revision_ids_absent_requested_raises(self):
        # Asking for missing revisions with a tip that is itself absent in the
        # source raises NoSuchRevision.
        repo_b = self.make_to_repository('target')
        repo_a = self.bzrdir.open_repository()
        # No pizza revisions anywhere
        self.assertFalse(repo_a.has_revision('pizza'))
        self.assertFalse(repo_b.has_revision('pizza'))
        # Asking specifically for an absent revision errors.
        self.assertRaises(errors.NoSuchRevision,
            repo_b.search_missing_revision_ids, repo_a, revision_ids=['pizza'],
            find_ghosts=True)
        self.assertRaises(errors.NoSuchRevision,
            repo_b.search_missing_revision_ids, repo_a, revision_ids=['pizza'],
            find_ghosts=False)
        self.callDeprecated(
            ['search_missing_revision_ids(revision_id=...) was deprecated in '
             '2.4.  Use revision_ids=[...] instead.'],
            self.assertRaises, errors.NoSuchRevision,
            repo_b.search_missing_revision_ids, repo_a, revision_id='pizza',
            find_ghosts=False)

    def test_search_missing_revision_ids_revision_limited(self):
        # revision ids in repository A that are not referenced by the
        # requested revision are not returned.
        # make a repository to compare against that is empty
        repo_b = self.make_to_repository('empty')
        repo_a = self.bzrdir.open_repository()
        result = repo_b.search_missing_revision_ids(
            repo_a, revision_ids=['rev1'])
        self.assertEqual(set(['rev1']), result.get_keys())
        self.assertEqual(('search', set(['rev1']), set([NULL_REVISION]), 1),
            result.get_recipe())

    def test_search_missing_revision_ids_limit(self):
        # The limit= argument makes fetch() limit
        # the results to the first X topo-sorted revisions.
        repo_b = self.make_to_repository('rev1_only')
        repo_a = self.bzrdir.open_repository()
        # check the test will be valid
        self.assertFalse(repo_b.has_revision('rev2'))
        result = repo_b.search_missing_revision_ids(repo_a, limit=1)
        self.assertEqual(('search', set(['rev1']), set(['null:']), 1),
            result.get_recipe())

    def test_fetch_fetches_signatures_too(self):
        from_repo = self.bzrdir.open_repository()
        from_signature = from_repo.get_signature_text('rev2')
        to_repo = self.make_to_repository('target')
        to_repo.fetch(from_repo)
        to_signature = to_repo.get_signature_text('rev2')
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
        #------------------------------
        # 'ghost'             -
        # 'references'    'references'
        # 'tip'               -
        # In this test we fetch 'tip' which should not fetch 'ghost'
        has_ghost = self.make_repository('has_ghost')
        missing_ghost = self.make_repository('missing_ghost')
        if [True, True] != [repo._format.supports_ghosts for repo in
            (has_ghost, missing_ghost)]:
            raise TestNotApplicable("Need ghost support.")

        def add_commit(repo, revision_id, parent_ids):
            repo.lock_write()
            repo.start_write_group()
            inv = Inventory(revision_id=revision_id)
            inv.root.revision = revision_id
            root_id = inv.root.file_id
            sha1 = repo.add_inventory(revision_id, inv, parent_ids)
            repo.texts.add_lines((root_id, revision_id), [], [])
            rev = bzrlib.revision.Revision(timestamp=0,
                                           timezone=None,
                                           committer="Foo Bar <foo@example.com>",
                                           message="Message",
                                           inventory_sha1=sha1,
                                           revision_id=revision_id)
            rev.parent_ids = parent_ids
            repo.add_revision(revision_id, rev)
            repo.commit_write_group()
            repo.unlock()
        add_commit(has_ghost, 'ghost', [])
        add_commit(has_ghost, 'references', ['ghost'])
        add_commit(missing_ghost, 'references', ['ghost'])
        add_commit(has_ghost, 'tip', ['references'])
        missing_ghost.fetch(has_ghost, 'tip', find_ghosts=True)
        # missing ghost now has tip and ghost.
        rev = missing_ghost.get_revision('tip')
        inv = missing_ghost.get_inventory('tip')
        rev = missing_ghost.get_revision('ghost')
        inv = missing_ghost.get_inventory('ghost')
        # rev must not be corrupt now
        self.assertThat(['ghost', 'references', 'tip'],
            MatchesAncestry(missing_ghost, 'tip'))
