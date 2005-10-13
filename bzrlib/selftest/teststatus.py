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
from bzrlib.merge import merge
from cStringIO import StringIO
from bzrlib.status import show_status
from bzrlib.branch import Branch
from os import mkdir
from bzrlib.clone import copy_branch

class BranchStatus(TestCaseInTempDir):
    
    def test_branch_status(self): 
        """Test basic branch status"""
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

    def status_string(self, branch):
        tof = StringIO()
        show_status(branch, to_file=tof)
        tof.seek(0)
        return tof.getvalue()

    def test_pending(self):
        """Pending merges display works"""
        mkdir("./branch")
        b = Branch.initialize('./branch')
        b.commit("Empty commit 1")
        b_2 = copy_branch(b, './copy')
        b.commit("Empty commit 2")
        merge(["./branch", -1], [None, None], this_dir = './copy')
        message = self.status_string(b_2)
        assert (message.startswith("pending merges:\n")), message
        assert (message.endswith("Empty commit 2\n")), message 
        b_2.commit("merged")
        b.commit("Empty commit 3 blah blah blah blah blah blah blah blah blah")
        merge(["./branch", -1], [None, None], this_dir = './copy')
        message = self.status_string(b_2)
        assert (message.startswith("pending merges:\n")), message
        assert ("Empty commit 3" in message), message
        assert (message.endswith("...\n")), message 

    def test_branch_status_specific_files(self): 
        """Tests branch status with given specific files"""
        from cStringIO import StringIO
        from bzrlib.status import show_status
        from bzrlib.branch import Branch
        
        b = Branch.initialize('.')

        self.build_tree(['directory/','directory/hello.c', 'bye.c','test.c','dir2/'])
        b.add('directory')
        b.add('test.c')
        b.commit('testing')
        
        tof = StringIO()
        show_status(b, to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  bye.c\n',
                           '  dir2\n',
                           '  directory/hello.c\n'
                           ])

        tof = StringIO()
        show_status(b, specific_files=['bye.c','test.c','absent.c'], to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  bye.c\n'
                           ])
        
        tof = StringIO()
        show_status(b, specific_files=['directory'], to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  directory/hello.c\n'
                           ])
        tof = StringIO()
        show_status(b, specific_files=['dir2'], to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  dir2\n'
                           ])
