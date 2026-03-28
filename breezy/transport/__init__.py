# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""Compatibility shim for transport module.

This module has been moved to the dromedary package.
This shim provides backward compatibility for code that imports from breezy.transport.
"""

# Re-export from dromedary for backward compatibility
from collections.abc import Callable

from catalogus import registry
from dromedary import (
    AppendBasedFileStream,
    ConnectedTransport,
    FileFileStream,
    LateReadError,
    Server,
    Transport,
    TransportHooks,
    do_catching_redirections,
    get_transport_from_path,
    get_transport_from_url,
    register_lazy_transport,
    register_transport,
    register_transport_proto,
    register_urlparse_netloc_protocol,
    transport_list_registry,
    unregister_transport,
)
from dromedary.errors import (
    FileExists,
    NoSuchFile,
)

import breezy
from dromedary.http import set_user_agent, set_credential_lookup

set_user_agent(f"Breezy/{breezy.__version__}")


def _breezy_credential_lookup(
    protocol, host, port=None, path=None, realm=None,
    user=None, user_prompt=None, password_prompt=None,
):
    """Look up credentials using breezy's AuthenticationConfig."""
    from breezy import config

    auth_conf = config.AuthenticationConfig()
    if user is None:
        user = auth_conf.get_user(
            protocol, host, port=port, path=path, realm=realm,
            ask=user_prompt is not None,
            prompt=user_prompt,
        )
    password = None
    if user is not None and password_prompt is not None:
        password = auth_conf.get_password(
            protocol, host, user, port=port, path=path, realm=realm,
            prompt=password_prompt,
        )
    return user, password


set_credential_lookup(_breezy_credential_lookup)


register_transport_proto("nosmart+")
register_lazy_transport(
    "nosmart+", "breezy.transport.nosmart", "NoSmartTransportDecorator"
)

register_transport_proto(
    "bzr://", help="Fast access using the Bazaar smart server.", register_netloc=True
)
register_lazy_transport("bzr://", "breezy.transport.remote", "RemoteTCPTransport")
register_transport_proto("bzr-v2://", register_netloc=True)
register_lazy_transport(
    "bzr-v2://", "breezy.transport.remote", "RemoteTCPTransportV2Only"
)
register_transport_proto("bzr+http://", register_netloc=True)
register_lazy_transport(
    "bzr+http://", "breezy.transport.remote", "RemoteHTTPTransport"
)
register_transport_proto("bzr+https://", register_netloc=True)
register_lazy_transport(
    "bzr+https://", "breezy.transport.remote", "RemoteHTTPTransport"
)
register_transport_proto(
    "bzr+ssh://",
    help="Fast access using the Bazaar smart server over SSH.",
    register_netloc=True,
)
register_lazy_transport(
    "bzr+ssh://", "breezy.transport.remote", "RemoteSSHTransport"
)
register_transport_proto("ssh:")
register_lazy_transport("ssh:", "breezy.transport.remote", "HintingSSHTransport")


transport_server_registry = registry.Registry[str, Callable, None]()
transport_server_registry.register_lazy(
    "bzr",
    "breezy.bzr.smart.server",
    "serve_bzr",
    help="The Bazaar smart server protocol over TCP. (default port: 4155)",
)
transport_server_registry.default_key = "bzr"


def get_transport(base, possible_transports=None, purpose=None):
    """Open a transport to access a URL or directory.

    Args:
      base: either a URL or a directory name.
      transports: optional reusable transports list. If not None, created
        transports will be added to the list.
      purpose: Purpose for which the transport will be used
        (e.g. 'read', 'write' or None)

    :return: A new transport optionally sharing its connection with one of
        possible_transports.
    """
    if base is None:
        base = "."
    from breezy.location import location_to_url

    return get_transport_from_url(
        location_to_url(base, purpose=purpose), possible_transports
    )
