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


"""Tests for bzr setting permissions.

Files which are created underneath .bzr/ should inherit its permissions.
So if the directory is group writable, the files and subdirs should be as well.

In the future, when we have Repository/Branch/Checkout information, the
permissions should be inherited individually, rather than all be the same.
"""

# TODO: jam 20051215 There are no tests for ftp yet, because we have no ftp server
# TODO: jam 20051215 Currently the default behavior for 'bzr branch' is just 
#                    defined by the local umask. This isn't terrible, is it
#                    the truly desired behavior?
 
import os
import sys
import stat
from StringIO import StringIO

from bzrlib.branch import Branch
from bzrlib.lockable_files import LockableFiles
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.transport import get_transport
from bzrlib.workingtree import WorkingTree


def chmod_r(base, file_mode, dir_mode):
    """Recursively chmod from a base directory"""
    assert os.path.isdir(base)
    os.chmod(base, dir_mode)
    for root, dirs, files in os.walk(base):
        for d in dirs:
            p = os.path.join(root, d)
            os.chmod(p, dir_mode)
        for f in files:
            p = os.path.join(root, f)
            os.chmod(p, file_mode)


def check_mode_r(test, base, file_mode, dir_mode, include_base=True):
    """Check that all permissions match

    :param test: The TestCase being run
    :param base: The path to the root directory to check
    :param file_mode: The mode for all files
    :param dir_mode: The mode for all directories
    :param include_base: If false, only check the subdirectories
    """
    assert os.path.isdir(base)
    t = get_transport(".")
    if include_base:
        test.assertTransportMode(t, base, dir_mode)
    for root, dirs, files in os.walk(base):
        for d in dirs:
            p = os.path.join(root, d)
            test.assertTransportMode(t, p, dir_mode)
        for f in files:
            p = os.path.join(root, f)
            test.assertTransportMode(t, p, file_mode)


def assertEqualMode(test, mode, mode_test):
    test.assertEqual(mode, mode_test,
                     'mode mismatch %o != %o' % (mode, mode_test))


class TestPermissions(TestCaseWithTransport):

    def test_new_files(self):
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')

        t = WorkingTree.create_standalone('.')
        b = t.branch
        open('a', 'wb').write('foo\n')
        t.add('a')
        t.commit('foo')

        # Delete them because we are modifying the filesystem underneath them
        del b, t 
        chmod_r('.bzr', 0644, 0755)
        check_mode_r(self, '.bzr', 0644, 0755)

        b = Branch.open('.')
        t = b.working_tree()
        assertEqualMode(self, 0755, b.control_files._dir_mode)
        assertEqualMode(self, 0644, b.control_files._file_mode)

        # Modifying a file shouldn't break the permissions
        open('a', 'wb').write('foo2\n')
        t.commit('foo2')
        # The mode should be maintained after commit
        check_mode_r(self, '.bzr', 0644, 0755)

        # Adding a new file should maintain the permissions
        open('b', 'wb').write('new b\n')
        t.add('b')
        t.commit('new b')
        check_mode_r(self, '.bzr', 0644, 0755)

        del b, t
        # Recursively update the modes of all files
        chmod_r('.bzr', 0664, 0775)
        check_mode_r(self, '.bzr', 0664, 0775)
        b = Branch.open('.')
        t = b.working_tree()
        assertEqualMode(self, 0775, b.control_files._dir_mode)
        assertEqualMode(self, 0664, b.control_files._file_mode)

        open('a', 'wb').write('foo3\n')
        t.commit('foo3')
        check_mode_r(self, '.bzr', 0664, 0775)

        open('c', 'wb').write('new c\n')
        t.add('c')
        t.commit('new c')
        check_mode_r(self, '.bzr', 0664, 0775)

        # Test the group sticky bit
        del b, t
        # Recursively update the modes of all files
        chmod_r('.bzr', 0664, 02775)
        check_mode_r(self, '.bzr', 0664, 02775)
        b = Branch.open('.')
        t = b.working_tree()
        assertEqualMode(self, 02775, b.control_files._dir_mode)
        assertEqualMode(self, 0664, b.control_files._file_mode)

        open('a', 'wb').write('foo4\n')
        t.commit('foo4')
        check_mode_r(self, '.bzr', 0664, 02775)

        open('d', 'wb').write('new d\n')
        t.add('d')
        t.commit('new d')
        check_mode_r(self, '.bzr', 0664, 02775)

    def test_disable_set_mode(self):
        # TODO: jam 20051215 Ultimately, this test should probably test that
        #                    extra chmod calls aren't being made
        try:
            transport = get_transport(self.get_url())
            transport.put('my-lock', StringIO(''))
            lockable = LockableFiles(transport, 'my-lock')
            self.assertNotEqual(None, lockable._dir_mode)
            self.assertNotEqual(None, lockable._file_mode)

            LockableFiles._set_dir_mode = False
            transport = get_transport('.')
            lockable = LockableFiles(transport, 'my-lock')
            self.assertEqual(None, lockable._dir_mode)
            self.assertNotEqual(None, lockable._file_mode)

            LockableFiles._set_file_mode = False
            transport = get_transport('.')
            lockable = LockableFiles(transport, 'my-lock')
            self.assertEqual(None, lockable._dir_mode)
            self.assertEqual(None, lockable._file_mode)

            LockableFiles._set_dir_mode = True
            transport = get_transport('.')
            lockable = LockableFiles(transport, 'my-lock')
            self.assertNotEqual(None, lockable._dir_mode)
            self.assertEqual(None, lockable._file_mode)

            LockableFiles._set_file_mode = True
            transport = get_transport('.')
            lockable = LockableFiles(transport, 'my-lock')
            self.assertNotEqual(None, lockable._dir_mode)
            self.assertNotEqual(None, lockable._file_mode)
        finally:
            LockableFiles._set_dir_mode = True
            LockableFiles._set_file_mode = True

    def test_new_branch(self):
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')
        #FIXME RBC 20060105 should test branch and repository 
        # permissions ? 
        # also, these are BzrBranch format specific things..
        os.mkdir('a')
        mode = stat.S_IMODE(os.stat('a').st_mode)
        t = WorkingTree.create_standalone('.')
        b = t.branch
        assertEqualMode(self, mode, b.control_files._dir_mode)
        assertEqualMode(self, mode & ~07111, b.control_files._file_mode)

        os.mkdir('b')
        os.chmod('b', 02777)
        b = Branch.create('b')
        assertEqualMode(self, 02777, b.control_files._dir_mode)
        assertEqualMode(self, 00666, b.control_files._file_mode)
        check_mode_r(self, 'b/.bzr', 00666, 02777)

        os.mkdir('c')
        os.chmod('c', 02750)
        b = Branch.create('c')
        assertEqualMode(self, 02750, b.control_files._dir_mode)
        assertEqualMode(self, 00640, b.control_files._file_mode)
        check_mode_r(self, 'c/.bzr', 00640, 02750)

        os.mkdir('d')
        os.chmod('d', 0700)
        b = Branch.create('d')
        assertEqualMode(self, 0700, b.control_files._dir_mode)
        assertEqualMode(self, 0600, b.control_files._file_mode)
        check_mode_r(self, 'd/.bzr', 00600, 0700)


