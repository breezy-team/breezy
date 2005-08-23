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

import sys

from bzrlib.selftest import TestBase, InTempDir, BzrTestBase



class ExternalBase(InTempDir):
    def runbzr(self, args, retcode=0,backtick=False):
        try:
            import shutil
            from subprocess import call
        except ImportError, e:
            _need_subprocess()
            raise

        if isinstance(args, basestring):
            args = args.split()

        if backtick:
            return self.backtick(['python', self.BZRPATH,] + args,
                           retcode=retcode)
        else:
            return self.runcmd(['python', self.BZRPATH,] + args,
                           retcode=retcode)



class MvCommand(BzrTestBase):
    def runbzr(self):
        """Test two modes of operation for mv"""
        b = Branch('.', init=True)
        self.build_tree(['a', 'c', 'subdir/'])
        self.run_bzr('mv', 'a', 'b')
        self.run_bzr('mv', 'b', 'subdir')
        self.run_bzr('mv', 'subdir/b', 'a')
        self.run_bzr('mv', 'a', 'b', 'subdir')
        self.run_bzr('mv', 'subdir/a', 'subdir/newa')



class TestVersion(BzrTestBase):
    """Check output from version command and master option is reasonable"""
    def runTest(self):
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        from cStringIO import StringIO
        save_out = sys.stdout
        try:
            sys.stdout = tmp_out = StringIO()
            
            self.run_bzr('version')
        finally:
            sys.stdout = save_out

        output = tmp_out.getvalue()
        self.log('bzr version output:')
        self.log(output)
        
        self.assert_(output.startswith('bzr (bazaar-ng) '))
        self.assertNotEqual(output.index('Canonical'), -1)

        # make sure --version is consistent
        try:
            sys.stdout = tmp_out = StringIO()
            
            self.run_bzr('--version')
        finally:
            sys.stdout = save_out

        self.log('bzr --version output:')
        self.log(tmp_out.getvalue())

        self.assertEquals(output, tmp_out.getvalue())


        


class HelpCommands(ExternalBase):
    def runTest(self):
        self.runbzr('--help')
        self.runbzr('help')
        self.runbzr('help commands')
        self.runbzr('help help')
        self.runbzr('commit -h')


class InitBranch(ExternalBase):
    def runTest(self):
        import os
        self.runbzr(['init'])



class UserIdentity(ExternalBase):
    def runTest(self):
        # this should always identify something, if only "john@localhost"
        self.runbzr("whoami")
        self.runbzr("whoami --email")

        self.assertEquals(self.runbzr("whoami --email",
                                      backtick=True).count('@'), 1)
        
class UserIdentityBranch(ExternalBase):
    def runTest(self):
        # tests branch specific user identity
        self.runbzr('init')
        f = file('.bzr/email', 'wt')
        f.write('Branch Identity <branch@identi.ty>')
        f.close()
        whoami = self.runbzr("whoami",backtick=True)
        whoami_email = self.runbzr("whoami --email",backtick=True)
        self.assertTrue(whoami.startswith('Branch Identity <branch@identi.ty>'))
        self.assertTrue(whoami_email.startswith('branch@identi.ty'))


class InvalidCommands(ExternalBase):
    def runTest(self):
        self.runbzr("pants", retcode=1)
        self.runbzr("--pants off", retcode=1)
        self.runbzr("diff --message foo", retcode=1)



class EmptyCommit(ExternalBase):
    def runTest(self):
        self.runbzr("init")
        self.build_tree(['hello.txt'])
        self.runbzr("commit -m empty", retcode=1)
        self.runbzr("add hello.txt")
        self.runbzr("commit -m added")



class IgnorePatterns(ExternalBase):
    def runTest(self):
        from bzrlib.branch import Branch
        
        b = Branch('.', init=True)
        self.assertEquals(list(b.unknowns()), [])

        file('foo.tmp', 'wt').write('tmp files are ignored')
        self.assertEquals(list(b.unknowns()), [])
        assert self.backtick('bzr unknowns') == ''

        file('foo.c', 'wt').write('int main() {}')
        self.assertEquals(list(b.unknowns()), ['foo.c'])
        assert self.backtick('bzr unknowns') == 'foo.c\n'

        self.runbzr(['add', 'foo.c'])
        assert self.backtick('bzr unknowns') == ''

        # 'ignore' works when creating the .bzignore file
        file('foo.blah', 'wt').write('blah')
        self.assertEquals(list(b.unknowns()), ['foo.blah'])
        self.runbzr('ignore *.blah')
        self.assertEquals(list(b.unknowns()), [])
        assert file('.bzrignore', 'rb').read() == '*.blah\n'

        # 'ignore' works when then .bzrignore file already exists
        file('garh', 'wt').write('garh')
        self.assertEquals(list(b.unknowns()), ['garh'])
        assert self.backtick('bzr unknowns') == 'garh\n'
        self.runbzr('ignore garh')
        self.assertEquals(list(b.unknowns()), [])
        assert file('.bzrignore', 'rb').read() == '*.blah\ngarh\n'
        



