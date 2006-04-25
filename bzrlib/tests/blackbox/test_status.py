# Copyright (C) 2005, 2006 by Canonical Ltd

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
from os import mkdir, chdir
import sys
from tempfile import TemporaryFile
import codecs

import bzrlib.branch
from bzrlib.builtins import merge
import bzrlib.bzrdir as bzrdir
import bzrlib.errors as errors
from bzrlib.osutils import pathjoin
from bzrlib.revisionspec import RevisionSpec
from bzrlib.status import show_tree_status
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class BranchStatus(TestCaseWithTransport):
    
    def test_branch_status(self): 
        """Test basic branch status"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        # status with nothing
        tof = StringIO()
        show_tree_status(wt, to_file=tof)
        self.assertEquals(tof.getvalue(), "")

        tof = StringIO()
        self.build_tree(['hello.c', 'bye.c'])
        wt.add_pending_merge('pending@pending-0-0')
        show_tree_status(wt, to_file=tof)
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
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        tof = StringIO()
        self.build_tree(['hello.c', 'bye.c'])
        wt.add('hello.c')
        wt.add('bye.c')
        wt.commit('Test message')

        tof = StringIO()
        revs =[]
        revs.append(RevisionSpec(0))
        
        show_tree_status(wt, to_file=tof, revision=revs)
        
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
        
        show_tree_status(wt, to_file=tof, revision=revs)
        
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['added:\n',
                           '  bye.c\n',
                           '  hello.c\n'])

    def status_string(self, wt):
        # use a real file rather than StringIO because it doesn't handle
        # Unicode very well.
        tof = codecs.getwriter('utf-8')(TemporaryFile())
        show_tree_status(wt, to_file=tof)
        tof.seek(0)
        return tof.read().decode('utf-8')

    def test_pending(self):
        """Pending merges display works, including Unicode"""
        mkdir("./branch")
        wt = self.make_branch_and_tree('branch')
        b = wt.branch
        wt.commit("Empty commit 1")
        b_2_dir = b.bzrdir.sprout('./copy')
        b_2 = b_2_dir.open_branch()
        wt2 = b_2_dir.open_workingtree()
        wt.commit(u"\N{TIBETAN DIGIT TWO} Empty commit 2")
        merge(["./branch", -1], [None, None], this_dir = './copy')
        message = self.status_string(wt2)
        self.assert_(message.startswith("pending merges:\n"))
        self.assert_(message.endswith("Empty commit 2\n")) 
        wt2.commit("merged")
        # must be long to make sure we see elipsis at the end
        wt.commit("Empty commit 3 " + 
                   "blah blah blah blah " * 10)
        merge(["./branch", -1], [None, None], this_dir = './copy')
        message = self.status_string(wt2)
        self.assert_(message.startswith("pending merges:\n"))
        self.assert_("Empty commit 3" in message)
        self.assert_(message.endswith("...\n")) 

    def test_branch_status_specific_files(self): 
        """Tests branch status with given specific files"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        self.build_tree(['directory/','directory/hello.c', 'bye.c','test.c','dir2/'])
        wt.add('directory')
        wt.add('test.c')
        wt.commit('testing')
        
        tof = StringIO()
        show_tree_status(wt, to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  bye.c\n',
                           '  dir2\n',
                           '  directory/hello.c\n'
                           ])

        self.assertRaises(errors.PathsDoNotExist,
                          show_tree_status,
                          wt, specific_files=['bye.c','test.c','absent.c'], 
                          to_file=tof)
        
        tof = StringIO()
        show_tree_status(wt, specific_files=['directory'], to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  directory/hello.c\n'
                           ])
        tof = StringIO()
        show_tree_status(wt, specific_files=['dir2'], to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  dir2\n'
                           ])

    def test_status_nonexistent_file(self):
        # files that don't exist in either the basis tree or working tree
        # should give an error
        wt = self.make_branch_and_tree('.')
        out, err = self.run_bzr('status', 'does-not-exist', retcode=3)
        self.assertContainsRe(err, r'do not exist.*does-not-exist')


class CheckoutStatus(BranchStatus):

    def setUp(self):
        super(CheckoutStatus, self).setUp()
        mkdir('codir')
        chdir('codir')
        
    def make_branch_and_tree(self, relpath):
        source = self.make_branch(pathjoin('..', relpath))
        checkout = bzrdir.BzrDirMetaFormat1().initialize(relpath)
        bzrlib.branch.BranchReferenceFormat().initialize(checkout, source)
        return checkout.create_workingtree()


class TestStatus(TestCaseWithTransport):

    def test_status(self):
        self.run_bzr("init")
        self.build_tree(['hello.txt'])
        result = self.run_bzr("status")[0]
        self.assert_("unknown:\n  hello.txt\n" in result, result)
        self.run_bzr("add", "hello.txt")
        result = self.run_bzr("status")[0]
        self.assert_("added:\n  hello.txt\n" in result, result)
        self.run_bzr("commit", "-m", "added")
        result = self.run_bzr("status", "-r", "0..1")[0]
        self.assert_("added:\n  hello.txt\n" in result, result)
        self.build_tree(['world.txt'])
        result = self.run_bzr("status", "-r", "0")[0]
        self.assert_("added:\n  hello.txt\n" \
                     "unknown:\n  world.txt\n" in result, result)

        result2 = self.run_bzr("status", "-r", "0..")[0]
        self.assertEquals(result2, result)


class TestStatusEncodings(TestCaseWithTransport):
    
    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.user_encoding = bzrlib.user_encoding
        self.stdout = sys.stdout

    def tearDown(self):
        bzrlib.user_encoding = self.user_encoding
        sys.stdout = self.stdout
        TestCaseWithTransport.tearDown(self)

    def make_uncommitted_tree(self):
        """Build a branch with uncommitted unicode named changes in the cwd."""
        working_tree = self.make_branch_and_tree(u'.')
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        working_tree.add(filename)
        return working_tree

    def test_stdout_ascii(self):
        sys.stdout = StringIO()
        bzrlib.user_encoding = 'ascii'
        working_tree = self.make_uncommitted_tree()
        stdout, stderr = self.run_bzr("status")

        self.assertEquals(stdout, """\
added:
  hell?
""")

    def test_stdout_latin1(self):
        sys.stdout = StringIO()
        bzrlib.user_encoding = 'latin-1'
        working_tree = self.make_uncommitted_tree()
        stdout, stderr = self.run_bzr('status')

        self.assertEquals(stdout, u"""\
added:
  hell\u00d8
""".encode('latin-1'))

