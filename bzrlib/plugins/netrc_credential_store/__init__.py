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

"""Use ~/.netrc as a credential store for authentication.conf."""

from bzrlib import (
    config,
    lazy_import,
    )

lazy_import.lazy_import(globals(), """
    import errno
    import netrc

    from bzrlib import (
        errors,
        )
""")


class NetrcCredentialStore(config.CredentialStore):

    def __init__(self):
        super(NetrcCredentialStore, self).__init__()
        try:
            self._netrc = netrc.netrc()
        except IOError, e:
            if e.args[0] == errno.ENOENT:
                raise errors.NoSuchFile(e.filename)
            else:
                raise

    def decode_password(self, credentials):
        auth = self._netrc.authenticators(credentials['host'])
        password = None
        if auth is not None:
            user, account, password = auth
            cred_user = credentials.get('user', None)
            if cred_user is None or user != cred_user:
                # We don't use the netrc ability to provide a user since this
                # is not handled by authentication.conf. So if the user doesn't
                # match, we don't return a password.
                password = None
        return password


config.credential_store_registry.register_lazy(
    'netrc', __name__, 'NetrcCredentialStore', help=__doc__)


def load_tests(basic_tests, module, loader):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
