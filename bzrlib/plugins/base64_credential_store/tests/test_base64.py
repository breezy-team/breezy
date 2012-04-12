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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from cStringIO import StringIO

from bzrlib import (
    config,
    errors,
    osutils,
    tests,
    )

from bzrlib.plugins import base64_credential_store


class TestBase64CredentialStore(tests.TestCase):

    def test_decode_password(self):
        import base64
        r = config.credential_store_registry
        plain_text = r.get_credential_store('base64')
        decoded = plain_text.decode_password(dict(password=base64.encodestring('secret-pass')))
        self.assertEquals('secret-pass', decoded)

