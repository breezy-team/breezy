# Copyright (C) 2005-2011 Canonical Ltd
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

# The newly committed revision is going to have a shape corresponding
# to that of the working tree.  Files that are not in the
# working tree and that were in the predecessor are reported as
# removed --- this can include files that were either removed from the
# inventory or deleted in the working tree.  If they were only
# deleted from disk, they are removed from the working inventory.

# We then consider the remaining entries, which will be in the new
# version.  Directory entries are simply copied across.  File entries
# must be checked to see if a new version of the file should be
# recorded.  For each parent revision tree, we check to see what
# version of the file was present.  If the file was present in at
# least one tree, and if it was the same version in all the trees,
# then we can just refer to that version.  Otherwise, a new version
# representing the merger of the file versions must be added.

# TODO: Update hashcache before and after - or does the WorkingTree
# look after that?

# TODO: Rather than mashing together the ancestry and storing it back,
# perhaps the weave should have single method which does it all in one
# go, avoiding a lot of redundant work.

# TODO: Perhaps give a warning if one of the revisions marked as
# merged is already in the ancestry, and then don't record it as a
# distinct parent.

# TODO: If the file is newly merged but unchanged from the version it
# merges from, then it should still be reported as newly added
# relative to the basis revision.

# TODO: Change the parameter 'rev_id' to 'revision_id' to be consistent with
# the rest of the code; add a deprecation of the old name.

from contextlib import ExitStack

import breezy.config

from . import debug, errors, trace, ui
from .branch import Branch
from .errors import BzrError, ConflictsInTree, StrictCommitFailed
from .i18n import gettext
from .osutils import (
    get_user_encoding,
    is_inside_any,
    minimum_path_selection,
)
from .trace import is_quiet, mutter, note
from .urlutils import unescape_for_display


class PointlessCommit(BzrError):
    _fmt = "No changes to commit"


class CannotCommitSelectedFileMerge(BzrError):
    _fmt = "Selected-file commit of merges is not supported yet: files %(files_str)s"

    def __init__(self, files):
        files_str = ", ".join(files)
        BzrError.__init__(self, files=files, files_str=files_str)


def filter_excluded(iter_changes, exclude):
    """Filter exclude filenames.

    :param iter_changes: iter_changes function
    :param exclude: List of paths to exclude
    :return: iter_changes function
    """
    for change in iter_changes:
        new_excluded = change.path[1] is not None and is_inside_any(
            exclude, change.path[1]
        )

        old_excluded = change.path[0] is not None and is_inside_any(
            exclude, change.path[0]
        )

        if old_excluded and new_excluded:
            continue

        if old_excluded or new_excluded:
            # TODO(jelmer): Perhaps raise an error here instead?
            continue

        yield change


class NullCommitReporter:
    """I report on progress of a commit."""

    def started(self, revno, revid, location):
        pass

    def snapshot_change(self, change, path):
        pass

    def completed(self, revno, rev_id):
        pass

    def deleted(self, path):
        pass

    def missing(self, path):
        pass

    def renamed(self, change, old_path, new_path):
        pass

    def is_verbose(self):
        return False


class ReportCommitToLog(NullCommitReporter):
    def _note(self, format, *args):
        """Output a message.

        Subclasses may choose to override this method.
        """
        note(format, *args)

    def snapshot_change(self, change, path):
        if path == "" and change in (gettext("added"), gettext("modified")):
            return
        self._note("%s %s", change, path)

    def started(self, revno, rev_id, location):
        self._note(
            gettext("Committing to: %s"), unescape_for_display(location, "utf-8")
        )

    def completed(self, revno, rev_id):
        if revno is not None:
            self._note(gettext("Committed revision %d."), revno)
            # self._note goes to the console too; so while we want to log the
            # rev_id, we can't trivially only log it. (See bug 526425). Long
            # term we should rearrange the reporting structure, but for now
            # we just mutter seperately. We mutter the revid and revno together
            # so that concurrent bzr invocations won't lead to confusion.
            mutter("Committed revid %s as revno %d.", rev_id, revno)
        else:
            self._note(gettext("Committed revid %s."), rev_id)

    def deleted(self, path):
        self._note(gettext("deleted %s"), path)

    def missing(self, path):
        self._note(gettext("missing %s"), path)

    def renamed(self, change, old_path, new_path):
        self._note("%s %s => %s", change, old_path, new_path)

    def is_verbose(self):
        return True


