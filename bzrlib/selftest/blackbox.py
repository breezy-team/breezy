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

# this code was previously in testbzr

from unittest import TestCase
from bzrlib.selftest import TestBase, InTempDir



class ExternalBase(InTempDir):
    def runbzr(self, args, retcode=0):
        try:
            import shutil
            from subprocess import call
        except ImportError, e:
            _need_subprocess()
            raise

        if isinstance(args, basestring):
            args = args.split()
            
        return self.runcmd(['python', self.BZRPATH,] + args,
                           retcode=retcode)



class TestVersion(ExternalBase):
    def runTest(self):
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        self.runbzr(['version'])



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
        self.assertEquals(self.backtick("bzr whoami --email").count('@'),
                          1)


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






        chdir('..')
        chdir('..')
        progress('branch')
        assert os.path.exists('branch1')
        assert not os.path.exists('branch2')
        # Can't create a branch if it already exists
        runbzr('branch branch1', retcode=1)
        # Can't create a branch if its parent doesn't exist
        runbzr('branch /unlikely/to/exist', retcode=1)
        runbzr('branch branch1 branch2')
        assert exists('branch2')
        assert exists('branch2/sub1')
        assert exists('branch2/sub1/hello.txt')
        
        runbzr('branch --revision 0 branch1 branch3')
        assert not exists('branch3/sub1/hello.txt')
        runbzr('branch --revision 0..3 branch1 branch4', retcode=1)

        progress("pull")
        chdir('branch1')
        runbzr('pull', retcode=1)
        runbzr('pull ../branch2')
        chdir('.bzr')
        runbzr('pull')
        runbzr('commit --unchanged -m empty')
        runbzr('pull')
        chdir('../../branch2')
        runbzr('pull')
        runbzr('commit --unchanged -m empty')
        chdir('../branch1')
        runbzr('commit --unchanged -m empty')
        runbzr('pull', retcode=1)
        chdir ('..')

        progress('status after remove')
        mkdir('status-after-remove')
        # see mail from William Dodé, 2005-05-25
        # $ bzr init; touch a; bzr add a; bzr commit -m "add a"
        #     * looking for changes...
        #     added a
        #     * commited r1
        #     $ bzr remove a
        #     $ bzr status
        #     bzr: local variable 'kind' referenced before assignment
        #     at /vrac/python/bazaar-ng/bzrlib/diff.py:286 in compare_trees()
        #     see ~/.bzr.log for debug information
        chdir('status-after-remove')
        runbzr('init')
        file('a', 'w').write('foo')
        runbzr('add a')
        runbzr(['commit', '-m', 'add a'])
        runbzr('remove a')
        runbzr('status')

        chdir('..')



        progress("recursive and non-recursive add")
        mkdir('no-recurse')
        chdir('no-recurse')
        runbzr('init')
        mkdir('foo')
        fp = os.path.join('foo', 'test.txt')
        f = file(fp, 'w')
        f.write('hello!\n')
        f.close()
        runbzr('add --no-recurse foo')
        runbzr('file-id foo')
        runbzr('file-id ' + fp, 1)      # not versioned yet
        runbzr('commit -m add-dir-only')

        self.runbzr('file-id ' + fp, 1)      # still not versioned 

        self.runbzr('add foo')
        self.runbzr('file-id ' + fp)
        self.runbzr('commit -m add-sub-file')

        chdir('..')



class RevertCommand(ExternalBase):
    def runTest(self):
        self.runbzr('init')

        file('hello', 'wt').write('foo')
        self.runbzr('add hello')
        self.runbzr('commit -m setup hello')
        
        file('hello', 'wt').write('bar')
        self.runbzr('revert hello')
        self.check_file_contents('hello', 'foo')

