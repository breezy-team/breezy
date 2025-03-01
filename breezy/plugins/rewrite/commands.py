# Copyright (C) 2007 by Jelmer Vernooij <jelmer@samba.org>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Bazaar command-line subcommands."""

from ...commands import Command, display_command
from ...errors import CommandError, ConflictsInTree, NoWorkingTree, UncommittedChanges
from ...i18n import gettext
from ...option import Option
from ...trace import note
from ...transport import NoSuchFile


def finish_rebase(state, wt, replace_map, replayer):
    from .rebase import rebase

    try:
        # Start executing plan from current Branch.last_revision()
        rebase(wt.branch.repository, replace_map, replayer)
    except ConflictsInTree:
        raise CommandError(
            gettext(
                "A conflict occurred replaying a commit."
                " Resolve the conflict and run 'brz rebase-continue' or "
                "run 'brz rebase-abort'."
            )
        )
    # Remove plan file
    state.remove_plan()


class cmd_rebase(Command):
    """Re-base a branch.

    Rebasing is the process of taking a branch and modifying the history so
    that it appears to start from a different point. This can be useful
    to clean up the history before submitting your changes. The tree at the
    end of the process will be the same as if you had merged the other branch,
    but the history will be different.

    The command takes the location of another branch on to which the branch in
    the specified directory (by default, the current working directory)
    will be rebased. If a branch is not specified then the parent branch
    is used, and this is usually the desired result.

    The first step identifies the revisions that are in the current branch that
    are not in the parent branch. The current branch is then set to be at the
    same revision as the target branch, and each revision is replayed on top
    of the branch. At the end of the process it will appear as though your
    current branch was branched off the current last revision of the target.

    Each revision that is replayed may cause conflicts in the tree. If this
    happens the command will stop and allow you to fix them up. Resolve the
    commits as you would for a merge, and then run 'brz resolve' to marked
    them as resolved. Once you have resolved all the conflicts you should
    run 'brz rebase-continue' to continue the rebase operation.

    If conflicts are encountered and you decide that you do not wish to continue
    you can run 'brz rebase-abort'.

    The '--onto' option allows you to specify a different revision in the
    target branch to start at when replaying the revisions. This means that
    you can change the point at which the current branch will appear to be
    branched from when the operation completes.
    """

    takes_args = ["upstream_location?"]
    takes_options = [
        "revision",
        "merge-type",
        "verbose",
        Option(
            "dry-run", help="Show what would be done, but don't actually do anything."
        ),
        Option(
            "always-rebase-merges",
            help="Don't skip revisions that merge already present revisions.",
        ),
        Option("pending-merges", help="Rebase pending merges onto local branch."),
        Option("onto", help="Different revision to replay onto.", type=str),
        Option(
            "directory",
            short_name="d",
            help="Branch to replay onto, rather than the one containing the working directory.",
            type=str,
        ),
    ]

    @display_command
    def run(
        self,
        upstream_location=None,
        onto=None,
        revision=None,
        merge_type=None,
        verbose=False,
        dry_run=False,
        always_rebase_merges=False,
        pending_merges=False,
        directory=".",
    ):
        from ...branch import Branch
        from ...revisionspec import RevisionSpec
        from ...workingtree import WorkingTree
        from .rebase import (
            RebaseState1,
            WorkingTreeRevisionRewriter,
            generate_simple_plan,
            rebase_todo,
            regenerate_default_revid,
        )

        if revision is not None and pending_merges:
            raise CommandError(
                gettext("--revision and --pending-merges are mutually exclusive")
            )

        wt = WorkingTree.open_containing(directory)[0]
        wt.lock_write()
        try:
            state = RebaseState1(wt)
            if upstream_location is None:
                if pending_merges:
                    upstream_location = directory
                else:
                    upstream_location = wt.branch.get_parent()
                    if upstream_location is None:
                        raise CommandError(gettext("No upstream branch specified."))
                    note(gettext("Rebasing on %s"), upstream_location)
            upstream = Branch.open_containing(upstream_location)[0]
            upstream_repository = upstream.repository
            upstream_revision = upstream.last_revision()
            # Abort if there already is a plan file
            if state.has_plan():
                raise CommandError(
                    gettext(
                        "A rebase operation was interrupted. "
                        "Continue using 'brz rebase-continue' or abort using 'brz "
                        "rebase-abort'"
                    )
                )

            start_revid = None
            stop_revid = None
            if revision is not None:
                if len(revision) == 1:
                    if revision[0] is not None:
                        stop_revid = revision[0].as_revision_id(wt.branch)
                elif len(revision) == 2:
                    if revision[0] is not None:
                        start_revid = revision[0].as_revision_id(wt.branch)
                    if revision[1] is not None:
                        stop_revid = revision[1].as_revision_id(wt.branch)
                else:
                    raise CommandError(
                        gettext("--revision takes only one or two arguments")
                    )

            if pending_merges:
                wt_parents = wt.get_parent_ids()
                if len(wt_parents) in (0, 1):
                    raise CommandError(gettext("No pending merges present."))
                elif len(wt_parents) > 2:
                    raise CommandError(
                        gettext("Rebasing more than one pending merge not supported")
                    )
                stop_revid = wt_parents[1]
                assert stop_revid is not None, "stop revid invalid"

            # Check for changes in the working tree.
            if not pending_merges and wt.basis_tree().changes_from(wt).has_changed():
                raise UncommittedChanges(wt)

            # Pull required revisions
            wt.branch.repository.fetch(upstream_repository, upstream_revision)
            if onto is None:
                onto = upstream.last_revision()
            else:
                rev_spec = RevisionSpec.from_string(onto)
                onto = rev_spec.as_revision_id(upstream)

            wt.branch.repository.fetch(upstream_repository, revision_id=onto)

            if stop_revid is None:
                stop_revid = wt.branch.last_revision()
            repo_graph = wt.branch.repository.get_graph()
            our_new, onto_unique = repo_graph.find_difference(stop_revid, onto)

            if start_revid is None:
                if not onto_unique:
                    self.outf.write(gettext("No revisions to rebase.\n"))
                    return
                if not our_new:
                    self.outf.write(
                        gettext(
                            "Base branch is descendant of current "
                            "branch. Pulling instead.\n"
                        )
                    )
                    if not dry_run:
                        wt.pull(upstream, stop_revision=onto)
                    return
            # else: include extra revisions needed to make start_revid mean
            # something.

            # Create plan
            replace_map = generate_simple_plan(
                our_new,
                start_revid,
                stop_revid,
                onto,
                repo_graph,
                lambda revid, ps: regenerate_default_revid(wt.branch.repository, revid),
                not always_rebase_merges,
            )

            if verbose or dry_run:
                todo = list(rebase_todo(wt.branch.repository, replace_map))
                note(gettext("%d revisions will be rebased:") % len(todo))
                for revid in todo:
                    note("{}".format(revid))

            if not dry_run:
                # Write plan file
                state.write_plan(replace_map)

                replayer = WorkingTreeRevisionRewriter(wt, state, merge_type=merge_type)

                finish_rebase(state, wt, replace_map, replayer)
        finally:
            wt.unlock()


