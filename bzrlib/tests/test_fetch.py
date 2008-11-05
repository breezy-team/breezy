# Copyright (C) 2005, 2007 Canonical Ltd
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
import re
import sys

import bzrlib
from bzrlib import (
    bzrdir,
    errors,
    merge,
    repository,
    versionedfile,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.repofmt import knitrepo
from bzrlib.tests import TestCaseWithTransport
from bzrlib.tests.http_utils import TestCaseWithWebserver
from bzrlib.tests.test_revision import make_branches
from bzrlib.trace import mutter
from bzrlib.upgrade import Convert
from bzrlib.workingtree import WorkingTree

# These tests are a bit old; please instead add new tests into
# interrepository_implementations/ so they'll run on all relevant
# combinations.


def has_revision(branch, revision_id):
    return branch.repository.has_revision(revision_id)

def fetch_steps(self, br_a, br_b, writable_a):
    """A foreign test method for testing fetch locally and remotely."""
     
    # TODO RBC 20060201 make this a repository test.
    repo_b = br_b.repository
    self.assertFalse(repo_b.has_revision(br_a.revision_history()[3]))
    self.assertTrue(repo_b.has_revision(br_a.revision_history()[2]))
    self.assertEquals(len(br_b.revision_history()), 7)
    self.assertEquals(br_b.fetch(br_a, br_a.revision_history()[2])[0], 0)
    # branch.fetch is not supposed to alter the revision history
    self.assertEquals(len(br_b.revision_history()), 7)
    self.assertFalse(repo_b.has_revision(br_a.revision_history()[3]))

    # fetching the next revision up in sample data copies one revision
    self.assertEquals(br_b.fetch(br_a, br_a.revision_history()[3])[0], 1)
    self.assertTrue(repo_b.has_revision(br_a.revision_history()[3]))
    self.assertFalse(has_revision(br_a, br_b.revision_history()[6]))
    self.assertTrue(br_a.repository.has_revision(br_b.revision_history()[5]))

    # When a non-branch ancestor is missing, it should be unlisted...
    # as its not reference from the inventory weave.
    br_b4 = self.make_branch('br_4')
    count, failures = br_b4.fetch(br_b)
    self.assertEqual(count, 7)
    self.assertEqual(failures, [])

    self.assertEqual(writable_a.fetch(br_b)[0], 1)
    self.assertTrue(has_revision(br_a, br_b.revision_history()[3]))
    self.assertTrue(has_revision(br_a, br_b.revision_history()[4]))
        
    br_b2 = self.make_branch('br_b2')
    self.assertEquals(br_b2.fetch(br_b)[0], 7)
    self.assertTrue(has_revision(br_b2, br_b.revision_history()[4]))
    self.assertTrue(has_revision(br_b2, br_a.revision_history()[2]))
    self.assertFalse(has_revision(br_b2, br_a.revision_history()[3]))

    br_a2 = self.make_branch('br_a2')
    self.assertEquals(br_a2.fetch(br_a)[0], 9)
    self.assertTrue(has_revision(br_a2, br_b.revision_history()[4]))
    self.assertTrue(has_revision(br_a2, br_a.revision_history()[3]))
    self.assertTrue(has_revision(br_a2, br_a.revision_history()[2]))

    br_a3 = self.make_branch('br_a3')
    # pulling a branch with no revisions grabs nothing, regardless of 
    # whats in the inventory.
    self.assertEquals(br_a3.fetch(br_a2)[0], 0)
    for revno in range(4):
        self.assertFalse(
            br_a3.repository.has_revision(br_a.revision_history()[revno]))
    self.assertEqual(br_a3.fetch(br_a2, br_a.revision_history()[2])[0], 3)
    # pull the 3 revisions introduced by a@u-0-3
    fetched = br_a3.fetch(br_a2, br_a.revision_history()[3])[0]
    self.assertEquals(fetched, 3, "fetched %d instead of 3" % fetched)
    # InstallFailed should be raised if the branch is missing the revision
    # that was requested.
    self.assertRaises(errors.InstallFailed, br_a3.fetch, br_a2, 'pizza')

    # TODO: Test trying to fetch from a branch that points to a revision not
    # actually present in its repository.  Not every branch format allows you
    # to directly point to such revisions, so it's a bit complicated to
    # construct.  One way would be to uncommit and gc the revision, but not
    # every branch supports that.  -- mbp 20070814

    #TODO: test that fetch correctly does reweaving when needed. RBC 20051008
    # Note that this means - updating the weave when ghosts are filled in to 
    # add the right parents.


class TestFetch(TestCaseWithTransport):

    def test_fetch(self):
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches(self, format='dirstate-tags')
        fetch_steps(self, br_a, br_b, br_a)

    def test_fetch_self(self):
        wt = self.make_branch_and_tree('br')
        self.assertEqual(wt.branch.fetch(wt.branch), (0, []))

    def test_fetch_root_knit(self):
        """Ensure that knit2.fetch() updates the root knit
        
        This tests the case where the root has a new revision, but there are no
        corresponding filename, parent, contents or other changes.
        """
        knit1_format = bzrdir.BzrDirMetaFormat1()
        knit1_format.repository_format = knitrepo.RepositoryFormatKnit1()
        knit2_format = bzrdir.BzrDirMetaFormat1()
        knit2_format.repository_format = knitrepo.RepositoryFormatKnit3()
        # we start with a knit1 repository because that causes the
        # root revision to change for each commit, even though the content,
        # parent, name, and other attributes are unchanged.
        tree = self.make_branch_and_tree('tree', knit1_format)
        tree.set_root_id('tree-root')
        tree.commit('rev1', rev_id='rev1')
        tree.commit('rev2', rev_id='rev2')

        # Now we convert it to a knit2 repository so that it has a root knit
        Convert(tree.basedir, knit2_format)
        tree = WorkingTree.open(tree.basedir)
        branch = self.make_branch('branch', format=knit2_format)
        branch.pull(tree.branch, stop_revision='rev1')
        repo = branch.repository
        repo.lock_read()
        try:
            # Make sure fetch retrieved only what we requested
            self.assertEqual({('tree-root', 'rev1'):()},
                repo.texts.get_parent_map(
                    [('tree-root', 'rev1'), ('tree-root', 'rev2')]))
        finally:
            repo.unlock()
        branch.pull(tree.branch)
        # Make sure that the next revision in the root knit was retrieved,
        # even though the text, name, parent_id, etc., were unchanged.
        repo.lock_read()
        try:
            # Make sure fetch retrieved only what we requested
            self.assertEqual({('tree-root', 'rev2'):(('tree-root', 'rev1'),)},
                repo.texts.get_parent_map([('tree-root', 'rev2')]))
        finally:
            repo.unlock()

    def test_fetch_incompatible(self):
        knit_tree = self.make_branch_and_tree('knit', format='knit')
        knit3_tree = self.make_branch_and_tree('knit3',
            format='dirstate-with-subtree')
        knit3_tree.commit('blah')
        e = self.assertRaises(errors.IncompatibleRepositories,
                              knit_tree.branch.fetch, knit3_tree.branch)
        self.assertContainsRe(str(e),
            r"(?m).*/knit.*\nis not compatible with\n.*/knit3/.*\n"
            r"different rich-root support")


class TestMergeFetch(TestCaseWithTransport):

    def test_merge_fetches_unrelated(self):
        """Merge brings across history from unrelated source"""
        wt1 = self.make_branch_and_tree('br1')
        br1 = wt1.branch
        wt1.commit(message='rev 1-1', rev_id='1-1')
        wt1.commit(message='rev 1-2', rev_id='1-2')
        wt2 = self.make_branch_and_tree('br2')
        br2 = wt2.branch
        wt2.commit(message='rev 2-1', rev_id='2-1')
        wt2.merge_from_branch(br1, from_revision='null:')
        self._check_revs_present(br2)

    def test_merge_fetches(self):
        """Merge brings across history from source"""
        wt1 = self.make_branch_and_tree('br1')
        br1 = wt1.branch
        wt1.commit(message='rev 1-1', rev_id='1-1')
        dir_2 = br1.bzrdir.sprout('br2')
        br2 = dir_2.open_branch()
        wt1.commit(message='rev 1-2', rev_id='1-2')
        wt2 = dir_2.open_workingtree()
        wt2.commit(message='rev 2-1', rev_id='2-1')
        wt2.merge_from_branch(br1)
        self._check_revs_present(br2)

    def _check_revs_present(self, br2):
        for rev_id in '1-1', '1-2', '2-1':
            self.assertTrue(br2.repository.has_revision(rev_id))
            rev = br2.repository.get_revision(rev_id)
            self.assertEqual(rev.revision_id, rev_id)
            self.assertTrue(br2.repository.get_inventory(rev_id))


class TestMergeFileHistory(TestCaseWithTransport):

    def setUp(self):
        super(TestMergeFileHistory, self).setUp()
        wt1 = self.make_branch_and_tree('br1')
        br1 = wt1.branch
        self.build_tree_contents([('br1/file', 'original contents\n')])
        wt1.add('file', 'this-file-id')
        wt1.commit(message='rev 1-1', rev_id='1-1')
        dir_2 = br1.bzrdir.sprout('br2')
        br2 = dir_2.open_branch()
        wt2 = dir_2.open_workingtree()
        self.build_tree_contents([('br1/file', 'original from 1\n')])
        wt1.commit(message='rev 1-2', rev_id='1-2')
        self.build_tree_contents([('br1/file', 'agreement\n')])
        wt1.commit(message='rev 1-3', rev_id='1-3')
        self.build_tree_contents([('br2/file', 'contents in 2\n')])
        wt2.commit(message='rev 2-1', rev_id='2-1')
        self.build_tree_contents([('br2/file', 'agreement\n')])
        wt2.commit(message='rev 2-2', rev_id='2-2')

    def test_merge_fetches_file_history(self):
        """Merge brings across file histories"""
        br2 = Branch.open('br2')
        br1 = Branch.open('br1')
        wt2 = WorkingTree.open('br2').merge_from_branch(br1)
        br2.lock_read()
        self.addCleanup(br2.unlock)
        for rev_id, text in [('1-2', 'original from 1\n'),
                             ('1-3', 'agreement\n'),
                             ('2-1', 'contents in 2\n'),
                             ('2-2', 'agreement\n')]:
            self.assertEqualDiff(
                br2.repository.revision_tree(
                    rev_id).get_file_text('this-file-id'), text)


class TestHttpFetch(TestCaseWithWebserver):
    # FIXME RBC 20060124 this really isn't web specific, perhaps an
    # instrumented readonly transport? Can we do an instrumented
    # adapter and use self.get_readonly_url ?

    def test_fetch(self):
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches(self)
        br_rem_a = Branch.open(self.get_readonly_url('branch1'))
        fetch_steps(self, br_rem_a, br_b, br_a)

    def _count_log_matches(self, target, logs):
        """Count the number of times the target file pattern was fetched in an http log"""
        get_succeeds_re = re.compile(
            '.*"GET .*%s HTTP/1.1" 20[06] - "-" "bzr/%s' %
            (     target,                    bzrlib.__version__))
        c = 0
        for line in logs:
            if get_succeeds_re.match(line):
                c += 1
        return c

    def test_weaves_are_retrieved_once(self):
        self.build_tree(("source/", "source/file", "target/"))
        # This test depends on knit dasta storage.
        wt = self.make_branch_and_tree('source', format='dirstate-tags')
        branch = wt.branch
        wt.add(["file"], ["id"])
        wt.commit("added file")
        open("source/file", 'w').write("blah\n")
        wt.commit("changed file")
        target = BzrDir.create_branch_and_repo("target/")
        source = Branch.open(self.get_readonly_url("source/"))
        self.assertEqual(target.fetch(source), (2, []))
        # this is the path to the literal file. As format changes 
        # occur it needs to be updated. FIXME: ask the store for the
        # path.
        self.log("web server logs are:")
        http_logs = self.get_readonly_server().logs
        self.log('\n'.join(http_logs))
        # unfortunately this log entry is branch format specific. We could 
        # factor out the 'what files does this format use' to a method on the 
        # repository, which would let us to this generically. RBC 20060419
        # RBC 20080408: Or perhaps we can assert that no files are fully read
        # twice?
        self.assertEqual(1, self._count_log_matches('/ce/id.kndx', http_logs))
        self.assertEqual(1, self._count_log_matches('/ce/id.knit', http_logs))
        self.assertEqual(1, self._count_log_matches('inventory.kndx', http_logs))
        # this r-h check test will prevent regressions, but it currently already 
        # passes, before the patch to cache-rh is applied :[
        self.assertTrue(1 >= self._count_log_matches('revision-history',
                                                     http_logs))
        self.assertTrue(1 >= self._count_log_matches('last-revision',
                                                     http_logs))
        # FIXME naughty poking in there.
        self.get_readonly_server().logs = []
        # check there is nothing more to fetch.  We take care to re-use the
        # existing transport so that the request logs we're about to examine
        # aren't cluttered with redundant probes for a smart server.
        # XXX: Perhaps this further parameterisation: test http with smart
        # server, and test http without smart server?
        source = Branch.open(
            self.get_readonly_url("source/"),
            possible_transports=[source.bzrdir.root_transport])
        self.assertEqual(target.fetch(source), (0, []))
        # should make just two requests
        http_logs = self.get_readonly_server().logs
        self.log("web server logs are:")
        self.log('\n'.join(http_logs))
        self.assertEqual(1, self._count_log_matches('branch-format', http_logs))
        self.assertEqual(1, self._count_log_matches('branch/format', http_logs))
        self.assertEqual(1, self._count_log_matches('repository/format',
            http_logs))
        self.assertTrue(1 >= self._count_log_matches('revision-history',
                                                     http_logs))
        self.assertTrue(1 >= self._count_log_matches('last-revision',
                                                     http_logs))
        self.assertEqual(4, len(http_logs))


class TestKnitToPackFetch(TestCaseWithTransport):

    def find_get_record_stream(self, calls):
        """In a list of calls, find 'get_record_stream' calls.

        This also ensures that there is only one get_record_stream call.
        """
        get_record_call = None
        for call in calls:
            if call[0] == 'get_record_stream':
                self.assertIs(None, get_record_call,
                              "there should only be one call to"
                              " get_record_stream")
                get_record_call = call
        self.assertIsNot(None, get_record_call,
                         "there should be exactly one call to "
                         " get_record_stream")
        return get_record_call

    def test_fetch_with_deltas_no_delta_closure(self):
        tree = self.make_branch_and_tree('source', format='dirstate')
        target = self.make_repository('target', format='pack-0.92')
        self.build_tree(['source/file'])
        tree.set_root_id('root-id')
        tree.add('file', 'file-id')
        tree.commit('one', rev_id='rev-one')
        source = tree.branch.repository
        source.texts = versionedfile.RecordingVersionedFilesDecorator(
                        source.texts)
        source.signatures = versionedfile.RecordingVersionedFilesDecorator(
                        source.signatures)
        source.revisions = versionedfile.RecordingVersionedFilesDecorator(
                        source.revisions)
        source.inventories = versionedfile.RecordingVersionedFilesDecorator(
                        source.inventories)
        # precondition
        self.assertTrue(target._fetch_uses_deltas)
        target.fetch(source, revision_id='rev-one')
        self.assertEqual(('get_record_stream', [('file-id', 'rev-one')],
                          target._fetch_order, False),
                         self.find_get_record_stream(source.texts.calls))
        self.assertEqual(('get_record_stream', [('rev-one',)],
                          target._fetch_order, False),
                         self.find_get_record_stream(source.inventories.calls))
        # Because of bugs in the old fetch code, revisions could accidentally
        # have deltas present in knits. However, it was never intended, so we
        # always for include_delta_closure=True, to make sure we get fulltexts.
        # bug #261339
        self.assertEqual(('get_record_stream', [('rev-one',)],
                          target._fetch_order, True),
                         self.find_get_record_stream(source.revisions.calls))
        # XXX: Signatures is special, and slightly broken. The
        # standard item_keys_introduced_by actually does a lookup for every
        # signature to see if it exists, rather than waiting to do them all at
        # once at the end. The fetch code then does an all-at-once and just
        # allows for some of them to be missing.
        # So we know there will be extra calls, but the *last* one is the one
        # we care about.
        signature_calls = source.signatures.calls[-1:]
        self.assertEqual(('get_record_stream', [('rev-one',)],
                          target._fetch_order, True),
                         self.find_get_record_stream(signature_calls))

    def test_fetch_no_deltas_with_delta_closure(self):
        tree = self.make_branch_and_tree('source', format='dirstate')
        target = self.make_repository('target', format='pack-0.92')
        self.build_tree(['source/file'])
        tree.set_root_id('root-id')
        tree.add('file', 'file-id')
        tree.commit('one', rev_id='rev-one')
        source = tree.branch.repository
        source.texts = versionedfile.RecordingVersionedFilesDecorator(
                        source.texts)
        source.signatures = versionedfile.RecordingVersionedFilesDecorator(
                        source.signatures)
        source.revisions = versionedfile.RecordingVersionedFilesDecorator(
                        source.revisions)
        source.inventories = versionedfile.RecordingVersionedFilesDecorator(
                        source.inventories)
        target._fetch_uses_deltas = False
        target.fetch(source, revision_id='rev-one')
        self.assertEqual(('get_record_stream', [('file-id', 'rev-one')],
                          target._fetch_order, True),
                         self.find_get_record_stream(source.texts.calls))
        self.assertEqual(('get_record_stream', [('rev-one',)],
                          target._fetch_order, True),
                         self.find_get_record_stream(source.inventories.calls))
        self.assertEqual(('get_record_stream', [('rev-one',)],
                          target._fetch_order, True),
                         self.find_get_record_stream(source.revisions.calls))
        # XXX: Signatures is special, and slightly broken. The
        # standard item_keys_introduced_by actually does a lookup for every
        # signature to see if it exists, rather than waiting to do them all at
        # once at the end. The fetch code then does an all-at-once and just
        # allows for some of them to be missing.
        # So we know there will be extra calls, but the *last* one is the one
        # we care about.
        signature_calls = source.signatures.calls[-1:]
        self.assertEqual(('get_record_stream', [('rev-one',)],
                          target._fetch_order, True),
                         self.find_get_record_stream(signature_calls))


class Test1To2Fetch(TestCaseWithTransport):
    """Tests for Model1To2 failure modes"""

    def make_tree_and_repo(self):
        self.tree = self.make_branch_and_tree('tree', format='pack-0.92')
        self.repo = self.make_repository('rich-repo', format='rich-root-pack')
        self.repo.lock_write()
        self.addCleanup(self.repo.unlock)

    def do_fetch_order_test(self, first, second):
        """Test that fetch works no matter what the set order of revision is.

        This test depends on the order of items in a set, which is
        implementation-dependant, so we test A, B and then B, A.
        """
        self.make_tree_and_repo()
        self.tree.commit('Commit 1', rev_id=first)
        self.tree.commit('Commit 2', rev_id=second)
        self.repo.fetch(self.tree.branch.repository, second)

    def test_fetch_order_AB(self):
        """See do_fetch_order_test"""
        self.do_fetch_order_test('A', 'B')

    def test_fetch_order_BA(self):
        """See do_fetch_order_test"""
        self.do_fetch_order_test('B', 'A')

    def get_parents(self, file_id, revision_id):
        self.repo.lock_read()
        try:
            parent_map = self.repo.texts.get_parent_map([(file_id, revision_id)])
            return parent_map[(file_id, revision_id)]
        finally:
            self.repo.unlock()

    def test_fetch_ghosts(self):
        self.make_tree_and_repo()
        self.tree.commit('first commit', rev_id='left-parent')
        self.tree.add_parent_tree_id('ghost-parent')
        fork = self.tree.bzrdir.sprout('fork', 'null:').open_workingtree()
        fork.commit('not a ghost', rev_id='not-ghost-parent')
        self.tree.branch.repository.fetch(fork.branch.repository,
                                     'not-ghost-parent')
        self.tree.add_parent_tree_id('not-ghost-parent')
        self.tree.commit('second commit', rev_id='second-id')
        self.repo.fetch(self.tree.branch.repository, 'second-id')
        root_id = self.tree.get_root_id()
        self.assertEqual(
            ((root_id, 'left-parent'), (root_id, 'ghost-parent'),
             (root_id, 'not-ghost-parent')),
            self.get_parents(root_id, 'second-id'))

    def make_two_commits(self, change_root, fetch_twice):
        self.make_tree_and_repo()
        self.tree.commit('first commit', rev_id='first-id')
        if change_root:
            self.tree.set_root_id('unique-id')
        self.tree.commit('second commit', rev_id='second-id')
        if fetch_twice:
            self.repo.fetch(self.tree.branch.repository, 'first-id')
        self.repo.fetch(self.tree.branch.repository, 'second-id')

    def test_fetch_changed_root(self):
        self.make_two_commits(change_root=True, fetch_twice=False)
        self.assertEqual((), self.get_parents('unique-id', 'second-id'))

    def test_two_fetch_changed_root(self):
        self.make_two_commits(change_root=True, fetch_twice=True)
        self.assertEqual((), self.get_parents('unique-id', 'second-id'))

    def test_two_fetches(self):
        self.make_two_commits(change_root=False, fetch_twice=True)
        self.assertEqual((('TREE_ROOT', 'first-id'),),
            self.get_parents('TREE_ROOT', 'second-id'))
