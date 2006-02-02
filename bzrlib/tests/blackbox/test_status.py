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
As such they really are blackbox tests even though some of the 
tests are not using self.capture. If we add tests for the programmatic
interface later, they will be non blackbox tests.
"""


from cStringIO import StringIO
from os import mkdir
from tempfile import TemporaryFile
import codecs

from bzrlib.branch import Branch
from bzrlib.builtins import merge
from bzrlib.revisionspec import RevisionSpec
from bzrlib.status import show_status
from bzrlib.tests import TestCaseInTempDir
from bzrlib.workingtree import WorkingTree


class BranchStatus(TestCaseInTempDir):
    
    def test_branch_status(self): 
        """Test basic branch status"""
        wt = WorkingTree.create_standalone('.')
        b = wt.branch

        # status with nothing
        tof = StringIO()
        show_status(b, to_file=tof)
        self.assertEquals(tof.getvalue(), "")

        tof = StringIO()
        self.build_tree(['hello.c', 'bye.c'])
        wt.add_pending_merge('pending@pending-0-0')
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
        wt = WorkingTree.create_standalone('.')
        b = wt.branch

        tof = StringIO()
        self.build_tree(['hello.c', 'bye.c'])
        wt.add('hello.c')
        wt.add('bye.c')
        wt.commit('Test message')

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
        wt.add('more.c')
        wt.commit('Another test message')
        
        tof = StringIO()
        revs.append(RevisionSpec(1))
        
        show_status(b, to_file=tof, revision=revs)
        
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['added:\n',
                           '  bye.c\n',
                           '  hello.c\n'])

    def status_string(self, branch):
        # use a real file rather than StringIO because it doesn't handle
        # Unicode very well.
        tof = codecs.getwriter('utf-8')(TemporaryFile())
        show_status(branch, to_file=tof)
        tof.seek(0)
        return tof.read().decode('utf-8')

    def test_pending(self):
        """Pending merges display works, including Unicode"""
        mkdir("./branch")
        wt = WorkingTree.create_standalone('branch')
        b = wt.branch
        wt.commit("Empty commit 1")
        b_2 = b.clone('./copy')
        wt2 = WorkingTree('copy', b_2)
        wt.commit(u"\N{TIBETAN DIGIT TWO} Empty commit 2")
        merge(["./branch", -1], [None, None], this_dir = './copy')
        message = self.status_string(b_2)
        self.assert_(message.startswith("pending merges:\n"))
        self.assert_(message.endswith("Empty commit 2\n")) 
        wt2.commit("merged")
        # must be long to make sure we see elipsis at the end
        wt.commit("Empty commit 3 " + 
                   "blah blah blah blah " * 10)
        merge(["./branch", -1], [None, None], this_dir = './copy')
        message = self.status_string(b_2)
        self.assert_(message.startswith("pending merges:\n"))
        self.assert_("Empty commit 3" in message)
        self.assert_(message.endswith("...\n")) 

    def test_branch_status_specific_files(self): 
        """Tests branch status with given specific files"""
        wt = WorkingTree.create_standalone('.')
        b = wt.branch

        self.build_tree(['directory/','directory/hello.c', 'bye.c','test.c','dir2/'])
        wt.add('directory')
        wt.add('test.c')
        wt.commit('testing')
        
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
