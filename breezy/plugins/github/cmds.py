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
    """Log into GitHub.

    When communicating with GitHub, some commands need to authenticate to
    GitHub.
    """

    __doc__ = """Log into GitHub.

    When communicating with GitHub, some commands need to authenticate to
    GitHub.
    """

    takes_args = ["username?"]

    def run(self, username=None):
        """Execute the github-login command.

        Args:
            username: Optional GitHub username to log in with.

        Raises:
            CommandError: If authentication fails or token already exists.
        """
        from github import Github, GithubException

        from ...config import AuthenticationConfig

        authconfig = AuthenticationConfig()
        if username is None:
            username = authconfig.get_user(
                "https", "github.com", prompt="GitHub username", ask=True
            )
        password = authconfig.get_password("https", "github.com", username)
        client = Github(username, password)
        user = client.get_user()
        try:
            authorization = user.create_authorization(
                scopes=["user", "repo", "delete_repo"],
                note="Breezy",
                note_url="https://github.com/breezy-team/breezy",
            )
        except GithubException as e:
            errs = e.data.get("errors", [])
            if errs:
                err_code = errs[0].get("code")
                if err_code == "already_exists":
                    raise errors.CommandError("token already exists") from e
            raise errors.CommandError(e.data["message"]) from e
        from .forge import store_github_token

        store_github_token(token=authorization.token)
