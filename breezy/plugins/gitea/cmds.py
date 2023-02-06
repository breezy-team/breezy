# Copyright (C) 2023 Jelmer Vernooij <jelmer@jelmer.uk>
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

from ... import (
    errors,
    urlutils,
    )
from ...commands import Command
from ...option import (
    Option,
    )
from ...trace import note


class cmd_gitea_login(Command):
    __doc__ = """Log into a Gitea instance.

    This command takes a Gitea/Forgejo instance URL (e.g. https://codehut.org)
    as well as an optional private token. Private tokens can be created via the
    web UI.

    :Examples:

      Log into codehut.org (prompts for a token):

         brz gitea-login https://codehut.org/
    """

    takes_args = ['url', 'private_token?']

    takes_options = [
        Option('name', help='Name for Gitea site in configuration.',
               type=str),
        Option('no-check',
               "Don't check that the token is valid."),
        ]

    def run(self, url, private_token=None, name=None, no_check=False):
        from breezy import ui
        from .forge import store_gitea_token
        if name is None:
            try:
                name = urlutils.parse_url(url)[3].split('.')[-2]
            except (ValueError, IndexError):
                raise errors.CommandError(
                    'please specify a site name with --name')
        if private_token is None:
            note("Please visit %s to obtain a private token.",
                 urlutils.join(url, "/user/settings/applications"))
            private_token = ui.ui_factory.get_password('Private token')
        if not no_check:
            from breezy.transport import get_transport
            from .forge import Gitea
            Gitea(get_transport(url), private_token=private_token)
        store_gitea_token(name=name, url=url, private_token=private_token)
