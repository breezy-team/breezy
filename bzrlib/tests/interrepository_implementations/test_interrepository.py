# (C) 2005, 2006 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for InterRepository implementastions."""


import bzrlib
import bzrlib.bzrdir as bzrdir
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
import bzrlib.errors as errors
from bzrlib.errors import (FileExists,
                           NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
import bzrlib.repository as repository
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport import get_transport


class TestCaseWithInterRepository(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithInterRepository, self).setUp()

    def make_branch(self, relpath):
        repo = self.make_repository(relpath)
        return repo.bzrdir.create_branch()

    def make_bzrdir(self, relpath, bzrdir_format=None):
        try:
            url = self.get_url(relpath)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except FileExists:
                    pass
            if bzrdir_format is None:
                bzrdir_format = self.repository_format._matchingbzrdir
            return bzrdir_format.initialize(url)
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable.")

    def make_repository(self, relpath):
        made_control = self.make_bzrdir(relpath)
        return self.repository_format.initialize(made_control)

    def make_to_repository(self, relpath):
        made_control = self.make_bzrdir(relpath,
            self.repository_format_to._matchingbzrdir)
        return self.repository_format_to.initialize(made_control)


class TestInterRepository(TestCaseWithInterRepository):

    def test_interrepository_get_returns_correct_optimiser(self):
        # we assume the optimising code paths are triggered
        # by the type of the repo not the transport - at this point.
        # we may need to update this test if this changes.
        source_repo = self.make_repository("source")
        target_repo = self.make_to_repository("target")
        interrepo = repository.InterRepository.get(source_repo, target_repo)
        self.assertEqual(self.interrepo_class, interrepo.__class__)

    def test_fetch(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        def check_push_rev1(repo):
            # ensure the revision is missing.
            self.assertRaises(NoSuchRevision, repo.get_revision, 'rev1')
            # fetch with a limit of NULL_REVISION and an explicit progress bar.
            repo.fetch(tree_a.branch.repository,
                       revision_id=NULL_REVISION,
                       pb=bzrlib.progress.DummyProgress())
            # nothing should have been pushed
            self.assertFalse(repo.has_revision('rev1'))
            # fetch with a default limit (grab everything)
            repo.fetch(tree_a.branch.repository)
            # check that b now has all the data from a's first commit.
            rev = repo.get_revision('rev1')
            tree = repo.revision_tree('rev1')
            tree.get_file_text('file1')
            for file_id in tree:
                if tree.inventory[file_id].kind == "file":
                    tree.get_file(file_id).read()

        # makes a target version repo 
        repo_b = self.make_to_repository('b')
        check_push_rev1(repo_b)
        
    def test_fetch_missing_revision_same_location_fails(self):
        repo_a = self.make_repository('.')
        repo_b = repository.Repository.open('.')
        self.assertRaises(errors.NoSuchRevision, repo_b.fetch, repo_a, revision_id='XXX')

    def test_fetch_same_location_trivial_works(self):
        repo_a = self.make_repository('.')
        repo_b = repository.Repository.open('.')
        repo_a.fetch(repo_b)


class TestCaseWithComplexRepository(TestCaseWithInterRepository):

    def setUp(self):
        super(TestCaseWithComplexRepository, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.bzrdir = tree_a.branch.bzrdir
        # add a corrupt inventory 'orphan'
        tree_a.branch.repository.control_weaves.add_text(
            'inventory', 'orphan', [], [],
            tree_a.branch.repository.get_transaction())
        # add a real revision 'rev1'
        tree_a.commit('rev1', rev_id='rev1', allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit('rev2', rev_id='rev2', allow_pointless=True)
        # and sign 'rev2'
        tree_a.branch.repository.sign_revision('rev2',
            bzrlib.gpg.LoopbackGPGStrategy(None))

    def test_missing_revision_ids(self):
        # revision ids in repository A but not B are returned, fake ones
        # are stripped. (fake meaning no revision object, but an inventory 
        # as some formats keyed off inventory data in the past.
        # make a repository to compare against that claims to have rev1
        repo_b = self.make_to_repository('rev1_only')
        repo_a = self.bzrdir.open_repository()
        repo_b.fetch(repo_a, 'rev1')
        # check the test will be valid
        self.assertFalse(repo_b.has_revision('rev2'))
        self.assertEqual(['rev2'],
                         repo_b.missing_revision_ids(repo_a))

    def test_missing_revision_ids_revision_limited(self):
        # revision ids in repository A that are not referenced by the
        # requested revision are not returned.
        # make a repository to compare against that is empty
        repo_b = self.make_to_repository('empty')
        repo_a = self.bzrdir.open_repository()
        self.assertEqual(['rev1'],
                         repo_b.missing_revision_ids(repo_a, revision_id='rev1'))
        
    def test_fetch_preserves_signatures(self):
        from_repo = self.bzrdir.open_repository()
        from_signature = from_repo.revision_store.get('rev2', 'sig').read()
        to_repo = self.make_to_repository('target')
        to_repo.fetch(from_repo)
        to_signature = to_repo.revision_store.get('rev2', 'sig').read()
        self.assertEqual(from_signature, to_signature)

