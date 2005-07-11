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

class TestVersion(TestBase):
    def runTest(self):
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        self.runcmd(['bzr', 'version'])



class HelpCommands(TestBase):
    def runTest(self):
        self.runcmd('bzr --help')
        self.runcmd('bzr help')
        self.runcmd('bzr help commands')
        self.runcmd('bzr help help')
        self.runcmd('bzr commit -h')


class InitBranch(InTempDir):
    def runTest(self):
        import os
        self.runcmd(['bzr', 'init'])



class UserIdentity(InTempDir):
    def runTest(self):
        # this should always identify something, if only "john@localhost"
        self.runcmd("bzr whoami")
        self.runcmd("bzr whoami --email")
        self.assertEquals(self.backtick("bzr whoami --email").count('@'),
                          1)


class InvalidCommands(InTempDir):
    def runTest(self):
        self.runcmd("bzr pants", retcode=1)
        self.runcmd("bzr --pants off", retcode=1)
        self.runcmd("bzr diff --message foo", retcode=1)



class EmptyCommit(InTempDir):
    def runTest(self):
        self.runcmd("bzr init")
        self.build_tree(['hello.txt'])
        self.runcmd("bzr commit -m empty", retcode=1)
        self.runcmd("bzr add hello.txt")
        self.runcmd("bzr commit -m added")



