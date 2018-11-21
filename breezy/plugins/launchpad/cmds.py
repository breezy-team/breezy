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

from __future__ import absolute_import

from ... import (
    branch as _mod_branch,
    controldir,
    trace,
    )
from ...commands import (
    Command,
    )
from ...errors import (
    BzrCommandError,
    NotBranchError,
    )
from ...i18n import gettext
from ...option import (
    Option,
    ListOption,
    )
from ...sixish import (
    text_type,
    )


class cmd_launchpad_open(Command):
    __doc__ = """Open a Launchpad branch page in your web browser."""

    aliases = ['lp-open']
    takes_options = [
        Option('dry-run',
               'Do not actually open the browser. Just say the URL we would '
               'use.'),
        ]
    takes_args = ['location?']

    def _possible_locations(self, location):
        """Yield possible external locations for the branch at 'location'."""
        yield location
        try:
            branch = _mod_branch.Branch.open_containing(location)[0]
        except NotBranchError:
            return
        branch_url = branch.get_public_branch()
        if branch_url is not None:
            yield branch_url
        branch_url = branch.get_push_location()
        if branch_url is not None:
            yield branch_url

    def _get_web_url(self, service, location):
        from .lp_registration import (
            InvalidURL,
            NotLaunchpadBranch)
        for branch_url in self._possible_locations(location):
            try:
                return service.get_web_url_from_branch_url(branch_url)
            except (NotLaunchpadBranch, InvalidURL):
                pass
        raise NotLaunchpadBranch(branch_url)

    def run(self, location=None, dry_run=False):
        from .lp_registration import (
            LaunchpadService)
        if location is None:
            location = u'.'
        web_url = self._get_web_url(LaunchpadService(), location)
        trace.note(gettext('Opening %s in web browser') % web_url)
        if not dry_run:
            import webbrowser   # this import should not be lazy
            # otherwise brz.exe lacks this module
            webbrowser.open(web_url)


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
    aliases = ['lp-login']
    takes_args = ['name?']
    takes_options = [
        'verbose',
        Option('no-check',
               "Don't check that the user name is valid."),
        ]

    def run(self, name=None, no_check=False, verbose=False):
        # This is totally separate from any launchpadlib login system.
        from . import account
        check_account = not no_check

        if name is None:
            username = account.get_lp_login()
            if username:
                if check_account:
                    account.check_lp_login(username)
                    if verbose:
                        self.outf.write(gettext(
                            "Launchpad user ID exists and has SSH keys.\n"))
                self.outf.write(username + '\n')
            else:
                self.outf.write(gettext('No Launchpad user ID configured.\n'))
                return 1
        else:
            name = name.lower()
            if check_account:
                account.check_lp_login(name)
                if verbose:
                    self.outf.write(gettext(
                        "Launchpad user ID exists and has SSH keys.\n"))
            account.set_lp_login(name)
            if verbose:
                self.outf.write(gettext("Launchpad user ID set to '%s'.\n") %
                                (name,))


class cmd_launchpad_logout(Command):
    __doc__ = """Unset the Launchpad user ID.

    When communicating with Launchpad, some commands need to know your
    Launchpad user ID.  This command will log you out from Launchpad.
    This means that communication with Launchpad will happen over
    HTTPS, and will not require one of your SSH keys to be available.
    """
    aliases = ['lp-logout']
    takes_options = ['verbose']

    def run(self, verbose=False):
        from . import account
        old_username = account.get_lp_login()
        if old_username is None:
            self.outf.write(gettext('Not logged into Launchpad.\n'))
            return 1
        account.set_lp_login(None)
        if verbose:
            self.outf.write(gettext(
                "Launchpad user ID %s logged out.\n") %
                old_username)


# XXX: cmd_launchpad_mirror is untested
class cmd_launchpad_mirror(Command):
    __doc__ = """Ask Launchpad to mirror a branch now."""

    aliases = ['lp-mirror']
    takes_args = ['location?']

    def run(self, location='.'):
        from . import lp_api
        from .lp_registration import LaunchpadService
        branch, _ = _mod_branch.Branch.open_containing(location)
        service = LaunchpadService()
        launchpad = lp_api.login(service)
        lp_branch = lp_api.LaunchpadBranch.from_bzr(launchpad, branch,
                                                    create_missing=False)
        lp_branch.lp.requestMirror()


class cmd_lp_propose_merge(Command):
    __doc__ = """Propose merging a branch on Launchpad.

    This will open your usual editor to provide the initial comment.  When it
    has created the proposal, it will open it in your default web browser.

    The branch will be proposed to merge into SUBMIT_BRANCH.  If SUBMIT_BRANCH
    is not supplied, the remembered submit branch will be used.  If no submit
    branch is remembered, the development focus will be used.

    By default, the SUBMIT_BRANCH's review team will be requested to review
    the merge proposal.  This can be overriden by specifying --review (-R).
    The parameter the launchpad account name of the desired reviewer.  This
    may optionally be followed by '=' and the review type.  For example:

      brz lp-propose-merge --review jrandom --review review-team=qa

    This will propose a merge,  request "jrandom" to perform a review of
    unspecified type, and request "review-team" to perform a "qa" review.
    """

    takes_options = [Option('staging',
                            help='Propose the merge on staging.'),
                     Option('message', short_name='m', type=text_type,
                            help='Commit message.'),
                     Option('approve',
                            help=('Mark the proposal as approved immediately, '
                                  'setting the approved revision to tip.')),
                     Option('fixes', 'The bug this proposal fixes.', str),
                     ListOption('review', short_name='R', type=text_type,
                                help='Requested reviewer and optional type.')]

    takes_args = ['submit_branch?']

    aliases = ['lp-submit', 'lp-propose']

    def run(self, submit_branch=None, review=None, staging=False,
            message=None, approve=False, fixes=None):
        from . import lp_propose
        tree, branch, relpath = controldir.ControlDir.open_containing_tree_or_branch(
            '.')
        if review is None:
            reviews = None
        else:
            reviews = []
            for review in review:
                if '=' in review:
                    reviews.append(review.split('=', 2))
                else:
                    reviews.append((review, ''))
            if submit_branch is None:
                submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            target = None
        else:
            target = _mod_branch.Branch.open(submit_branch)
        proposer = lp_propose.Proposer(tree, branch, target, message,
                                       reviews, staging, approve=approve,
                                       fixes=fixes)
        proposer.check_proposal()
        proposer.create_proposal()


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

    takes_options = ['revision']

    def run(self, revision=None):
        from ... import ui
        from . import lp_api
        import webbrowser
        b = _mod_branch.Branch.open_containing('.')[0]
        with ui.ui_factory.nested_progress_bar() as pb, b.lock_read():
            if revision is None:
                revision_id = b.last_revision()
            else:
                revision_id = revision[0].as_revision_id(b)
            merged = self._find_proposals(revision_id, pb)
            if len(merged) == 0:
                raise BzrCommandError(gettext('No review found.'))
            trace.note(gettext('%d proposals(s) found.') % len(merged))
            for mp in merged:
                webbrowser.open(lp_api.canonical_url(mp))

    def _find_proposals(self, revision_id, pb):
        from . import (lp_api, lp_registration)
        # "devel" because branches.getMergeProposals is not part of 1.0 API.
        launchpad = lp_api.login(lp_registration.LaunchpadService(),
                                 version='devel')
        pb.update(gettext('Finding proposals'))
        return list(launchpad.branches.getMergeProposals(
                    merged_revision=revision_id))