class cmd_rebase_abort(Command):
    """Abort an interrupted rebase."""

    takes_options = [
        Option(
            "directory",
            short_name="d",
            help="Branch to replay onto, rather than the one containing the working directory.",
            type=str,
        )
    ]

    @display_command
    def run(self, directory="."):
        from ...workingtree import WorkingTree
        from .rebase import RebaseState1, complete_revert

        wt = WorkingTree.open_containing(directory)[0]
        wt.lock_write()
        try:
            state = RebaseState1(wt)
            # Read plan file and set last revision
            try:
                last_rev_info = state.read_plan()[0]
            except NoSuchFile:
                raise CommandError("No rebase to abort")
            complete_revert(wt, [last_rev_info[1]])
            state.remove_plan()
        finally:
            wt.unlock()


class cmd_rebase_continue(Command):
    """Continue an interrupted rebase after resolving conflicts."""

    takes_options = [
        "merge-type",
        Option(
            "directory",
            short_name="d",
            help="Branch to replay onto, rather than the one containing the working directory.",
            type=str,
        ),
    ]

    @display_command
    def run(self, merge_type=None, directory="."):
        from ...workingtree import WorkingTree
        from .rebase import RebaseState1, WorkingTreeRevisionRewriter

        wt = WorkingTree.open_containing(directory)[0]
        wt.lock_write()
        try:
            state = RebaseState1(wt)
            replayer = WorkingTreeRevisionRewriter(wt, state, merge_type=merge_type)
            # Abort if there are any conflicts
            if len(wt.conflicts()) != 0:
                raise CommandError(
                    gettext(
                        "There are still conflicts present. "
                        "Resolve the conflicts and then run "
                        "'brz resolve' and try again."
                    )
                )
            # Read plan file
            try:
                replace_map = state.read_plan()[1]
            except NoSuchFile:
                raise CommandError(gettext("No rebase to continue"))
            oldrevid = state.read_active_revid()
            if oldrevid is not None:
                oldrev = wt.branch.repository.get_revision(oldrevid)
                replayer.commit_rebase(oldrev, replace_map[oldrevid][0])
            finish_rebase(state, wt, replace_map, replayer)
        finally:
            wt.unlock()


