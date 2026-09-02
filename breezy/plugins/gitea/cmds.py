# Copyright (C) 2026 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Gitea command implementations."""

import base64
import json

from ... import errors
from ...commands import Command


class cmd_gitea_login(Command):
    """Log into a Gitea instance.

    When communicating with a Gitea instance, some commands need to
    authenticate. This creates a personal access token via basic auth and
    stores it in Breezy's authentication configuration.
    """

    __doc__ = """Log into a Gitea instance.

    When communicating with a Gitea instance, some commands need to
    authenticate. This creates a personal access token via basic auth and
    stores it in Breezy's authentication configuration.
    """

    takes_args = ["url", "username?"]

    def run(self, url, username=None):
        """Execute the gitea-login command.

        Args:
            url: The base URL of the Gitea instance to log into.
            username: Optional Gitea username to log in with.

        Raises:
            CommandError: If authentication fails or the token cannot be
                created.
        """
        from ... import urlutils
        from ...config import AuthenticationConfig
        from ...transport import get_transport
        from .forge import API_PATH, store_gitea_token

        authconfig = AuthenticationConfig()
        (scheme, _user, _password, host, _port, _path) = urlutils.parse_url(url)
        scheme = scheme or "https"
        if username is None:
            username = authconfig.get_user(
                scheme, host, prompt="Gitea username", ask=True
            )
        password = authconfig.get_password(scheme, host, username)
        transport = get_transport(urlutils.join(url, API_PATH))
        basic = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        data = {"name": "Breezy", "scopes": ["write:repository", "write:user"]}
        response = transport.request(
            "POST",
            urlutils.join(transport.base, f"users/{username}/tokens"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {basic}",
            },
            body=json.dumps(data).encode("utf-8"),
        )
        if response.status != 201:
            raise errors.CommandError(
                f"Unable to create Gitea access token: {response.text}"
            )
        token = json.loads(response.text)["sha1"]
        store_gitea_token(name=host, url=url, private_token=token)
