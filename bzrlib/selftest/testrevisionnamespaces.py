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
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.errors import NoCommonAncestor, NoCommits
from bzrlib.branch import copy_branch
from bzrlib.merge import merge

class TestRevisionNamespaces(TestCaseInTempDir):

    def test_revision_namespaces(self):
        """Test revision specifiers.

        These identify revisions by date, etc."""
        from bzrlib.errors import NoSuchRevision
        from bzrlib.branch import Branch
        from bzrlib.revisionspec import RevisionSpec

        b = Branch.initialize('.')

        b.commit('Commit one', rev_id='a@r-0-1', timestamp=time.time() - 60*60*24)
        b.commit('Commit two', rev_id='a@r-0-2')
        b.commit('Commit three', rev_id='a@r-0-3')

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
        b3.commit('Commit four', rev_id='b@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:.').in_history(b3).rev_id,
                          'a@r-0-3')
        merge(['copy', -1], [None, None])
        b.commit('Commit five', rev_id='a@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:copy').in_history(b).rev_id,
                          'b@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:.').in_history(b3).rev_id,
                          'b@r-0-4')