class cmd_rebase_todo(Command):
    """Print list of revisions that still need to be replayed as part of the
    current rebase operation.

    """

    takes_options = [
        Option(
            "directory",
            short_name="d",
            help="Branch to replay onto, rather than the one containing the working directory.",
            type=str,
        )
    ]

    def run(self, directory="."):
        from ...workingtree import WorkingTree
        from .rebase import RebaseState1, rebase_todo

        wt = WorkingTree.open_containing(directory)[0]
        with wt.lock_read():
            state = RebaseState1(wt)
            try:
                replace_map = state.read_plan()[1]
            except NoSuchFile:
                raise CommandError(gettext("No rebase in progress"))
            currentrevid = state.read_active_revid()
            if currentrevid is not None:
                note(gettext("Currently replaying: %s") % currentrevid)
            for revid in rebase_todo(wt.branch.repository, replace_map):
                note(gettext("{0} -> {1}").format(revid, replace_map[revid][0]))


class cmd_replay(Command):
    """Replay commits from another branch on top of this one."""

    takes_options = [
        "revision",
        "merge-type",
        Option(
            "directory",
            short_name="d",
            help="Branch to replay onto, rather than the one containing the working directory.",
            type=str,
        ),
    ]
    takes_args = ["location"]
    hidden = True

    def run(self, location, revision=None, merge_type=None, directory="."):
        from ... import ui
        from ...branch import Branch
        from ...workingtree import WorkingTree
        from .rebase import (
            RebaseState1,
            WorkingTreeRevisionRewriter,
            regenerate_default_revid,
        )

        from_branch = Branch.open_containing(location)[0]

        if revision is not None:
            if len(revision) == 1:
                if revision[0] is not None:
                    todo = [revision[0].as_revision_id(from_branch)]
            elif len(revision) == 2:
                from_revno, from_revid = revision[0].in_history(from_branch)
                to_revno, to_revid = revision[1].in_history(from_branch)
                if to_revid is None:
                    to_revno = from_branch.revno()
                todo = []
                for revno in range(from_revno, to_revno + 1):
                    todo.append(from_branch.get_rev_id(revno))
            else:
                raise CommandError(
                    gettext("--revision takes only one or two arguments")
                )
        else:
            raise CommandError(gettext("--revision is mandatory"))

        wt = WorkingTree.open(directory)
        wt.lock_write()
        try:
            state = RebaseState1(wt)
            replayer = WorkingTreeRevisionRewriter(wt, state, merge_type=merge_type)
            pb = ui.ui_factory.nested_progress_bar()
            try:
                for revid in todo:
                    pb.update(
                        gettext("replaying commits"), todo.index(revid), len(todo)
                    )
                    wt.branch.repository.fetch(from_branch.repository, revid)
                    newrevid = regenerate_default_revid(wt.branch.repository, revid)
                    replayer(revid, newrevid, [wt.last_revision()])
            finally:
                pb.finished()
        finally:
            wt.unlock()


