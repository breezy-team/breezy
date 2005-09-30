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
command-line interface.

This always reinvokes bzr through a new Python interpreter, which is a
bit inefficient but arguably tests in a way more representative of how
it's normally invoked.
"""

from cStringIO import StringIO
import os
import shutil
import sys
import os

from bzrlib.selftest import TestCaseInTempDir, BzrTestBase
from bzrlib.branch import Branch


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

    def test_ignore_patterns(self):
        from bzrlib.branch import Branch
        
        b = Branch.initialize('.')
        self.assertEquals(list(b.unknowns()), [])

        file('foo.tmp', 'wt').write('tmp files are ignored')
        self.assertEquals(list(b.unknowns()), [])
        assert self.capture('unknowns') == ''

        file('foo.c', 'wt').write('int main() {}')
        self.assertEquals(list(b.unknowns()), ['foo.c'])
        assert self.capture('unknowns') == 'foo.c\n'

        self.runbzr(['add', 'foo.c'])
        assert self.capture('unknowns') == ''

        # 'ignore' works when creating the .bzignore file
        file('foo.blah', 'wt').write('blah')
        self.assertEquals(list(b.unknowns()), ['foo.blah'])
        self.runbzr('ignore *.blah')
        self.assertEquals(list(b.unknowns()), [])
        assert file('.bzrignore', 'rU').read() == '*.blah\n'

        # 'ignore' works when then .bzrignore file already exists
        file('garh', 'wt').write('garh')
        self.assertEquals(list(b.unknowns()), ['garh'])
        assert self.capture('unknowns') == 'garh\n'
        self.runbzr('ignore garh')
        self.assertEquals(list(b.unknowns()), [])
        assert file('.bzrignore', 'rU').read() == '*.blah\ngarh\n'

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

    def test_diff(self):
        self.example_branch()
        file('hello', 'wt').write('hello world!')
        self.runbzr('commit -m fixing hello')
        output = self.runbzr('diff -r 2..3', backtick=1)
        self.assert_('\n+hello world!' in output)
        output = self.runbzr('diff -r last:3..last:1', backtick=1)
        self.assert_('\n+baz' in output)

    def test_branch(self):
        """Branch from one branch to another."""
        os.mkdir('a')
        os.chdir('a')
        self.example_branch()
        os.chdir('..')
        self.runbzr('branch a b')
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
        self.runbzr('merge ../b')
        self.check_file_contents('goodbye', 'quux')
        # Merging a branch pulls its revision into the tree
        a = Branch.open('.')
        b = Branch.open('../b')
        a.get_revision_xml(b.last_revision())
        self.log('pending merges: %s', a.pending_merges())
        #        assert a.pending_merges() == [b.last_revision()], "Assertion %s %s" \
        #        % (a.pending_merges(), b.last_revision())

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
        assert a.revision_history() == b.revision_history()[:-1]
        self.runbzr('pull ../b')
        assert a.revision_history() == b.revision_history()
        self.runbzr('commit -m blah2 --unchanged')
        os.chdir('../b')
        self.runbzr('commit -m blah3 --unchanged')
        self.runbzr('pull ../a', retcode=1)
        print "DECIDE IF PULL CAN CONVERGE, blackbox.py"
        return
        os.chdir('../a')
        self.runbzr('merge ../b')
        self.runbzr('commit -m blah4 --unchanged')
        os.chdir('../b/subdir')
        self.runbzr('pull ../../a')
        assert a.revision_history()[-1] == b.revision_history()[-1]
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

    def test_unknown_command(self):
        """Handling of unknown command."""
        out, err = self.run_bzr_captured(['fluffy-badger'],
                                         retcode=1)
        self.assertEquals(out, '')
        err.index('unknown command')
        


def has_symlinks():
    if hasattr(os, 'symlink'):
        return True
    else:
        return False

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
        assert out == 'unknown:\n  test.txt\n'

        out = capture("status --all")
        assert out == "unknown:\n  test.txt\n"

        out = capture("status test.txt --all")
        assert out == "unknown:\n  test.txt\n"

        f = file('test2.txt', 'wt')
        f.write('goodbye cruel world...\n')
        f.close()

        out = capture("status test.txt")
        assert out == "unknown:\n  test.txt\n"

        out = capture("status")
        assert out == ("unknown:\n"
                       "  test.txt\n"
                       "  test2.txt\n")

        os.unlink('test2.txt')

        progress("command aliases")
        out = capture("st --all")
        assert out == ("unknown:\n"
                       "  test.txt\n")

        out = capture("stat")
        assert out == ("unknown:\n"
                       "  test.txt\n")

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
        assert capture("unknowns") == ''
        assert capture("status --all") == ("added:\n"
                                                "  test.txt\n")

        progress("rename newly-added file")
        runbzr("rename test.txt hello.txt")
        assert os.path.exists("hello.txt")
        assert not os.path.exists("test.txt")

        assert capture("revno") == '0\n'

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
        assert capture("relpath sub2/hello.txt") == os.path.join("sub2", "hello.txt\n")

        assert exists("sub2")
        assert exists("sub2/hello.txt")
        assert not exists("sub1")
        assert not exists("hello.txt")

        runbzr(['commit', '-m', 'commit with some things moved to subdirs'])

        mkdir("sub1")
        runbzr('add sub1')
        runbzr('move sub2/hello.txt sub1')
        assert not exists('sub2/hello.txt')
        assert exists('sub1/hello.txt')
        runbzr('move sub2 sub1')
        assert not exists('sub2')
        assert exists('sub1/sub2')

        runbzr(['commit', '-m', 'rename nested subdirectories'])

        chdir('sub1/sub2')
        self.assertEquals(capture('root')[:-1],
                          os.path.join(self.test_dir, 'branch1'))
        runbzr('move ../hello.txt .')
        assert exists('./hello.txt')
        self.assertEquals(capture('relpath hello.txt'),
                          os.path.join('sub1', 'sub2', 'hello.txt') + '\n')
        assert capture('relpath ../../sub1/sub2/hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')
        runbzr(['commit', '-m', 'move to parent directory'])
        chdir('..')
        assert capture('relpath sub2/hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')

        runbzr('move sub2/hello.txt .')
        assert exists('hello.txt')

        f = file('hello.txt', 'wt')
        f.write('some nice new content\n')
        f.close()

        f = file('msg.tmp', 'wt')
        f.write('this is my new commit\n')
        f.close()

        runbzr('commit -F msg.tmp')

        assert capture('revno') == '5\n'
        runbzr('export -r 5 export-5.tmp')
        runbzr('export export.tmp')

        runbzr('log')
        runbzr('log -v')
        runbzr('log -v --forward')
        runbzr('log -m', retcode=1)
        log_out = capture('log -m commit')
        assert "this is my new commit" in log_out
        assert "rename nested" not in log_out
        assert 'revision-id' not in log_out
        assert 'revision-id' in capture('log --show-ids -m commit')


        progress("file with spaces in name")
        mkdir('sub directory')
        file('sub directory/file with spaces ', 'wt').write('see how this works\n')
        runbzr('add .')
        runbzr('diff')
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
            assert self.capture('unknowns') == ''
            runbzr(['commit', '-m', '1: added symlink link1'])
    
            mkdir('d1')
            runbzr('add d1')
            assert self.capture('unknowns') == ''
            os.symlink("NOWHERE2", "d1/link2")
            assert self.capture('unknowns') == 'd1/link2\n'
            # is d1/link2 found when adding d1
            runbzr('add d1')
            assert self.capture('unknowns') == ''
            os.symlink("NOWHERE3", "d1/link3")
            assert self.capture('unknowns') == 'd1/link3\n'
            runbzr(['commit', '-m', '2: added dir, symlink'])
    
            runbzr('rename d1 d2')
            runbzr('move d2/link2 .')
            runbzr('move link1 d2')
            assert os.readlink("./link2") == "NOWHERE2"
            assert os.readlink("d2/link1") == "NOWHERE1"
            runbzr('add d2/link3')
            runbzr('diff')
            runbzr(['commit', '-m', '3: rename of dir, move symlinks, add link3'])
    
            os.unlink("link2")
            os.symlink("TARGET 2", "link2")
            os.unlink("d2/link1")
            os.symlink("TARGET 1", "d2/link1")
            runbzr('diff')
            assert self.capture("relpath d2/link1") == "d2/link1\n"
            runbzr(['commit', '-m', '4: retarget of two links'])
    
            runbzr('remove d2/link1')
            assert self.capture('unknowns') == 'd2/link1\n'
            runbzr(['commit', '-m', '5: remove d2/link1'])
    
            os.mkdir("d1")
            runbzr('add d1')
            runbzr('rename d2/link3 d1/link3new')
            assert self.capture('unknowns') == 'd2/link1\n'
            runbzr(['commit', '-m', '6: remove d2/link1, move/rename link3'])
            
            runbzr(['check'])
            
            runbzr(['export', '-r', '1', 'exp1.tmp'])
            chdir("exp1.tmp")
            assert listdir_sorted(".") == [ "link1" ]
            assert os.readlink("link1") == "NOWHERE1"
            chdir("..")
            
            runbzr(['export', '-r', '2', 'exp2.tmp'])
            chdir("exp2.tmp")
            assert listdir_sorted(".") == [ "d1", "link1" ]
            chdir("..")
            
            runbzr(['export', '-r', '3', 'exp3.tmp'])
            chdir("exp3.tmp")
            assert listdir_sorted(".") == [ "d2", "link2" ]
            assert listdir_sorted("d2") == [ "link1", "link3" ]
            assert os.readlink("d2/link1") == "NOWHERE1"
            assert os.readlink("link2")    == "NOWHERE2"
            chdir("..")
            
            runbzr(['export', '-r', '4', 'exp4.tmp'])
            chdir("exp4.tmp")
            assert listdir_sorted(".") == [ "d2", "link2" ]
            assert os.readlink("d2/link1") == "TARGET 1"
            assert os.readlink("link2")    == "TARGET 2"
            assert listdir_sorted("d2") == [ "link1", "link3" ]
            chdir("..")
            
            runbzr(['export', '-r', '5', 'exp5.tmp'])
            chdir("exp5.tmp")
            assert listdir_sorted(".") == [ "d2", "link2" ]
            assert os.path.islink("link2")
            assert listdir_sorted("d2")== [ "link3" ]
            chdir("..")
            
            runbzr(['export', '-r', '6', 'exp6.tmp'])
            chdir("exp6.tmp")
            assert listdir_sorted(".") == [ "d1", "d2", "link2" ]
            assert listdir_sorted("d1") == [ "link3new" ]
            assert listdir_sorted("d2") == []
            assert os.readlink("d1/link3new") == "NOWHERE3"
            chdir("..")
        else:
            progress("skipping symlink tests")
            
