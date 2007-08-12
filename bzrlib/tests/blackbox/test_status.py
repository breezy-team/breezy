# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Tests of status command.

Most of these depend on the particular formatting used.
As such they really are blackbox tests even though some of the 
tests are not using self.capture. If we add tests for the programmatic
interface later, they will be non blackbox tests.
"""

from cStringIO import StringIO
import codecs
from os import mkdir, chdir, rmdir, unlink
import sys
from tempfile import TemporaryFile

from bzrlib import (
    bzrdir,
    conflicts,
    errors,
    )
import bzrlib.branch
from bzrlib.osutils import pathjoin
from bzrlib.revisionspec import RevisionSpec
from bzrlib.status import show_tree_status
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.workingtree import WorkingTree


class BranchStatus(TestCaseWithTransport):
    
    def assertStatus(self, expected_lines, working_tree,
        revision=None, short=False):
        """Run status in working_tree and look for output.
        
        :param expected_lines: The lines to look for.
        :param working_tree: The tree to run status in.
        """
        output_string = self.status_string(working_tree, revision, short)
        self.assertEqual(expected_lines, output_string.splitlines(True))
    
    def status_string(self, wt, revision=None, short=False):
        # use a real file rather than StringIO because it doesn't handle
        # Unicode very well.
        tof = codecs.getwriter('utf-8')(TemporaryFile())
        show_tree_status(wt, to_file=tof, revision=revision, short=short)
        tof.seek(0)
        return tof.read().decode('utf-8')

    def test_branch_status(self):
        """Test basic branch status"""
        wt = self.make_branch_and_tree('.')

        # status with no commits or files - it must
        # work and show no output. We do this with no
        # commits to be sure that it's not going to fail
        # as a corner case.
        self.assertStatus([], wt)

        self.build_tree(['hello.c', 'bye.c'])
        self.assertStatus([
                'unknown:\n',
                '  bye.c\n',
                '  hello.c\n',
            ],
            wt)
        self.assertStatus([
                '?   bye.c\n',
                '?   hello.c\n',
            ],
            wt, short=True)

        # add a commit to allow showing pending merges.
        wt.commit('create a parent to allow testing merge output')

        wt.add_parent_tree_id('pending@pending-0-0')
        self.assertStatus([
                'unknown:\n',
                '  bye.c\n',
                '  hello.c\n',
                'pending merges:\n',
                '  pending@pending-0-0\n',
            ],
            wt)
        self.assertStatus([
                '?   bye.c\n',
                '?   hello.c\n',
                'P   pending@pending-0-0\n',
            ],
            wt, short=True)

    def test_branch_status_revisions(self):
        """Tests branch status with revisions"""
        wt = self.make_branch_and_tree('.')

        self.build_tree(['hello.c', 'bye.c'])
        wt.add('hello.c')
        wt.add('bye.c')
        wt.commit('Test message')

        revs = [RevisionSpec.from_string('0')]
        self.assertStatus([
                'added:\n',
                '  bye.c\n',
                '  hello.c\n'
            ],
            wt,
            revision=revs)

        self.build_tree(['more.c'])
        wt.add('more.c')
        wt.commit('Another test message')
        
        revs.append(RevisionSpec.from_string('1'))
        self.assertStatus([
                'added:\n',
                '  bye.c\n',
                '  hello.c\n',
            ],
            wt,
            revision=revs)

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
        wt2.merge_from_branch(wt.branch)
        message = self.status_string(wt2)
        self.assertStartsWith(message, "pending merges:\n")
        self.assertEndsWith(message, "Empty commit 2\n")
        wt2.commit("merged")
        # must be long to make sure we see elipsis at the end
        wt.commit("Empty commit 3 " +
                   "blah blah blah blah " * 100)
        wt2.merge_from_branch(wt.branch)
        message = self.status_string(wt2)
        self.assertStartsWith(message, "pending merges:\n")
        self.assert_("Empty commit 3" in message)
        self.assertEndsWith(message, "...\n")

    def test_tree_status_ignores(self):
        """Tests branch status with ignores"""
        wt = self.make_branch_and_tree('.')
        self.run_bzr('ignore *~')
        wt.commit('commit .bzrignore')
        self.build_tree(['foo.c', 'foo.c~'])
        self.assertStatus([
                'unknown:\n',
                '  foo.c\n',
                ],
                wt)
        self.assertStatus([
                '?   foo.c\n',
                ],
                wt, short=True)

    def test_tree_status_specific_files(self):
        """Tests branch status with given specific files"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        self.build_tree(['directory/','directory/hello.c', 'bye.c','test.c','dir2/'])
        wt.add('directory')
        wt.add('test.c')
        wt.commit('testing')
        
        self.assertStatus([
                'unknown:\n',
                '  bye.c\n',
                '  dir2/\n',
                '  directory/hello.c\n'
                ],
                wt)

        self.assertStatus([
                '?   bye.c\n',
                '?   dir2/\n',
                '?   directory/hello.c\n'
                ],
                wt, short=True)

        tof = StringIO()
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
        show_tree_status(wt, specific_files=['directory'], to_file=tof,
                         short=True)
        tof.seek(0)
        self.assertEquals(tof.readlines(), ['?   directory/hello.c\n'])

        tof = StringIO()
        show_tree_status(wt, specific_files=['dir2'], to_file=tof)
        tof.seek(0)
        self.assertEquals(tof.readlines(),
                          ['unknown:\n',
                           '  dir2/\n'
                           ])
        tof = StringIO()
        show_tree_status(wt, specific_files=['dir2'], to_file=tof, short=True)
        tof.seek(0)
        self.assertEquals(tof.readlines(), ['?   dir2/\n'])

    def test_specific_files_conflicts(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir2/'])
        tree.add('dir2')
        tree.commit('added dir2')
        tree.set_conflicts(conflicts.ConflictList(
            [conflicts.ContentsConflict('foo')]))
        tof = StringIO()
        show_tree_status(tree, specific_files=['dir2'], to_file=tof)
        self.assertEqualDiff('', tof.getvalue())
        tree.set_conflicts(conflicts.ConflictList(
            [conflicts.ContentsConflict('dir2')]))
        tof = StringIO()
        show_tree_status(tree, specific_files=['dir2'], to_file=tof)
        self.assertEqualDiff('conflicts:\n  Contents conflict in dir2\n',
                             tof.getvalue())

        tree.set_conflicts(conflicts.ConflictList(
            [conflicts.ContentsConflict('dir2/file1')]))
        tof = StringIO()
        show_tree_status(tree, specific_files=['dir2'], to_file=tof)
        self.assertEqualDiff('conflicts:\n  Contents conflict in dir2/file1\n',
                             tof.getvalue())

    def test_status_nonexistent_file(self):
        # files that don't exist in either the basis tree or working tree
        # should give an error
        wt = self.make_branch_and_tree('.')
        out, err = self.run_bzr('status does-not-exist', retcode=3)
        self.assertContainsRe(err, r'do not exist.*does-not-exist')

    def test_status_out_of_date(self):
        """Simulate status of out-of-date tree after remote push"""
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('a', 'foo\n')])
        tree.lock_write()
        try:
            tree.add(['a'])
            tree.commit('add test file')
            # simulate what happens after a remote push
            tree.set_last_revision("0")
        finally:
            # before run another commands we should unlock tree
            tree.unlock()
        out, err = self.run_bzr('status')
        self.assertEqual("working tree is out of date, run 'bzr update'\n",
                         err)


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

    def test_status_plain(self):
        self.run_bzr("init")

        self.build_tree(['hello.txt'])
        result = self.run_bzr("status")[0]
        self.assertContainsRe(result, "unknown:\n  hello.txt\n")

        self.run_bzr("add hello.txt")
        result = self.run_bzr("status")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        self.run_bzr("commit -m added")
        result = self.run_bzr("status -r 0..1")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        self.build_tree(['world.txt'])
        result = self.run_bzr("status -r 0")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n" \
                                      "unknown:\n  world.txt\n")
        result2 = self.run_bzr("status -r 0..")[0]
        self.assertEquals(result2, result)

    def test_status_short(self):
        self.run_bzr("init")

        self.build_tree(['hello.txt'])
        result = self.run_bzr("status --short")[0]
        self.assertContainsRe(result, "[?]   hello.txt\n")

        self.run_bzr("add hello.txt")
        result = self.run_bzr("status --short")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n")

        self.run_bzr("commit -m added")
        result = self.run_bzr("status --short -r 0..1")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n")

        self.build_tree(['world.txt'])
        result = self.run_bzr("status --short -r 0")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n" \
                                      "[?]   world.txt\n")
        result2 = self.run_bzr("status --short -r 0..")[0]
        self.assertEquals(result2, result)

    def test_status_versioned(self):
        self.run_bzr("init")

        self.build_tree(['hello.txt'])
        result = self.run_bzr("status --versioned")[0]
        self.assertNotContainsRe(result, "unknown:\n  hello.txt\n")

        self.run_bzr("add hello.txt")
        result = self.run_bzr("status --versioned")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        self.run_bzr("commit -m added")
        result = self.run_bzr("status --versioned -r 0..1")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        self.build_tree(['world.txt'])
        result = self.run_bzr("status --versioned -r 0")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")
        self.assertNotContainsRe(result, "unknown:\n  world.txt\n")
        result2 = self.run_bzr("status --versioned -r 0..")[0]
        self.assertEquals(result2, result)

    def assertStatusContains(self, pattern):
        """Run status, and assert it contains the given pattern"""
        result = self.run_bzr("status --short")[0]
        self.assertContainsRe(result, pattern)

    def test_kind_change_short(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        tree.add('file')
        tree.commit('added file')
        unlink('file')
        self.build_tree(['file/'])
        self.assertStatusContains('K  file => file/')
        tree.rename_one('file', 'directory')
        self.assertStatusContains('RK  file => directory/')
        rmdir('directory')
        self.assertStatusContains('RD  file => directory')


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

