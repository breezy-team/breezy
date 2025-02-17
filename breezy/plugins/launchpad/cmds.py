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
        trace.warning("lp-open is deprecated. Please use web-open instead")
        from ..propose.cmds import cmd_web_open

        return cmd_web_open().run(location=location, dry_run=dry_run)


class cmd_launchpad_login(Command):
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
    __doc__ = """Unset the Launchpad user ID.

    When communicating with Launchpad, some commands need to know your
    Launchpad user ID.  This command will log you out from Launchpad.
    This means that communication with Launchpad will happen over
    HTTPS, and will not require one of your SSH keys to be available.
    """
    aliases = ["lp-logout"]
    takes_options = ["verbose"]

    def run(self, verbose=False):
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
