# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""GitLab command implementations."""

from __future__ import absolute_import

from ... import (
    errors,
    urlutils,
    )
from ...commands import Command
from ...option import (
    Option,
    )
from ...trace import note


class cmd_gitlab_login(Command):
    __doc__ = """Log into a GitLab instance.

    This command takes a GitLab instance URL (e.g. https://gitlab.com)
    as well as an optional private token. Private tokens can be created via the
    web UI.

    :Examples:

      Log into GNOME's GitLab (prompts for a token):

         brz gitlab-login https://gitlab.gnome.org/

      Log into Debian's salsa, using a token created earlier:

         brz gitlab-login https://salsa.debian.org if4Theis6Eich7aef0zo
    """

    takes_args = ['url', 'private_token?']

    takes_options = [
        Option('name', help='Name for GitLab site in configuration.',
               type=str),
        Option('no-check',
               "Don't check that the token is valid."),
        ]

    def run(self, url, private_token=None, name=None, no_check=False):
        from breezy import ui
        from .forge import store_gitlab_token
        if name is None:
            try:
                name = urlutils.parse_url(url)[3].split('.')[-2]
            except (ValueError, IndexError):
                raise errors.CommandError(
                    'please specify a site name with --name')
        if private_token is None:
            note("Please visit %s to obtain a private token.",
                 urlutils.join(url, "-/profile/personal_access_tokens"))
            private_token = ui.ui_factory.get_password(u'Private token')
        if not no_check:
            from breezy.transport import get_transport
            from .forge import GitLab
            GitLab(get_transport(url), private_token=private_token)
        store_gitlab_token(name=name, url=url, private_token=private_token)
