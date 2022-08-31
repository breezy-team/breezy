# Copyright (C) 2005-2011, 2016 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# Mr. Smoketoomuch: I'm sorry?
# Mr. Bounder: You'd better cut down a little then.
# Mr. Smoketoomuch: Oh, I see! Smoke too much so I'd better cut down a little
#                   then!

"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but
rather starts again from the run_brz function.
"""


# XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
# Note: Please don't add new tests here, it's too big and bulky.  Instead add
# them into small suites in breezy.tests.blackbox.test_FOO for the particular
# UI command/aspect that is being tested.


import os
import re
import sys

import breezy
from breezy import (
    osutils,
    )
from breezy.branch import Branch
from breezy.errors import CommandError
from breezy.tests.http_utils import TestCaseWithWebserver
from breezy.tests.test_sftp_transport import TestCaseWithSFTPServer
from breezy.tests import TestCaseWithTransport
from breezy.workingtree import WorkingTree


class TestCommands(TestCaseWithTransport):

    def test_invalid_commands(self):
        self.run_bzr("pants", retcode=3)
        self.run_bzr("--pants off", retcode=3)
        self.run_bzr("diff --message foo", retcode=3)

    def test_revert(self):
        self.run_bzr('init')

        with open('hello', 'wt') as f:
            f.write('foo')
        self.run_bzr('add hello')
        self.run_bzr('commit -m setup hello')

        with open('goodbye', 'wt') as f:
            f.write('baz')
        self.run_bzr('add goodbye')
        self.run_bzr('commit -m setup goodbye')

        with open('hello', 'wt') as f:
            f.write('bar')
        with open('goodbye', 'wt') as f:
            f.write('qux')
        self.run_bzr('revert hello')
        self.check_file_contents('hello', b'foo')
        self.check_file_contents('goodbye', b'qux')
        self.run_bzr('revert')
        self.check_file_contents('goodbye', b'baz')

        os.mkdir('revertdir')
        self.run_bzr('add revertdir')
        self.run_bzr('commit -m f')
        os.rmdir('revertdir')
        self.run_bzr('revert')

        if osutils.supports_symlinks(self.test_dir):
            os.symlink('/unlikely/to/exist', 'symlink')
            self.run_bzr('add symlink')
            self.run_bzr('commit -m f')
            os.unlink('symlink')
            self.run_bzr('revert')
            self.assertPathExists('symlink')
            os.unlink('symlink')
            os.symlink('a-different-path', 'symlink')
            self.run_bzr('revert')
            self.assertEqual('/unlikely/to/exist',
                             os.readlink('symlink'))
        else:
            self.log("skipping revert symlink tests")

        with open('hello', 'wt') as f:
            f.write('xyz')
        self.run_bzr('commit -m xyz hello')
        self.run_bzr('revert -r 1 hello')
        self.check_file_contents('hello', b'foo')
        self.run_bzr('revert hello')
        self.check_file_contents('hello', b'xyz')
        os.chdir('revertdir')
        self.run_bzr('revert')
        os.chdir('..')

    def example_branch(test):
        test.run_bzr('init')
        with open('hello', 'wt') as f:
            f.write('foo')
        test.run_bzr('add hello')
        test.run_bzr('commit -m setup hello')
        with open('goodbye', 'wt') as f:
            f.write('baz')
        test.run_bzr('add goodbye')
        test.run_bzr('commit -m setup goodbye')

    def test_pull_verbose(self):
        """Pull changes from one branch to another and watch the output."""

        os.mkdir('a')
        os.chdir('a')

        self.example_branch()

        os.chdir('..')
        self.run_bzr('branch a b')
        os.chdir('b')
        with open('b', 'wb') as f:
            f.write(b'else\n')
        self.run_bzr('add b')
        self.run_bzr(['commit', '-m', 'added b'])

        os.chdir('../a')
        out = self.run_bzr('pull --verbose ../b')[0]
        self.assertNotEqual(out.find('Added Revisions:'), -1)
        self.assertNotEqual(out.find('message:\n  added b'), -1)
        self.assertNotEqual(out.find('added b'), -1)

        # Check that --overwrite --verbose prints out the removed entries
        self.run_bzr('commit -m foo --unchanged')
        os.chdir('../b')
        self.run_bzr('commit -m baz --unchanged')
        self.run_bzr('pull ../a', retcode=3)
        out = self.run_bzr('pull --overwrite --verbose ../a')[0]

        remove_loc = out.find('Removed Revisions:')
        self.assertNotEqual(remove_loc, -1)
        added_loc = out.find('Added Revisions:')
        self.assertNotEqual(added_loc, -1)

        removed_message = out.find('message:\n  baz')
        self.assertNotEqual(removed_message, -1)
        self.assertTrue(remove_loc < removed_message < added_loc)

        added_message = out.find('message:\n  foo')
        self.assertNotEqual(added_message, -1)
        self.assertTrue(added_loc < added_message)

    def test_locations(self):
        """Using and remembering different locations"""
        os.mkdir('a')
        os.chdir('a')
        self.run_bzr('init')
        self.run_bzr('commit -m unchanged --unchanged')
        self.run_bzr('pull', retcode=3)
        self.run_bzr('merge', retcode=3)
        self.run_bzr('branch . ../b')
        os.chdir('../b')
        self.run_bzr('pull')
        self.run_bzr('branch . ../c')
        self.run_bzr('pull ../c')
        self.run_bzr('merge')
        os.chdir('../a')
        self.run_bzr('pull ../b')
        self.run_bzr('pull')
        self.run_bzr('pull ../c')
        self.run_bzr('branch ../c ../d')
        osutils.rmtree('../c')
        self.run_bzr('pull')
        os.chdir('../b')
        self.run_bzr('pull')
        os.chdir('../d')
        self.run_bzr('pull', retcode=3)
        self.run_bzr('pull ../a --remember')
        self.run_bzr('pull')

    def test_unknown_command(self):
        """Handling of unknown command."""
        out, err = self.run_bzr('fluffy-badger', retcode=3)
        self.assertEqual(out, '')
        err.index('unknown command')

    def create_conflicts(self):
        """Create a conflicted tree"""
        os.mkdir('base')
        os.chdir('base')
        with open('hello', 'wb') as f:
            f.write(b"hi world")
        with open('answer', 'wb') as f:
            f.write(b"42")
        self.run_bzr('init')
        self.run_bzr('add')
        self.run_bzr('commit -m base')
        self.run_bzr('branch . ../other')
        self.run_bzr('branch . ../this')
        os.chdir('../other')
        with open('hello', 'wb') as f:
            f.write(b"Hello.")
        with open('answer', 'wb') as f:
            f.write(b"Is anyone there?")
        self.run_bzr('commit -m other')
        os.chdir('../this')
        with open('hello', 'wb') as f:
            f.write(b"Hello, world")
        self.run_bzr('mv answer question')
        with open('question', 'wb') as f:
            f.write(b"What do you get when you multiply six"
                    b"times nine?")
        self.run_bzr('commit -m this')

    def test_status(self):
        os.mkdir('branch1')
        os.chdir('branch1')
        self.run_bzr('init')
        self.run_bzr('commit --unchanged --message f')
        self.run_bzr('branch . ../branch2')
        self.run_bzr('branch . ../branch3')
        self.run_bzr('commit --unchanged --message peter')
        os.chdir('../branch2')
        self.run_bzr('merge ../branch1')
        self.run_bzr('commit --unchanged --message pumpkin')
        os.chdir('../branch3')
        self.run_bzr('merge ../branch2')
        message = self.run_bzr('status')[0]

    def test_conflicts(self):
        """Handling of merge conflicts"""
        self.create_conflicts()
        self.run_bzr('merge ../other --show-base', retcode=1)
        with open('hello', 'r') as f:
            conflict_text = f.read()
        self.assertTrue('<<<<<<<' in conflict_text)
        self.assertTrue('>>>>>>>' in conflict_text)
        self.assertTrue('=======' in conflict_text)
        self.assertTrue('|||||||' in conflict_text)
        self.assertTrue('hi world' in conflict_text)
        self.run_bzr('revert')
        self.run_bzr('resolve --all')
        self.run_bzr('merge ../other', retcode=1)
        with open('hello', 'r') as f:
            conflict_text = f.read()
        self.assertTrue('|||||||' not in conflict_text)
        self.assertTrue('hi world' not in conflict_text)
        result = self.run_bzr('conflicts')[0]
        self.assertEqual(result, "Text conflict in hello\nText conflict in"
                         " question\n")
        result = self.run_bzr('status')[0]
        self.assertTrue("conflicts:\n  Text conflict in hello\n"
                        "  Text conflict in question\n" in result, result)
        self.run_bzr('resolve hello')
        result = self.run_bzr('conflicts')[0]
        self.assertEqual(result, "Text conflict in question\n")
        self.run_bzr('commit -m conflicts', retcode=3)
        self.run_bzr('resolve --all')
        result = self.run_bzr('conflicts')[0]
        self.run_bzr('commit -m conflicts')
        self.assertEqual(result, "")

    def test_push(self):
        # create a source branch
        os.mkdir('my-branch')
        os.chdir('my-branch')
        self.example_branch()

        # with no push target, fail
        self.run_bzr('push', retcode=3)
        # with an explicit target work
        self.run_bzr('push ../output-branch')
        # with an implicit target work
        self.run_bzr('push')
        # nothing missing
        self.run_bzr('missing ../output-branch')
        # advance this branch
        self.run_bzr('commit --unchanged -m unchanged')

        os.chdir('../output-branch')
        # There is no longer a difference as long as we have
        # access to the working tree
        self.run_bzr('diff')

        # But we should be missing a revision
        self.run_bzr('missing ../my-branch', retcode=1)

        # diverge the branches
        self.run_bzr('commit --unchanged -m unchanged')
        os.chdir('../my-branch')
        # cannot push now
        self.run_bzr('push', retcode=3)
        # and there are difference
        self.run_bzr('missing ../output-branch', retcode=1)
        self.run_bzr('missing --verbose ../output-branch', retcode=1)
        # but we can force a push
        self.run_bzr('push --overwrite')
        # nothing missing
        self.run_bzr('missing ../output-branch')

        # pushing to a new dir with no parent should fail
        self.run_bzr('push ../missing/new-branch', retcode=3)
        # unless we provide --create-prefix
        self.run_bzr('push --create-prefix ../missing/new-branch')
        # nothing missing
        self.run_bzr('missing ../missing/new-branch')

    def test_external_command(self):
        """Test that external commands can be run by setting the path
        """
        # We don't at present run brz in a subprocess for blackbox tests, and so
        # don't really capture stdout, only the internal python stream.
        # Therefore we don't use a subcommand that produces any output or does
        # anything -- we just check that it can be run successfully.
        cmd_name = 'test-command'
        if sys.platform == 'win32':
            cmd_name += '.bat'
        self.overrideEnv('BZRPATH', None)

        f = open(cmd_name, 'wb')
        if sys.platform == 'win32':
            f.write(b'@echo off\n')
        else:
            f.write(b'#!/bin/sh\n')
        # f.write('echo Hello from test-command')
        f.close()
        os.chmod(cmd_name, 0o755)

        # It should not find the command in the local
        # directory by default, since it is not in my path
        self.run_bzr(cmd_name, retcode=3)

        # Now put it into my path
        self.overrideEnv('BZRPATH', '.')
        self.run_bzr(cmd_name)

        # Make sure empty path elements are ignored
        self.overrideEnv('BZRPATH', os.pathsep)
        self.run_bzr(cmd_name, retcode=3)


def listdir_sorted(dir):
    L = sorted(os.listdir(dir))
    return L


class OldTests(TestCaseWithTransport):
    """old tests moved from ./testbzr."""

    def test_bzr(self):
        from os import chdir, mkdir
        from os.path import exists

        progress = self.log

        progress("basic branch creation")
        mkdir('branch1')
        chdir('branch1')
        self.run_bzr('init')

        self.assertIsSameRealPath(self.run_bzr('root')[0].rstrip(),
                                  osutils.pathjoin(self.test_dir, 'branch1'))

        progress("status of new file")

        with open('test.txt', 'wt') as f:
            f.write('hello world!\n')

        self.assertEqual(self.run_bzr('unknowns')[0], 'test.txt\n')

        out = self.run_bzr("status")[0]
        self.assertEqual(out, 'unknown:\n  test.txt\n')

        with open('test2.txt', 'wt') as f:
            f.write('goodbye cruel world...\n')

        out = self.run_bzr("status test.txt")[0]
        self.assertEqual(out, "unknown:\n  test.txt\n")

        out = self.run_bzr("status")[0]
        self.assertEqual(out, ("unknown:\n" "  test.txt\n" "  test2.txt\n"))

        os.unlink('test2.txt')

        progress("command aliases")
        out = self.run_bzr("st")[0]
        self.assertEqual(out, ("unknown:\n" "  test.txt\n"))

        out = self.run_bzr("stat")[0]
        self.assertEqual(out, ("unknown:\n" "  test.txt\n"))

        progress("command help")
        self.run_bzr("help st")
        self.run_bzr("help")
        self.run_bzr("help commands")
        self.run_bzr("help slartibartfast", retcode=3)

        out = self.run_bzr("help ci")[0]
        out.index('Aliases:  ci, checkin\n')

        with open('hello.txt', 'wt') as f:
            f.write('some nice new content\n')

        self.run_bzr("add hello.txt")

        with open('msg.tmp', 'wt') as f:
            f.write('this is my new commit\nand it has multiple lines, for fun')

        self.run_bzr('commit -F msg.tmp')

        self.assertEqual(self.run_bzr('revno')[0], '1\n')
        self.run_bzr('export -r 1 export-1.tmp')
        self.run_bzr('export export.tmp')

        self.run_bzr('log')
        self.run_bzr('log -v')
        self.run_bzr('log -v --forward')
        self.run_bzr('log -m', retcode=3)
        log_out = self.run_bzr('log -m commit')[0]
        self.assertTrue("this is my new commit\n  and" in log_out)
        self.assertTrue("rename nested" not in log_out)
        self.assertTrue('revision-id' not in log_out)
        self.assertTrue(
            'revision-id' in self.run_bzr('log --show-ids -m commit')[0])

        log_out = self.run_bzr('log --line')[0]
        # determine the widest line we want
        max_width = osutils.terminal_width()
        if max_width is not None:
            for line in log_out.splitlines():
                self.assertTrue(len(line) <= max_width - 1, len(line))
        self.assertTrue("this is my new commit and" not in log_out)
        self.assertTrue("this is my new commit" in log_out)

        progress("file with spaces in name")
        mkdir('sub directory')
        with open('sub directory/file with spaces ', 'wt') as f:
            f.write('see how this works\n')
        self.run_bzr('add .')
        self.run_bzr('diff', retcode=1)
        self.run_bzr('commit -m add-spaces')
        self.run_bzr('check')

        self.run_bzr('log')
        self.run_bzr('log --forward')

        self.run_bzr('info')

        if osutils.supports_symlinks(self.test_dir):
            progress("symlinks")
            mkdir('symlinks')
            chdir('symlinks')
            self.run_bzr('init')
            os.symlink("NOWHERE1", "link1")
            self.run_bzr('add link1')
            self.assertEqual(self.run_bzr('unknowns')[0], '')
            self.run_bzr(['commit', '-m', '1: added symlink link1'])

            mkdir('d1')
            self.run_bzr('add d1')
            self.assertEqual(self.run_bzr('unknowns')[0], '')
            os.symlink("NOWHERE2", "d1/link2")
            self.assertEqual(self.run_bzr('unknowns')[0], 'd1/link2\n')
            # is d1/link2 found when adding d1
            self.run_bzr('add d1')
            self.assertEqual(self.run_bzr('unknowns')[0], '')
            os.symlink("NOWHERE3", "d1/link3")
            self.assertEqual(self.run_bzr('unknowns')[0], 'd1/link3\n')
            self.run_bzr(['commit', '-m', '2: added dir, symlink'])

            self.run_bzr('rename d1 d2')
            self.run_bzr('move d2/link2 .')
            self.run_bzr('move link1 d2')
            self.assertEqual(os.readlink("./link2"), "NOWHERE2")
            self.assertEqual(os.readlink("d2/link1"), "NOWHERE1")
            self.run_bzr('add d2/link3')
            self.run_bzr('diff', retcode=1)
            self.run_bzr(['commit', '-m',
                          '3: rename of dir, move symlinks, add link3'])

            os.unlink("link2")
            os.symlink("TARGET 2", "link2")
            os.unlink("d2/link1")
            os.symlink("TARGET 1", "d2/link1")
            self.run_bzr('diff', retcode=1)
            self.assertEqual(self.run_bzr("relpath d2/link1")[0], "d2/link1\n")
            self.run_bzr(['commit', '-m', '4: retarget of two links'])

            self.run_bzr('remove --keep d2/link1')
            self.assertEqual(self.run_bzr('unknowns')[0], 'd2/link1\n')
            self.run_bzr(['commit', '-m', '5: remove d2/link1'])
            # try with the rm alias
            self.run_bzr('add d2/link1')
            self.run_bzr(['commit', '-m', '6: add d2/link1'])
            self.run_bzr('rm --keep d2/link1')
            self.assertEqual(self.run_bzr('unknowns')[0], 'd2/link1\n')
            self.run_bzr(['commit', '-m', '7: remove d2/link1'])

            os.mkdir("d1")
            self.run_bzr('add d1')
            self.run_bzr('rename d2/link3 d1/link3new')
            self.assertEqual(self.run_bzr('unknowns')[0], 'd2/link1\n')
            self.run_bzr(['commit', '-m',
                          '8: remove d2/link1, move/rename link3'])

            self.run_bzr('check')

            self.run_bzr('export -r 1 exp1.tmp')
            chdir("exp1.tmp")
            self.assertEqual(listdir_sorted("."), ["link1"])
            self.assertEqual(os.readlink("link1"), "NOWHERE1")
            chdir("..")

            self.run_bzr('export -r 2 exp2.tmp')
            chdir("exp2.tmp")
            self.assertEqual(listdir_sorted("."), ["d1", "link1"])
            chdir("..")

            self.run_bzr('export -r 3 exp3.tmp')
            chdir("exp3.tmp")
            self.assertEqual(listdir_sorted("."), ["d2", "link2"])
            self.assertEqual(listdir_sorted("d2"), ["link1", "link3"])
            self.assertEqual(os.readlink("d2/link1"), "NOWHERE1")
            self.assertEqual(os.readlink("link2"), "NOWHERE2")
            chdir("..")

            self.run_bzr('export -r 4 exp4.tmp')
            chdir("exp4.tmp")
            self.assertEqual(listdir_sorted("."), ["d2", "link2"])
            self.assertEqual(os.readlink("d2/link1"), "TARGET 1")
            self.assertEqual(os.readlink("link2"), "TARGET 2")
            self.assertEqual(listdir_sorted("d2"), ["link1", "link3"])
            chdir("..")

            self.run_bzr('export -r 5 exp5.tmp')
            chdir("exp5.tmp")
            self.assertEqual(listdir_sorted("."), ["d2", "link2"])
            self.assertTrue(os.path.islink("link2"))
            self.assertTrue(listdir_sorted("d2") == ["link3"])
            chdir("..")

            self.run_bzr('export -r 8 exp6.tmp')
            chdir("exp6.tmp")
            self.assertEqual(listdir_sorted("."), ["d1", "d2", "link2"])
            self.assertEqual(listdir_sorted("d1"), ["link3new"])
            self.assertEqual(listdir_sorted("d2"), [])
            self.assertEqual(os.readlink("d1/link3new"), "NOWHERE3")
            chdir("..")
        else:
            progress("skipping symlink tests")


class RemoteTests(object):
    """Test brz ui commands against remote branches."""

    def test_branch(self):
        os.mkdir('from')
        wt = self.make_branch_and_tree('from')
        branch = wt.branch
        wt.commit('empty commit for nonsense', allow_pointless=True)
        url = self.get_readonly_url('from')
        self.run_bzr(['branch', url, 'to'])
        branch = Branch.open('to')
        self.assertEqual(1, branch.last_revision_info()[0])
        # the branch should be set in to to from
        self.assertEqual(url + '/', branch.get_parent())

    def test_log(self):
        self.build_tree(['branch/', 'branch/file'])
        self.run_bzr('init branch')[0]
        self.run_bzr('add branch/file')[0]
        self.run_bzr('commit -m foo branch')[0]
        url = self.get_readonly_url('branch/file')
        output = self.run_bzr('log %s' % url)[0]
        self.assertEqual(8, len(output.split('\n')))

    def test_check(self):
        self.build_tree(['branch/', 'branch/file'])
        self.run_bzr('init branch')[0]
        self.run_bzr('add branch/file')[0]
        self.run_bzr('commit -m foo branch')[0]
        url = self.get_readonly_url('branch/')
        self.run_bzr(['check', url])

    def test_push(self):
        # create a source branch
        os.mkdir('my-branch')
        os.chdir('my-branch')
        self.run_bzr('init')
        with open('hello', 'wt') as f:
            f.write('foo')
        self.run_bzr('add hello')
        self.run_bzr('commit -m setup')

        # with an explicit target work
        self.run_bzr(['push', self.get_url('output-branch')])


class HTTPTests(TestCaseWithWebserver, RemoteTests):
    """Test various commands against a HTTP server."""


class SFTPTestsAbsolute(TestCaseWithSFTPServer, RemoteTests):
    """Test various commands against a SFTP server using abs paths."""


class SFTPTestsAbsoluteSibling(TestCaseWithSFTPServer, RemoteTests):
    """Test various commands against a SFTP server using abs paths."""

    def setUp(self):
        super(SFTPTestsAbsoluteSibling, self).setUp()
        self._override_home = '/dev/noone/runs/tests/here'


class SFTPTestsRelative(TestCaseWithSFTPServer, RemoteTests):
    """Test various commands against a SFTP server using homedir rel paths."""

    def setUp(self):
        super(SFTPTestsRelative, self).setUp()
        self._get_remote_is_absolute = False
