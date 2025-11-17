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

"""Propose command implementations."""

from io import StringIO

from ... import branch as _mod_branch
from ... import controldir, errors, msgeditor, urlutils
from ... import forge as _mod_forge
from ... import log as _mod_log
from ... import missing as _mod_missing
from ...commands import Command
from ...i18n import gettext
from ...option import ListOption, Option, RegistryOption
from ...trace import note, warning


def branch_name(branch):
    if branch.name:
        return branch.name
    return urlutils.basename(branch.user_url)


def _check_already_merged(branch, target):
    # TODO(jelmer): Check entire ancestry rather than just last revision?
    if branch.last_revision() == target.last_revision():
        raise errors.CommandError(
            gettext("All local changes are already present in target.")
        )


class cmd_publish_derived(Command):
    __doc__ = """Publish a derived branch.

    Try to create a public copy of a local branch on a hosting site,
    derived from the specified base branch.

    Reasonable defaults are picked for owner name, branch name and project
    name, but they can also be overridden from the command-line.
    """

    takes_options = [
        "directory",
        Option("owner", help="Owner of the new remote branch.", type=str),
        Option("project", help="Project name for the new remote branch.", type=str),
        Option("name", help="Name of the new remote branch.", type=str),
        Option("no-allow-lossy", help="Allow fallback to lossy push, if necessary."),
        Option("overwrite", help="Overwrite existing commits."),
        "revision",
    ]
    takes_args = ["submit_branch?"]

    def run(
        self,
        submit_branch=None,
        owner=None,
        name=None,
        project=None,
        no_allow_lossy=False,
        overwrite=False,
        directory=".",
        revision=None,
    ):
        local_branch = _mod_branch.Branch.open_containing(directory)[0]
        self.add_cleanup(local_branch.lock_write().unlock)
        if submit_branch is None:
            submit_branch = local_branch.get_submit_branch()
            note(gettext("Using submit branch %s") % submit_branch)
        if submit_branch is None:
            submit_branch = local_branch.get_parent()
            note(gettext("Using parent branch %s") % submit_branch)
        submit_branch = _mod_branch.Branch.open(submit_branch)
        _check_already_merged(local_branch, submit_branch)
        if name is None:
            name = branch_name(local_branch)
        forge = _mod_forge.get_forge(submit_branch)
        if revision is None:
            stop_revision = None
        else:
            stop_revision = revision.as_revision_id(branch)
        remote_branch, public_url = forge.publish_derived(
            local_branch,
            submit_branch,
            name=name,
            project=project,
            owner=owner,
            allow_lossy=not no_allow_lossy,
            overwrite=overwrite,
            revision_id=stop_revision,
        )
        local_branch.set_push_location(remote_branch.user_url)
        local_branch.set_public_branch(public_url)
        local_branch.set_submit_branch(submit_branch.user_url)
        note(gettext("Pushed to %s") % public_url)


def summarize_unmerged(local_branch, remote_branch, target, prerequisite_branch=None):
    """Generate a text description of the unmerged revisions in branch.

    :param branch: The proposed branch
    :param target: Target branch
    :param prerequisite_branch: Optional prerequisite branch
    :return: A string
    """
    log_format = _mod_log.log_formatter_registry.get_default(local_branch)
    to_file = StringIO()
    lf = log_format(to_file=to_file, show_ids=False, show_timezone="original")
    if prerequisite_branch:
        local_extra = _mod_missing.find_unmerged(
            remote_branch, prerequisite_branch, restrict="local"
        )[0]
    else:
        local_extra = _mod_missing.find_unmerged(
            remote_branch, target, restrict="local"
        )[0]

    if remote_branch.supports_tags():
        rev_tag_dict = remote_branch.tags.get_reverse_tag_dict()
    else:
        rev_tag_dict = {}

    for revision in _mod_missing.iter_log_revisions(
        local_extra, local_branch.repository, False, rev_tag_dict
    ):
        lf.log_revision(revision)
    return to_file.getvalue()