class cmd_pseudonyms(Command):
    """Show a list of 'pseudonym' revisions.

    Pseudonym revisions are revisions that are roughly the same revision,
    usually because they were converted from the same revision in a
    foreign version control system.
    """

    takes_args = ["repository?"]
    hidden = True

    def run(self, repository=None):
        from ...controldir import ControlDir

        dir, _ = ControlDir.open_containing(repository)
        r = dir.find_repository()
        from .pseudonyms import find_pseudonyms

        for pseudonyms in find_pseudonyms(r, r.all_revision_ids()):
            self.outf.write(", ".join(pseudonyms) + "\n")


class cmd_rebase_foreign(Command):
    """Rebase revisions based on a branch created with a different import tool.

    This will change the identity of revisions whose parents
    were mapped from revisions in the other version control system.

    You are recommended to run "brz check" in the local repository
    after running this command.
    """

    takes_args = ["new_base?"]
    takes_options = [
        "verbose",
        Option("idmap-file", help="Write map with old and new revision ids.", type=str),
        Option(
            "directory",
            short_name="d",
            help="Branch to replay onto, rather than the one containing the working directory.",
            type=str,
        ),
    ]

    def run(self, new_base=None, verbose=False, idmap_file=None, directory="."):
        from ... import urlutils
        from ...branch import Branch
        from ...foreign import update_workingtree_fileids
        from ...workingtree import WorkingTree
        from .pseudonyms import (
            find_pseudonyms,
            generate_rebase_map_from_pseudonyms,
            pseudonyms_as_dict,
        )
        from .upgrade import create_deterministic_revid, upgrade_branch

        try:
            wt_to = WorkingTree.open(directory)
            branch_to = wt_to.branch
        except NoWorkingTree:
            wt_to = None
            branch_to = Branch.open(directory)

        stored_loc = branch_to.get_parent()
        if new_base is None:
            if stored_loc is None:
                raise CommandError(gettext("No pull location known or specified."))
            else:
                display_url = urlutils.unescape_for_display(
                    stored_loc, self.outf.encoding
                )
                self.outf.write(gettext("Using saved location: %s\n") % display_url)
                new_base = Branch.open(stored_loc)
        else:
            new_base = Branch.open(new_base)

        branch_to.repository.fetch(
            new_base.repository, revision_id=branch_to.last_revision()
        )

        pseudonyms = pseudonyms_as_dict(
            find_pseudonyms(
                branch_to.repository, branch_to.repository.all_revision_ids()
            )
        )

        def generate_rebase_map(revision_id):
            return generate_rebase_map_from_pseudonyms(
                pseudonyms,
                branch_to.repository.get_ancestry(revision_id),
                branch_to.repository.get_ancestry(new_base.last_revision()),
            )

        def determine_new_revid(old_revid, new_parents):
            return create_deterministic_revid(old_revid, new_parents)

        branch_to.lock_write()
        try:
            branch_to.repository.get_graph()
            renames = upgrade_branch(
                branch_to,
                generate_rebase_map,
                determine_new_revid,
                allow_changes=True,
                verbose=verbose,
            )
            if wt_to is not None:
                basis_tree = wt_to.basis_tree()
                basis_tree.lock_read()
                try:
                    update_workingtree_fileids(wt_to, basis_tree)
                finally:
                    basis_tree.unlock()
        finally:
            branch_to.unlock()

        if renames == {}:
            note(gettext("Nothing to do."))

        if idmap_file is not None:
            f = open(idmap_file, "w")
            try:
                for oldid, newid in renames.iteritems():
                    f.write("{}\t{}\n".format(oldid, newid))
            finally:
                f.close()

        if wt_to is not None:
            wt_to.set_last_revision(branch_to.last_revision())
