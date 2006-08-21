# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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
import time

from bzrlib import (
    errors,
    )
from bzrlib.builtins import merge
from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport
from bzrlib.errors import NoCommonAncestor, NoCommits
from bzrlib.revisionspec import RevisionSpec


class TestRevisionNamespaces(TestCaseWithTransport):

    def test_revno_n_path(self):
        """Test revision specifiers.

        These identify revisions by date, etc."""
        wta = self.make_branch_and_tree('a')
        ba = wta.branch
        
        wta.commit('Commit one', rev_id='a@r-0-1')
        wta.commit('Commit two', rev_id='a@r-0-2')
        wta.commit('Commit three', rev_id='a@r-0-3')

        wtb = self.make_branch_and_tree('b')
        bb = wtb.branch

        wtb.commit('Commit one', rev_id='b@r-0-1')
        wtb.commit('Commit two', rev_id='b@r-0-2')
        wtb.commit('Commit three', rev_id='b@r-0-3')

        self.assertEquals(RevisionSpec('revno:1:a/').in_history(ba),
                          (1, 'a@r-0-1'))
        # The argument of in_history should be ignored since it is
        # redundant with the path in the spec.
        self.assertEquals(RevisionSpec('revno:1:a/').in_history(None),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revno:1:a/').in_history(bb),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revno:2:b/').in_history(None),
                          (2, 'b@r-0-2'))


    def test_revision_namespaces(self):
        """Test revision specifiers.

        These identify revisions by date, etc."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        wt.commit('Commit one', rev_id='a@r-0-1', timestamp=time.time() - 60*60*24)
        wt.commit('Commit two', rev_id='a@r-0-2')
        wt.commit('Commit three', rev_id='a@r-0-3')

        self.assertEquals(RevisionSpec(None).in_history(b), (0, None))
        self.assertEquals(RevisionSpec(1).in_history(b), (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revno:1').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revid:a@r-0-1').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revid:a@r-0-0').in_history, b)
        self.assertRaises(TypeError, RevisionSpec, object)

        self.assertEquals(RevisionSpec('date:today').in_history(b),
                          (2, 'a@r-0-2'))
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('date:tomorrow').in_history, b)
        self.assertEquals(RevisionSpec('date:yesterday').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('before:date:today').in_history(b),
                          (1, 'a@r-0-1'))

        self.assertEquals(RevisionSpec('last:1').in_history(b),
                          (3, 'a@r-0-3'))
        self.assertEquals(RevisionSpec('-1').in_history(b), (3, 'a@r-0-3'))
#        self.assertEquals(b.get_revision_info('last:1'), (3, 'a@r-0-3'))
#        self.assertEquals(b.get_revision_info('-1'), (3, 'a@r-0-3'))

        self.assertEquals(RevisionSpec('ancestor:.').in_history(b).rev_id,
                          'a@r-0-3')

        os.mkdir('newbranch')
        wt2 = self.make_branch_and_tree('newbranch')
        b2 = wt2.branch
        self.assertRaises(NoCommits, RevisionSpec('ancestor:.').in_history, b2)

        d3 = b.bzrdir.sprout('copy')
        b3 = d3.open_branch()
        wt3 = d3.open_workingtree()
        wt3.commit('Commit four', rev_id='b@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:.').in_history(b3).rev_id,
                          'a@r-0-3')
        merge(['copy', -1], [None, None])
        wt.commit('Commit five', rev_id='a@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:copy').in_history(b).rev_id,
                          'b@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:.').in_history(b3).rev_id,
                          'b@r-0-4')

        # This should be in the revision store, but not in revision-history
        self.assertEquals((None, 'b@r-0-4'),
                RevisionSpec('revid:b@r-0-4').in_history(b))

    def test_branch_namespace(self):
        """Ensure that the branch namespace pulls in the requisite content."""
        self.build_tree(['branch1/', 'branch1/file', 'branch2/'])
        wt = self.make_branch_and_tree('branch1')
        branch = wt.branch
        wt.add(['file'])
        wt.commit('add file')
        d2 = branch.bzrdir.sprout('branch2')
        print >> open('branch2/file', 'w'), 'new content'
        branch2 = d2.open_branch()
        d2.open_workingtree().commit('update file', rev_id='A')
        spec = RevisionSpec('branch:./branch2/.bzr/../')
        rev_info = spec.in_history(branch)
        self.assertEqual(rev_info, (None, 'A'))

    def test_invalid_revno(self):
        self.build_tree(['branch1/', 'branch1/file'])
        wt = self.make_branch_and_tree('branch1')
        wt.add('file')
        wt.commit('first commit', rev_id='r1')
        wt.commit('second commit', rev_id='r2')

        # In the future -20 will probably just fall back to 0
        # but for now, we want to make sure it raises the right error
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('-20').in_history, wt.branch)
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('10').in_history, wt.branch)

        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revno:-20').in_history, wt.branch)
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revno:10').in_history, wt.branch)
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revno:a').in_history, wt.branch)


# Basic class, which just creates a really basic set of revisions
class TestRevisionSpec(TestCaseWithTransport):

    def setUp(self):
        super(TestRevisionSpec, self).setUp()

        self.tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        self.tree.add(['a'])
        self.tree.commit('a', rev_id='r1')

        self.tree2 = self.tree.bzrdir.sprout('tree2').open_workingtree()
        self.tree2.commit('alt', rev_id='alt_r2')

        self.tree.branch.repository.fetch(self.tree2.branch.repository,
                                          revision_id='alt_r2')
        self.tree.set_pending_merges(['alt_r2'])
        self.tree.commit('second', rev_id='r2')

    def get_in_history(self, revision_spec):
        return RevisionSpec(revision_spec).in_history(self.tree.branch)

    def assertInHistoryIs(self, exp_revno, exp_revision_id, revision_spec):
        rev_info = self.get_in_history(revision_spec)
        self.assertEqual(exp_revno, rev_info.revno,
                         'Revision spec: %s returned wrong revno: %s != %s'
                         % (revision_spec, exp_revno, rev_info.revno))
        self.assertEqual(exp_revision_id, rev_info.rev_id,
                         'Revision spec: %s returned wrong revision id:'
                         ' %s != %s'
                         % (revision_spec, exp_revision_id, rev_info.rev_id))

    def assertInvalid(self, revision_spec, extra='', real_spec=None):
        if real_spec is None:
            real_spec = revision_spec
        try:
            self.get_in_history(revision_spec)
        except errors.InvalidRevisionSpec, e:
            self.assertEqual(real_spec, e.spec)
            self.assertEqual(extra, e.extra)
        else:
            self.fail('Expected InvalidRevisionSpec to be raised for %s'
                      % (revision_spec,))


class TestRevisionSpec_int(TestRevisionSpec):
    
    def test_positive(self):
        self.assertInHistoryIs(0, None, '0')
        self.assertInHistoryIs(1, 'r1', '1')
        self.assertInHistoryIs(2, 'r2', '2')

        self.assertInvalid('3', real_spec=3)

    def test_negative(self):
        self.assertInHistoryIs(2, 'r2', '-1')
        self.assertInHistoryIs(1, 'r1', '-2')

        # XXX: This is probably bogus, and will change to Invalid in the future
        self.assertInHistoryIs(0, None, '-3')


        # TODO: In the future, a negative number that is too large
        # may be translated into the first revision
        self.assertInvalid('-4', real_spec=-4)


class TestRevisionSpec_revno(TestRevisionSpec):

    def test_positive(self):
        self.assertInHistoryIs(0, None, 'revno:0')
        self.assertInHistoryIs(1, 'r1', 'revno:1')
        self.assertInHistoryIs(2, 'r2', 'revno:2')

        self.assertInvalid('revno:3')

    def test_negative(self):
        self.assertInHistoryIs(2, 'r2', 'revno:-1')
        self.assertInHistoryIs(1, 'r1', 'revno:-2')

        # XXX: This is probably bogus, and will change to Invalid in the future
        self.assertInHistoryIs(0, None, 'revno:-3')

        # TODO: In the future, a negative number that is too large
        # may be translated into the first revision
        self.assertInvalid('revno:-4')

    def test_invalid_number(self):
        # Get the right exception text
        try:
            int('X')
        except ValueError, e:
            pass
        self.assertInvalid('revno:X', extra='; ' + str(e))

    def test_missing_number_and_branch(self):
        self.assertInvalid('revno::',
                           extra='; cannot have an empty revno and no branch')

    def test_invalid_number_with_branch(self):
        try:
            int('X')
        except ValueError, e:
            pass
        self.assertInvalid('revno:X:tree2', extra='; ' + str(e))

    def test_with_branch(self):
        # Passing a URL overrides the supplied branch path
        revinfo = self.get_in_history('revno:2:tree2')
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual('alt_r2', revinfo.rev_id)

    def test_with_url(self):
        url = self.get_url() + '/tree2'
        revinfo = self.get_in_history('revno:2:%s' % (url,))
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual('alt_r2', revinfo.rev_id)

    def test_negative_with_url(self):
        url = self.get_url() + '/tree2'
        revinfo = self.get_in_history('revno:-1:%s' % (url,))
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual('alt_r2', revinfo.rev_id)

    def test_invalid_branch(self):
        self.assertRaises(errors.NotBranchError,
                          self.get_in_history, 'revno:-1:tree3')

    def test_invalid_revno_in_branch(self):
        self.tree.commit('three', rev_id='r3')
        self.assertInvalid('revno:3:tree2')


class TestRevisionSpec_revid(TestRevisionSpec):
    
    def test_in_history(self):
        # We should be able to access revisions that are directly
        # in the history.
        self.assertInHistoryIs(1, 'r1', 'revid:r1')
        self.assertInHistoryIs(2, 'r2', 'revid:r2')
        
    def test_missing(self):
        self.assertInvalid('revid:r3')

    def test_merged(self):
        """We can reach revisions in the ancestry"""
        self.assertInHistoryIs(None, 'alt_r2', 'revid:alt_r2')

    def test_not_here(self):
        self.tree2.commit('alt third', rev_id='alt_r3')
        # It exists in tree2, but not in tree
        self.assertInvalid('revid:alt_r3')

    def test_in_repository(self):
        """We can get any revision id in the repository"""
        # XXX: This may change in the future, but for now, it is true
        self.tree2.commit('alt third', rev_id='alt_r3')
        self.tree.branch.repository.fetch(self.tree2.branch.repository,
                                          revision_id='alt_r3')
        self.assertInHistoryIs(None, 'alt_r3', 'revid:alt_r3')