class cmd_propose_merge(Command):
    __doc__ = """Propose a branch for merging.

    This command creates a merge proposal for the local
    branch to the target branch. The format of the merge
    proposal depends on the submit branch.
    """

    takes_options = [
        "directory",
        RegistryOption(
            "forge", help="Use the forge.", lazy_registry=("breezy.forge", "forges")
        ),
        ListOption("reviewers", short_name="R", type=str, help="Requested reviewers."),
        Option("name", help="Name of the new remote branch.", type=str),
        Option("description", help="Description of the change.", type=str),
        Option("prerequisite", help="Prerequisite branch.", type=str),
        Option("wip", help="Mark merge request as work-in-progress"),
        Option("auto", help="Automatically merge when the CI passes"),
        Option(
            "commit-message",
            help="Set commit message for merge, if supported",
            type=str,
        ),
        ListOption("labels", short_name="l", type=str, help="Labels to apply."),
        Option("no-allow-lossy", help="Allow fallback to lossy push, if necessary."),
        Option(
            "allow-collaboration",
            help="Allow collaboration from target branch maintainer(s)",
        ),
        Option("allow-empty", help="Do not prevent empty merge proposals."),
        Option("overwrite", help="Overwrite existing commits."),
        Option("open", help="Open merge proposal in web browser"),
        Option(
            "delete-source-after-merge",
            help="Delete source branch when proposal is merged",
        ),
        "revision",
    ]
    takes_args = ["submit_branch?"]

    aliases = ["propose"]

    def run(
        self,
        submit_branch=None,
        directory=".",
        forge=None,
        reviewers=None,
        name=None,
        no_allow_lossy=False,
        description=None,
        labels=None,
        prerequisite=None,
        commit_message=None,
        wip=False,
        allow_collaboration=False,
        allow_empty=False,
        overwrite=False,
        open=False,
        auto=False,
        delete_source_after_merge=None,
        revision=None,
    ):
        _tree, branch, _relpath = controldir.ControlDir.open_containing_tree_or_branch(
            directory
        )
        if submit_branch is None:
            submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.CommandError(
                gettext("No target location specified or remembered")
            )
        target = _mod_branch.Branch.open(submit_branch)
        if not allow_empty:
            _check_already_merged(branch, target)
        if forge is None:
            forge = _mod_forge.get_forge(target)
        else:
            forge = forge.probe(target)
        if name is None:
            name = branch_name(branch)
        if revision is None:
            stop_revision = None
        else:
            stop_revision = revision.as_revision_id(branch)
        remote_branch, public_branch_url = forge.publish_derived(
            branch,
            target,
            name=name,
            allow_lossy=not no_allow_lossy,
            overwrite=overwrite,
            revision_id=stop_revision,
        )
        branch.set_push_location(remote_branch.user_url)
        branch.set_submit_branch(target.user_url)
        note(
            gettext("Published branch to %s"),
            forge.get_web_url(remote_branch) or public_branch_url,
        )
        if prerequisite is not None:
            prerequisite_branch = _mod_branch.Branch.open(prerequisite)
        else:
            prerequisite_branch = None
        proposal_builder = forge.get_proposer(remote_branch, target)
        if description is None:
            body = proposal_builder.get_initial_body()
            info = proposal_builder.get_infotext()
            info += "\n\n" + summarize_unmerged(
                branch, remote_branch, target, prerequisite_branch
            )
            description = msgeditor.edit_commit_message(info, start_message=body)
        try:
            proposal = proposal_builder.create_proposal(
                description=description,
                reviewers=reviewers,
                prerequisite_branch=prerequisite_branch,
                labels=labels,
                commit_message=commit_message,
                work_in_progress=wip,
                allow_collaboration=allow_collaboration,
                delete_source_after_merge=delete_source_after_merge,
            )
        except _mod_forge.MergeProposalExists as e:
            note(gettext("There is already a branch merge proposal: %s"), e.url)
        else:
            note(gettext("Merge proposal created: %s") % proposal.url)
            if open:
                web_url = proposal.get_web_url()
                import webbrowser

                note(gettext("Opening %s in web browser"), web_url)
                webbrowser.open(web_url)
            if auto:
                proposal.merge(auto=True)


class cmd_find_merge_proposal(Command):
    __doc__ = """Find a merge proposal.

    """

    takes_options = ["directory"]
    takes_args = ["submit_branch?"]
    aliases = ["find-proposal"]

    def run(self, directory=".", submit_branch=None):
        _tree, branch, _relpath = controldir.ControlDir.open_containing_tree_or_branch(
            directory
        )
        public_location = branch.get_public_branch()
        if public_location:
            branch = _mod_branch.Branch.open(public_location)
        if submit_branch is None:
            submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.CommandError(
                gettext("No target location specified or remembered")
            )
        else:
            target = _mod_branch.Branch.open(submit_branch)
        forge = _mod_forge.get_forge(branch)
        for mp in forge.iter_proposals(branch, target):
            self.outf.write(gettext("Merge proposal: %s\n") % mp.url)


