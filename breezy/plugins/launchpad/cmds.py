# Copyright (C) 2006-2017 Canonical Ltd
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

"""Launchpad plugin commands."""

from ... import branch as _mod_branch
from ... import trace
from ...commands import Command
from ...errors import CommandError
from ...i18n import gettext
from ...option import Option


class cmd_launchpad_open(Command):
    """Command to open a Launchpad branch page in your web browser.

    This command is deprecated in favor of the more general 'web-open' command.
    It provides backward compatibility for users who still use the 'lp-open' alias.
    """

    __doc__ = """Open a Launchpad branch page in your web browser."""

    aliases = ["lp-open"]
    takes_options = [
        Option(
            "dry-run",
            "Do not actually open the browser. Just say the URL we would use.",
        ),
    ]
    takes_args = ["location?"]

    def run(self, location=None, dry_run=False):
        """Execute the launchpad-open command.

        Args:
            location: Optional location to open. If not provided, uses current directory.
            dry_run: If True, only shows the URL without opening the browser.

        Returns:
            The result from cmd_web_open().run().
        """
        trace.warning("lp-open is deprecated. Please use web-open instead")
        from ..propose.cmds import cmd_web_open

        return cmd_web_open().run(location=location, dry_run=dry_run)


class cmd_launchpad_login(Command):
    """Command to show or set the Launchpad user ID for authentication.

    This command manages the Launchpad user credentials used by Breezy
    for operations that require authentication with Launchpad services.
    It can display the current user ID or set a new one, with optional
    validation to ensure the user exists and has SSH keys configured.
    """

    __doc__ = """Show or set the Launchpad user ID.

    When communicating with Launchpad, some commands need to know your
    Launchpad user ID.  This command can be used to set or show the
    user ID that Bazaar will use for such communication.

    :Examples:
      Show the Launchpad ID of the current user::

          brz launchpad-login

      Set the Launchpad ID of the current user to 'bob'::

          brz launchpad-login bob
    """
    aliases = ["lp-login"]
    takes_args = ["name?"]
    takes_options = [
        "verbose",
        Option("no-check", "Don't check that the user name is valid."),
        Option("service-root", type=str, help="Launchpad service root to connect to"),
    ]

    def run(self, name=None, no_check=False, verbose=False, service_root="production"):
        """Execute the launchpad-login command.

        Args:
            name: Optional username to set. If None, displays current username.
            no_check: If True, skips validation of the username.
            verbose: If True, provides additional output.
            service_root: Launchpad service root to connect to.

        Returns:
            int: 1 if no username is configured and none provided, 0 otherwise.
        """
        # This is totally separate from any launchpadlib login system.
        from . import account

        check_account = not no_check

        if name is None:
            username = account.get_lp_login()
            if username:
                if check_account:
                    account.check_lp_login(username)
                    if verbose:
                        self.outf.write(
                            gettext("Launchpad user ID exists and has SSH keys.\n")
                        )
                self.outf.write(username + "\n")
            else:
                self.outf.write(gettext("No Launchpad user ID configured.\n"))
                return 1
        else:
            name = name.lower()
            if check_account:
                account.check_lp_login(name)
                if verbose:
                    self.outf.write(
                        gettext("Launchpad user ID exists and has SSH keys.\n")
                    )
            account.set_lp_login(name)
            if verbose:
                self.outf.write(gettext("Launchpad user ID set to '%s'.\n") % (name,))
        if check_account:
            from .lp_api import connect_launchpad
            from .uris import lookup_service_root

            connect_launchpad(lookup_service_root(service_root))


class cmd_launchpad_logout(Command):
    """Command to unset the Launchpad user ID and log out.

    This command clears the stored Launchpad user credentials, effectively
    logging the user out from Launchpad services. After logout, communication
    with Launchpad will use HTTPS without SSH key authentication.
    """

    __doc__ = """Unset the Launchpad user ID.

    When communicating with Launchpad, some commands need to know your
    Launchpad user ID.  This command will log you out from Launchpad.
    This means that communication with Launchpad will happen over
    HTTPS, and will not require one of your SSH keys to be available.
    """
    aliases = ["lp-logout"]
    takes_options = ["verbose"]

    def run(self, verbose=False):
        """Execute the launchpad-logout command.

        Args:
            verbose: If True, provides additional output about the logout.

        Returns:
            int: 1 if not logged in, 0 if successfully logged out.
        """
        from . import account

        old_username = account.get_lp_login()
        if old_username is None:
            self.outf.write(gettext("Not logged into Launchpad.\n"))
            return 1
        account.set_lp_login(None)
        if verbose:
            self.outf.write(
                gettext("Launchpad user ID %s logged out.\n") % old_username
            )


class cmd_lp_find_proposal(Command):
    """Command to find and open merge proposals for a specific revision.

    This command searches for merge proposals in Launchpad that are associated
    with a given revision and opens them in a web browser. It uses the
    Launchpad API to find proposals where the specified revision was merged.
    """

    __doc__ = """Find the proposal to merge this revision.

    Finds the merge proposal(s) that discussed landing the specified revision.
    This works only if the if the merged_revno was recorded for the merge
    proposal.  The proposal(s) are opened in a web browser.

    Only the revision specified is searched for.  To find the mainline
    revision that merged it into mainline, use the "mainline" revision spec.

    So, to find the merge proposal that reviewed line 1 of README::

      brz lp-find-proposal -r mainline:annotate:README:1
    """

    takes_options = ["revision"]

    def run(self, revision=None):
        """Execute the lp-find-proposal command.

        Args:
            revision: Optional revision specification. If None, uses the
                last revision of the current branch.

        Raises:
            CommandError: If no merge proposals are found for the revision.
        """
        import webbrowser

        from ... import ui
        from . import uris

        b = _mod_branch.Branch.open_containing(".")[0]
        with ui.ui_factory.nested_progress_bar() as pb, b.lock_read():
            if revision is None:
                revision_id = b.last_revision()
            else:
                revision_id = revision[0].as_revision_id(b)
            merged = self._find_proposals(revision_id, pb)
            if len(merged) == 0:
                raise CommandError(gettext("No review found."))
            trace.note(gettext("%d proposals(s) found.") % len(merged))
            for mp in merged:
                webbrowser.open(uris.canonical_url(mp))

    def _find_proposals(self, revision_id, pb):
        """Find merge proposals for a given revision ID.

        Args:
            revision_id: The revision ID to search for.
            pb: Progress bar for user feedback.

        Returns:
            list: List of merge proposal objects from Launchpad.
        """
        from . import lp_api, uris

        # "devel" because branches.getMergeProposals is not part of 1.0 API.
        lp_base_url = uris.LPNET_SERVICE_ROOT
        launchpad = lp_api.connect_launchpad(lp_base_url, version="devel")
        pb.update(gettext("Finding proposals"))
        return list(
            launchpad.branches.getMergeProposals(
                merged_revision=revision_id.decode("utf-8")
            )
        )
