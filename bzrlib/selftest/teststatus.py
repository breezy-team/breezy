# Copyright (C) 2005 by Canonical Ltd

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


"""Tests of status command.

Most of these depend on the particular formatting used.
"""


from bzrlib.selftest import TestCaseInTempDir
from bzrlib.revisionspec import RevisionSpec

class BranchStatus(TestCaseInTempDir):
    
    def test_branch_status(self): 
        """Basic 'bzr mkdir' operation"""
        from cStringIO import StringIO
        from bzrlib.status import show_status
        from bzrlib.branch import Branch
        
        b = Branch.initialize('.')

        # status with nothing
        tof = StringIO()
        show_status(b, to_file=tof)
        self.assertEquals(tof.getvalue(), "")

        tof = StringIO()
        self.build_tree(['hello.c', 'bye.c'])
        b.add_pending_merge('pending@pending-0-0')
        show_status(b, to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  bye.c\n',
                           '  hello.c\n',
                           'pending merges:\n',
                           '  pending@pending-0-0\n'
                           ])

    def test_branch_status_revisions(self):
        """Tests branch status with revisions"""
        from cStringIO import StringIO
        from bzrlib.status import show_status
        from bzrlib.branch import Branch
        
        b = Branch.initialize('.')

        tof = StringIO()
        self.build_tree(['hello.c', 'bye.c'])
        b.add('hello.c')
        b.add('bye.c')
        b.commit('Test message')

        tof = StringIO()
        revs =[]
        revs.append(RevisionSpec(0))
        
        show_status(b, to_file=tof, revision=revs)
        
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['added:\n',
                           '  bye.c\n',
                           '  hello.c\n'])

        self.build_tree(['more.c'])
        b.add('more.c')
        b.commit('Another test message')
        
        tof = StringIO()
        revs.append(RevisionSpec(1))
        
        show_status(b, to_file=tof, revision=revs)
        
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['added:\n',
                           '  bye.c\n',
                           '  hello.c\n'])

