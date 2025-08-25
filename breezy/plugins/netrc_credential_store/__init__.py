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

"""Use ~/.netrc as a credential store for authentication.conf."""

__doc__ = """Use ~/.netrc as a credential store for authentication.conf."""

# Since we are a built-in plugin we share the breezy version
from ... import (
    config,
    version_info,  # noqa: F401
)
from ... import transport as _mod_transport


class NetrcCredentialStore(config.CredentialStore):
    """Credential store that reads from ~/.netrc file."""

    def __init__(self):
        """Initialize the netrc credential store.

        Raises:
            NoSuchFile: If ~/.netrc file doesn't exist.
        """
        super().__init__()
        import netrc

        try:
            self._netrc = netrc.netrc()
        except FileNotFoundError as e:
            raise _mod_transport.NoSuchFile(e.filename) from e

    def decode_password(self, credentials):
        """Decode password from netrc for given credentials.

        Args:
            credentials: Dictionary containing host and optionally user.

        Returns:
            Password string if found and user matches, None otherwise.
        """
        auth = self._netrc.authenticators(credentials["host"])
        password = None
        if auth is not None:
            user, account, password = auth
            cred_user = credentials.get("user", None)
            if cred_user is None or user != cred_user:
                # We don't use the netrc ability to provide a user since there
                # is no way to give it back to AuthConfig. So if the user
                # doesn't match, we don't return a password.
                password = None
        return password


config.credential_store_registry.register_lazy(
    "netrc", __name__, "NetrcCredentialStore", help=__doc__
)


def load_tests(loader, basic_tests, pattern):
    """Load test modules for the netrc credential store plugin.

    Args:
        loader: Test loader.
        basic_tests: Basic test suite.
        pattern: Test pattern (unused).

    Returns:
        Updated test suite with plugin tests.
    """
    testmod_names = [
        "tests",
    ]
    for tmn in testmod_names:
        basic_tests.addTest(loader.loadTestsFromName(f"{__name__}.{tmn}"))
    return basic_tests
