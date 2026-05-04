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

__all__ = [
    "AppendBasedFileStream",
    "ConnectedTransport",
    "FileExists",
    "FileFileStream",
    "LateReadError",
    "NoSuchFile",
    "Server",
    "Transport",
    "TransportHooks",
    "_file_streams",
    "do_catching_redirections",
    "get_transport_from_path",
    "get_transport_from_url",
    "register_lazy_transport",
    "register_transport",
    "register_transport_proto",
    "register_urlparse_netloc_protocol",
    "set_credential_lookup",
    "set_user_agent",
    "transport_list_registry",
    "unregister_transport",
]

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
    _file_streams,
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

from breezy import hooks as _breezy_hooks


class TransportHooks(_breezy_hooks.Hooks):
    """Mapping of hook names to registered callbacks for transport hooks.

    This is the breezy-flavoured version that integrates with breezy's
    `known_hooks` registry; the dromedary core uses a minimal local hooks
    implementation when used standalone.
    """

    def __init__(self):
        """Register the ``post_connect`` hook point."""
        super().__init__("breezy.transport", "Transport.hooks")
        self.add_hook(
            "post_connect",
            "Called after a new connection is established or a reconnect "
            "occurs. The sole argument passed is either the connected "
            "transport or smart medium instance.",
            (2, 5),
        )


# Override the dromedary-flavoured TransportHooks instance with our own.
Transport.hooks = TransportHooks()  # type: ignore[assignment]
# Wire up breezy integrations into dromedary's callback points
import dromedary.http as _dromedary_http
from dromedary import _bedding, _config, _ui
from dromedary.errors import (
    FileExists,
    NoSuchFile,
)
from dromedary.http import (
    set_auth_header_trace,
    set_credential_lookup,
    set_user_agent,
)

import breezy
from breezy import bedding, ui


def _breezy_report_activity(transport, byte_count, direction):
    ui.ui_factory.report_transport_activity(transport, byte_count, direction)


def _breezy_get_password(prompt="", **kwargs):
    return ui.ui_factory.get_password(prompt, **kwargs)


def _breezy_get_username(prompt, **kwargs):
    return ui.ui_factory.get_username(prompt, **kwargs)


def _breezy_show_message(msg):
    ui.ui_factory.show_message(msg)


_ui.report_transport_activity = _breezy_report_activity
_ui.get_password = _breezy_get_password
_ui.get_username = _breezy_get_username
_ui.show_message = _breezy_show_message


def _breezy_get_ssh_vendor_name():
    from breezy import config

    return config.GlobalStack().get("ssh")


def _breezy_get_auth_user(
    scheme, host, port=None, default=None, ask=False, prompt=None
):
    from breezy import config

    return config.AuthenticationConfig().get_user(
        scheme, host, port=port, default=default, ask=ask, prompt=prompt
    )


def _breezy_get_auth_password(scheme, host, user, port=None):
    from breezy import config

    return config.AuthenticationConfig().get_password(scheme, host, user, port=port)


_config.get_ssh_vendor_name = _breezy_get_ssh_vendor_name
_config.get_auth_user = _breezy_get_auth_user
_config.get_auth_password = _breezy_get_auth_password

_bedding.config_dir = bedding.config_dir
_bedding.ensure_config_dir_exists = bedding.ensure_config_dir_exists


set_user_agent(f"Breezy/{breezy.__version__}")


