# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""GitHub command implementations."""

from ... import errors
from ...commands import Command


class cmd_github_login(Command):
    __doc__ = """Log into GitHub.

    When communicating with GitHub, some commands need to authenticate to
    GitHub. This command asks for a personal access token, which can be
    created at https://github.com/settings/tokens, and stores it. The token
    needs the repo scope, and delete_repo to remove forks.
    """

    def run(self):
        from ... import ui
        from ...trace import note
        from .forge import store_github_token

        note(
            "Please visit https://github.com/settings/tokens to create a token"
            " with the repo scope."
        )
        token = ui.ui_factory.get_password("GitHub personal access token")
        if not token:
            raise errors.CommandError("no token given")
        store_github_token(token=token)