class cmd_my_merge_proposals(Command):
    __doc__ = """List all merge proposals owned by the logged-in user.

    """

    hidden = True

    takes_args = ["base_url?"]
    takes_options = [
        "verbose",
        RegistryOption.from_kwargs(
            "status",
            title="Proposal Status",
            help="Only include proposals with specified status.",
            value_switches=True,
            enum_switch=True,
            all="All merge proposals",
            open="Open merge proposals",
            merged="Merged merge proposals",
            closed="Closed merge proposals",
        ),
        RegistryOption(
            "forge", help="Use the forge.", lazy_registry=("breezy.forge", "forges")
        ),
    ]

    def run(self, status="open", verbose=False, forge=None, base_url=None):
        for instance in _mod_forge.iter_forge_instances(forge=forge):
            if base_url is not None and instance.base_url != base_url:
                continue
            try:
                for mp in instance.iter_my_proposals(status=status):
                    self.outf.write("{}\n".format(mp.url))
                    if verbose:
                        source_branch_url = mp.get_source_branch_url()
                        if source_branch_url:
                            self.outf.write(
                                "(Merging {} into {})\n".format(
                                    source_branch_url, mp.get_target_branch_url()
                                )
                            )
                        else:
                            self.outf.write(
                                "(Merging into {})\n".format(mp.get_target_branch_url())
                            )
                        description = mp.get_description()
                        if description:
                            self.outf.writelines(
                                ["\t{}\n".format(l) for l in description.splitlines()]
                            )
                        self.outf.write("\n")
            except _mod_forge.ForgeLoginRequired:
                warning("Skipping %s, login required.", instance)


class cmd_land_merge_proposal(Command):
    __doc__ = """Land a merge proposal."""

    takes_args = ["url"]
    takes_options = [Option("message", help="Commit message to use.", type=str)]

    def run(self, url, message=None):
        proposal = _mod_forge.get_proposal_by_url(url)
        proposal.merge(commit_message=message)


class cmd_web_open(Command):
    __doc__ = """Open a branch page in your web browser."""

    takes_options = [
        Option(
            "dry-run",
            "Do not actually open the browser. Just say the URL we would use.",
        ),
    ]
    takes_args = ["location?"]

    def _possible_locations(self, location):
        """Yield possible external locations for the branch at 'location'."""
        yield location
        try:
            branch = _mod_branch.Branch.open_containing(location)[0]
        except errors.NotBranchError:
            return
        branch_url = branch.get_public_branch()
        if branch_url is not None:
            yield branch_url
        branch_url = branch.get_push_location()
        if branch_url is not None:
            yield branch_url

    def _get_web_url(self, location):
        for branch_url in self._possible_locations(location):
            try:
                branch = _mod_branch.Branch.open_containing(branch_url)[0]
            except errors.NotBranchError as e:
                mutter("Unable to open branch %s: %s", branch_url, e)
                continue

            try:
                forge = _mod_forge.get_forge(branch)
            except _mod_forge.UnsupportedForge:
                continue

            return forge.get_web_url(branch)
        raise errors.CommandError("Unable to get web URL for {}".format(location))

    def run(self, location=None, dry_run=False):
        if location is None:
            location = "."
        web_url = self._get_web_url(location)
        note(gettext("Opening %s in web browser") % web_url)
        if not dry_run:
            import webbrowser

            # otherwise brz.exe lacks this module
            webbrowser.open(web_url)


class cmd_forges(Command):
    __doc__ = """List all known hosting sites and user details."""

    hidden = True

    def run(self):
        for instance in _mod_forge.iter_forge_instances():
            current_user = instance.get_current_user()
            if current_user is not None:
                current_user_url = instance.get_user_url(current_user)
                if current_user_url is not None:
                    self.outf.write(
                        gettext("%s (%s) - user: %s (%s)\n")
                        % (
                            instance.name,
                            instance.base_url,
                            current_user,
                            current_user_url,
                        )
                    )
                else:
                    self.outf.write(
                        gettext("%s (%s) - user: %s\n")
                        % (instance.name, instance.base_url, current_user)
                    )
            else:
                self.outf.write(
                    gettext("%s (%s) - not logged in\n")
                    % (instance.name, instance.base_url)
                )
