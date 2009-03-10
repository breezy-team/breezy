# Copyright (C) 2008 Canonical Ltd
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

from bzrlib import (
    config,
    errors,
    osutils,
    tests,
    )

from bzrlib.plugins import netrc_credential_store


class TestNetrcCSNoNetrc(tests.TestCaseInTempDir):

    def test_home_netrc_does_not_exist(self):
        self.assertRaises(errors.NoSuchFile,
                          config.credential_store_registry.get_credential_store,
                          'netrc')


class TestNetrcCS(tests.TestCaseInTempDir):

    def setUp(self):
        super(TestNetrcCS, self).setUp()
        # Create a .netrc file
        netrc_content = """
machine host login joe password secret
default login anonymous password joe@home
"""
        f = open(osutils.pathjoin(self.test_home_dir, '.netrc'), 'wb')
        try:
            f.write(netrc_content)
        finally:
            f.close()
        
        # Create a test AuthenticationConfig object
        ac_content = """
[host1]
host = host
user = joe
password_encoding = netrc

[host2]
host = host
user = jim
password_encoding = netrc

[other]
host = other
user = anonymous
password_encoding = netrc
"""
        ac_path = osutils.pathjoin(self.test_home_dir, 'netrc-authentication.conf')
        f = open(ac_path, 'wb')
        try:
            f.write(ac_content)
        finally:
            f.close()
        self.ac = config.AuthenticationConfig(_file=ac_path)

    def test_not_matching_user(self):
        credentials = self.ac.get_credentials('scheme', 'host', user='jim')
        self.assertIsNot(None, credentials)
        self.assertIs(None, credentials.get('password', None))

    def test_matching_user(self):
        credentials = self.ac.get_credentials('scheme', 'host', user='joe')
        self.assertIsNot(None, credentials)
        self.assertEquals('secret', credentials.get('password', None))

    def test_default_password(self):
        credentials = self.ac.get_credentials('scheme', 'other', user='anonymous')
        self.assertIsNot(None, credentials)
        self.assertEquals('joe@home', credentials.get('password', None))

    def test_default_password_without_user(self):
        self.assertIsNot(None, self.ac)
        credentials = self.ac.get_credentials('scheme', 'other')
        self.assertIs(None, credentials)