class OldTests(InTempDir):
    # old tests moved from ./testbzr
    def runTest(self):
        from os import chdir, mkdir
        from os.path import exists
        import os

        runcmd = self.runcmd
        backtick = self.backtick
        progress = self.log

        progress("basic branch creation")
        runcmd(['mkdir', 'branch1'])
        chdir('branch1')
        runcmd('bzr init')

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
        runcmd("bzr help st")
        runcmd("bzr help")
        runcmd("bzr help commands")
        runcmd("bzr help slartibartfast", 1)

        out = backtick("bzr help ci")
        out.index('aliases: ')

        progress("can't rename unversioned file")
        runcmd("bzr rename test.txt new-test.txt", 1)

        progress("adding a file")

        runcmd("bzr add test.txt")
        assert backtick("bzr unknowns") == ''
        assert backtick("bzr status --all") == ("added:\n"
                                                "  test.txt\n")

        progress("rename newly-added file")
        runcmd("bzr rename test.txt hello.txt")
        assert os.path.exists("hello.txt")
        assert not os.path.exists("test.txt")

        assert backtick("bzr revno") == '0\n'

        progress("add first revision")
        runcmd(["bzr", "commit", "-m", 'add first revision'])

        progress("more complex renames")
        os.mkdir("sub1")
        runcmd("bzr rename hello.txt sub1", 1)
        runcmd("bzr rename hello.txt sub1/hello.txt", 1)
        runcmd("bzr move hello.txt sub1", 1)

        runcmd("bzr add sub1")
        runcmd("bzr rename sub1 sub2")
        runcmd("bzr move hello.txt sub2")
        assert backtick("bzr relpath sub2/hello.txt") == os.path.join("sub2", "hello.txt\n")

        assert exists("sub2")
        assert exists("sub2/hello.txt")
        assert not exists("sub1")
        assert not exists("hello.txt")

        runcmd(['bzr', 'commit', '-m', 'commit with some things moved to subdirs'])

        mkdir("sub1")
        runcmd('bzr add sub1')
        runcmd('bzr move sub2/hello.txt sub1')
        assert not exists('sub2/hello.txt')
        assert exists('sub1/hello.txt')
        runcmd('bzr move sub2 sub1')
        assert not exists('sub2')
        assert exists('sub1/sub2')

        runcmd(['bzr', 'commit', '-m', 'rename nested subdirectories'])

        chdir('sub1/sub2')
        self.assertEquals(backtick('bzr root')[:-1],
                          os.path.join(self.test_dir, 'branch1'))
        runcmd('bzr move ../hello.txt .')
        assert exists('./hello.txt')
        assert backtick('bzr relpath hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')
        assert backtick('bzr relpath ../../sub1/sub2/hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')
        runcmd(['bzr', 'commit', '-m', 'move to parent directory'])
        chdir('..')
        assert backtick('bzr relpath sub2/hello.txt') == os.path.join('sub1', 'sub2', 'hello.txt\n')

        runcmd('bzr move sub2/hello.txt .')
        assert exists('hello.txt')

        f = file('hello.txt', 'wt')
        f.write('some nice new content\n')
        f.close()

        f = file('msg.tmp', 'wt')
        f.write('this is my new commit\n')
        f.close()

        runcmd('bzr commit -F msg.tmp')

        assert backtick('bzr revno') == '5\n'
        runcmd('bzr export -r 5 export-5.tmp')
        runcmd('bzr export export.tmp')

        runcmd('bzr log')
        runcmd('bzr log -v')



        progress("file with spaces in name")
        mkdir('sub directory')
        file('sub directory/file with spaces ', 'wt').write('see how this works\n')
        runcmd('bzr add .')
        runcmd('bzr diff')
        runcmd('bzr commit -m add-spaces')
        runcmd('bzr check')

        runcmd('bzr log')
        runcmd('bzr log --forward')

        runcmd('bzr info')






        chdir('..')
        chdir('..')
        progress('branch')
        # Can't create a branch if it already exists
        runcmd('bzr branch branch1', retcode=1)
        # Can't create a branch if its parent doesn't exist
        runcmd('bzr branch /unlikely/to/exist', retcode=1)
        runcmd('bzr branch branch1 branch2')

        progress("pull")
        chdir('branch1')
        runcmd('bzr pull', retcode=1)
        runcmd('bzr pull ../branch2')
        chdir('.bzr')
        runcmd('bzr pull')
        runcmd('bzr commit --unchanged -m empty')
        runcmd('bzr pull')
        chdir('../../branch2')
        runcmd('bzr pull')
        runcmd('bzr commit --unchanged -m empty')
        chdir('../branch1')
        runcmd('bzr commit --unchanged -m empty')
        runcmd('bzr pull', retcode=1)
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
        runcmd('bzr init')
        file('a', 'w').write('foo')
        runcmd('bzr add a')
        runcmd(['bzr', 'commit', '-m', 'add a'])
        runcmd('bzr remove a')
        runcmd('bzr status')

        chdir('..')

        progress('ignore patterns')
        mkdir('ignorebranch')
        chdir('ignorebranch')
        runcmd('bzr init')
        assert backtick('bzr unknowns') == ''

        file('foo.tmp', 'wt').write('tmp files are ignored')
        assert backtick('bzr unknowns') == ''

        file('foo.c', 'wt').write('int main() {}')
        assert backtick('bzr unknowns') == 'foo.c\n'
        runcmd('bzr add foo.c')
        assert backtick('bzr unknowns') == ''

        # 'ignore' works when creating the .bzignore file
        file('foo.blah', 'wt').write('blah')
        assert backtick('bzr unknowns') == 'foo.blah\n'
        runcmd('bzr ignore *.blah')
        assert backtick('bzr unknowns') == ''
        assert file('.bzrignore', 'rb').read() == '*.blah\n'

        # 'ignore' works when then .bzrignore file already exists
        file('garh', 'wt').write('garh')
        assert backtick('bzr unknowns') == 'garh\n'
        runcmd('bzr ignore garh')
        assert backtick('bzr unknowns') == ''
        assert file('.bzrignore', 'rb').read() == '*.blah\ngarh\n'

        chdir('..')




        progress("recursive and non-recursive add")
        mkdir('no-recurse')
        chdir('no-recurse')
        runcmd('bzr init')
        mkdir('foo')
        fp = os.path.join('foo', 'test.txt')
        f = file(fp, 'w')
        f.write('hello!\n')
        f.close()
        runcmd('bzr add --no-recurse foo')
        runcmd('bzr file-id foo')
        runcmd('bzr file-id ' + fp, 1)      # not versioned yet
        runcmd('bzr commit -m add-dir-only')

        runcmd('bzr file-id ' + fp, 1)      # still not versioned 

        runcmd('bzr add foo')
        runcmd('bzr file-id ' + fp)
        runcmd('bzr commit -m add-sub-file')

        chdir('..')



class RevertCommand(InTempDir):
    def runTest(self):
        self.runcmd('bzr init')

        file('hello', 'wt').write('foo')
        self.runcmd('bzr add hello')
        self.runcmd('bzr commit -m setup hello')
        
        file('hello', 'wt').write('bar')
        self.runcmd('bzr revert hello')
        self.check_file_contents('hello', 'foo')

    
        


# lists all tests from this module in the best order to run them.  we
# do it this way rather than just discovering them all because it
# allows us to test more basic functions first where failures will be
# easiest to understand.
TEST_CLASSES = [TestVersion,
                InitBranch,
                HelpCommands,
                UserIdentity,
                InvalidCommands,
                RevertCommand,
                OldTests,
                EmptyCommit,
                ]
