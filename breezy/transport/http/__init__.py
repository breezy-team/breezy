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

from ... import config
from ... import version_string as breezy_version


def default_user_agent():
    """Get the default User-Agent string for HTTP requests.

    Returns:
        str: The User-Agent string in the format "Breezy/<version>".
    """
    return f"Breezy/{breezy_version}"


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
    """Return a path to a CA bundle if Breezy can find one on disk.

    On Linux/BSD distros that ship a PEM bundle in a well-known location
    we point at it explicitly; everywhere else we return ``None`` and let
    ``ssl.create_default_context()`` load the system trust store via
    ``SSLContext.load_default_certs()`` (which on Windows reads the
    Windows certificate store and on other platforms falls back to
    OpenSSL's defaults).
    """
    if sys.platform in ("win32", "darwin"):
        # Python's ssl module loads the system trust store itself on
        # Windows; on macOS it depends on how Python was built (the
        # python.org installer ships with certifi, Homebrew uses OpenSSL's
        # defaults). In neither case should we invent a cafile path.
        return None
    for path in _ssl_ca_certs_known_locations:
        if os.path.exists(path):
            return path
    return None


def ca_certs_from_store(path):
    """Validate and return a CA certificates path from configuration.

    Args:
        path: The path to the CA certificates bundle.

    Returns:
        str: The validated path.

    Raises:
        ValueError: If the path does not exist.
    """
    if not os.path.exists(path):
        raise ValueError(f"ca certs path {path} does not exist")
    return path


def cert_reqs_from_store(unicode_str):
    """Convert a certificate requirement string to SSL constant.

    Args:
        unicode_str: Either "required" or "none" specifying the certificate
            verification requirement.

    Returns:
        int: SSL constant (ssl.CERT_REQUIRED or ssl.CERT_NONE).

    Raises:
        ValueError: If unicode_str is not "required" or "none".
    """
    import ssl

    try:
        return {"required": ssl.CERT_REQUIRED, "none": ssl.CERT_NONE}[unicode_str]
    except KeyError as e:
        raise ValueError(f"invalid value {unicode_str}") from e


def default_ca_reqs():
    """Return the default certificate verification requirement.

    Always ``"required"``. Earlier versions defaulted to ``"none"`` on
    Windows and macOS because Python lacked an out-of-the-box trust store
    integration; that hasn't been true for a decade and silently disabling
    verification is a serious security regression. Users who genuinely
    need to skip verification can pass ``-Ossl.cert_reqs=none``.
    """
    return "required"


opt_ssl_ca_certs = config.Option(
    "ssl.ca_certs",
    from_unicode=ca_certs_from_store,
    default=default_ca_certs,
    invalid="warning",
    help="""\
Path to certification authority certificates to trust.

This should be a valid path to a bundle containing all root Certificate
Authorities used to verify an https server certificate.

Use ssl.cert_reqs=none to disable certificate verification.
""",
)

opt_ssl_cert_reqs = config.Option(
    "ssl.cert_reqs",
    default=default_ca_reqs,
    from_unicode=cert_reqs_from_store,
    invalid="error",
    help="""\
Whether to require a certificate from the remote side. (default:required)

Possible values:
 * none: Certificates ignored
 * required: Certificates required and validated
""",
)
