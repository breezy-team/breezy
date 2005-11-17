# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

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


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but 
rather starts again from the run_bzr function.
"""


from cStringIO import StringIO
import os
import re
import shutil
import sys

from bzrlib.branch import Branch
from bzrlib.clone import copy_branch
from bzrlib.errors import BzrCommandError
from bzrlib.osutils import has_symlinks
from bzrlib.selftest import TestCaseInTempDir, BzrTestBase
from bzrlib.selftest.HTTPTestUtil import TestCaseWithWebserver


class ExternalBase(TestCaseInTempDir):

    def runbzr(self, args, retcode=0, backtick=False):
        if isinstance(args, basestring):
            args = args.split()

        if backtick:
            return self.run_bzr_captured(args, retcode=retcode)[0]
        else:
            return self.run_bzr_captured(args, retcode=retcode)


class TestCommands(ExternalBase):

    def test_help_commands(self):
        self.runbzr('--help')
        self.runbzr('help')
        self.runbzr('help commands')
        self.runbzr('help help')
        self.runbzr('commit -h')

    def test_init_branch(self):
        self.runbzr(['init'])

        # Can it handle subdirectories as well?
        self.runbzr('init subdir1')
        self.assert_(os.path.exists('subdir1'))
        self.assert_(os.path.exists('subdir1/.bzr'))

        self.runbzr('init subdir2/nothere', retcode=2)
        
        os.mkdir('subdir2')
        self.runbzr('init subdir2')
        self.runbzr('init subdir2', retcode=1)

        self.runbzr('init subdir2/subsubdir1')
        self.assert_(os.path.exists('subdir2/subsubdir1/.bzr'))

    def test_whoami(self):
        # this should always identify something, if only "john@localhost"
        self.runbzr("whoami")
        self.runbzr("whoami --email")

        self.assertEquals(self.runbzr("whoami --email",
                                      backtick=True).count('@'), 1)
        
    def test_whoami_branch(self):
        """branch specific user identity works."""
        self.runbzr('init')
        f = file('.bzr/email', 'wt')
        f.write('Branch Identity <branch@identi.ty>')
        f.close()
        bzr_email = os.environ.get('BZREMAIL')
        if bzr_email is not None:
            del os.environ['BZREMAIL']
        whoami = self.runbzr("whoami",backtick=True)
        whoami_email = self.runbzr("whoami --email",backtick=True)
        self.assertTrue(whoami.startswith('Branch Identity <branch@identi.ty>'))
        self.assertTrue(whoami_email.startswith('branch@identi.ty'))
        # Verify that the environment variable overrides the value 
        # in the file
        os.environ['BZREMAIL'] = 'Different ID <other@environ.ment>'
        whoami = self.runbzr("whoami",backtick=True)
        whoami_email = self.runbzr("whoami --email",backtick=True)
        self.assertTrue(whoami.startswith('Different ID <other@environ.ment>'))
        self.assertTrue(whoami_email.startswith('other@environ.ment'))
        if bzr_email is not None:
            os.environ['BZREMAIL'] = bzr_email

    def test_invalid_commands(self):
        self.runbzr("pants", retcode=1)
        self.runbzr("--pants off", retcode=1)
        self.runbzr("diff --message foo", retcode=1)

    def test_empty_commit(self):
        self.runbzr("init")
        self.build_tree(['hello.txt'])
        self.runbzr("commit -m empty", retcode=1)
        self.runbzr("add hello.txt")
        self.runbzr("commit -m added")

    def test_empty_commit_message(self):
        self.runbzr("init")
        file('foo.c', 'wt').write('int main() {}')
        self.runbzr(['add', 'foo.c'])
        self.runbzr(["commit", "-m", ""] , retcode=1) 

    def test_remove_deleted(self):
        self.runbzr("init")
        self.build_tree(['a'])
        self.runbzr(['add', 'a'])
        self.runbzr(['commit', '-m', 'added a'])
        os.unlink('a')
        self.runbzr(['remove', 'a'])

    def test_other_branch_commit(self):
        # this branch is to ensure consistent behaviour, whether we're run
        # inside a branch, or not.
        os.mkdir('empty_branch')
        os.chdir('empty_branch')
        self.runbzr('init')
        os.mkdir('branch')
        os.chdir('branch')
        self.runbzr('init')
        file('foo.c', 'wt').write('int main() {}')
        file('bar.c', 'wt').write('int main() {}')
        os.chdir('..')
        self.runbzr(['add', 'branch/foo.c'])
        self.runbzr(['add', 'branch'])
        # can't commit files in different trees; sane error
        self.runbzr('commit -m newstuff branch/foo.c .', retcode=1)
        self.runbzr('commit -m newstuff branch/foo.c')
        self.runbzr('commit -m newstuff branch')
        self.runbzr('commit -m newstuff branch', retcode=1)


    def test_ignore_patterns(self):
        from bzrlib.branch import Branch
        
        b = Branch.initialize('.')
        self.assertEquals(list(b.unknowns()), [])

        file('foo.tmp', 'wt').write('tmp files are ignored')
        self.assertEquals(list(b.unknowns()), [])
        self.assertEquals(self.capture('unknowns'), '')

        file('foo.c', 'wt').write('int main() {}')
        self.assertEquals(list(b.unknowns()), ['foo.c'])
        self.assertEquals(self.capture('unknowns'), 'foo.c\n')

        self.runbzr(['add', 'foo.c'])
        self.assertEquals(self.capture('unknowns'), '')

        # 'ignore' works when creating the .bzignore file
        file('foo.blah', 'wt').write('blah')
        self.assertEquals(list(b.unknowns()), ['foo.blah'])
        self.runbzr('ignore *.blah')
        self.assertEquals(list(b.unknowns()), [])
        self.assertEquals(file('.bzrignore', 'rU').read(), '*.blah\n')

        # 'ignore' works when then .bzrignore file already exists
        file('garh', 'wt').write('garh')
        self.assertEquals(list(b.unknowns()), ['garh'])
        self.assertEquals(self.capture('unknowns'), 'garh\n')
        self.runbzr('ignore garh')
        self.assertEquals(list(b.unknowns()), [])
        self.assertEquals(file('.bzrignore', 'rU').read(), '*.blah\ngarh\n')

    def test_revert(self):
        self.runbzr('init')

        file('hello', 'wt').write('foo')
        self.runbzr('add hello')
        self.runbzr('commit -m setup hello')

        file('goodbye', 'wt').write('baz')
        self.runbzr('add goodbye')
        self.runbzr('commit -m setup goodbye')

        file('hello', 'wt').write('bar')
        file('goodbye', 'wt').write('qux')
        self.runbzr('revert hello')
        self.check_file_contents('hello', 'foo')
        self.check_file_contents('goodbye', 'qux')
        self.runbzr('revert')
        self.check_file_contents('goodbye', 'baz')

        os.mkdir('revertdir')
        self.runbzr('add revertdir')
        self.runbzr('commit -m f')
        os.rmdir('revertdir')
        self.runbzr('revert')

        os.symlink('/unlikely/to/exist', 'symlink')
        self.runbzr('add symlink')
        self.runbzr('commit -m f')
        os.unlink('symlink')
        self.runbzr('revert')
        self.failUnlessExists('symlink')
        os.unlink('symlink')
        os.symlink('a-different-path', 'symlink')
        self.runbzr('revert')
        self.assertEqual('/unlikely/to/exist',
                         os.readlink('symlink'))
        
        file('hello', 'wt').write('xyz')
        self.runbzr('commit -m xyz hello')
        self.runbzr('revert -r 1 hello')
        self.check_file_contents('hello', 'foo')
        self.runbzr('revert hello')
        self.check_file_contents('hello', 'xyz')
        os.chdir('revertdir')
        self.runbzr('revert')
        os.chdir('..')


    def test_mv_modes(self):
        """Test two modes of operation for mv"""
        from bzrlib.branch import Branch
        b = Branch.initialize('.')
        self.build_tree(['a', 'c', 'subdir/'])
        self.run_bzr_captured(['add', self.test_dir])
        self.run_bzr_captured(['mv', 'a', 'b'])
        self.run_bzr_captured(['mv', 'b', 'subdir'])
        self.run_bzr_captured(['mv', 'subdir/b', 'a'])
        self.run_bzr_captured(['mv', 'a', 'c', 'subdir'])
        self.run_bzr_captured(['mv', 'subdir/a', 'subdir/newa'])

    def test_main_version(self):
        """Check output from version command and master option is reasonable"""
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        output = self.runbzr('version', backtick=1)
        self.log('bzr version output:')
        self.log(output)
        self.assert_(output.startswith('bzr (bazaar-ng) '))
        self.assertNotEqual(output.index('Canonical'), -1)
        # make sure --version is consistent
        tmp_output = self.runbzr('--version', backtick=1)
        self.log('bzr --version output:')
        self.log(tmp_output)
        self.assertEquals(output, tmp_output)

    def example_branch(test):
        test.runbzr('init')
        file('hello', 'wt').write('foo')
        test.runbzr('add hello')
        test.runbzr('commit -m setup hello')
        file('goodbye', 'wt').write('baz')
        test.runbzr('add goodbye')
        test.runbzr('commit -m setup goodbye')

    def test_export(self):
        os.mkdir('branch')
        os.chdir('branch')
        self.example_branch()
        self.runbzr('export ../latest')
        self.assertEqual(file('../latest/goodbye', 'rt').read(), 'baz')
        self.runbzr('export ../first -r 1')
        self.assert_(not os.path.exists('../first/goodbye'))
        self.assertEqual(file('../first/hello', 'rt').read(), 'foo')
        self.runbzr('export ../first.gz -r 1')
        self.assertEqual(file('../first.gz/hello', 'rt').read(), 'foo')
        self.runbzr('export ../first.bz2 -r 1')
        self.assertEqual(file('../first.bz2/hello', 'rt').read(), 'foo')
        self.runbzr('export ../first.tar -r 1')
        self.assert_(os.path.isfile('../first.tar'))
        from tarfile import TarFile
        tf = TarFile('../first.tar')
        self.assert_('first/hello' in tf.getnames(), tf.getnames())
        self.assertEqual(tf.extractfile('first/hello').read(), 'foo')
        self.runbzr('export ../first.tar.gz -r 1')
        self.assert_(os.path.isfile('../first.tar.gz'))
        self.runbzr('export ../first.tbz2 -r 1')
        self.assert_(os.path.isfile('../first.tbz2'))
        self.runbzr('export ../first.tar.bz2 -r 1')
        self.assert_(os.path.isfile('../first.tar.bz2'))
        self.runbzr('export ../first.tar.tbz2 -r 1')
        self.assert_(os.path.isfile('../first.tar.tbz2'))
        from bz2 import BZ2File
        tf = TarFile('../first.tar.tbz2', 
                     fileobj=BZ2File('../first.tar.tbz2', 'r'))
        self.assert_('first.tar/hello' in tf.getnames(), tf.getnames())
        self.assertEqual(tf.extractfile('first.tar/hello').read(), 'foo')
        self.runbzr('export ../first2.tar -r 1 --root pizza')
        tf = TarFile('../first2.tar')
        self.assert_('pizza/hello' in tf.getnames(), tf.getnames())

    def test_diff(self):
        self.example_branch()
        file('hello', 'wt').write('hello world!')
        self.runbzr('commit -m fixing hello')
        output = self.runbzr('diff -r 2..3', backtick=1, retcode=1)
        self.assert_('\n+hello world!' in output)
        output = self.runbzr('diff -r last:3..last:1', backtick=1, retcode=1)
        self.assert_('\n+baz' in output)

    def test_diff_branches(self):
        self.build_tree(['branch1/', 'branch1/file', 'branch2/'])
        branch = Branch.initialize('branch1')
        branch.working_tree().add(['file'])
        branch.working_tree().commit('add file')
        copy_branch(branch, 'branch2')
        print >> open('branch2/file', 'w'), 'new content'
        branch2 = Branch.open('branch2')
        branch2.working_tree().commit('update file')
        # should open branch1 and diff against branch2, 
        output = self.run_bzr_captured(['diff', '-r', 'branch:branch2', 
                                        'branch1'],
                                       retcode=1)
        self.assertEquals(("=== modified file 'file'\n"
                           "--- file\n"
                           "+++ file\n"
                           "@@ -1,1 +1,1 @@\n"
                           "-new content\n"
                           "+contents of branch1/file\n"
                           "\n", ''), output)

    def test_branch(self):
        """Branch from one branch to another."""
        os.mkdir('a')
        os.chdir('a')
        self.example_branch()
        os.chdir('..')
        self.runbzr('branch a b')
        self.assertFileEqual('b\n', 'b/.bzr/branch-name')
        self.runbzr('branch a c -r 1')
        os.chdir('b')
        self.runbzr('commit -m foo --unchanged')
        os.chdir('..')
        # naughty - abstraction violations RBC 20050928  
        print "test_branch used to delete the stores, how is this meant to work ?"
        #shutil.rmtree('a/.bzr/revision-store')
        #shutil.rmtree('a/.bzr/inventory-store', ignore_errors=True)
        #shutil.rmtree('a/.bzr/text-store', ignore_errors=True)
        self.runbzr('branch a d --basis b')

    def test_merge(self):
        from bzrlib.branch import Branch
        
        os.mkdir('a')
        os.chdir('a')
        self.example_branch()
        os.chdir('..')
        self.runbzr('branch a b')
        os.chdir('b')
        file('goodbye', 'wt').write('quux')
        self.runbzr(['commit',  '-m',  "more u's are always good"])

        os.chdir('../a')
        file('hello', 'wt').write('quuux')
        # We can't merge when there are in-tree changes
        self.runbzr('merge ../b', retcode=1)
        self.runbzr(['commit', '-m', "Like an epidemic of u's"])
        self.runbzr('merge ../b -r last:1..last:1 --merge-type blooof',
                    retcode=1)
        self.runbzr('merge ../b -r last:1..last:1 --merge-type merge3')
        self.runbzr('revert --no-backup')
        self.runbzr('merge ../b -r last:1..last:1 --merge-type weave')
        self.runbzr('revert --no-backup')
        self.runbzr('merge ../b -r last:1..last:1 --reprocess')
        self.runbzr('revert --no-backup')
        self.runbzr('merge ../b -r last:1')
        self.check_file_contents('goodbye', 'quux')
        # Merging a branch pulls its revision into the tree
        a = Branch.open('.')
        b = Branch.open('../b')
        a.get_revision_xml(b.last_revision())
        self.log('pending merges: %s', a.working_tree().pending_merges())
        self.assertEquals(a.working_tree().pending_merges(),
                          [b.last_revision()])
        self.runbzr('commit -m merged')
        self.runbzr('merge ../b -r last:1')
        self.assertEqual(Branch.open('.').working_tree().pending_merges(), [])

    def test_merge_with_missing_file(self):
        """Merge handles missing file conflicts"""
        os.mkdir('a')
        os.chdir('a')
        os.mkdir('sub')
        print >> file('sub/a.txt', 'wb'), "hello"
        print >> file('b.txt', 'wb'), "hello"
        print >> file('sub/c.txt', 'wb'), "hello"
        self.runbzr('init')
        self.runbzr('add')
        self.runbzr(('commit', '-m', 'added a'))
        self.runbzr('branch . ../b')
        print >> file('sub/a.txt', 'ab'), "there"
        print >> file('b.txt', 'ab'), "there"
        print >> file('sub/c.txt', 'ab'), "there"
        self.runbzr(('commit', '-m', 'Added there'))
        os.unlink('sub/a.txt')
        os.unlink('sub/c.txt')
        os.rmdir('sub')
        os.unlink('b.txt')
        self.runbzr(('commit', '-m', 'Removed a.txt'))
        os.chdir('../b')
        print >> file('sub/a.txt', 'ab'), "something"
        print >> file('b.txt', 'ab'), "something"
        print >> file('sub/c.txt', 'ab'), "something"
        self.runbzr(('commit', '-m', 'Modified a.txt'))
        self.runbzr('merge ../a/', retcode=1)
        self.assert_(os.path.exists('sub/a.txt.THIS'))
        self.assert_(os.path.exists('sub/a.txt.BASE'))
        os.chdir('../a')
        self.runbzr('merge ../b/', retcode=1)
        self.assert_(os.path.exists('sub/a.txt.OTHER'))
        self.assert_(os.path.exists('sub/a.txt.BASE'))

    def test_pull(self):
        """Pull changes from one branch to another."""
        os.mkdir('a')
        os.chdir('a')

        self.example_branch()
        self.runbzr('pull', retcode=1)
        self.runbzr('missing', retcode=1)
        self.runbzr('missing .')
        self.runbzr('missing')
        self.runbzr('pull')
        self.runbzr('pull /', retcode=1)
        self.runbzr('pull')

        os.chdir('..')
        self.runbzr('branch a b')
        os.chdir('b')
        self.runbzr('pull')
        os.mkdir('subdir')
        self.runbzr('add subdir')
        self.runbzr('commit -m blah --unchanged')
        os.chdir('../a')
        a = Branch.open('.')
        b = Branch.open('../b')
        self.assertEquals(a.revision_history(), b.revision_history()[:-1])
        self.runbzr('pull ../b')
        self.assertEquals(a.revision_history(), b.revision_history())
        self.runbzr('commit -m blah2 --unchanged')
        os.chdir('../b')
        self.runbzr('commit -m blah3 --unchanged')
        # no overwrite
        self.runbzr('pull ../a', retcode=1)
        os.chdir('..')
        self.runbzr('branch b overwriteme')
        os.chdir('overwriteme')
        self.runbzr('pull --overwrite ../a')
        overwritten = Branch.open('.')
        self.assertEqual(overwritten.revision_history(),
                         a.revision_history())
        os.chdir('../a')
        self.runbzr('merge ../b')
        self.runbzr('commit -m blah4 --unchanged')
        os.chdir('../b/subdir')
        self.runbzr('pull ../../a')
        self.assertEquals(a.revision_history()[-1], b.revision_history()[-1])
        self.runbzr('commit -m blah5 --unchanged')
        self.runbzr('commit -m blah6 --unchanged')
        os.chdir('..')
        self.runbzr('pull ../a')
        os.chdir('../a')
        self.runbzr('commit -m blah7 --unchanged')
        self.runbzr('merge ../b')
        self.runbzr('commit -m blah8 --unchanged')
        self.runbzr('pull ../b')
        self.runbzr('pull ../b')

    def test_ls(self):
        """Test the abilities of 'bzr ls'"""
        bzr = self.runbzr
        def bzrout(*args, **kwargs):
            kwargs['backtick'] = True
            return self.runbzr(*args, **kwargs)

        def ls_equals(value, *args):
            out = self.runbzr(['ls'] + list(args), backtick=True)
            self.assertEquals(out, value)

        bzr('init')
        open('a', 'wb').write('hello\n')

        # Can't supply both
        bzr('ls --verbose --null', retcode=1)

        ls_equals('a\n')
        ls_equals('?        a\n', '--verbose')
        ls_equals('a\n', '--unknown')
        ls_equals('', '--ignored')
        ls_equals('', '--versioned')
        ls_equals('a\n', '--unknown', '--ignored', '--versioned')
        ls_equals('', '--ignored', '--versioned')
        ls_equals('a\0', '--null')

        bzr('add a')
        ls_equals('V        a\n', '--verbose')
        bzr('commit -m add')
        
        os.mkdir('subdir')
        ls_equals('V        a\n'
                  '?        subdir/\n'
                  , '--verbose')
        open('subdir/b', 'wb').write('b\n')
        bzr('add')
        ls_equals('V        a\n'
                  'V        subdir/\n'
                  'V        subdir/b\n'
                  , '--verbose')
        bzr('commit -m subdir')

        ls_equals('a\n'
                  'subdir\n'
                  , '--non-recursive')

        ls_equals('V        a\n'
                  'V        subdir/\n'
                  , '--verbose', '--non-recursive')

        # Check what happens in a sub-directory
        os.chdir('subdir')
        ls_equals('b\n')
        ls_equals('b\0'
                  , '--null')
        ls_equals('a\n'
                  'subdir\n'
                  'subdir/b\n'
                  , '--from-root')
        ls_equals('a\0'
                  'subdir\0'
                  'subdir/b\0'
                  , '--from-root', '--null')
        ls_equals('a\n'
                  'subdir\n'
                  , '--from-root', '--non-recursive')

        os.chdir('..')

        # Check what happens when we supply a specific revision
        ls_equals('a\n', '--revision', '1')
        ls_equals('V        a\n'
                  , '--verbose', '--revision', '1')

        os.chdir('subdir')
        ls_equals('', '--revision', '1')

        # Now try to do ignored files.
        os.chdir('..')
        open('blah.py', 'wb').write('unknown\n')
        open('blah.pyo', 'wb').write('ignored\n')
        ls_equals('a\n'
                  'blah.py\n'
                  'blah.pyo\n'
                  'subdir\n'
                  'subdir/b\n')
        ls_equals('V        a\n'
                  '?        blah.py\n'
                  'I        blah.pyo\n'
                  'V        subdir/\n'
                  'V        subdir/b\n'
                  , '--verbose')
        ls_equals('blah.pyo\n'
                  , '--ignored')
        ls_equals('blah.py\n'
                  , '--unknown')
        ls_equals('a\n'
                  'subdir\n'
                  'subdir/b\n'
                  , '--versioned')

    def test_pull_verbose(self):
        """Pull changes from one branch to another and watch the output."""

        os.mkdir('a')
        os.chdir('a')

        bzr = self.runbzr
        self.example_branch()

        os.chdir('..')
        bzr('branch a b')
        os.chdir('b')
        open('b', 'wb').write('else\n')
        bzr('add b')
        bzr(['commit', '-m', 'added b'])

        os.chdir('../a')
        out = bzr('pull --verbose ../b', backtick=True)
        self.failIfEqual(out.find('Added Revisions:'), -1)
        self.failIfEqual(out.find('message:\n  added b'), -1)
        self.failIfEqual(out.find('added:\n  b'), -1)

        # Check that --overwrite --verbose prints out the removed entries
        bzr('commit -m foo --unchanged')
        os.chdir('../b')
        bzr('commit -m baz --unchanged')
        bzr('pull ../a', retcode=1)
        out = bzr('pull --overwrite --verbose ../a', backtick=1)

        remove_loc = out.find('Removed Revisions:')
        self.failIfEqual(remove_loc, -1)
        added_loc = out.find('Added Revisions:')
        self.failIfEqual(added_loc, -1)

        removed_message = out.find('message:\n  baz')
        self.failIfEqual(removed_message, -1)
        self.failUnless(remove_loc < removed_message < added_loc)

        added_message = out.find('message:\n  foo')
        self.failIfEqual(added_message, -1)
        self.failUnless(added_loc < added_message)
        
    def test_locations(self):
        """Using and remembering different locations"""
        os.mkdir('a')
        os.chdir('a')
        self.runbzr('init')
        self.runbzr('commit -m unchanged --unchanged')
        self.runbzr('pull', retcode=1)
        self.runbzr('merge', retcode=1)
        self.runbzr('branch . ../b')
        os.chdir('../b')
        self.runbzr('pull')
        self.runbzr('branch . ../c')
        self.runbzr('pull ../c')
        self.runbzr('merge')
        os.chdir('../a')
        self.runbzr('pull ../b')
        self.runbzr('pull')
        self.runbzr('pull ../c')
        self.runbzr('branch ../c ../d')
        shutil.rmtree('../c')
        self.runbzr('pull')
        os.chdir('../b')
        self.runbzr('pull')
        os.chdir('../d')
        self.runbzr('pull', retcode=1)
        self.runbzr('pull ../a --remember')
        self.runbzr('pull')
        
    def test_add_reports(self):
        """add command prints the names of added files."""
        b = Branch.initialize('.')
        self.build_tree(['top.txt', 'dir/', 'dir/sub.txt'])
        out = self.run_bzr_captured(['add'], retcode = 0)[0]
        # the ordering is not defined at the moment
        results = sorted(out.rstrip('\n').split('\n'))
        self.assertEquals(['added dir',
                           'added dir'+os.sep+'sub.txt',
                           'added top.txt',],
                          results)

    def test_add_quiet_is(self):
        """add -q does not print the names of added files."""
        b = Branch.initialize('.')
        self.build_tree(['top.txt', 'dir/', 'dir/sub.txt'])
        out = self.run_bzr_captured(['add', '-q'], retcode = 0)[0]
        # the ordering is not defined at the moment
        results = sorted(out.rstrip('\n').split('\n'))
        self.assertEquals([''], results)

    def test_unknown_command(self):
        """Handling of unknown command."""
        out, err = self.run_bzr_captured(['fluffy-badger'],
                                         retcode=1)
        self.assertEquals(out, '')
        err.index('unknown command')

    def test_conflicts(self):
        """Handling of merge conflicts"""
        os.mkdir('base')
        os.chdir('base')
        file('hello', 'wb').write("hi world")
        file('answer', 'wb').write("42")
        self.runbzr('init')
        self.runbzr('add')
        self.runbzr('commit -m base')
        self.runbzr('branch . ../other')
        self.runbzr('branch . ../this')
        os.chdir('../other')
        file('hello', 'wb').write("Hello.")
        file('answer', 'wb').write("Is anyone there?")
        self.runbzr('commit -m other')
        os.chdir('../this')
        file('hello', 'wb').write("Hello, world")
        self.runbzr('mv answer question')
        file('question', 'wb').write("What do you get when you multiply six"
                                   "times nine?")
        self.runbzr('commit -m this')
        self.runbzr('merge ../other --show-base', retcode=1)
        conflict_text = file('hello').read()
        self.assert_('<<<<<<<' in conflict_text)
        self.assert_('>>>>>>>' in conflict_text)
        self.assert_('=======' in conflict_text)
        self.assert_('|||||||' in conflict_text)
        self.assert_('hi world' in conflict_text)
        self.runbzr('revert')
        self.runbzr('resolve --all')
        self.runbzr('merge ../other', retcode=1)
        conflict_text = file('hello').read()
        self.assert_('|||||||' not in conflict_text)
        self.assert_('hi world' not in conflict_text)
        result = self.runbzr('conflicts', backtick=1)
        self.assertEquals(result, "hello\nquestion\n")
        result = self.runbzr('status', backtick=1)
        self.assert_("conflicts:\n  hello\n  question\n" in result, result)
        self.runbzr('resolve hello')
        result = self.runbzr('conflicts', backtick=1)
        self.assertEquals(result, "question\n")
        self.runbzr('commit -m conflicts', retcode=1)
        self.runbzr('resolve --all')
        result = self.runbzr('conflicts', backtick=1)
        self.runbzr('commit -m conflicts')
        self.assertEquals(result, "")

    def test_resign(self):
        """Test re signing of data."""
        import bzrlib.gpg
        oldstrategy = bzrlib.gpg.GPGStrategy
        branch = Branch.initialize('.')
        branch.working_tree().commit("base", allow_pointless=True, rev_id='A')
        try:
            # monkey patch gpg signing mechanism
            from bzrlib.testament import Testament
            bzrlib.gpg.GPGStrategy = bzrlib.gpg.LoopbackGPGStrategy
            self.runbzr('re-sign -r revid:A')
            self.assertEqual(Testament.from_revision(branch,'A').as_short_text(),
                             branch.revision_store.get('A', 'sig').read())
        finally:
            bzrlib.gpg.GPGStrategy = oldstrategy
            
    def test_resign_range(self):
        import bzrlib.gpg
        oldstrategy = bzrlib.gpg.GPGStrategy
        branch = Branch.initialize('.')
        branch.working_tree().commit("base", allow_pointless=True, rev_id='A')
        branch.working_tree().commit("base", allow_pointless=True, rev_id='B')
        branch.working_tree().commit("base", allow_pointless=True, rev_id='C')
        try:
            # monkey patch gpg signing mechanism
            from bzrlib.testament import Testament
            bzrlib.gpg.GPGStrategy = bzrlib.gpg.LoopbackGPGStrategy
            self.runbzr('re-sign -r 1..')
            self.assertEqual(Testament.from_revision(branch,'A').as_short_text(),
                             branch.revision_store.get('A', 'sig').read())
            self.assertEqual(Testament.from_revision(branch,'B').as_short_text(),
                             branch.revision_store.get('B', 'sig').read())
            self.assertEqual(Testament.from_revision(branch,'C').as_short_text(),
                             branch.revision_store.get('C', 'sig').read())
        finally:
            bzrlib.gpg.GPGStrategy = oldstrategy

    def test_push(self):
        # create a source branch
        os.mkdir('my-branch')
        os.chdir('my-branch')
        self.example_branch()

        # with no push target, fail
        self.runbzr('push', retcode=1)
        # with an explicit target work
        self.runbzr('push ../output-branch')
        # with an implicit target work
        self.runbzr('push')
        # nothing missing
        self.runbzr('missing ../output-branch')
        # advance this branch
        self.runbzr('commit --unchanged -m unchanged')

        os.chdir('../output-branch')
        # should be a diff as we have not pushed the tree
        self.runbzr('diff', retcode=1)
        self.runbzr('revert')
        # but not now.
        self.runbzr('diff')
        # diverge the branches
        self.runbzr('commit --unchanged -m unchanged')
        os.chdir('../my-branch')
        # cannot push now
        self.runbzr('push', retcode=1)
        # and there are difference
        self.runbzr('missing ../output-branch', retcode=1)
        # but we can force a push
        self.runbzr('push --overwrite')
        # nothing missing
        self.runbzr('missing ../output-branch')
        
        # pushing to a new dir with no parent should fail
        self.runbzr('push ../missing/new-branch', retcode=1)
        # unless we provide --create-prefix
        self.runbzr('push --create-prefix ../missing/new-branch')
        # nothing missing
        self.runbzr('missing ../missing/new-branch')

    def test_external_command(self):
        """test that external commands can be run by setting the path"""
        cmd_name = 'test-command'
        output = 'Hello from test-command'
        if sys.platform == 'win32':
            cmd_name += '.bat'
            output += '\r\n'
        else:
            output += '\n'

        oldpath = os.environ.get('BZRPATH', None)

        bzr = self.capture

        try:
            if os.environ.has_key('BZRPATH'):
                del os.environ['BZRPATH']

            f = file(cmd_name, 'wb')
            if sys.platform == 'win32':
                f.write('@echo off\n')
            else:
                f.write('#!/bin/sh\n')
            f.write('echo Hello from test-command')
            f.close()
            os.chmod(cmd_name, 0755)

            # It should not find the command in the local 
            # directory by default, since it is not in my path
            bzr(cmd_name, retcode=1)

            # Now put it into my path
            os.environ['BZRPATH'] = '.'

            bzr(cmd_name)
            # The test suite does not capture stdout for external commands
            # this is because you have to have a real file object
            # to pass to Popen(stdout=FOO), and StringIO is not one of those.
            # (just replacing sys.stdout does not change a spawned objects stdout)
            #self.assertEquals(bzr(cmd_name), output)

            # Make sure empty path elements are ignored
            os.environ['BZRPATH'] = os.pathsep

            bzr(cmd_name, retcode=1)

        finally:
            if oldpath:
                os.environ['BZRPATH'] = oldpath


def listdir_sorted(dir):
    L = os.listdir(dir)
    L.sort()
    return L


class OldTests(ExternalBase):
    """old tests moved from ./testbzr."""

    def test_bzr(self):
        from os import chdir, mkdir
        from os.path import exists

        runbzr = self.runbzr
        capture = self.capture
        progress = self.log

        progress("basic branch creation")
        mkdir('branch1')
        chdir('branch1')
        runbzr('init')

        self.assertEquals(capture('root').rstrip(),
                          os.path.join(self.test_dir, 'branch1'))

        progress("status of new file")

        f = file('test.txt', 'wt')
        f.write('hello world!\n')
        f.close()

        self.assertEquals(capture('unknowns'), 'test.txt\n')

        out = capture("status")
        self.assertEquals(out, 'unknown:\n  test.txt\n')

        out = capture("status --all")
        self.assertEquals(out, "unknown:\n  test.txt\n")

        out = capture("status test.txt --all")
        self.assertEquals(out, "unknown:\n  test.txt\n")

        f = file('test2.txt', 'wt')
        f.write('goodbye cruel world...\n')
        f.close()

        out = capture("status test.txt")
        self.assertEquals(out, "unknown:\n  test.txt\n")

        out = capture("status")
        self.assertEquals(out, ("unknown:\n" "  test.txt\n" "  test2.txt\n"))

        os.unlink('test2.txt')

        progress("command aliases")
        out = capture("st --all")
        self.assertEquals(out, ("unknown:\n" "  test.txt\n"))

        out = capture("stat")
        self.assertEquals(out, ("unknown:\n" "  test.txt\n"))

        progress("command help")
        runbzr("help st")
        runbzr("help")
        runbzr("help commands")
        runbzr("help slartibartfast", 1)

        out = capture("help ci")
        out.index('aliases: ')

        progress("can't rename unversioned file")
        runbzr("rename test.txt new-test.txt", 1)

        progress("adding a file")

        runbzr("add test.txt")
        self.assertEquals(capture("unknowns"), '')
        self.assertEquals(capture("status --all"), ("added:\n" "  test.txt\n"))

        progress("rename newly-added file")
        runbzr("rename test.txt hello.txt")
        self.assert_(os.path.exists("hello.txt"))
        self.assert_(not os.path.exists("test.txt"))

        self.assertEquals(capture("revno"), '0\n')

        progress("add first revision")
        runbzr(['commit', '-m', 'add first revision'])

        progress("more complex renames")
        os.mkdir("sub1")
        runbzr("rename hello.txt sub1", 1)
        runbzr("rename hello.txt sub1/hello.txt", 1)
        runbzr("move hello.txt sub1", 1)

        runbzr("add sub1")
        runbzr("rename sub1 sub2")
        runbzr("move hello.txt sub2")
        self.assertEqual(capture("relpath sub2/hello.txt"),
                         os.path.join("sub2", "hello.txt\n"))

        self.assert_(exists("sub2"))
        self.assert_(exists("sub2/hello.txt"))
        self.assert_(not exists("sub1"))
        self.assert_(not exists("hello.txt"))

        runbzr(['commit', '-m', 'commit with some things moved to subdirs'])

        mkdir("sub1")
        runbzr('add sub1')
        runbzr('move sub2/hello.txt sub1')
        self.assert_(not exists('sub2/hello.txt'))
        self.assert_(exists('sub1/hello.txt'))
        runbzr('move sub2 sub1')
        self.assert_(not exists('sub2'))
        self.assert_(exists('sub1/sub2'))

        runbzr(['commit', '-m', 'rename nested subdirectories'])

        chdir('sub1/sub2')
        self.assertEquals(capture('root')[:-1],
                          os.path.join(self.test_dir, 'branch1'))
        runbzr('move ../hello.txt .')
        self.assert_(exists('./hello.txt'))
        self.assertEquals(capture('relpath hello.txt'),
                          os.path.join('sub1', 'sub2', 'hello.txt') + '\n')
        self.assertEquals(capture('relpath ../../sub1/sub2/hello.txt'), os.path.join('sub1', 'sub2', 'hello.txt\n'))
        runbzr(['commit', '-m', 'move to parent directory'])
        chdir('..')
        self.assertEquals(capture('relpath sub2/hello.txt'), os.path.join('sub1', 'sub2', 'hello.txt\n'))

        runbzr('move sub2/hello.txt .')
        self.assert_(exists('hello.txt'))

        f = file('hello.txt', 'wt')
        f.write('some nice new content\n')
        f.close()

        f = file('msg.tmp', 'wt')
        f.write('this is my new commit\nand it has multiple lines, for fun')
        f.close()

        runbzr('commit -F msg.tmp')

        self.assertEquals(capture('revno'), '5\n')
        runbzr('export -r 5 export-5.tmp')
        runbzr('export export.tmp')

        runbzr('log')
        runbzr('log -v')
        runbzr('log -v --forward')
        runbzr('log -m', retcode=1)
        log_out = capture('log -m commit')
        self.assert_("this is my new commit\n  and" in log_out)
        self.assert_("rename nested" not in log_out)
        self.assert_('revision-id' not in log_out)
        self.assert_('revision-id' in capture('log --show-ids -m commit'))

        log_out = capture('log --line')
        for line in log_out.splitlines():
            self.assert_(len(line) <= 79, len(line))
        self.assert_("this is my new commit and" in log_out)


        progress("file with spaces in name")
        mkdir('sub directory')
        file('sub directory/file with spaces ', 'wt').write('see how this works\n')
        runbzr('add .')
        runbzr('diff', retcode=1)
        runbzr('commit -m add-spaces')
        runbzr('check')

        runbzr('log')
        runbzr('log --forward')

        runbzr('info')

        if has_symlinks():
            progress("symlinks")
            mkdir('symlinks')
            chdir('symlinks')
            runbzr('init')
            os.symlink("NOWHERE1", "link1")
            runbzr('add link1')
            self.assertEquals(self.capture('unknowns'), '')
            runbzr(['commit', '-m', '1: added symlink link1'])
    
            mkdir('d1')
            runbzr('add d1')
            self.assertEquals(self.capture('unknowns'), '')
            os.symlink("NOWHERE2", "d1/link2")
            self.assertEquals(self.capture('unknowns'), 'd1/link2\n')
            # is d1/link2 found when adding d1
            runbzr('add d1')
            self.assertEquals(self.capture('unknowns'), '')
            os.symlink("NOWHERE3", "d1/link3")
            self.assertEquals(self.capture('unknowns'), 'd1/link3\n')
            runbzr(['commit', '-m', '2: added dir, symlink'])
    
            runbzr('rename d1 d2')
            runbzr('move d2/link2 .')
            runbzr('move link1 d2')
            self.assertEquals(os.readlink("./link2"), "NOWHERE2")
            self.assertEquals(os.readlink("d2/link1"), "NOWHERE1")
            runbzr('add d2/link3')
            runbzr('diff', retcode=1)
            runbzr(['commit', '-m', '3: rename of dir, move symlinks, add link3'])
    
            os.unlink("link2")
            os.symlink("TARGET 2", "link2")
            os.unlink("d2/link1")
            os.symlink("TARGET 1", "d2/link1")
            runbzr('diff', retcode=1)
            self.assertEquals(self.capture("relpath d2/link1"), "d2/link1\n")
            runbzr(['commit', '-m', '4: retarget of two links'])
    
            runbzr('remove d2/link1')
            self.assertEquals(self.capture('unknowns'), 'd2/link1\n')
            runbzr(['commit', '-m', '5: remove d2/link1'])
            # try with the rm alias
            runbzr('add d2/link1')
            runbzr(['commit', '-m', '6: add d2/link1'])
            runbzr('rm d2/link1')
            self.assertEquals(self.capture('unknowns'), 'd2/link1\n')
            runbzr(['commit', '-m', '7: remove d2/link1'])
    
            os.mkdir("d1")
            runbzr('add d1')
            runbzr('rename d2/link3 d1/link3new')
            self.assertEquals(self.capture('unknowns'), 'd2/link1\n')
            runbzr(['commit', '-m', '8: remove d2/link1, move/rename link3'])
            
            runbzr(['check'])
            
            runbzr(['export', '-r', '1', 'exp1.tmp'])
            chdir("exp1.tmp")
            self.assertEquals(listdir_sorted("."), [ "link1" ])
            self.assertEquals(os.readlink("link1"), "NOWHERE1")
            chdir("..")
            
            runbzr(['export', '-r', '2', 'exp2.tmp'])
            chdir("exp2.tmp")
            self.assertEquals(listdir_sorted("."), [ "d1", "link1" ])
            chdir("..")
            
            runbzr(['export', '-r', '3', 'exp3.tmp'])
            chdir("exp3.tmp")
            self.assertEquals(listdir_sorted("."), [ "d2", "link2" ])
            self.assertEquals(listdir_sorted("d2"), [ "link1", "link3" ])
            self.assertEquals(os.readlink("d2/link1"), "NOWHERE1")
            self.assertEquals(os.readlink("link2")   , "NOWHERE2")
            chdir("..")
            
            runbzr(['export', '-r', '4', 'exp4.tmp'])
            chdir("exp4.tmp")
            self.assertEquals(listdir_sorted("."), [ "d2", "link2" ])
            self.assertEquals(os.readlink("d2/link1"), "TARGET 1")
            self.assertEquals(os.readlink("link2")   , "TARGET 2")
            self.assertEquals(listdir_sorted("d2"), [ "link1", "link3" ])
            chdir("..")
            
            runbzr(['export', '-r', '5', 'exp5.tmp'])
            chdir("exp5.tmp")
            self.assertEquals(listdir_sorted("."), [ "d2", "link2" ])
            self.assert_(os.path.islink("link2"))
            self.assert_(listdir_sorted("d2")== [ "link3" ])
            chdir("..")
            
            runbzr(['export', '-r', '8', 'exp6.tmp'])
            chdir("exp6.tmp")
            self.assertEqual(listdir_sorted("."), [ "d1", "d2", "link2"])
            self.assertEquals(listdir_sorted("d1"), [ "link3new" ])
            self.assertEquals(listdir_sorted("d2"), [])
            self.assertEquals(os.readlink("d1/link3new"), "NOWHERE3")
            chdir("..")
        else:
            progress("skipping symlink tests")


class HttpTests(TestCaseWithWebserver):
    """Test bzr ui commands against remote branches."""

    def test_branch(self):
        os.mkdir('from')
        branch = Branch.initialize('from')
        branch.working_tree().commit('empty commit for nonsense', allow_pointless=True)
        url = self.get_remote_url('from')
        self.run_bzr('branch', url, 'to')
        branch = Branch.open('to')
        self.assertEqual(1, len(branch.revision_history()))

    def test_log(self):
        self.build_tree(['branch/', 'branch/file'])
        branch = Branch.initialize('branch')
        branch.working_tree().add(['file'])
        branch.working_tree().commit('add file', rev_id='A')
        url = self.get_remote_url('branch/file')
        output = self.capture('log %s' % url)
        self.assertEqual(7, len(output.split('\n')))