class Commit:
    """Task of committing a new revision.

    This is a MethodObject: it accumulates state as the commit is
    prepared, and then it is discarded.  It doesn't represent
    historical revisions, just the act of recording a new one.

            missing_ids
            Modified to hold a list of files that have been deleted from
            the working directory; these should be removed from the
            working inventory.
    """

    def __init__(self, reporter=None, config_stack=None):
        """Create a Commit object.

        :param reporter: the default reporter to use or None to decide later
        """
        self.reporter = reporter
        self.config_stack = config_stack

    @staticmethod
    def update_revprops(
        revprops, branch, authors=None, local=False, possible_master_transports=None
    ):
        if revprops is None:
            revprops = {}
        if possible_master_transports is None:
            possible_master_transports = []
        if (
            "branch-nick" not in revprops
            and branch.repository._format.supports_storing_branch_nick
        ):
            revprops["branch-nick"] = branch._get_nick(
                local, possible_master_transports
            )
        if authors is not None:
            if "author" in revprops or "authors" in revprops:
                # XXX: maybe we should just accept one of them?
                raise AssertionError("author property given twice")
            if authors:
                for individual in authors:
                    if "\n" in individual:
                        raise AssertionError(
                            "\\n is not a valid character in an author identity"
                        )
                revprops["authors"] = "\n".join(authors)
        return revprops

    def commit(
        self,
        message=None,
        timestamp=None,
        timezone=None,
        committer=None,
        specific_files=None,
        rev_id=None,
        allow_pointless=True,
        strict=False,
        verbose=False,
        revprops=None,
        working_tree=None,
        local=False,
        reporter=None,
        config=None,
        message_callback=None,
        recursive="down",
        exclude=None,
        possible_master_transports=None,
        lossy=False,
    ):
        """Commit working copy as a new revision.

        :param message: the commit message (it or message_callback is required)
        :param message_callback: A callback: message =
            message_callback(cmt_obj)

        :param timestamp: if not None, seconds-since-epoch for a
            postdated/predated commit.

        :param specific_files: If not None, commit only those files. An empty
            list means 'commit no files'.

        :param rev_id: If set, use this as the new revision id.
            Useful for test or import commands that need to tightly
            control what revisions are assigned.  If you duplicate
            a revision id that exists elsewhere it is your own fault.
            If null (default), a time/random revision id is generated.

        :param allow_pointless: If true (default), commit even if nothing
            has changed and no merges are recorded.

        :param strict: If true, don't allow a commit if the working tree
            contains unknown files.

        :param revprops: Properties for new revision
        :param local: Perform a local only commit.
        :param reporter: the reporter to use or None for the default
        :param verbose: if True and the reporter is not None, report everything
        :param recursive: If set to 'down', commit in any subtrees that have
            pending changes of any sort during this commit.
        :param exclude: None or a list of relative paths to exclude from the
            commit. Pending changes to excluded files will be ignored by the
            commit.
        :param lossy: When committing to a foreign VCS, ignore any
            data that can not be natively represented.
        """
        with ExitStack() as stack:
            self.revprops = revprops or {}
            # XXX: Can be set on __init__ or passed in - this is a bit ugly.
            self.config_stack = config or self.config_stack
            mutter("preparing to commit")

            if working_tree is None:
                raise BzrError("working_tree must be passed into commit().")
            else:
                self.work_tree = working_tree
                self.branch = self.work_tree.branch
                if getattr(self.work_tree, "requires_rich_root", lambda: False)():
                    if not self.branch.repository.supports_rich_root():
                        raise errors.RootNotRich()
            if message_callback is None:
                if message is not None:
                    if isinstance(message, bytes):
                        message = message.decode(get_user_encoding())

                    def message_callback(x):
                        return message
                else:
                    raise BzrError(
                        "The message or message_callback keyword"
                        " parameter is required for commit()."
                    )

            self.bound_branch = None
            self.any_entries_deleted = False
            if exclude is not None:
                self.exclude = sorted(minimum_path_selection(exclude))
            else:
                self.exclude = []
            self.local = local
            self.master_branch = None
            self.recursive = recursive
            self.rev_id = None
            # self.specific_files is None to indicate no filter, or any iterable to
            # indicate a filter - [] means no files at all, as per iter_changes.
            if specific_files is not None:
                self.specific_files = sorted(minimum_path_selection(specific_files))
            else:
                self.specific_files = None

            self.allow_pointless = allow_pointless
            self.message_callback = message_callback
            self.timestamp = timestamp
            self.timezone = timezone
            self.committer = committer
            self.strict = strict
            self.verbose = verbose

            stack.enter_context(self.work_tree.lock_write())
            self.parents = self.work_tree.get_parent_ids()
            self.pb = ui.ui_factory.nested_progress_bar()
            stack.callback(self.pb.finished)
            self.basis_revid = self.work_tree.last_revision()
            self.basis_tree = self.work_tree.basis_tree()
            stack.enter_context(self.basis_tree.lock_read())
            # Cannot commit with conflicts present.
            if len(self.work_tree.conflicts()) > 0:
                raise ConflictsInTree

            # Setup the bound branch variables as needed.
            self._check_bound_branch(stack, possible_master_transports)
            if self.config_stack is None:
                self.config_stack = self.work_tree.get_config_stack()

            # Check that the working tree is up to date
            old_revno, old_revid, new_revno = self._check_out_of_date_tree()

            # Complete configuration setup
            if reporter is not None:
                self.reporter = reporter
            elif self.reporter is None:
                self.reporter = self._select_reporter()

            # Setup the progress bar. As the number of files that need to be
            # committed in unknown, progress is reported as stages.
            # We keep track of entries separately though and include that
            # information in the progress bar during the relevant stages.
            self.pb_stage_name = ""
            self.pb_stage_count = 0
            self.pb_stage_total = 5
            if self.bound_branch:
                # 2 extra stages: "Uploading data to master branch" and "Merging
                # tags to master branch"
                self.pb_stage_total += 2
            self.pb.show_pct = False
            self.pb.show_spinner = False
            self.pb.show_eta = False
            self.pb.show_count = True
            self.pb.show_bar = True

            # After a merge, a selected file commit is not supported.
            # See 'bzr help merge' for an explanation as to why.
            if len(self.parents) > 1 and self.specific_files is not None:
                raise CannotCommitSelectedFileMerge(self.specific_files)
            # Excludes are a form of selected file commit.
            if len(self.parents) > 1 and self.exclude:
                raise CannotCommitSelectedFileMerge(self.exclude)

            # Collect the changes
            self._set_progress_stage("Collecting changes", counter=True)
            self._lossy = lossy
            self.builder = self.branch.get_commit_builder(
                self.parents,
                self.config_stack,
                timestamp,
                timezone,
                committer,
                self.revprops,
                rev_id,
                lossy=lossy,
            )

            if self.builder.updates_branch and self.bound_branch:
                self.builder.abort()
                raise AssertionError(
                    "bound branches not supported for commit builders "
                    "that update the branch"
                )

            try:
                # find the location being committed to
                if self.bound_branch:
                    master_location = self.master_branch.base
                else:
                    master_location = self.branch.base

                # report the start of the commit
                self.reporter.started(new_revno, self.rev_id, master_location)

                self._update_builder_with_changes()
                self._check_pointless()

                # TODO: Now the new inventory is known, check for conflicts.
                # ADHB 2006-08-08: If this is done, populate_new_inv should not add
                # weave lines, because nothing should be recorded until it is known
                # that commit will succeed.
                self._set_progress_stage("Saving data locally")
                self.builder.finish_inventory()

                # Prompt the user for a commit message if none provided
                message = message_callback(self)
                self.message = message

                # Add revision data to the local branch
                self.rev_id = self.builder.commit(self.message)

            except Exception:
                mutter("aborting commit write group because of exception:")
                trace.log_exception_quietly()
                self.builder.abort()
                raise

            self._update_branches(old_revno, old_revid, new_revno)

            # Make the working tree be up to date with the branch. This
            # includes automatic changes scheduled to be made to the tree, such
            # as updating its basis and unversioning paths that were missing.
            self.work_tree.unversion(self.deleted_paths)
            self._set_progress_stage("Updating the working tree")
            self.work_tree.update_basis_by_delta(
                self.rev_id, self.builder.get_basis_delta()
            )
            self.reporter.completed(new_revno, self.rev_id)
            self._process_post_hooks(old_revno, new_revno)
            return self.rev_id

    def _update_branches(self, old_revno, old_revid, new_revno):
        """Update the master and local branch to the new revision.

        This will try to make sure that the master branch is updated
        before the local branch.

        :param old_revno: Revision number of master branch before the
            commit
        :param old_revid: Tip of master branch before the commit
        :param new_revno: Revision number of the new commit
        """
        if not self.builder.updates_branch:
            self._process_pre_hooks(old_revno, new_revno)

            # Upload revision data to the master.
            # this will propagate merged revisions too if needed.
            if self.bound_branch:
                self._set_progress_stage("Uploading data to master branch")
                # 'commit' to the master first so a timeout here causes the
                # local branch to be out of date
                (new_revno, self.rev_id) = (
                    self.master_branch.import_last_revision_info_and_tags(
                        self.branch, new_revno, self.rev_id, lossy=self._lossy
                    )
                )
                if self._lossy:
                    self.branch.fetch(self.master_branch, self.rev_id)

            # and now do the commit locally.
            if new_revno is None:
                # Keep existing behaviour around ghosts
                new_revno = 1
            self.branch.set_last_revision_info(new_revno, self.rev_id)
        else:
            try:
                self._process_pre_hooks(old_revno, new_revno)
            except BaseException:
                # The commit builder will already have updated the branch,
                # revert it.
                self.branch.set_last_revision_info(old_revno, old_revid)
                raise

        # Merge local tags to remote
        if self.bound_branch:
            self._set_progress_stage("Merging tags to master branch")
            tag_updates, tag_conflicts = self.branch.tags.merge_to(
                self.master_branch.tags
            )
            if tag_conflicts:
                warning_lines = ["    " + name for name, _, _ in tag_conflicts]
                note(
                    gettext("Conflicting tags in bound branch:\n%s")
                    % ("\n".join(warning_lines),)
                )

    def _select_reporter(self):
        """Select the CommitReporter to use."""
        if is_quiet():
            return NullCommitReporter()
        return ReportCommitToLog()

    def _check_pointless(self):
        if self.allow_pointless:
            return
        # A merge with no effect on files
        if len(self.parents) > 1:
            return
        if self.builder.any_changes():
            return
        raise PointlessCommit()

    def _check_bound_branch(self, stack, possible_master_transports=None):
        """Check to see if the local branch is bound.

        If it is bound, then most of the commit will actually be
        done using the remote branch as the target branch.
        Only at the end will the local branch be updated.
        """
        if self.local and not self.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        if not self.local:
            self.master_branch = self.branch.get_master_branch(
                possible_master_transports
            )

        if not self.master_branch:
            # make this branch the reference branch for out of date checks.
            self.master_branch = self.branch
            return

        # If the master branch is bound, we must fail
        master_bound_location = self.master_branch.get_bound_location()
        if master_bound_location:
            raise errors.CommitToDoubleBoundBranch(
                self.branch, self.master_branch, master_bound_location
            )

        # TODO: jam 20051230 We could automatically push local
        #       commits to the remote branch if they would fit.
        #       But for now, just require remote to be identical
        #       to local.

        # Make sure the local branch is identical to the master
        master_revid = self.master_branch.last_revision()
        local_revid = self.branch.last_revision()
        if local_revid != master_revid:
            raise errors.BoundBranchOutOfDate(self.branch, self.master_branch)

        # Now things are ready to change the master branch
        # so grab the lock
        self.bound_branch = self.branch
        stack.enter_context(self.master_branch.lock_write())

    def _check_out_of_date_tree(self):
        """Check that the working tree is up to date.

        :return: old_revision_number, old_revision_id, new_revision_number
            tuple
        """
        try:
            first_tree_parent = self.work_tree.get_parent_ids()[0]
        except IndexError:
            # if there are no parents, treat our parent as 'None'
            # this is so that we still consider the master branch
            # - in a checkout scenario the tree may have no
            # parents but the branch may do.
            first_tree_parent = breezy.revision.NULL_REVISION
        if self.master_branch._format.stores_revno() or self.config_stack.get(
            "calculate_revnos"
        ):
            try:
                old_revno, master_last = self.master_branch.last_revision_info()
            except errors.UnsupportedOperation:
                master_last = self.master_branch.last_revision()
                old_revno = self.branch.revision_id_to_revno(master_last)
        else:
            master_last = self.master_branch.last_revision()
            old_revno = None
        if master_last != first_tree_parent:
            if master_last != breezy.revision.NULL_REVISION:
                raise errors.OutOfDateTree(self.work_tree)
        if old_revno is not None and self.branch.repository.has_revision(
            first_tree_parent
        ):
            new_revno = old_revno + 1
        else:
            # ghost parents never appear in revision history.
            new_revno = None
        return old_revno, master_last, new_revno

    def _process_pre_hooks(self, old_revno, new_revno):
        """Process any registered pre commit hooks."""
        self._set_progress_stage("Running pre_commit hooks")
        self._process_hooks("pre_commit", old_revno, new_revno)

    def _process_post_hooks(self, old_revno, new_revno):
        """Process any registered post commit hooks."""
        # Process the post commit hooks, if any
        self._set_progress_stage("Running post_commit hooks")
        # old style commit hooks - should be deprecated ? (obsoleted in
        # 0.15^H^H^H^H 2.5.0)
        post_commit = self.config_stack.get("post_commit")
        if post_commit is not None:
            hooks = post_commit.split(" ")
            # this would be nicer with twisted.python.reflect.namedAny
            for hook in hooks:
                eval(
                    hook + "(branch, rev_id)",
                    {"branch": self.branch, "breezy": breezy, "rev_id": self.rev_id},
                )
        # process new style post commit hooks
        self._process_hooks("post_commit", old_revno, new_revno)

    def _process_hooks(self, hook_name, old_revno, new_revno):
        if not Branch.hooks[hook_name]:
            return

        # new style commit hooks:
        if not self.bound_branch:
            hook_master = self.branch
            hook_local = None
        else:
            hook_master = self.master_branch
            hook_local = self.branch
        # With bound branches, when the master is behind the local branch,
        # the 'old_revno' and old_revid values here are incorrect.
        # XXX: FIXME ^. RBC 20060206
        if self.parents:
            old_revid = self.parents[0]
        else:
            old_revid = breezy.revision.NULL_REVISION

        if hook_name == "pre_commit":
            future_tree = self.builder.revision_tree()
            tree_delta = future_tree.changes_from(self.basis_tree, include_root=True)

        for hook in Branch.hooks[hook_name]:
            # show the running hook in the progress bar. As hooks may
            # end up doing nothing (e.g. because they are not configured by
            # the user) this is still showing progress, not showing overall
            # actions - its up to each plugin to show a UI if it want's to
            # (such as 'Emailing diff to foo@example.com').
            self.pb_stage_name = "Running {} hooks [{}]".format(
                hook_name,
                Branch.hooks.get_hook_name(hook),
            )
            self._emit_progress()
            if "hooks" in debug.debug_flags:
                mutter("Invoking commit hook: %r", hook)
            if hook_name == "post_commit":
                hook(
                    hook_local,
                    hook_master,
                    old_revno,
                    old_revid,
                    new_revno,
                    self.rev_id,
                )
            elif hook_name == "pre_commit":
                hook(
                    hook_local,
                    hook_master,
                    old_revno,
                    old_revid,
                    new_revno,
                    self.rev_id,
                    tree_delta,
                    future_tree,
                )

    def _update_builder_with_changes(self):
        """Update the commit builder with the data about what has changed."""
        specific_files = self.specific_files
        mutter("Selecting files for commit with filter %r", specific_files)

        self._check_strict()
        iter_changes = self.work_tree.iter_changes(
            self.basis_tree, specific_files=specific_files
        )
        if self.exclude:
            iter_changes = filter_excluded(iter_changes, self.exclude)
        iter_changes = self._filter_iter_changes(iter_changes)
        for path, fs_hash in self.builder.record_iter_changes(
            self.work_tree, self.basis_revid, iter_changes
        ):
            self.work_tree._observed_sha1(path, fs_hash)

    def _filter_iter_changes(self, iter_changes):
        """Process iter_changes.

        This method reports on the changes in iter_changes to the user, and
        converts 'missing' entries in the iter_changes iterator to 'deleted'
        entries. 'missing' entries have their

        :param iter_changes: An iter_changes to process.
        :return: A generator of changes.
        """
        reporter = self.reporter
        report_changes = reporter.is_verbose()
        deleted_paths = []
        for change in iter_changes:
            if report_changes:
                old_path = change.path[0]
                new_path = change.path[1]
                versioned = change.versioned[1]
            kind = change.kind[1]
            versioned = change.versioned[1]
            if kind is None and versioned:
                # 'missing' path
                if report_changes:
                    reporter.missing(new_path)
                if (
                    change.kind[0] == "symlink"
                    and not self.work_tree.supports_symlinks()
                ):
                    trace.warning(
                        'Ignoring "{}" as symlinks are not '
                        "supported on this filesystem.".format(change.path[0])
                    )
                    continue
                deleted_paths.append(change.path[1])
                # Reset the new path (None) and new versioned flag (False)
                change = change.discard_new()
                new_path = change.path[1]
                versioned = False
            elif kind == "tree-reference":
                if self.recursive == "down":
                    self._commit_nested_tree(change.path[1])
            if change.versioned[0] or change.versioned[1]:
                yield change
                if report_changes:
                    if new_path is None:
                        reporter.deleted(old_path)
                    elif old_path is None:
                        reporter.snapshot_change(gettext("added"), new_path)
                    elif old_path != new_path:
                        reporter.renamed(gettext("renamed"), old_path, new_path)
                    else:
                        if (
                            new_path
                            or self.work_tree.branch.repository._format.rich_root_data
                        ):
                            # Don't report on changes to '' in non rich root
                            # repositories.
                            reporter.snapshot_change(gettext("modified"), new_path)
            self._next_progress_entry()
        # Unversion files that were found to be deleted
        self.deleted_paths = deleted_paths

    def _check_strict(self):
        # XXX: when we use iter_changes this would likely be faster if
        # iter_changes would check for us (even in the presence of
        # selected_files).
        if self.strict:
            # raise an exception as soon as we find a single unknown.
            for _unknown in self.work_tree.unknowns():
                raise StrictCommitFailed()

    def _commit_nested_tree(self, path):
        """Commit a nested tree."""
        sub_tree = self.work_tree.get_nested_tree(path)
        # FIXME: be more comprehensive here:
        # this works when both trees are in --trees repository,
        # but when both are bound to a different repository,
        # it fails; a better way of approaching this is to
        # finally implement the explicit-caches approach design
        # a while back - RBC 20070306.
        if sub_tree.branch.repository.has_same_location(
            self.work_tree.branch.repository
        ):
            sub_tree.branch.repository = self.work_tree.branch.repository
        try:
            return sub_tree.commit(
                message=None,
                revprops=self.revprops,
                recursive=self.recursive,
                message_callback=self.message_callback,
                timestamp=self.timestamp,
                timezone=self.timezone,
                committer=self.committer,
                allow_pointless=self.allow_pointless,
                strict=self.strict,
                verbose=self.verbose,
                local=self.local,
                reporter=self.reporter,
            )
        except PointlessCommit:
            return self.work_tree.get_reference_revision(path)

    def _set_progress_stage(self, name, counter=False):
        """Set the progress stage and emit an update to the progress bar."""
        self.pb_stage_name = name
        self.pb_stage_count += 1
        if counter:
            self.pb_entries_count = 0
        else:
            self.pb_entries_count = None
        self._emit_progress()

    def _next_progress_entry(self):
        """Emit an update to the progress bar and increment the entry count."""
        self.pb_entries_count += 1
        self._emit_progress()

    def _emit_progress(self):
        if self.pb_entries_count is not None:
            text = gettext("{0} [{1}] - Stage").format(
                self.pb_stage_name, self.pb_entries_count
            )
        else:
            text = gettext("%s - Stage") % (self.pb_stage_name,)
        self.pb.update(text, self.pb_stage_count, self.pb_stage_total)
