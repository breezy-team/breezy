# Copyright (C) 2008-2011 Canonical Ltd
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

__doc__ = """Base64 credential store for the authentication.conf file"""
# Since we are a built-in plugin we share the bzrlib version
from bzrlib import version_info

from bzrlib import (
    config,
    lazy_import,
    )

lazy_import.lazy_import(globals(), """
import errno
import base64
from bzrlib import (
    errors,
    )
""")

class Base64CredentialStore(config.CredentialStore):
    
    def decode_password(self, credentials):
        """See CredentialStore.decode_password."""
        return base64.decodestring(credentials['password'])

config.credential_store_registry.register_lazy('base64', __name__, 'Base64CredentialStore', help=__doc__)



def load_tests(basic_tests, module, loader):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