class OldTests(ExternalBase):
    # old tests moved from ./testbzr
    def runTest(self):
        from os import chdir, mkdir
        from os.path import exists
        import os

        runbzr = self.runbzr
        backtick = self.backtick
        progress = self.log

        progress("basic branch creation")
        mkdir('branch1')
        chdir('branch1')
        runbzr('init')

        self.assertEquals(backtick('bzr root').rstrip(),
                          os.path.join(self.test_dir, 'branch1'))

        progress("status of new file")

        f = file('test.txt', 'wt')
        f.write('hello world!\n')
        f.close()

        out = backtick("bzr unknowns")
        self.assertEquals(out, 'test.txt\n')

        out = backtick("bzr status")
        assert out == 'unknown:\n  test.txt\n'

        out = backtick("bzr status --all")
        assert out == "unknown:\n  test.txt\n"

        out = backtick("bzr status test.txt --all")
        assert out == "unknown:\n  test.txt\n"

        f = file('test2.txt', 'wt')
        f.write('goodbye cruel world...\n')
        f.close()

        out = backtick("bzr status test.txt")
        assert out == "unknown:\n  test.txt\n"

        out = backtick("bzr status")
        assert out == ("unknown:\n"
                       "  test.txt\n"
                       "  test2.txt\n")

        os.unlink('test2.txt')

        progress("command aliases")
        out = backtick("bzr st --all")
        assert out == ("unknown:\n"
                       "  test.txt\n")

        out = backtick("bzr stat")
        assert out == ("unknown:\n"
                       "  test.txt\n")

        progress("command help")
        runbzr("help st")
        runbzr("help")
        runbzr("help commands")
        runbzr("help slartibartfast", 1)

        out = backtick("bzr help ci")
        out.index('aliases: ')

        progress("can't rename unversioned file")
        runbzr("rename test.txt new-test.txt", 1)

        progress("adding a file")

        runbzr("add test.txt")
        assert backtick("bzr unknowns") == ''
        assert backtick("bzr status --all") == ("added:\n"
                                                "  test.txt\n")

        progress("rename newly-added file")
        runbzr("rename test.txt hello.txt")
        assert os.path.exists("hello.txt")
        assert not os.path.exists("test.txt")

        assert backtick("bzr revno") == '0\n'

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
        assert backtick("bzr relpath sub2/hello.txt") == os.path.join("sub2", "hello.txt\n")

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
        self.assertEquals(backtick('bzr root')[:-1],
                          os.path.join(self.test_dir, 'branch1'))
        runbzr('move ../hello.txt .')
        assert exists('./hello.txt')
        assert backtick('bzr relpath hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')
        assert backtick('bzr relpath ../../sub1/sub2/hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')
        runbzr(['commit', '-m', 'move to parent directory'])
        chdir('..')
        assert backtick('bzr relpath sub2/hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')

        runbzr('move sub2/hello.txt .')
        assert exists('hello.txt')

        f = file('hello.txt', 'wt')
        f.write('some nice new content\n')
        f.close()

        f = file('msg.tmp', 'wt')
        f.write('this is my new commit\n')
        f.close()

        runbzr('commit -F msg.tmp')

        assert backtick('bzr revno') == '5\n'
        runbzr('export -r 5 export-5.tmp')
        runbzr('export export.tmp')

        runbzr('log')
        runbzr('log -v')
        runbzr('log -v --forward')
        runbzr('log -m', retcode=1)
        log_out = backtick('bzr log -m commit')
        assert "this is my new commit" in log_out
        assert "rename nested" not in log_out
        assert 'revision-id' not in log_out
        assert 'revision-id' in backtick('bzr log --show-ids -m commit')


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






class RevertCommand(ExternalBase):
    def runTest(self):
        import os
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