class TestSftpPermissions(TestCaseWithSFTPServer):

    def test_new_files(self):
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')
        # Though it would be nice to test that SFTP to a server
        # which does support chmod has the right effect

        from bzrlib.transport.sftp import SFTPTransport

        # We don't actually use it directly, we just want to
        # keep the connection open, since StubSFTPServer only
        # allows 1 connection
        _transport = SFTPTransport(self._sftp_url)

        os.mkdir('local')
        t_local = WorkingTree.create_standalone('local')
        b_local = t_local.branch
        open('local/a', 'wb').write('foo\n')
        t_local.add('a')
        t_local.commit('foo')

        # Delete them because we are modifying the filesystem underneath them
        del b_local, t_local 
        chmod_r('local/.bzr', 0644, 0755)
        check_mode_r(self, 'local/.bzr', 0644, 0755)

        b_local = Branch.open(u'local')
        t_local = b_local.working_tree()
        assertEqualMode(self, 0755, b_local.control_files._dir_mode)
        assertEqualMode(self, 0644, b_local.control_files._file_mode)

        os.mkdir('sftp')
        sftp_url = self.get_remote_url('sftp')
        b_sftp = Branch.create(sftp_url)

        b_sftp.pull(b_local)
        del b_sftp
        chmod_r('sftp/.bzr', 0644, 0755)
        check_mode_r(self, 'sftp/.bzr', 0644, 0755)

        b_sftp = Branch.open(sftp_url)
        assertEqualMode(self, 0755, b_sftp.control_files._dir_mode)
        assertEqualMode(self, 0644, b_sftp.control_files._file_mode)

        open('local/a', 'wb').write('foo2\n')
        t_local.commit('foo2')
        b_sftp.pull(b_local)
        # The mode should be maintained after commit
        check_mode_r(self, 'sftp/.bzr', 0644, 0755)

        open('local/b', 'wb').write('new b\n')
        t_local.add('b')
        t_local.commit('new b')
        b_sftp.pull(b_local)
        check_mode_r(self, 'sftp/.bzr', 0644, 0755)

        del b_sftp
        # Recursively update the modes of all files
        chmod_r('sftp/.bzr', 0664, 0775)
        check_mode_r(self, 'sftp/.bzr', 0664, 0775)

        b_sftp = Branch.open(sftp_url)
        assertEqualMode(self, 0775, b_sftp.control_files._dir_mode)
        assertEqualMode(self, 0664, b_sftp.control_files._file_mode)

        open('local/a', 'wb').write('foo3\n')
        t_local.commit('foo3')
        b_sftp.pull(b_local)
        check_mode_r(self, 'sftp/.bzr', 0664, 0775)

        open('local/c', 'wb').write('new c\n')
        t_local.add('c')
        t_local.commit('new c')
        b_sftp.pull(b_local)
        check_mode_r(self, 'sftp/.bzr', 0664, 0775)

    def test_sftp_server_modes(self):
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')

        umask = 0022
        original_umask = os.umask(umask)

        try:
            from bzrlib.transport.sftp import SFTPTransport
            t = SFTPTransport(self._sftp_url)
            # Direct access should be masked by umask
            t._sftp_open_exclusive('a', mode=0666).write('foo\n')
            self.assertTransportMode(t, 'a', 0666 &~umask)

            # but Transport overrides umask
            t.put('b', 'txt', mode=0666)
            self.assertTransportMode(t, 'b', 0666)

            t._sftp.mkdir('c', mode=0777)
            self.assertTransportMode(t, 'c', 0777 &~umask)

            t.mkdir('d', mode=0777)
            self.assertTransportMode(t, 'd', 0777)
        finally:
            os.umask(original_umask)
