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


"""Black-box tests for bzr setting permissions.
"""

import os
import sys
import stat

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.tests.test_sftp import TestCaseWithSFTPServer


def chmod_r(base, file_mode, dir_mode):
    """Recursively chmod from a base directory"""
    for root, dirs, files in os.walk(base):
        for d in dirs:
            p = os.path.join(root, d)
            os.chmod(p, dir_mode)
        for f in files:
            p = os.path.join(root, f)
            os.chmod(p, file_mode)


def check_mode(test, path, mode):
    """Check that a particular path has the correct mode."""
    actual_mode = stat.S_IMODE(os.stat(path).st_mode)
    test.assertEqual(mode, actual_mode,
        'mode of %r incorrect (%o != %o)' % (path, mode, actual_mode))


def check_mode_r(test, base, file_mode, dir_mode):
    """Check that all permissions match"""
    for root, dirs, files in os.walk(base):
        for d in dirs:
            p = os.path.join(root, d)
            check_mode(test, p, dir_mode)
        for f in files:
            p = os.path.join(root, f)
            check_mode(test, p, file_mode)


class TestPermissions(TestCaseInTempDir):

    def test_new_files(self):
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')

        b = Branch.initialize(u'.')
        t = b.working_tree()
        open('a', 'wb').write('foo\n')
        t.add('a')
        t.commit('foo')

        # Delete them because we are modifying the filesystem underneath them
        del b, t 
        chmod_r('.bzr', 0644, 0755)
        check_mode_r(self, '.bzr', 0644, 0755)

        b = Branch.open('.')
        t = b.working_tree()

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

        open('a', 'wb').write('foo3\n')
        t.commit('foo3')
        check_mode_r(self, '.bzr', 0664, 0775)

        open('c', 'wb').write('new c\n')
        t.add('c')
        t.commit('new c')
        check_mode_r(self, '.bzr', 0664, 0775)


# TODO: JAM 20051215 Probably we want to check FTP permissions as well
#       but we need an FTP server for that
class TestSftpPermissions(TestCaseWithSFTPServer):

    def test_new_files(self):
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')

        # We don't actually use it directly, we just want to
        # keep the connection open, since StubSFTPServer only
        # allows 1 connection. Also, this calls delayed_setup()
        _transport = self.get_transport()

        os.mkdir('local')
        b_local = Branch.initialize(u'local')
        t_local = b_local.working_tree()
        open('local/a', 'wb').write('foo\n')
        t_local.add('a')
        t_local.commit('foo')

        # Delete them because we are modifying the filesystem underneath them
        del b_local, t_local 
        chmod_r('local/.bzr', 0644, 0755)
        check_mode_r(self, 'local/.bzr', 0644, 0755)

        b_local = Branch.open(u'local')
        t_local = b_local.working_tree()
        os.chdir('..')

        os.mkdir('sftp')
        sftp_url = self._sftp_url + '/sftp'
        b_sftp = Branch.initialize(sftp_url)

        b_sftp.pull(b_local)
        del b_sftp
        chmod_r('sftp/.bzr', 0644, 0755)
        check_mode_r(self, 'sftp/.bzr', 0644, 0755)

        b_sftp = Branch.open(sftp_url)

        open('local/a', 'wb').write('foo2\n')
        t_local.commit('foo2')
        b_sftp.pull(b_local)
        # The mode should be maintained after commit
        check_mode_r(self, 'sftp/.bzr', 0644, 0755)

        open('b', 'wb').write('new b\n')
        t_local.add('b')
        t_local.commit('new b')
        b_sftp.pull(b_local)
        check_mode_r(self, 'sftp/.bzr', 0644, 0755)

        del b_sftp
        # Recursively update the modes of all files
        chmod_r('sftp/.bzr', 0664, 0775)
        check_mode_r(self, 'sftp/.bzr', 0664, 0775)

        b_sftp = Branch.open(sftp_url)

        open('a', 'wb').write('foo3\n')
        t_local.commit('foo3')
        b_sftp.pull(b_local)
        check_mode_r(self, 'sftp/.bzr', 0664, 0775)

        open('c', 'wb').write('new c\n')
        t_local.add('c')
        t_local.commit('new c')
        b_sftp.pull(b_local)
        check_mode_r(self, 'sftp/.bzr', 0664, 0775)


