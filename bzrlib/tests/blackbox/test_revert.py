# Copyright (C) 2005 Canonical Ltd
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

"""Black-box tests for bzr revert."""

import os

import bzrlib.osutils
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree


class TestRevert(ExternalBase):

    def _prepare_tree(self):
        self.runbzr('init')
        self.runbzr('mkdir dir')

        f = file('dir/file', 'wb')
        f.write('spam')
        f.close()
        self.runbzr('add dir/file')

        self.runbzr('commit -m1')

        # modify file
        f = file('dir/file', 'wb')
        f.write('eggs')
        f.close()

        # check status
        self.assertEquals('modified:\n  dir/file\n', self.capture('status'))

    def _prepare_rename_mod_tree(self):
        self.build_tree(['a/', 'a/b', 'a/c', 'a/d/', 'a/d/e', 'f/', 'f/g', 
                         'f/h', 'f/i'])
        self.run_bzr('init')
        self.run_bzr('add')
        self.run_bzr('commit', '-m', '1')
        wt = WorkingTree.open('.')
        wt.rename_one('a/b', 'f/b')
        wt.rename_one('a/d/e', 'f/e')
        wt.rename_one('a/d', 'f/d')
        wt.rename_one('f/g', 'a/g')
        wt.rename_one('f/h', 'h')
        wt.rename_one('f', 'j')

    def helper(self, param=''):
        self._prepare_tree()
        # change dir
        # revert to default revision for file in subdir does work
        os.chdir('dir')
        mutter('cd dir\n')

        self.assertEquals('1\n', self.capture('revno'))
        self.runbzr('revert %s file' % param)
        self.assertEquals('spam', open('file', 'rb').read())

    def test_revert_in_subdir(self):
        self.helper()

    def test_revert_to_revision_in_subdir(self):
        # test case for bug #29424:
        # revert to specific revision for file in subdir does not work
        self.helper('-r 1')

    def test_revert_in_checkout(self):
        os.mkdir('brach')
        os.chdir('brach')
        self._prepare_tree()
        self.runbzr('checkout --lightweight . ../sprach')
        self.runbzr('commit -m more')
        os.chdir('../sprach')
        self.assertEqual('', self.capture('status'))
        self.runbzr('revert')
        self.assertEqual('', self.capture('status'))

    def test_revert_dirname(self):
        """Test that revert DIRECTORY does what's expected"""
        self._prepare_rename_mod_tree()
        self.run_bzr('revert', 'a')
        self.failUnlessExists('a/b')
        self.failUnlessExists('a/d')
        self.failIfExists('a/g')
        self.failUnlessExists('j')
        self.failUnlessExists('h')
        self.run_bzr('revert', 'f')
        self.failIfExists('j')
        self.failIfExists('h')
        self.failUnlessExists('a/d/e')

    def test_revert(self):
        self.run_bzr('init')

        file('hello', 'wt').write('foo')
        self.run_bzr('add', 'hello')
        self.run_bzr('commit', '-m', 'setup', 'hello')

        file('goodbye', 'wt').write('baz')
        self.run_bzr('add', 'goodbye')
        self.run_bzr('commit', '-m', 'setup', 'goodbye')

        file('hello', 'wt').write('bar')
        file('goodbye', 'wt').write('qux')
        self.run_bzr('revert', 'hello')
        self.check_file_contents('hello', 'foo')
        self.check_file_contents('goodbye', 'qux')
        self.run_bzr('revert')
        self.check_file_contents('goodbye', 'baz')

        os.mkdir('revertdir')
        self.run_bzr('add', 'revertdir')
        self.run_bzr('commit', '-m', 'f')
        os.rmdir('revertdir')
        self.run_bzr('revert')

        if bzrlib.osutils.has_symlinks():
            os.symlink('/unlikely/to/exist', 'symlink')
            self.run_bzr('add', 'symlink')
            self.run_bzr('commit', '-m', 'f')
            os.unlink('symlink')
            self.run_bzr('revert')
            self.failUnlessExists('symlink')
            os.unlink('symlink')
            os.symlink('a-different-path', 'symlink')
            self.run_bzr('revert')
            self.assertEqual('/unlikely/to/exist',
                             os.readlink('symlink'))
        else:
            self.log("skipping revert symlink tests")
        
        file('hello', 'wt').write('xyz')
        self.run_bzr('commit', '-m', 'xyz', 'hello')
        self.run_bzr('revert', '-r', '1', 'hello')
        self.check_file_contents('hello', 'foo')
        self.run_bzr('revert', 'hello')
        self.check_file_contents('hello', 'xyz')
        os.chdir('revertdir')
        self.run_bzr('revert')
        os.chdir('..')

