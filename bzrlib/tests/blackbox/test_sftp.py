# Copyright (C) 2006 by Canonical Ltd
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

"""Tests for how bzr interacts when really connecting to sftp"""

from bzrlib.tests import TestCase, TestSkipped


class TestRealSFTP(TestCase):

    def test_bad_connection(self):
        # This is a blackbox test because we need to spawn a real bzr
        # so that it tries to use a real 'ssh' connection
        bogus_url = 'sftp://127.0.0.1:1/'
        # We should get a connection error
        out, err = self.run_bzr_subprocess('log', bogus_url, retcode=3)
        self.assertEqual('', out)
        if "NameError: global name 'SSHException'" in err:
            # We aren't fixing this bug, because it is a bug in
            # paramiko, but we know about it, so we don't have to
            # fail the test
            raise TestSkipped('Known NameError bug with paramiko-1.6.1')
        self.assertContainsRe(err, 'Connection error')