def _breezy_credential_lookup(
    protocol,
    host,
    port=None,
    path=None,
    realm=None,
    user=None,
    is_proxy=False,
):
    """Look up credentials using breezy's AuthenticationConfig.

    ``user`` carries a username hint from the URL (e.g. the ``joe``
    in ``http://joe@host/``). When supplied, we skip
    AuthenticationConfig's user lookup and go straight to asking for
    the password — matching urllib's old behaviour where a URL-user
    was treated as authoritative.

    ``is_proxy`` is True when the credentials are requested for a
    proxy (HTTP 407) rather than the origin server (HTTP 401). It
    only affects the label prepended to interactive prompts so
    users can tell the two prompts apart.
    """
    from breezy import config

    auth_conf = config.AuthenticationConfig()
    user_prompt = None
    password_prompt = None
    if is_proxy:
        # Match the shape of the urllib-era prompts that breezy's
        # tests assert against: "Proxy HTTP host:port, Realm: 'X'
        # username: " / "Proxy HTTP user@host:port, Realm: 'X'
        # password: ".
        scheme_upper = protocol.upper()
        if realm:
            user_prompt = f"Proxy {scheme_upper} %(host)s, Realm: '{realm}' username"
            password_prompt = (
                f"Proxy {scheme_upper} %(user)s@%(host)s, Realm: '{realm}' password"
            )
        else:
            user_prompt = f"Proxy {scheme_upper} %(host)s username"
            password_prompt = f"Proxy {scheme_upper} %(user)s@%(host)s password"
    if user is None:
        # `ask=True` so AuthenticationConfig prompts via the UI
        # factory when the config has no registered user for this
        # host. Matches urllib's behaviour where a 401 with no cached
        # creds and no URL-user triggered an interactive prompt.
        user = auth_conf.get_user(
            protocol,
            host,
            port=port,
            path=path,
            realm=realm,
            prompt=user_prompt,
            ask=True,
        )
    password = None
    if user is not None:
        password = auth_conf.get_password(
            protocol,
            host,
            user,
            port=port,
            path=path,
            realm=realm,
            prompt=password_prompt,
        )
    return user, password


set_credential_lookup(_breezy_credential_lookup)


def _breezy_auth_header_trace(header_name):
    """Log that an auth header was sent, without exposing its value.

    Invoked by the Rust HTTP client right before a request carrying
    an ``Authorization`` or ``Proxy-Authorization`` header goes on
    the wire. Only emits a ``trace.mutter`` line when the ``http``
    debug flag is on, matching the old urllib handler's behaviour
    so ``test_no_credential_leaks_in_log`` passes.
    """
    from breezy import debug, trace

    if "http" not in debug.get_debug_flags():
        return
    trace.mutter("> %s: <masked>", header_name)


set_auth_header_trace(_breezy_auth_header_trace)


# Plain http://, https://, and the WebDAV variants are handled by
# dromedary's own transports; `breezy.bzr.smart.transport.get_smart_medium`
# knows how to wrap a dromedary HttpTransport in a SmartClientHTTPMedium
# when bzr code needs to tunnel the smart protocol over HTTP.

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
register_lazy_transport("bzr+http://", "breezy.transport.remote", "RemoteHTTPTransport")
register_transport_proto("bzr+https://", register_netloc=True)
register_lazy_transport(
    "bzr+https://", "breezy.transport.remote", "RemoteHTTPTransport"
)
register_transport_proto(
    "bzr+ssh://",
    help="Fast access using the Bazaar smart server over SSH.",
    register_netloc=True,
)
register_lazy_transport("bzr+ssh://", "breezy.transport.remote", "RemoteSSHTransport")
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


# Route breezy's ``ssl.ca_certs`` / ``ssl.cert_reqs`` config options into
# dromedary.http so the Rust HttpTransport picks them up. The hook
# functions re-read GlobalStack on every call rather than snapshotting a
# value, so tests that configure ca_certs via a tempfile and tear it down
# don't leak stale paths across the run.
#
# The hooks lazy-import ``breezy.config`` inside their bodies rather than
# at module-top level so installing them here doesn't pull in the whole
# config / workingtree / tree / lock / transport import chain — that
# cycle already bit an earlier revision of this code that tried a
# top-level ``from breezy.config import _install_ssl_hooks_from_config``.
def _breezy_ssl_ca_certs():
    import os

    from dromedary.http import default_ca_certs

    from breezy.config import GlobalStack

    configured = GlobalStack().get("ssl.ca_certs")
    if configured is not None and os.path.exists(configured):
        return configured
    return default_ca_certs()


def _breezy_ssl_cert_reqs():
    from breezy.config import GlobalStack

    return GlobalStack().get("ssl.cert_reqs")


_dromedary_http.ssl_ca_certs = _breezy_ssl_ca_certs
_dromedary_http.ssl_cert_reqs = _breezy_ssl_cert_reqs
