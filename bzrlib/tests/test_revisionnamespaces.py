# Copyright (C) 2004, 2005 by Canonical Ltd

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

import os
import time

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir
from bzrlib.errors import NoCommonAncestor, NoCommits
from bzrlib.errors import NoSuchRevision
from bzrlib.clone import copy_branch
from bzrlib.builtins import merge
from bzrlib.revisionspec import RevisionSpec

class TestRevisionNamespaces(TestCaseInTempDir):

    def test_revision_namespaces(self):
        """Test revision specifiers.

        These identify revisions by date, etc."""

        b = Branch.initialize(u'.')

        b.working_tree().commit('Commit one', rev_id='a@r-0-1', timestamp=time.time() - 60*60*24)
        b.working_tree().commit('Commit two', rev_id='a@r-0-2')
        b.working_tree().commit('Commit three', rev_id='a@r-0-3')

        self.assertEquals(RevisionSpec(None).in_history(b), (0, None))
        self.assertEquals(RevisionSpec(1).in_history(b), (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revno:1').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revid:a@r-0-1').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertRaises(NoSuchRevision,
                          RevisionSpec('revid:a@r-0-0').in_history, b)
        self.assertRaises(TypeError, RevisionSpec, object)

        self.assertEquals(RevisionSpec('date:today').in_history(b),
                          (2, 'a@r-0-2'))
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
        b2 = Branch.initialize('newbranch')
        self.assertRaises(NoCommits, RevisionSpec('ancestor:.').in_history, b2)

        os.mkdir('copy')
        b3 = copy_branch(b, 'copy')
        b3.working_tree().commit('Commit four', rev_id='b@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:.').in_history(b3).rev_id,
                          'a@r-0-3')
        merge(['copy', -1], [None, None])
        b.working_tree().commit('Commit five', rev_id='a@r-0-4')
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
        branch = Branch.initialize('branch1')
        branch.working_tree().add(['file'])
        branch.working_tree().commit('add file')
        copy_branch(branch, 'branch2')
        print >> open('branch2/file', 'w'), 'new content'
        branch2 = Branch.open('branch2')
        branch2.working_tree().commit('update file', rev_id='A')
        spec = RevisionSpec('branch:./branch2/.bzr/../')
        rev_info = spec.in_history(branch)
        self.assertEqual(rev_info, (None, 'A'))

