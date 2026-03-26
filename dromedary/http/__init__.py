# Copyright (C) 2005-2010 Canonical Ltd
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

"""Base implementation of Transport over http.

There are separate implementation modules for each http client implementation.
"""

DEBUG = 0

import os
import sys

from dromedary.version import version_string as dromedary_version


_user_agent_prefix = f"Dromedary/{dromedary_version}"


def set_user_agent(prefix):
    """Set the User-Agent prefix for HTTP requests.

    Args:
        prefix: The User-Agent string to use, e.g. "Breezy/3.4.0".
    """
    global _user_agent_prefix
    _user_agent_prefix = prefix


def _default_credential_lookup(
    protocol, host, port=None, path=None, realm=None,
    user=None, user_prompt=None, password_prompt=None,
):
    """Default credential lookup returning no credentials.

    Override via set_credential_lookup() to integrate with a credential store.

    Returns:
        tuple: (user, password) or (None, None) if no credentials found.
    """
    return None, None


_credential_lookup = _default_credential_lookup


def set_credential_lookup(func):
    """Set the function used to look up HTTP credentials.

    Args:
        func: A callable(protocol, host, port=None, path=None, realm=None,
            user=None, user_prompt=None, password_prompt=None)
            returning (user, password) or (None, None).
    """
    global _credential_lookup
    _credential_lookup = func


def get_credentials(
    protocol, host, port=None, path=None, realm=None,
    user=None, user_prompt=None, password_prompt=None,
):
    """Look up stored credentials for an HTTP connection."""
    return _credential_lookup(
        protocol, host, port=port, path=path, realm=realm,
        user=user, user_prompt=user_prompt, password_prompt=password_prompt,
    )


def default_user_agent():
    """Get the default User-Agent string for HTTP requests."""
    return _user_agent_prefix


# Note for packagers: if there is no package providing certs for your platform,
# the curl project produces http://curl.haxx.se/ca/cacert.pem weekly.
_ssl_ca_certs_known_locations = [
    "/etc/ssl/certs/ca-certificates.crt",  # Ubuntu/debian/gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora/CentOS/RH
    "/etc/ssl/ca-bundle.pem",  # OpenSuse
    "/etc/ssl/cert.pem",  # OpenSuse
    "/usr/local/share/certs/ca-root-nss.crt",  # FreeBSD
    # XXX: Needs checking, can't trust the interweb ;) -- vila 2012-01-25
    "/etc/openssl/certs/ca-certificates.crt",  # Solaris
]


def default_ca_certs():
    """Get the default path to CA certificates for SSL verification.

    Searches for CA certificate bundles in platform-specific locations.
    On Windows, looks for cacert.pem in the executable's directory.
    On other platforms, searches a list of known locations and returns
    the first existing path.

    Returns:
        str: Path to the CA certificate bundle. If no bundle is found,
            returns the first known location as a default.
    """
    if sys.platform == "win32":
        return os.path.join(os.path.dirname(sys.executable), "cacert.pem")
    elif sys.platform == "darwin":
        # FIXME: Needs some default value for osx, waiting for osx installers
        # guys feedback -- vila 2012-01-25
        pass
    else:
        # Try known locations for friendly OSes providing the root certificates
        # without making them hard to use for any https client.
        for path in _ssl_ca_certs_known_locations:
            if os.path.exists(path):
                # First found wins
                return path
    # A default path that makes sense and will be mentioned in the error
    # presented to the user, even if not correct for all platforms
    return _ssl_ca_certs_known_locations[0]


def default_cert_reqs():
    """Get the default certificate verification requirement for the platform.

    On Windows and macOS, returns ssl.CERT_NONE due to lack of native access
    to root certificates. On other platforms, returns ssl.CERT_REQUIRED.
    """
    import ssl

    if sys.platform in ("win32", "darwin"):
        # FIXME: Once we get a native access to root certificates there, this
        # won't needed anymore. See http://pad.lv/920455 -- vila 2012-02-15
        return ssl.CERT_NONE
    else:
        return ssl.CERT_REQUIRED


ssl_ca_certs = default_ca_certs()
ssl_cert_reqs = default_cert_reqs()
