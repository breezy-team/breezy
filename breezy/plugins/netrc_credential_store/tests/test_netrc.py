# Copyright (C) 2008, 2009, 2013, 2016 Canonical Ltd
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

from io import BytesIO

from .... import config, osutils, tests
from .... import transport as _mod_transport


class TestNetrcCSNoNetrc(tests.TestCaseInTempDir):
    def test_home_netrc_does_not_exist(self):
        self.assertRaises(
            _mod_transport.NoSuchFile,
            config.credential_store_registry.get_credential_store,
            "netrc",
        )


class TestNetrcCS(tests.TestCaseInTempDir):
    def setUp(self):
        super().setUp()
        # Create a .netrc file
        netrc_content = b"""
machine host login joe password secret
default login anonymous password joe@home
"""
        netrc_path = osutils.pathjoin(self.test_home_dir, ".netrc")
        with open(netrc_path, "wb") as f:
            f.write(netrc_content)
        # python's netrc will complain about access permissions starting with
        # 2.7.5-8 so we restrict the access unconditionally
        osutils.chmod_if_possible(netrc_path, 0o600)

    def _get_netrc_cs(self):
        return config.credential_store_registry.get_credential_store("netrc")

    def test_not_matching_user(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host="host", user="jim"))
        self.assertIs(None, password)

    def test_matching_user(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host="host", user="joe"))
        self.assertEqual("secret", password)

    def test_default_password(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host="other", user="anonymous"))
        self.assertEqual("joe@home", password)

    def test_default_password_without_user(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host="other"))
        self.assertIs(None, password)

    def test_get_netrc_credentials_via_auth_config(self):
        # Create a test AuthenticationConfig object
        ac_content = b"""
[host1]
host = host
user = joe
password_encoding = netrc
"""
        conf = config.AuthenticationConfig(_file=BytesIO(ac_content))
        credentials = conf.get_credentials("scheme", "host", user="joe")
        self.assertIsNot(None, credentials)
        self.assertEqual("secret", credentials.get("password", None))
