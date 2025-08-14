# Copyright (C) 2005-2012 Canonical Ltd
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

"""builtin brz commands."""

import os
import sys

import breezy.bzr
import breezy.git

from . import controldir, errors, lazy_import, osutils, transport

lazy_import.lazy_import(
    globals(),
    """
import time

import breezy
from breezy import (
    branch as _mod_branch,
    bugtracker,
    delta,
    config as _mod_config,
    gpg,
    hooks,
    log,
    merge as _mod_merge,
    patch,
    revision as _mod_revision,
    symbol_versioning,
    tree as _mod_tree,
    ui,
    urlutils,
    )
from breezy.branch import Branch
from breezy.i18n import gettext, ngettext
""",
)

import contextlib

from .commands import Command, builtin_command_registry, display_command
from .option import ListOption, Option, RegistryOption, _parse_revision_str, custom_help
from .revisionspec import RevisionInfo, RevisionSpec
from .trace import get_verbosity_level, is_quiet, mutter, note, warning


def _get_branch_location(control_dir, possible_transports=None):
    """Return location of branch for this control dir."""
    try:
        target = control_dir.get_branch_reference()
    except errors.NotBranchError:
        return control_dir.root_transport.base
    if target is not None:
        return target
    this_branch = control_dir.open_branch(possible_transports=possible_transports)
    # This may be a heavy checkout, where we want the master branch
    master_location = this_branch.get_bound_location()
    if master_location is not None:
        return master_location
    # If not, use a local sibling
    return this_branch.base


def _is_colocated(control_dir, possible_transports=None):
    """Check if the branch in control_dir is colocated.

    :param control_dir: Control directory
    :return: Tuple with boolean indicating whether the branch is colocated
        and the full URL to the actual branch
    """
    # This path is meant to be relative to the existing branch
    this_url = _get_branch_location(
        control_dir, possible_transports=possible_transports
    )
    # Perhaps the target control dir supports colocated branches?
    try:
        root = controldir.ControlDir.open(
            this_url, possible_transports=possible_transports
        )
    except errors.NotBranchError:
        return (False, this_url)
    else:
        try:
            control_dir.open_workingtree()
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            return (False, this_url)
        else:
            return (
                root._format.colocated_branches
                and control_dir.control_url == root.control_url,
                this_url,
            )


def lookup_new_sibling_branch(control_dir, location, possible_transports=None):
    """Lookup the location for a new sibling branch.

    :param control_dir: Control directory to find sibling branches from
    :param location: Name of the new branch
    :return: Full location to the new branch
    """
    from .directory_service import directories

    location = directories.dereference(location)
    if "/" not in location and "\\" not in location:
        (colocated, this_url) = _is_colocated(control_dir, possible_transports)

        if colocated:
            return urlutils.join_segment_parameters(
                this_url, {"branch": urlutils.escape(location)}
            )
        else:
            return urlutils.join(this_url, "..", urlutils.escape(location))
    return location


def open_sibling_branch(control_dir, location, possible_transports=None):
    """Open a branch, possibly a sibling of another.

    :param control_dir: Control directory relative to which to lookup the
        location.
    :param location: Location to look up
    :return: branch to open
    """
    try:
        # Perhaps it's a colocated branch?
        return control_dir.open_branch(
            location, possible_transports=possible_transports
        )
    except (errors.NotBranchError, controldir.NoColocatedBranchSupport):
        this_url = _get_branch_location(control_dir)
        return Branch.open(urlutils.join(this_url, "..", urlutils.escape(location)))


def open_nearby_branch(near=None, location=None, possible_transports=None):
    """Open a nearby branch.

    :param near: Optional location of container from which to open branch
    :param location: Location of the branch
    :return: Branch instance
    """
    if near is None:
        if location is None:
            location = "."
        try:
            return Branch.open(location, possible_transports=possible_transports)
        except errors.NotBranchError:
            near = "."
    cdir = controldir.ControlDir.open(near, possible_transports=possible_transports)
    return open_sibling_branch(cdir, location, possible_transports=possible_transports)


def iter_sibling_branches(control_dir, possible_transports=None):
    """Iterate over the siblings of a branch.

    :param control_dir: Control directory for which to look up the siblings
    :return: Iterator over tuples with branch name and branch object
    """
    try:
        reference = control_dir.get_branch_reference()
    except errors.NotBranchError:
        reference = None
    if reference is not None:
        try:
            ref_branch = Branch.open(reference, possible_transports=possible_transports)
        except errors.NotBranchError:
            ref_branch = None
    else:
        ref_branch = None
    if ref_branch is None or ref_branch.name:
        if ref_branch is not None:
            control_dir = ref_branch.controldir
        for name, branch in control_dir.get_branches().items():
            yield name, branch
    else:
        repo = ref_branch.controldir.find_repository()
        for branch in repo.find_branches(using=True):
            name = urlutils.relative_url(repo.user_url, branch.user_url).rstrip("/")
            yield name, branch


def tree_files_for_add(file_list):
    """Return a tree and list of absolute paths from a file list.

    Similar to tree_files, but add handles files a bit differently, so it a
    custom implementation.  In particular, MutableTreeTree.smart_add expects
    absolute paths, which it immediately converts to relative paths.
    """
    from . import views
    from .workingtree import WorkingTree

    # FIXME Would be nice to just return the relative paths like
    # internal_tree_files does, but there are a large number of unit tests
    # that assume the current interface to mutabletree.smart_add
    if file_list:
        tree, relpath = WorkingTree.open_containing(file_list[0])
        if tree.supports_views():
            view_files = tree.views.lookup_view()
            if view_files:
                for filename in file_list:
                    if not osutils.is_inside_any(view_files, filename):
                        raise views.FileOutsideView(filename, view_files)
        file_list = file_list[:]
        file_list[0] = tree.abspath(relpath)
    else:
        tree = WorkingTree.open_containing(".")[0]
        if tree.supports_views():
            view_files = tree.views.lookup_view()
            if view_files:
                file_list = view_files
                view_str = views.view_display_str(view_files)
                note(gettext("Ignoring files outside view. View is %s"), view_str)
    return tree, file_list


def _get_one_revision(command_name, revisions):
    """Get exactly one revision from a revision list.

    Args:
        command_name: Name of the command for error messages.
        revisions: List of revisions or None.

    Returns:
        The single revision from the list, or None if revisions is None.

    Raises:
        CommandError: If revisions list doesn't contain exactly one revision.
    """
    if revisions is None:
        return None
    if len(revisions) != 1:
        raise errors.CommandError(
            gettext("brz %s --revision takes exactly one revision identifier")
            % (command_name,)
        )
    return revisions[0]


def _get_one_revision_tree(command_name, revisions, branch=None, tree=None):
    """Get a revision tree. Not suitable for commands that change the tree.

    Specifically, the basis tree in dirstate trees is coupled to the dirstate
    and doing a commit/uncommit/pull will at best fail due to changing the
    basis revision data.

    If tree is passed in, it should be already locked, for lifetime management
    of the trees internal cached state.
    """
    if branch is None:
        branch = tree.branch
    if revisions is None:
        rev_tree = tree.basis_tree() if tree is not None else branch.basis_tree()
    else:
        revision = _get_one_revision(command_name, revisions)
        rev_tree = revision.as_tree(branch)
    return rev_tree


def _get_view_info_for_change_reporter(tree):
    """Get the view information from a tree for change reporting."""
    from . import views

    view_info = None
    try:
        current_view = tree.views.get_view_info()[0]
        if current_view is not None:
            view_info = (current_view, tree.views.lookup_view())
    except views.ViewsNotSupported:
        pass
    return view_info


def _open_directory_or_containing_tree_or_branch(filename, directory):
    """Open the tree or branch containing the specified file, unless
    the --directory option is used to specify a different branch.
    """
    if directory is not None:
        return (None, Branch.open(directory), filename)
    return controldir.ControlDir.open_containing_tree_or_branch(filename)


# TODO: Make sure no commands unconditionally use the working directory as a
# branch.  If a filename argument is used, the first of them should be used to
# specify the branch.  (Perhaps this can be factored out into some kind of
# Argument class, representing a file in a branch, where the first occurrence
# opens the branch?)


class cmd_status(Command):
    __doc__ = """Display status summary.

    This reports on versioned and unknown files, reporting them
    grouped by state.  Possible states are:

    added
        Versioned in the working copy but not in the previous revision.

    removed
        Versioned in the previous revision but removed or deleted
        in the working copy.

    renamed
        Path of this file changed from the previous revision;
        the text may also have changed.  This includes files whose
        parent directory was renamed.

    modified
        Text has changed since the previous revision.

    kind changed
        File kind has been changed (e.g. from file to directory).

    unknown
        Not versioned and not matching an ignore pattern.

    Additionally for directories, symlinks and files with a changed
    executable bit, Breezy indicates their type using a trailing
    character: '/', '@' or '*' respectively. These decorations can be
    disabled using the '--no-classify' option.

    To see ignored files use 'brz ignored'.  For details on the
    changes to file texts, use 'brz diff'.

    Note that --short or -S gives status flags for each item, similar
    to Subversion's status command. To get output similar to svn -q,
    use brz status -SV.

    If no arguments are specified, the status of the entire working
    directory is shown.  Otherwise, only the status of the specified
    files or directories is reported.  If a directory is given, status
    is reported for everything inside that directory.

    Before merges are committed, the pending merge tip revisions are
    shown. To see all pending merge revisions, use the -v option.
    To skip the display of pending merge information altogether, use
    the no-pending option or specify a file/directory.

    To compare the working directory to a specific revision, pass a
    single revision to the revision argument.

    To see which files have changed in a specific revision, or between
    two revisions, pass a revision range to the revision argument.
    This will produce the same results as calling 'brz diff --summarize'.
    """

    # TODO: --no-recurse/-N, --recurse options

    takes_args = ["file*"]
    takes_options = [
        "show-ids",
        "revision",
        "change",
        "verbose",
        Option("short", help="Use short status indicators.", short_name="S"),
        Option("versioned", help="Only show versioned files.", short_name="V"),
        Option("no-pending", help="Don't show pending merges."),
        Option("no-classify", help="Do not mark object type using indicator."),
    ]
    aliases = ["st", "stat"]

    encoding_type = "replace"
    _see_also = ["diff", "revert", "status-flags"]

    @display_command
    def run(
        self,
        show_ids=False,
        file_list=None,
        revision=None,
        short=False,
        versioned=False,
        no_pending=False,
        verbose=False,
        no_classify=False,
    ):
        """Display status of files in the working tree.

        Args:
            show_ids: Show file ids in output.
            file_list: List of files to show status for.
            revision: Show status relative to a revision or revision range.
            short: Use short status indicators.
            versioned: Only show versioned files.
            no_pending: Don't show pending merges.
            verbose: Show detailed status information.
            no_classify: Don't mark object type using indicators.
        """
        from .status import show_tree_status
        from .workingtree import WorkingTree

        if revision and len(revision) > 2:
            raise errors.CommandError(
                gettext(
                    "brz status --revision takes exactly one or two revision specifiers"
                )
            )

        tree, relfile_list = WorkingTree.open_containing_paths(file_list)
        # Avoid asking for specific files when that is not needed.
        if relfile_list == [""]:
            relfile_list = None
            # Don't disable pending merges for full trees other than '.'.
            if file_list == ["."]:
                no_pending = True
        # A specific path within a tree was given.
        elif relfile_list is not None:
            no_pending = True
        show_tree_status(
            tree,
            show_ids=show_ids,
            specific_files=relfile_list,
            revision=revision,
            to_file=self.outf,
            short=short,
            versioned=versioned,
            show_pending=(not no_pending),
            verbose=verbose,
            classify=not no_classify,
        )


class cmd_cat_revision(Command):
    __doc__ = """Write out metadata for a revision.

    The revision to print can either be specified by a specific
    revision identifier, or you can use --revision.
    """

    hidden = True
    takes_args = ["revision_id?"]
    takes_options = ["directory", "revision"]
    # cat-revision is more for frontends so should be exact
    encoding = "strict"

    def print_revision(self, revisions, revid):
        """Print revision metadata to output.

        Args:
            revisions: Revision store to get revision from.
            revid: Revision ID to print.
        """
        stream = revisions.get_record_stream([(revid,)], "unordered", True)
        record = next(stream)
        if record.storage_kind == "absent":
            raise errors.NoSuchRevision(revisions, revid)
        revtext = record.get_bytes_as("fulltext")
        self.outf.write(revtext.decode("utf-8"))

    @display_command
    def run(self, revision_id=None, revision=None, directory="."):
        """Write out metadata for a revision.

        Args:
            revision_id: Specific revision identifier to print.
            revision: Revision specification to use instead of revision_id.
            directory: Directory containing the repository.
        """
        if revision_id is not None and revision is not None:
            raise errors.CommandError(
                gettext("You can only supply one of revision_id or --revision")
            )
        if revision_id is None and revision is None:
            raise errors.CommandError(
                gettext("You must supply either --revision or a revision_id")
            )

        b = controldir.ControlDir.open_containing_tree_or_branch(directory)[1]

        revisions = getattr(b.repository, "revisions", None)
        if revisions is None:
            raise errors.CommandError(
                gettext("Repository %r does not support access to raw revision texts")
                % b.repository
            )

        with b.repository.lock_read():
            # TODO: jam 20060112 should cat-revision always output utf-8?
            if revision_id is not None:
                revision_id = revision_id.encode("utf-8")
                try:
                    self.print_revision(revisions, revision_id)
                except errors.NoSuchRevision as exc:
                    msg = gettext(
                        "The repository {0} contains no revision {1}."
                    ).format(b.repository.base, revision_id.decode("utf-8"))
                    raise errors.CommandError(msg) from exc
            elif revision is not None:
                for rev in revision:
                    if rev is None:
                        raise errors.CommandError(
                            gettext("You cannot specify a NULL revision.")
                        )
                    rev_id = rev.as_revision_id(b)
                    self.print_revision(revisions, rev_id)


class cmd_remove_tree(Command):
    __doc__ = """Remove the working tree from a given branch/checkout.

    Since a lightweight checkout is little more than a working tree
    this will refuse to run against one.

    To re-create the working tree, use "brz checkout".
    """
    _see_also = ["checkout", "working-trees"]
    takes_args = ["location*"]
    takes_options = [
        Option(
            "force",
            help="Remove the working tree even if it has "
            "uncommitted or shelved changes.",
        ),
    ]

    def run(self, location_list, force=False):
        """Execute the remove-tree command.

        Args:
            location_list: List of locations to remove working trees from.
                          If empty, defaults to current directory.
            force: If True, remove working tree even if it has uncommitted
                  or shelved changes.

        Raises:
            CommandError: If working tree cannot be safely removed.
        """
        if not location_list:
            location_list = ["."]

        for location in location_list:
            d = controldir.ControlDir.open(location)

            try:
                working = d.open_workingtree()
            except errors.NoWorkingTree as exc:
                raise errors.CommandError(gettext("No working tree to remove")) from exc
            except errors.NotLocalUrl as exc:
                raise errors.CommandError(
                    gettext("You cannot remove the working tree of a remote path")
                ) from exc
            if not force:
                if working.has_changes():
                    raise errors.UncommittedChanges(working)
                if working.get_shelf_manager().last_shelf() is not None:
                    raise errors.ShelvedChanges(working)

            if working.user_url != working.branch.user_url:
                raise errors.CommandError(
                    gettext(
                        "You cannot remove the working tree from a lightweight checkout"
                    )
                )

            d.destroy_workingtree()


class cmd_repair_workingtree(Command):
    __doc__ = """Reset the working tree state file.

    This is not meant to be used normally, but more as a way to recover from
    filesystem corruption, etc. This rebuilds the working inventory back to a
    'known good' state. Any new modifications (adding a file, renaming, etc)
    will be lost, though modified files will still be detected as such.

    Most users will want something more like "brz revert" or "brz update"
    unless the state file has become corrupted.

    By default this attempts to recover the current state by looking at the
    headers of the state file. If the state file is too corrupted to even do
    that, you can supply --revision to force the state of the tree.
    """

    takes_options = [
        "revision",
        "directory",
        Option(
            "force", help="Reset the tree even if it doesn't appear to be corrupted."
        ),
    ]
    hidden = True

    def run(self, revision=None, directory=".", force=False):
        from .workingtree import WorkingTree

        tree, _ = WorkingTree.open_containing(directory)
        self.enter_context(tree.lock_tree_write())
        if not force:
            try:
                tree.check_state()
            except errors.BzrError:
                pass  # There seems to be a real error here, so we'll reset
            else:
                # Refuse
                raise errors.CommandError(
                    gettext(
                        "The tree does not appear to be corrupt. You probably"
                        ' want "brz revert" instead. Use "--force" if you are'
                        " sure you want to reset the working tree."
                    )
                )
        if revision is None:
            revision_ids = None
        else:
            revision_ids = [r.as_revision_id(tree.branch) for r in revision]
        try:
            tree.reset_state(revision_ids)
        except errors.BzrError as exc:
            if revision_ids is None:
                extra = gettext(
                    ", the header appears corrupt, try passing "
                    "-r -1 to set the state to the last commit"
                )
            else:
                extra = ""
            raise errors.CommandError(
                gettext("failed to reset the tree state{0}").format(extra)
            ) from exc


class cmd_revno(Command):
    __doc__ = """Show current revision number.

    This is equal to the number of revisions on this branch.
    """

    _see_also = ["info"]
    takes_args = ["location?"]
    takes_options = [
        Option("tree", help="Show revno of working tree."),
        "revision",
    ]

    @display_command
    def run(self, tree=False, location=".", revision=None):
        from .workingtree import WorkingTree

        if revision is not None and tree:
            raise errors.CommandError(
                gettext("--tree and --revision can not be used together")
            )

        if tree:
            try:
                wt = WorkingTree.open_containing(location)[0]
                self.enter_context(wt.lock_read())
            except (errors.NoWorkingTree, errors.NotLocalUrl) as exc:
                raise errors.NoWorkingTree(location) from exc
            b = wt.branch
            revid = wt.last_revision()
        else:
            b = Branch.open_containing(location)[0]
            self.enter_context(b.lock_read())
            if revision:
                if len(revision) != 1:
                    raise errors.CommandError(
                        gettext(
                            "Revision numbers only make sense for single "
                            "revisions, not ranges"
                        )
                    )
                revid = revision[0].as_revision_id(b)
            else:
                revid = b.last_revision()
        try:
            revno_t = b.revision_id_to_dotted_revno(revid)
        except (errors.NoSuchRevision, errors.GhostRevisionsHaveNoRevno):
            revno_t = ("???",)
        revno = ".".join(str(n) for n in revno_t)
        self.cleanup_now()
        self.outf.write(revno + "\n")


class cmd_revision_info(Command):
    __doc__ = """Show revision number and revision id for a given revision identifier.
    """
    hidden = True
    takes_args = ["revision_info*"]
    takes_options = [
        "revision",
        custom_help(
            "directory",
            help="Branch to examine, "
            "rather than the one containing the working directory.",
        ),
        Option("tree", help="Show revno of working tree."),
    ]

    @display_command
    def run(self, revision=None, directory=".", tree=False, revision_info_list=None):
        from .workingtree import WorkingTree

        try:
            wt = WorkingTree.open_containing(directory)[0]
            b = wt.branch
            self.enter_context(wt.lock_read())
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            wt = None
            b = Branch.open_containing(directory)[0]
            self.enter_context(b.lock_read())
        revision_ids = []
        if revision is not None:
            revision_ids.extend(rev.as_revision_id(b) for rev in revision)
        if revision_info_list is not None:
            for rev_str in revision_info_list:
                rev_spec = RevisionSpec.from_string(rev_str)
                revision_ids.append(rev_spec.as_revision_id(b))
        # No arguments supplied, default to the last revision
        if len(revision_ids) == 0:
            if tree:
                if wt is None:
                    raise errors.NoWorkingTree(directory)
                revision_ids.append(wt.last_revision())
            else:
                revision_ids.append(b.last_revision())

        revinfos = []
        maxlen = 0
        for revision_id in revision_ids:
            try:
                dotted_revno = b.revision_id_to_dotted_revno(revision_id)
                revno = ".".join(str(i) for i in dotted_revno)
            except errors.NoSuchRevision:
                revno = "???"
            maxlen = max(maxlen, len(revno))
            revinfos.append((revno, revision_id))

        self.cleanup_now()
        for revno, revid in revinfos:
            self.outf.write("%*s %s\n" % (maxlen, revno, revid.decode("utf-8")))


class cmd_add(Command):
    __doc__ = """Add specified files or directories.

    In non-recursive mode, all the named items are added, regardless
    of whether they were previously ignored.  A warning is given if
    any of the named files are already versioned.

    In recursive mode (the default), files are treated the same way
    but the behaviour for directories is different.  Directories that
    are already versioned do not give a warning.  All directories,
    whether already versioned or not, are searched for files or
    subdirectories that are neither versioned or ignored, and these
    are added.  This search proceeds recursively into versioned
    directories.  If no names are given '.' is assumed.

    A warning will be printed when nested trees are encountered,
    unless they are explicitly ignored.

    Therefore simply saying 'brz add' will version all files that
    are currently unknown.

    Adding a file whose parent directory is not versioned will
    implicitly add the parent, and so on up to the root. This means
    you should never need to explicitly add a directory, they'll just
    get added when you add a file in the directory.

    --dry-run will show which files would be added, but not actually
    add them.

    --file-ids-from will try to use the file ids from the supplied path.
    It looks up ids trying to find a matching parent directory with the
    same filename, and then by pure path. This option is rarely needed
    but can be useful when adding the same logical file into two
    branches that will be merged later (without showing the two different
    adds as a conflict). It is also useful when merging another project
    into a subdirectory of this one.

    Any files matching patterns in the ignore list will not be added
    unless they are explicitly mentioned.

    In recursive mode, files larger than the configuration option
    add.maximum_file_size will be skipped. Named items are never skipped due
    to file size.
    """
    takes_args = ["file*"]
    takes_options = [
        Option(
            "no-recurse",
            help="Don't recursively add the contents of directories.",
            short_name="N",
        ),
        Option(
            "dry-run",
            help="Show what would be done, but don't actually do anything.",
        ),
        "verbose",
        Option("file-ids-from", type=str, help="Lookup file ids from this tree."),
    ]
    encoding_type = "replace"
    _see_also = ["remove", "ignore"]

    def run(
        self,
        file_list,
        no_recurse=False,
        dry_run=False,
        verbose=False,
        file_ids_from=None,
    ):
        """Execute the add command to add files to version control.

        Args:
            file_list: List of files/directories to add. If empty, adds
                      all files in current directory recursively.
            no_recurse: If True, don't recursively add directory contents.
            dry_run: If True, show what would be done without making changes.
            verbose: If True, show additional information during operation.
            file_ids_from: Tree to lookup file ids from for compatibility.

        Note:
            Files larger than add.maximum_file_size configuration option
            will be skipped in recursive mode, but explicitly named files
            are never skipped due to size.
        """
        import breezy.add

        from .workingtree import WorkingTree

        tree, file_list = tree_files_for_add(file_list)

        if file_ids_from is not None and not tree.supports_setting_file_ids():
            warning(
                gettext(
                    "Ignoring --file-ids-from, since the tree does not "
                    "support setting file ids."
                )
            )
            file_ids_from = None

        base_tree = None
        if file_ids_from is not None:
            try:
                base_tree, base_path = WorkingTree.open_containing(file_ids_from)
            except errors.NoWorkingTree:
                base_branch, base_path = Branch.open_containing(file_ids_from)
                base_tree = base_branch.basis_tree()

            action = breezy.add.AddFromBaseAction(
                base_tree, base_path, to_file=self.outf, should_print=(not is_quiet())
            )
        else:
            action = breezy.add.AddWithSkipLargeAction(
                to_file=self.outf, should_print=(not is_quiet())
            )

        if base_tree:
            self.enter_context(base_tree.lock_read())
        added, ignored = tree.smart_add(
            file_list, not no_recurse, action=action, save=not dry_run
        )
        self.cleanup_now()
        if len(ignored) > 0 and verbose:
            for glob in sorted(ignored):
                for path in ignored[glob]:
                    self.outf.write(
                        gettext('ignored {0} matching "{1}"\n').format(path, glob)
                    )


class cmd_mkdir(Command):
    __doc__ = """Create a new versioned directory.

    This is equivalent to creating the directory and then adding it.
    """

    takes_args = ["dir+"]
    takes_options = [
        Option(
            "parents",
            help="No error if existing, make parent directories as needed.",
            short_name="p",
        )
    ]
    encoding_type = "replace"

    @classmethod
    def add_file_with_parents(cls, wt, relpath):
        """Add a file and its parent directories to version control.

        Args:
            wt: Working tree to add the file to.
            relpath: Relative path of the file to add.

        Note:
            If the file is already versioned, this method does nothing.
            Parent directories are recursively added if not already versioned.
        """
        if wt.is_versioned(relpath):
            return
        cls.add_file_with_parents(wt, osutils.dirname(relpath))
        wt.add([relpath])

    @classmethod
    def add_file_single(cls, wt, relpath):
        """Add a single file to version control.

        Args:
            wt: Working tree to add the file to.
            relpath: Relative path of the file to add.
        """
        wt.add([relpath])

    def run(self, dir_list, parents=False):
        """Execute the mkdir command to create versioned directories.

        Args:
            dir_list: List of directory names to create and add to version control.
            parents: If True, create parent directories as needed and don't error
                    if directories already exist.

        Note:
            This is equivalent to creating the directory with mkdir and then
            adding it to version control.
        """
        from .workingtree import WorkingTree

        add_file = self.add_file_with_parents if parents else self.add_file_single
        for dir in dir_list:
            wt, relpath = WorkingTree.open_containing(dir)
            if parents:
                with contextlib.suppress(FileExistsError):
                    os.makedirs(dir)
            else:
                os.mkdir(dir)
            add_file(wt, relpath)
            if not is_quiet():
                self.outf.write(gettext("added %s\n") % dir)


class cmd_relpath(Command):
    __doc__ = """Show path of a file relative to root"""

    takes_args = ["filename"]
    hidden = True

    @display_command
    def run(self, filename):
        from .workingtree import WorkingTree

        # TODO: jam 20050106 Can relpath return a munged path if
        #       sys.stdout encoding cannot represent it?
        tree, relpath = WorkingTree.open_containing(filename)
        self.outf.write(relpath)
        self.outf.write("\n")


class cmd_inventory(Command):
    __doc__ = """Show inventory of the current working copy or a revision.

    It is possible to limit the output to a particular entry
    type using the --kind option.  For example: --kind file.

    It is also possible to restrict the list of files to a specific
    set. For example: brz inventory --show-ids this/file
    """

    hidden = True
    _see_also = ["ls"]
    takes_options = [
        "revision",
        "show-ids",
        Option(
            "include-root", help="Include the entry for the root of the tree, if any."
        ),
        Option(
            "kind",
            help="List entries of a particular kind: file, directory, symlink.",
            type=str,
        ),
    ]
    takes_args = ["file*"]

    @display_command
    def run(
        self,
        revision=None,
        show_ids=False,
        kind=None,
        include_root=False,
        file_list=None,
    ):
        from .workingtree import WorkingTree

        if kind and kind not in ["file", "directory", "symlink"]:
            raise errors.CommandError(gettext("invalid kind %r specified") % (kind,))

        revision = _get_one_revision("inventory", revision)
        work_tree, file_list = WorkingTree.open_containing_paths(file_list)
        self.enter_context(work_tree.lock_read())
        if revision is not None:
            tree = revision.as_tree(work_tree.branch)

            extra_trees = [work_tree]
            self.enter_context(tree.lock_read())
        else:
            tree = work_tree
            extra_trees = []

        self.enter_context(tree.lock_read())
        if file_list is not None:
            paths = tree.find_related_paths_across_trees(
                file_list, extra_trees, require_versioned=True
            )
            # find_ids_across_trees may include some paths that don't
            # exist in 'tree'.
            entries = tree.iter_entries_by_dir(specific_files=paths)
        else:
            entries = tree.iter_entries_by_dir()

        for path, entry in sorted(entries):
            if kind and kind != entry.kind:
                continue
            if path == "" and not include_root:
                continue
            if show_ids:
                self.outf.write("%-50s %s\n" % (path, entry.file_id.decode("utf-8")))
            else:
                self.outf.write(path)
                self.outf.write("\n")


class cmd_cp(Command):
    __doc__ = """Copy a file.

    :Usage:
        brz cp OLDNAME NEWNAME

        brz cp SOURCE... DESTINATION

    If the last argument is a versioned directory, all the other names
    are copied into it.  Otherwise, there must be exactly two arguments
    and the file is copied to a new name.

    Files cannot be copied between branches. Only files can be copied
    at the moment.
    """

    takes_args = ["names*"]
    aliases = ["copy"]
    encoding_type = "replace"

    def run(self, names_list):
        from .workingtree import WorkingTree

        if names_list is None:
            names_list = []
        if len(names_list) < 2:
            raise errors.CommandError(gettext("missing file argument"))
        tree, rel_names = WorkingTree.open_containing_paths(
            names_list, canonicalize=False
        )
        for file_name in rel_names[0:-1]:
            if file_name == "":
                raise errors.CommandError(gettext("can not copy root of branch"))
        self.enter_context(tree.lock_tree_write())
        into_existing = osutils.isdir(names_list[-1])
        if not into_existing:
            try:
                (src, dst) = rel_names
            except IndexError as exc:
                raise errors.CommandError(
                    gettext(
                        "to copy multiple files the"
                        " destination must be a versioned"
                        " directory"
                    )
                ) from exc
            pairs = [(src, dst)]
        else:
            pairs = [
                (n, osutils.joinpath([rel_names[-1], osutils.basename(n)]))
                for n in rel_names[:-1]
            ]

        for src, dst in pairs:
            try:
                src_kind = tree.stored_kind(src)
            except transport.NoSuchFile as exc:
                raise errors.CommandError(
                    gettext("Could not copy %s => %s: %s is not versioned.")
                    % (src, dst, src)
                ) from exc
            if src_kind is None:
                raise errors.CommandError(
                    gettext("Could not copy %s => %s . %s is not versioned\\.")
                    % (src, dst, src)
                )
            if src_kind == "directory":
                raise errors.CommandError(
                    gettext("Could not copy %s => %s . %s is a directory.")
                    % (src, dst, src)
                )
            dst_parent = osutils.split(dst)[0]
            if dst_parent != "":
                try:
                    dst_parent_kind = tree.stored_kind(dst_parent)
                except transport.NoSuchFile as exc:
                    raise errors.CommandError(
                        gettext("Could not copy %s => %s: %s is not versioned.")
                        % (src, dst, dst_parent)
                    ) from exc
                if dst_parent_kind != "directory":
                    raise errors.CommandError(
                        gettext("Could not copy to %s: %s is not a directory.")
                        % (dst_parent, dst_parent)
                    )

            tree.copy_one(src, dst)


class cmd_mv(Command):
    __doc__ = """Move or rename a file.

    :Usage:
        brz mv OLDNAME NEWNAME

        brz mv SOURCE... DESTINATION

    If the last argument is a versioned directory, all the other names
    are moved into it.  Otherwise, there must be exactly two arguments
    and the file is changed to a new name.

    If OLDNAME does not exist on the filesystem but is versioned and
    NEWNAME does exist on the filesystem but is not versioned, mv
    assumes that the file has been manually moved and only updates
    its internal inventory to reflect that change.
    The same is valid when moving many SOURCE files to a DESTINATION.

    Files cannot be moved between branches.
    """

    takes_args = ["names*"]
    takes_options = [
        Option(
            "after",
            help="Move only the brz identifier"
            " of the file, because the file has already been moved.",
        ),
        Option("auto", help="Automatically guess renames."),
        Option("dry-run", help="Avoid making changes when guessing renames."),
    ]
    aliases = ["move", "rename"]
    encoding_type = "replace"

    def run(self, names_list, after=False, auto=False, dry_run=False):
        from .workingtree import WorkingTree

        if auto:
            return self.run_auto(names_list, after, dry_run)
        elif dry_run:
            raise errors.CommandError(gettext("--dry-run requires --auto."))
        if names_list is None:
            names_list = []
        if len(names_list) < 2:
            raise errors.CommandError(gettext("missing file argument"))
        tree, rel_names = WorkingTree.open_containing_paths(
            names_list, canonicalize=False
        )
        for file_name in rel_names[0:-1]:
            if file_name == "":
                raise errors.CommandError(gettext("can not move root of branch"))
        self.enter_context(tree.lock_tree_write())
        self._run(tree, names_list, rel_names, after)

    def run_auto(self, names_list, after, dry_run):
        from .rename_map import RenameMap
        from .workingtree import WorkingTree

        if names_list is not None and len(names_list) > 1:
            raise errors.CommandError(
                gettext("Only one path may be specified to --auto.")
            )
        if after:
            raise errors.CommandError(
                gettext("--after cannot be specified with --auto.")
            )
        work_tree, file_list = WorkingTree.open_containing_paths(
            names_list, default_directory="."
        )
        self.enter_context(work_tree.lock_tree_write())
        RenameMap.guess_renames(work_tree.basis_tree(), work_tree, dry_run)

    def _run(self, tree, names_list, rel_names, after):
        into_existing = osutils.isdir(names_list[-1])
        if into_existing and len(names_list) == 2:
            # special cases:
            # a. case-insensitive filesystem and change case of dir
            # b. move directory after the fact (if the source used to be
            #    a directory, but now doesn't exist in the working tree
            #    and the target is an existing directory, just rename it)
            if not tree.case_sensitive and rel_names[0].lower() == rel_names[1].lower():
                into_existing = False
            else:
                # 'fix' the case of a potential 'from'
                from_path = tree.get_canonical_path(rel_names[0])
                if (
                    not osutils.lexists(names_list[0])
                    and tree.is_versioned(from_path)
                    and tree.stored_kind(from_path) == "directory"
                ):
                    into_existing = False
        # move/rename
        if into_existing:
            # move into existing directory
            # All entries reference existing inventory items, so fix them up
            # for cicp file-systems.
            rel_names = list(tree.get_canonical_paths(rel_names))
            for src, dest in tree.move(rel_names[:-1], rel_names[-1], after=after):
                if not is_quiet():
                    self.outf.write(f"{src} => {dest}\n")
        else:
            if len(names_list) != 2:
                raise errors.CommandError(
                    gettext(
                        "to mv multiple files the"
                        " destination must be a versioned"
                        " directory"
                    )
                )

            # for cicp file-systems: the src references an existing inventory
            # item:
            src = tree.get_canonical_path(rel_names[0])
            # Find the canonical version of the destination:  In all cases, the
            # parent of the target must be in the inventory, so we fetch the
            # canonical version from there (we do not always *use* the
            # canonicalized tail portion - we may be attempting to rename the
            # case of the tail)
            canon_dest = tree.get_canonical_path(rel_names[1])
            dest_parent = osutils.dirname(canon_dest)
            spec_tail = osutils.basename(rel_names[1])
            # For a CICP file-system, we need to avoid creating 2 inventory
            # entries that differ only by case.  So regardless of the case
            # we *want* to use (ie, specified by the user or the file-system),
            # we must always choose to use the case of any existing inventory
            # items.  The only exception to this is when we are attempting a
            # case-only rename (ie, canonical versions of src and dest are
            # the same)
            dest_id = tree.path2id(canon_dest)
            if dest_id is None or tree.path2id(src) == dest_id:
                # No existing item we care about, so work out what case we
                # are actually going to use.
                if after:
                    # If 'after' is specified, the tail must refer to a file on disk.
                    if dest_parent:
                        dest_parent_fq = osutils.pathjoin(tree.basedir, dest_parent)
                    else:
                        # pathjoin with an empty tail adds a slash, which breaks
                        # relpath :(
                        dest_parent_fq = tree.basedir

                    dest_tail = osutils.canonical_relpath(
                        dest_parent_fq, osutils.pathjoin(dest_parent_fq, spec_tail)
                    )
                else:
                    # not 'after', so case as specified is used
                    dest_tail = spec_tail
            else:
                # Use the existing item so 'mv' fails with AlreadyVersioned.
                dest_tail = os.path.basename(canon_dest)
            dest = osutils.pathjoin(dest_parent, dest_tail)
            mutter("attempting to move %s => %s", src, dest)
            tree.rename_one(src, dest, after=after)
            if not is_quiet():
                self.outf.write(f"{src} => {dest}\n")


class cmd_pull(Command):
    __doc__ = """Turn this branch into a mirror of another branch.

    By default, this command only works on branches that have not diverged.
    Branches are considered diverged if the destination branch's most recent
    commit is one that has not been merged (directly or indirectly) into the
    parent.

    If branches have diverged, you can use 'brz merge' to integrate the changes
    from one into the other.  Once one branch has merged, the other should
    be able to pull it again.

    If you want to replace your local changes and just want your branch to
    match the remote one, use pull --overwrite. This will work even if the two
    branches have diverged.

    If there is no default location set, the first pull will set it (use
    --no-remember to avoid setting it). After that, you can omit the
    location to use the default.  To change the default, use --remember. The
    value will only be saved if the remote location can be accessed.

    The --verbose option will display the revisions pulled using the log_format
    configuration option. You can use a different format by overriding it with
    -Olog_format=<other_format>.

    Note: The location can be specified either in the form of a branch,
    or in the form of a path to a file containing a merge directive generated
    with brz send.
    """

    _see_also = ["push", "update", "status-flags", "send"]
    takes_options = [
        "remember",
        "overwrite",
        "revision",
        custom_help("verbose", help="Show logs of pulled revisions."),
        custom_help(
            "directory",
            help="Branch to pull into, "
            "rather than the one containing the working directory.",
        ),
        Option(
            "local",
            help="Perform a local pull in a bound "
            "branch.  Local pulls are not applied to "
            "the master branch.",
        ),
        Option("show-base", help="Show base revision text in conflicts."),
        Option("overwrite-tags", help="Overwrite tags only."),
    ]
    takes_args = ["location?"]
    encoding_type = "replace"

    def run(
        self,
        location=None,
        remember=None,
        overwrite=False,
        revision=None,
        verbose=False,
        directory=None,
        local=False,
        show_base=False,
        overwrite_tags=False,
    ):
        from . import mergeable as _mod_mergeable
        from .workingtree import WorkingTree

        if overwrite:
            overwrite = ["history", "tags"]
        elif overwrite_tags:
            overwrite = ["tags"]
        else:
            overwrite = []
        # FIXME: too much stuff is in the command class
        revision_id = None
        mergeable = None
        if directory is None:
            directory = "."
        try:
            tree_to = WorkingTree.open_containing(directory)[0]
            branch_to = tree_to.branch
            self.enter_context(tree_to.lock_write())
        except errors.NoWorkingTree:
            tree_to = None
            branch_to = Branch.open_containing(directory)[0]
            self.enter_context(branch_to.lock_write())
            if show_base:
                warning(gettext("No working tree, ignoring --show-base"))

        if local and not branch_to.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        possible_transports = []
        if location is not None:
            try:
                mergeable = _mod_mergeable.read_mergeable_from_url(
                    location, possible_transports=possible_transports
                )
            except errors.NotABundle:
                mergeable = None

        stored_loc = branch_to.get_parent()
        if location is None:
            if stored_loc is None:
                raise errors.CommandError(
                    gettext("No pull location known or specified.")
                )
            else:
                display_url = urlutils.unescape_for_display(
                    stored_loc, self.outf.encoding
                )
                if not is_quiet():
                    self.outf.write(
                        gettext("Using saved parent location: %s\n") % display_url
                    )
                location = stored_loc

        revision = _get_one_revision("pull", revision)
        if mergeable is not None:
            if revision is not None:
                raise errors.CommandError(
                    gettext("Cannot use -r with merge directives or bundles")
                )
            mergeable.install_revisions(branch_to.repository)
            base_revision_id, revision_id, verified = mergeable.get_merge_request(
                branch_to.repository
            )
            branch_from = branch_to
        else:
            branch_from = Branch.open(location, possible_transports=possible_transports)
            self.enter_context(branch_from.lock_read())
            # Remembers if asked explicitly or no previous location is set
            if remember or (remember is None and branch_to.get_parent() is None):
                # FIXME: This shouldn't be done before the pull
                # succeeds... -- vila 2012-01-02
                branch_to.set_parent(branch_from.base)

        if revision is not None:
            revision_id = revision.as_revision_id(branch_from)

        if tree_to is not None:
            view_info = _get_view_info_for_change_reporter(tree_to)
            change_reporter = delta._ChangeReporter(
                unversioned_filter=tree_to.is_ignored, view_info=view_info
            )
            result = tree_to.pull(
                branch_from,
                overwrite=overwrite,
                stop_revision=revision_id,
                change_reporter=change_reporter,
                local=local,
                show_base=show_base,
            )
        else:
            result = branch_to.pull(
                branch_from, overwrite=overwrite, stop_revision=revision_id, local=local
            )

        result.report(self.outf)
        if verbose and result.old_revid != result.new_revid:
            log.show_branch_change(
                branch_to, self.outf, result.old_revno, result.old_revid
            )
        if getattr(result, "tag_conflicts", None):
            return 1
        else:
            return 0


class cmd_push(Command):
    __doc__ = """Update a mirror of this branch.

    The target branch will not have its working tree populated because this
    is both expensive, and is not supported on remote file systems.

    Some smart servers or protocols *may* put the working tree in place in
    the future.

    This command only works on branches that have not diverged.  Branches are
    considered diverged if the destination branch's most recent commit is one
    that has not been merged (directly or indirectly) by the source branch.

    If branches have diverged, you can use 'brz push --overwrite' to replace
    the other branch completely, discarding its unmerged changes.

    If you want to ensure you have the different changes in the other branch,
    do a merge (see brz help merge) from the other branch, and commit that.
    After that you will be able to do a push without '--overwrite'.

    If there is no default push location set, the first push will set it (use
    --no-remember to avoid setting it).  After that, you can omit the
    location to use the default.  To change the default, use --remember. The
    value will only be saved if the remote location can be accessed.

    The --verbose option will display the revisions pushed using the log_format
    configuration option. You can use a different format by overriding it with
    -Olog_format=<other_format>.
    """

    _see_also = ["pull", "update", "working-trees"]
    takes_options = [
        "remember",
        "overwrite",
        "verbose",
        "revision",
        Option(
            "create-prefix",
            help="Create the path leading up to the branch "
            "if it does not already exist.",
        ),
        custom_help(
            "directory",
            help="Branch to push from, "
            "rather than the one containing the working directory.",
        ),
        Option(
            "use-existing-dir",
            help="By default push will fail if the target"
            " directory exists, but does not already"
            " have a control directory.  This flag will"
            " allow push to proceed.",
        ),
        Option(
            "stacked",
            help="Create a stacked branch that references the public location "
            "of the parent branch.",
        ),
        Option(
            "stacked-on",
            help="Create a stacked branch that refers to another branch "
            "for the commit history. Only the work not present in the "
            "referenced branch is included in the branch created.",
            type=str,
        ),
        Option(
            "strict",
            help="Refuse to push if there are uncommitted changes in"
            " the working tree, --no-strict disables the check.",
        ),
        Option(
            "no-tree",
            help="Don't populate the working tree, even for protocols that support it.",
        ),
        Option("overwrite-tags", help="Overwrite tags only."),
        Option(
            "lossy",
            help="Allow lossy push, i.e. dropping metadata "
            "that can't be represented in the target.",
        ),
    ]
    takes_args = ["location?"]
    encoding_type = "replace"

    def run(
        self,
        location=None,
        remember=None,
        overwrite=False,
        create_prefix=False,
        verbose=False,
        revision=None,
        use_existing_dir=False,
        directory=None,
        stacked_on=None,
        stacked=False,
        strict=None,
        no_tree=False,
        overwrite_tags=False,
        lossy=False,
    ):
        from .location import location_to_url
        from .push import _show_push_branch

        if overwrite:
            overwrite = ["history", "tags"]
        elif overwrite_tags:
            overwrite = ["tags"]
        else:
            overwrite = []

        if directory is None:
            directory = "."
        # Get the source branch
        (tree, br_from, _unused) = controldir.ControlDir.open_containing_tree_or_branch(
            directory
        )
        # Get the tip's revision_id
        revision = _get_one_revision("push", revision)
        if revision is not None:
            revision_id = revision.in_history(br_from).rev_id
        else:
            revision_id = None
        if tree is not None and revision_id is None:
            tree.check_changed_or_out_of_date(
                strict,
                "push_strict",
                more_error="Use --no-strict to force the push.",
                more_warning="Uncommitted changes will not be pushed.",
            )
        # Get the stacked_on branch, if any
        if stacked_on is not None:
            stacked_on = location_to_url(stacked_on, "read")
            stacked_on = urlutils.normalize_url(stacked_on)
        elif stacked:
            parent_url = br_from.get_parent()
            if parent_url:
                parent = Branch.open(parent_url)
                stacked_on = parent.get_public_branch()
                if not stacked_on:
                    # I considered excluding non-http url's here, thus forcing
                    # 'public' branches only, but that only works for some
                    # users, so it's best to just depend on the user spotting an
                    # error by the feedback given to them. RBC 20080227.
                    stacked_on = parent_url
            if not stacked_on:
                raise errors.CommandError(
                    gettext("Could not determine branch to refer to.")
                )

        # Get the destination location
        if location is None:
            stored_loc = br_from.get_push_location()
            if stored_loc is None:
                parent_loc = br_from.get_parent()
                if parent_loc:
                    raise errors.CommandError(
                        gettext(
                            "No push location known or specified. To push to the "
                            "parent branch (at %s), use 'brz push :parent'."
                        )
                        % urlutils.unescape_for_display(parent_loc, self.outf.encoding)
                    )
                else:
                    raise errors.CommandError(
                        gettext("No push location known or specified.")
                    )
            else:
                display_url = urlutils.unescape_for_display(
                    stored_loc, self.outf.encoding
                )
                note(gettext("Using saved push location: %s") % display_url)
                location = stored_loc

        _show_push_branch(
            br_from,
            revision_id,
            location,
            self.outf,
            verbose=verbose,
            overwrite=overwrite,
            remember=remember,
            stacked_on=stacked_on,
            create_prefix=create_prefix,
            use_existing_dir=use_existing_dir,
            no_tree=no_tree,
            lossy=lossy,
        )


class cmd_branch(Command):
    __doc__ = """Create a new branch that is a copy of an existing branch.

    If the TO_LOCATION is omitted, the last component of the FROM_LOCATION will
    be used.  In other words, "branch ../foo/bar" will attempt to create ./bar.
    If the FROM_LOCATION has no / or path separator embedded, the TO_LOCATION
    is derived from the FROM_LOCATION by stripping a leading scheme or drive
    identifier, if any. For example, "branch lp:foo-bar" will attempt to
    create ./foo-bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "branch foo/bar -r 5".
    """

    aliase = ["sprout"]
    _see_also = ["checkout"]
    takes_args = ["from_location", "to_location?"]
    takes_options = [
        "revision",
        Option("hardlink", help="Hard-link working tree files where possible."),
        Option("files-from", type=str, help="Get file contents from this tree."),
        Option("no-tree", help="Create a branch without a working-tree."),
        Option(
            "switch",
            help="Switch the checkout in the current directory to the new branch.",
        ),
        Option(
            "stacked",
            help="Create a stacked branch referring to the source branch. "
            "The new branch will depend on the availability of the source "
            "branch for all operations.",
        ),
        Option("standalone", help="Do not use a shared repository, even if available."),
        Option(
            "use-existing-dir",
            help="By default branch will fail if the target"
            " directory exists, but does not already"
            " have a control directory.  This flag will"
            " allow branch to proceed.",
        ),
        Option("bind", help="Bind new branch to from location."),
        Option("no-recurse-nested", help="Do not recursively check out nested trees."),
        Option(
            "colocated-branch",
            short_name="b",
            type=str,
            help="Name of colocated branch to sprout.",
        ),
    ]

    def run(
        self,
        from_location,
        to_location=None,
        revision=None,
        hardlink=False,
        stacked=False,
        standalone=False,
        no_tree=False,
        use_existing_dir=False,
        switch=False,
        bind=False,
        files_from=None,
        no_recurse_nested=False,
        colocated_branch=None,
    ):
        from breezy import switch as _mod_switch

        from .workingtree import WorkingTree

        accelerator_tree, br_from = controldir.ControlDir.open_tree_or_branch(
            from_location, name=colocated_branch
        )
        recurse = "none" if no_recurse_nested else "down"
        if not (hardlink or files_from):
            # accelerator_tree is usually slower because you have to read N
            # files (no readahead, lots of seeks, etc), but allow the user to
            # explicitly request it
            accelerator_tree = None
        if files_from is not None and files_from != from_location:
            accelerator_tree = WorkingTree.open(files_from)
        revision = _get_one_revision("branch", revision)
        self.enter_context(br_from.lock_read())
        if revision is not None:
            revision_id = revision.as_revision_id(br_from)
        else:
            # FIXME - wt.last_revision, fallback to branch, fall back to
            # None or perhaps NULL_REVISION to mean copy nothing
            # RBC 20060209
            revision_id = br_from.last_revision()
        if to_location is None:
            to_location = urlutils.derive_to_location(from_location)
        to_transport = transport.get_transport(to_location, purpose="write")
        try:
            to_transport.mkdir(".")
        except transport.FileExists:
            try:
                to_dir = controldir.ControlDir.open_from_transport(to_transport)
            except errors.NotBranchError as exc:
                if not use_existing_dir:
                    raise errors.CommandError(
                        gettext('Target directory "%s" already exists.') % to_location
                    ) from exc
                else:
                    to_dir = None
            else:
                try:
                    to_dir.open_branch()
                except errors.NotBranchError:
                    pass
                else:
                    raise errors.AlreadyBranchError(to_location)
        except transport.NoSuchFile as exc:
            raise errors.CommandError(
                gettext('Parent of "%s" does not exist.') % to_location
            ) from exc
        else:
            to_dir = None
        if to_dir is None:
            try:
                # preserve whatever source format we have.
                to_dir = br_from.controldir.sprout(
                    to_transport.base,
                    revision_id,
                    possible_transports=[to_transport],
                    accelerator_tree=accelerator_tree,
                    hardlink=hardlink,
                    stacked=stacked,
                    force_new_repo=standalone,
                    create_tree_if_local=not no_tree,
                    source_branch=br_from,
                    recurse=recurse,
                )
                branch = to_dir.open_branch(
                    possible_transports=[
                        br_from.controldir.root_transport,
                        to_transport,
                    ]
                )
            except errors.NoSuchRevision as exc:
                to_transport.delete_tree(".")
                msg = gettext("The branch {0} has no revision {1}.").format(
                    from_location, revision
                )
                raise errors.CommandError(msg) from exc
        else:
            try:
                to_repo = to_dir.open_repository()
            except errors.NoRepositoryPresent:
                to_repo = to_dir.create_repository()
            to_repo.fetch(br_from.repository, revision_id=revision_id)
            branch = br_from.sprout(to_dir, revision_id=revision_id)
        br_from.tags.merge_to(branch.tags)

        # If the source branch is stacked, the new branch may
        # be stacked whether we asked for that explicitly or not.
        # We therefore need a try/except here and not just 'if stacked:'
        try:
            note(
                gettext("Created new stacked branch referring to %s.")
                % branch.get_stacked_on_url()
            )
        except (
            errors.NotStacked,
            _mod_branch.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat,
        ):
            revno = branch.revno()
            if revno is not None:
                note(
                    ngettext(
                        "Branched %d revision.",
                        "Branched %d revisions.",
                        branch.revno(),
                    )
                    % revno
                )
            else:
                note(gettext("Created new branch."))
        if bind:
            # Bind to the parent
            parent_branch = Branch.open(from_location)
            branch.bind(parent_branch)
            note(gettext("New branch bound to %s") % from_location)
        if switch:
            # Switch to the new branch
            wt, _ = WorkingTree.open_containing(".")
            _mod_switch.switch(wt.controldir, branch)
            note(
                gettext("Switched to branch: %s"),
                urlutils.unescape_for_display(branch.base, "utf-8"),
            )


class cmd_branches(Command):
    __doc__ = """List the branches available at the current location.

    This command will print the names of all the branches at the current
    location.
    """

    takes_args = ["location?"]
    takes_options = [
        Option(
            "recursive",
            short_name="R",
            help="Recursively scan for branches rather than "
            "just looking in the specified location.",
        )
    ]

    def run(self, location=".", recursive=False):
        if recursive:
            t = transport.get_transport(location, purpose="read")
            if not t.listable():
                raise errors.CommandError("Can't scan this type of location.")
            for b in controldir.ControlDir.find_branches(t):
                self.outf.write(
                    "{}\n".format(
                        urlutils.unescape_for_display(
                            urlutils.relative_url(t.base, b.base), self.outf.encoding
                        ).rstrip("/")
                    )
                )
        else:
            dir = controldir.ControlDir.open_containing(location)[0]
            try:
                active_branch = dir.open_branch(name="")
            except errors.NotBranchError:
                active_branch = None
            names = {}
            for name, branch in iter_sibling_branches(dir):
                if name == "":
                    continue
                active = (
                    active_branch is not None
                    and active_branch.user_url == branch.user_url
                )
                names[name] = active
            # Only mention the current branch explicitly if it's not
            # one of the colocated branches
            if not any(names.values()) and active_branch is not None:
                self.outf.write(f"* {gettext('(default)')}\n")
            for name in sorted(names):
                active = names[name]
                prefix = "*" if active else " "
                self.outf.write(f"{prefix} {name}\n")


class cmd_checkout(Command):
    __doc__ = """Create a new checkout of an existing branch.

    If BRANCH_LOCATION is omitted, checkout will reconstitute a working tree
    for the branch found in '.'. This is useful if you have removed the working
    tree or if it was never created - i.e. if you pushed the branch to its
    current location using SFTP.

    If the TO_LOCATION is omitted, the last component of the BRANCH_LOCATION
    will be used.  In other words, "checkout ../foo/bar" will attempt to create
    ./bar.  If the BRANCH_LOCATION has no / or path separator embedded, the
    TO_LOCATION is derived from the BRANCH_LOCATION by stripping a leading
    scheme or drive identifier, if any. For example, "checkout lp:foo-bar" will
    attempt to create ./foo-bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "checkout foo/bar -r 5". Note that this will be
    immediately out of date [so you cannot commit] but it may be useful (i.e.
    to examine old code.)
    """

    _see_also = ["checkouts", "branch", "working-trees", "remove-tree"]
    takes_args = ["branch_location?", "to_location?"]
    takes_options = [
        "revision",
        Option(
            "lightweight",
            help="Perform a lightweight checkout.  Lightweight "
            "checkouts depend on access to the branch for "
            "every operation.  Normal checkouts can perform "
            "common operations like diff and status without "
            "such access, and also support local commits.",
        ),
        Option("files-from", type=str, help="Get file contents from this tree."),
        Option("hardlink", help="Hard-link working tree files where possible."),
    ]
    aliases = ["co"]

    def run(
        self,
        branch_location=None,
        to_location=None,
        revision=None,
        lightweight=False,
        files_from=None,
        hardlink=False,
    ):
        from .workingtree import WorkingTree

        if branch_location is None:
            branch_location = osutils.getcwd()
            to_location = branch_location
        accelerator_tree, source = controldir.ControlDir.open_tree_or_branch(
            branch_location
        )
        if not (hardlink or files_from):
            # accelerator_tree is usually slower because you have to read N
            # files (no readahead, lots of seeks, etc), but allow the user to
            # explicitly request it
            accelerator_tree = None
        revision = _get_one_revision("checkout", revision)
        if files_from is not None and files_from != branch_location:
            accelerator_tree = WorkingTree.open(files_from)
        revision_id = revision.as_revision_id(source) if revision is not None else None
        if to_location is None:
            to_location = urlutils.derive_to_location(branch_location)
        # if the source and to_location are the same,
        # and there is no working tree,
        # then reconstitute a branch
        if osutils.abspath(to_location) == osutils.abspath(branch_location):
            try:
                source.controldir.open_workingtree()
            except errors.NoWorkingTree:
                source.controldir.create_workingtree(revision_id)
                return
        source.create_checkout(
            to_location,
            revision_id=revision_id,
            lightweight=lightweight,
            accelerator_tree=accelerator_tree,
            hardlink=hardlink,
        )


class cmd_clone(Command):
    __doc__ = """Clone a control directory.
    """

    takes_args = ["from_location", "to_location?"]
    takes_options = [
        "revision",
        Option("no-recurse-nested", help="Do not recursively check out nested trees."),
    ]

    def run(
        self, from_location, to_location=None, revision=None, no_recurse_nested=False
    ):
        accelerator_tree, br_from = controldir.ControlDir.open_tree_or_branch(
            from_location
        )
        if no_recurse_nested:
            pass
        else:
            pass
        revision = _get_one_revision("branch", revision)
        self.enter_context(br_from.lock_read())
        if revision is not None:
            revision_id = revision.as_revision_id(br_from)
        else:
            # FIXME - wt.last_revision, fallback to branch, fall back to
            # None or perhaps NULL_REVISION to mean copy nothing
            # RBC 20060209
            revision_id = br_from.last_revision()
        if to_location is None:
            to_location = urlutils.derive_to_location(from_location)
        br_from.controldir.clone(to_location, revision_id=revision_id)
        note(gettext("Created new control directory."))


class cmd_renames(Command):
    __doc__ = """Show list of renamed files.
    """
    # TODO: Option to show renames between two historical versions.

    # TODO: Only show renames under dir, rather than in the whole branch.
    _see_also = ["status"]
    takes_args = ["dir?"]

    @display_command
    def run(self, dir="."):
        from .workingtree import WorkingTree

        tree = WorkingTree.open_containing(dir)[0]
        self.enter_context(tree.lock_read())
        old_tree = tree.basis_tree()
        self.enter_context(old_tree.lock_read())
        renames = []
        iterator = tree.iter_changes(old_tree, include_unchanged=True)
        for change in iterator:
            if change.path[0] == change.path[1]:
                continue
            if None in change.path:
                continue
            renames.append(change.path)
        renames.sort()
        for old_name, new_name in renames:
            self.outf.write(f"{old_name} => {new_name}\n")


class cmd_update(Command):
    __doc__ = """Update a working tree to a new revision.

    This will perform a merge of the destination revision (the tip of the
    branch, or the specified revision) into the working tree, and then make
    that revision the basis revision for the working tree.

    You can use this to visit an older revision, or to update a working tree
    that is out of date from its branch.

    If there are any uncommitted changes in the tree, they will be carried
    across and remain as uncommitted changes after the update.  To discard
    these changes, use 'brz revert'.  The uncommitted changes may conflict
    with the changes brought in by the change in basis revision.

    If the tree's branch is bound to a master branch, brz will also update
    the branch from the master.

    You cannot update just a single file or directory, because each Breezy
    working tree has just a single basis revision.  If you want to restore a
    file that has been removed locally, use 'brz revert' instead of 'brz
    update'.  If you want to restore a file to its state in a previous
    revision, use 'brz revert' with a '-r' option, or use 'brz cat' to write
    out the old content of that file to a new location.

    The 'dir' argument, if given, must be the location of the root of a
    working tree to update.  By default, the working tree that contains the
    current working directory is used.
    """

    _see_also = ["pull", "working-trees", "status-flags"]
    takes_args = ["dir?"]
    takes_options = [
        "revision",
        Option("show-base", help="Show base revision text in conflicts."),
    ]
    aliases = ["up"]

    def run(self, dir=None, revision=None, show_base=None):
        from .workingtree import WorkingTree

        if revision is not None and len(revision) != 1:
            raise errors.CommandError(
                gettext("brz update --revision takes exactly one revision")
            )
        if dir is None:
            tree = WorkingTree.open_containing(".")[0]
        else:
            tree, relpath = WorkingTree.open_containing(dir)
            if relpath:
                # See bug 557886.
                raise errors.CommandError(
                    gettext(
                        "brz update can only update a whole tree, "
                        "not a file or subdirectory"
                    )
                )
        branch = tree.branch
        possible_transports = []
        master = branch.get_master_branch(possible_transports=possible_transports)
        if master is not None:
            branch_location = master.base
            self.enter_context(tree.lock_write())
        else:
            branch_location = tree.branch.base
            self.enter_context(tree.lock_tree_write())
        # get rid of the final '/' and be ready for display
        branch_location = urlutils.unescape_for_display(
            branch_location.rstrip("/"), self.outf.encoding
        )
        existing_pending_merges = tree.get_parent_ids()[1:]
        if master is None:
            old_tip = None
        else:
            # may need to fetch data into a heavyweight checkout
            # XXX: this may take some time, maybe we should display a
            # message
            old_tip = branch.update(possible_transports)
        if revision is not None:
            revision_id = revision[0].as_revision_id(branch)
        else:
            revision_id = branch.last_revision()
        if revision_id == tree.last_revision():
            revno = branch.revision_id_to_dotted_revno(revision_id)
            note(
                gettext("Tree is up to date at revision {0} of branch {1}").format(
                    ".".join(map(str, revno)), branch_location
                )
            )
            return 0
        view_info = _get_view_info_for_change_reporter(tree)
        change_reporter = delta._ChangeReporter(
            unversioned_filter=tree.is_ignored, view_info=view_info
        )
        try:
            conflicts = tree.update(
                change_reporter,
                possible_transports=possible_transports,
                revision=revision_id,
                old_tip=old_tip,
                show_base=show_base,
            )
        except errors.NoSuchRevision as exc:
            raise errors.CommandError(
                gettext(
                    "branch has no revision %s\n"
                    "brz update --revision only works"
                    " for a revision in the branch history"
                )
                % (exc.revision)
            ) from exc
        revno = tree.branch.revision_id_to_dotted_revno(tree.last_revision())
        note(
            gettext("Updated to revision {0} of branch {1}").format(
                ".".join(map(str, revno)), branch_location
            )
        )
        parent_ids = tree.get_parent_ids()
        if parent_ids[1:] and parent_ids[1:] != existing_pending_merges:
            note(
                gettext(
                    "Your local commits will now show as pending merges with "
                    "'brz status', and can be committed with 'brz commit'."
                )
            )
        if conflicts != 0:
            return 1
        else:
            return 0


class cmd_info(Command):
    __doc__ = """Show information about a working tree, branch or repository.

    This command will show all known locations and formats associated to the
    tree, branch or repository.

    In verbose mode, statistical information is included with each report.
    To see extended statistic information, use a verbosity level of 2 or
    higher by specifying the verbose option multiple times, e.g. -vv.

    Branches and working trees will also report any missing revisions.

    :Examples:

      Display information on the format and related locations:

        brz info

      Display the above together with extended format information and
      basic statistics (like the number of files in the working tree and
      number of revisions in the branch and repository):

        brz info -v

      Display the above together with number of committers to the branch:

        brz info -vv
    """
    _see_also = ["revno", "working-trees", "repositories"]
    takes_args = ["location?"]
    takes_options = ["verbose"]
    encoding_type = "replace"

    @display_command
    def run(self, location=None, verbose=False):
        noise_level = get_verbosity_level() if verbose else 0
        from .info import show_bzrdir_info

        show_bzrdir_info(
            controldir.ControlDir.open_containing(location)[0],
            verbose=noise_level,
            outfile=self.outf,
        )


class cmd_remove(Command):
    __doc__ = """Remove files or directories.

    This makes Breezy stop tracking changes to the specified files. Breezy will
    delete them if they can easily be recovered using revert otherwise they
    will be backed up (adding an extension of the form .~#~). If no options or
    parameters are given Breezy will scan for files that are being tracked by
    Breezy but missing in your tree and stop tracking them for you.
    """
    takes_args = ["file*"]
    takes_options = [
        "verbose",
        Option("new", help="Only remove files that have never been committed."),
        RegistryOption.from_kwargs(
            "file-deletion-strategy",
            "The file deletion mode to be used.",
            title="Deletion Strategy",
            value_switches=True,
            enum_switch=False,
            safe="Backup changed files (default).",
            keep="Delete from brz but leave the working copy.",
            no_backup="Don't backup changed files.",
        ),
    ]
    aliases = ["rm", "del"]
    encoding_type = "replace"

    def run(self, file_list, verbose=False, new=False, file_deletion_strategy="safe"):
        from .workingtree import WorkingTree

        tree, file_list = WorkingTree.open_containing_paths(file_list)

        if file_list is not None:
            file_list = list(file_list)

        self.enter_context(tree.lock_write())
        # Heuristics should probably all move into tree.remove_smart or
        # some such?
        if new:
            added = tree.changes_from(tree.basis_tree(), specific_files=file_list).added
            file_list = sorted([f.path[1] for f in added], reverse=True)
            if len(file_list) == 0:
                raise errors.CommandError(gettext("No matching files."))
        elif file_list is None:
            # missing files show up in iter_changes(basis) as
            # versioned-with-no-kind.
            missing = []
            for change in tree.iter_changes(tree.basis_tree()):
                # Find paths in the working tree that have no kind:
                if change.path[1] is not None and change.kind[1] is None:
                    missing.append(change.path[1])
            file_list = sorted(missing, reverse=True)
            file_deletion_strategy = "keep"
        tree.remove(
            file_list,
            verbose=verbose,
            to_file=self.outf,
            keep_files=file_deletion_strategy == "keep",
            force=(file_deletion_strategy == "no-backup"),
        )


class cmd_reconcile(Command):
    __doc__ = """Reconcile brz metadata in a branch.

    This can correct data mismatches that may have been caused by
    previous ghost operations or brz upgrades. You should only
    need to run this command if 'brz check' or a brz developer
    advises you to run it.

    If a second branch is provided, cross-branch reconciliation is
    also attempted, which will check that data like the tree root
    id which was not present in very early brz versions is represented
    correctly in both branches.

    At the same time it is run it may recompress data resulting in
    a potential saving in disk space or performance gain.

    The branch *MUST* be on a listable system such as local disk or sftp.
    """

    _see_also = ["check"]
    takes_args = ["branch?"]
    takes_options = [
        Option(
            "canonicalize-chks",
            help="Make sure CHKs are in canonical form (repairs bug 522637).",
            hidden=True,
        ),
    ]

    def run(self, branch=".", canonicalize_chks=False):
        from .reconcile import reconcile

        dir = controldir.ControlDir.open(branch)
        reconcile(dir, canonicalize_chks=canonicalize_chks)


class cmd_revision_history(Command):
    __doc__ = """Display the list of revision ids on a branch."""

    _see_also = ["log"]
    takes_args = ["location?"]

    hidden = True

    @display_command
    def run(self, location="."):
        branch = Branch.open_containing(location)[0]
        self.enter_context(branch.lock_read())
        graph = branch.repository.get_graph()
        history = list(
            graph.iter_lefthand_ancestry(
                branch.last_revision(), [_mod_revision.NULL_REVISION]
            )
        )
        for revid in reversed(history):
            self.outf.write(revid)
            self.outf.write("\n")


class cmd_ancestry(Command):
    __doc__ = """List all revisions merged into this branch."""

    _see_also = ["log", "revision-history"]
    takes_args = ["location?"]

    hidden = True

    @display_command
    def run(self, location="."):
        from .workingtree import WorkingTree

        try:
            wt = WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = Branch.open(location)
            last_revision = b.last_revision()
        else:
            b = wt.branch
            last_revision = wt.last_revision()

        self.enter_context(b.repository.lock_read())
        graph = b.repository.get_graph()
        revisions = [revid for revid, parents in graph.iter_ancestry([last_revision])]
        for revision_id in reversed(revisions):
            if _mod_revision.is_null(revision_id):
                continue
            self.outf.write(revision_id.decode("utf-8") + "\n")


class cmd_init(Command):
    __doc__ = """Make a directory into a versioned branch.

    Use this to create an empty branch, or before importing an
    existing project.

    If there is a repository in a parent directory of the location, then
    the history of the branch will be stored in the repository.  Otherwise
    init creates a standalone branch which carries its own history
    in the .bzr directory.

    If there is already a branch at the location but it has no working tree,
    the tree can be populated with 'brz checkout'.

    Recipe for importing a tree of files::

        cd ~/project
        brz init
        brz add .
        brz status
        brz commit -m "imported project"
    """

    _see_also = ["init-shared-repository", "branch", "checkout"]
    takes_args = ["location?"]
    takes_options = [
        Option(
            "create-prefix",
            help="Create the path leading up to the branch "
            "if it does not already exist.",
        ),
        RegistryOption(
            "format",
            help="Specify a format for this branch. "
            'See "help formats" for a full list.',
            lazy_registry=("breezy.controldir", "format_registry"),
            converter=lambda name: controldir.format_registry.make_controldir(  # type: ignore
                name
            ),
            value_switches=True,
            title="Branch format",
        ),
        Option(
            "append-revisions-only",
            help="Never change revnos or the existing log."
            "  Append revisions to it only.",
        ),
        Option("no-tree", "Create a branch without a working tree."),
    ]

    def run(
        self,
        location=None,
        format=None,
        append_revisions_only=False,
        create_prefix=False,
        no_tree=False,
    ):
        if format is None:
            format = controldir.format_registry.make_controldir("default")
        if location is None:
            location = "."

        to_transport = transport.get_transport(location, purpose="write")

        # The path has to exist to initialize a
        # branch inside of it.
        # Just using os.mkdir, since I don't
        # believe that we want to create a bunch of
        # locations if the user supplies an extended path
        try:
            to_transport.ensure_base()
        except transport.NoSuchFile as exc:
            if not create_prefix:
                raise errors.CommandError(
                    gettext(
                        "Parent directory of %s"
                        " does not exist."
                        "\nYou may supply --create-prefix to create all"
                        " leading parent directories."
                    )
                    % location
                ) from exc
            to_transport.create_prefix()

        try:
            a_controldir = controldir.ControlDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            # really a NotBzrDir error...
            create_branch = controldir.ControlDir.create_branch_convenience
            force_new_tree = False if no_tree else None
            branch = create_branch(
                to_transport.base,
                format=format,
                possible_transports=[to_transport],
                force_new_tree=force_new_tree,
            )
            a_controldir = branch.controldir
        else:
            from .transport.local import LocalTransport

            if a_controldir.has_branch():
                if (
                    isinstance(to_transport, LocalTransport)
                    and not a_controldir.has_workingtree()
                ):
                    raise errors.BranchExistsWithoutWorkingTree(location)
                raise errors.AlreadyBranchError(location)
            branch = a_controldir.create_branch()
            if not no_tree and not a_controldir.has_workingtree():
                a_controldir.create_workingtree()
        if append_revisions_only:
            try:
                branch.set_append_revisions_only(True)
            except errors.UpgradeRequired as exc:
                raise errors.CommandError(
                    gettext(
                        "This branch format cannot be set"
                        " to append-revisions-only.  Try --default."
                    )
                ) from exc
        if not is_quiet():
            from .info import describe_format, describe_layout

            try:
                tree = a_controldir.open_workingtree(recommend_upgrade=False)
            except (errors.NoWorkingTree, errors.NotLocalUrl):
                tree = None
            repository = branch.repository
            layout = describe_layout(repository, branch, tree).lower()
            format = describe_format(a_controldir, repository, branch, tree)
            self.outf.write(
                gettext("Created a {0} (format: {1})\n").format(layout, format)
            )
            if repository.is_shared():
                # XXX: maybe this can be refactored into transport.path_or_url()
                url = repository.controldir.root_transport.external_url()
                with contextlib.suppress(urlutils.InvalidURL):
                    url = urlutils.local_path_from_url(url)
                self.outf.write(gettext("Using shared repository: %s\n") % url)


class cmd_init_shared_repository(Command):
    __doc__ = """Create a shared repository for branches to share storage space.

    New branches created under the repository directory will store their
    revisions in the repository, not in the branch directory.  For branches
    with shared history, this reduces the amount of storage needed and
    speeds up the creation of new branches.

    If the --no-trees option is given then the branches in the repository
    will not have working trees by default.  They will still exist as
    directories on disk, but they will not have separate copies of the
    files at a certain revision.  This can be useful for repositories that
    store branches which are interacted with through checkouts or remote
    branches, such as on a server.

    :Examples:
        Create a shared repository holding just branches::

            brz init-shared-repo --no-trees repo
            brz init repo/trunk

        Make a lightweight checkout elsewhere::

            brz checkout --lightweight repo/trunk trunk-checkout
            cd trunk-checkout
            (add files here)
    """

    _see_also = ["init", "branch", "checkout", "repositories"]
    takes_args = ["location"]
    takes_options = [
        RegistryOption(
            "format",
            help="Specify a format for this repository. See"
            ' "brz help formats" for details.',
            lazy_registry=("breezy.controldir", "format_registry"),
            converter=lambda name: controldir.format_registry.make_controldir(  # type: ignore
                name
            ),
            value_switches=True,
            title="Repository format",
        ),
        Option(
            "no-trees",
            help="Branches in the repository will default to"
            " not having a working tree.",
        ),
    ]
    aliases = ["init-shared-repo", "init-repo"]

    def run(self, location, format=None, no_trees=False):
        if format is None:
            format = controldir.format_registry.make_controldir("default")

        if location is None:
            location = "."

        to_transport = transport.get_transport(location, purpose="write")

        if format.fixed_components:
            repo_format_name = None
        else:
            repo_format_name = format.repository_format.get_format_string()

        (
            repo,
            newdir,
            require_stacking,
            repository_policy,
        ) = format.initialize_on_transport_ex(
            to_transport,
            create_prefix=True,
            make_working_trees=not no_trees,
            shared_repo=True,
            force_new_repo=True,
            use_existing_dir=True,
            repo_format_name=repo_format_name,
        )
        if not is_quiet():
            from .info import show_bzrdir_info

            show_bzrdir_info(newdir, verbose=0, outfile=self.outf)


class cmd_diff(Command):
    __doc__ = """Show differences in the working tree, between revisions or branches.

    If no arguments are given, all changes for the current tree are listed.
    If files are given, only the changes in those files are listed.
    Remote and multiple branches can be compared by using the --old and
    --new options. If not provided, the default for both is derived from
    the first argument, if any, or the current tree if no arguments are
    given.

    "brz diff -p1" is equivalent to "brz diff --prefix old/:new/", and
    produces patches suitable for "patch -p1".

    Note that when using the -r argument with a range of revisions, the
    differences are computed between the two specified revisions.  That
    is, the command does not show the changes introduced by the first
    revision in the range.  This differs from the interpretation of
    revision ranges used by "brz log" which includes the first revision
    in the range.

    :Exit values:
        1 - changed
        2 - unrepresentable changes
        3 - error
        0 - no change

    :Examples:
        Shows the difference in the working tree versus the last commit::

            brz diff

        Difference between the working tree and revision 1::

            brz diff -r1

        Difference between revision 3 and revision 1::

            brz diff -r1..3

        Difference between revision 3 and revision 1 for branch xxx::

            brz diff -r1..3 xxx

        The changes introduced by revision 2 (equivalent to -r1..2)::

            brz diff -c2

        To see the changes introduced by revision X::

            brz diff -cX

        Note that in the case of a merge, the -c option shows the changes
        compared to the left hand parent. To see the changes against
        another parent, use::

            brz diff -r<chosen_parent>..X

        The changes between the current revision and the previous revision
        (equivalent to -c-1 and -r-2..-1)

            brz diff -r-2..

        Show just the differences for file NEWS::

            brz diff NEWS

        Show the differences in working tree xxx for file NEWS::

            brz diff xxx/NEWS

        Show the differences from branch xxx to this working tree:

            brz diff --old xxx

        Show the differences between two branches for file NEWS::

            brz diff --old xxx --new yyy NEWS

        Same as 'brz diff' but prefix paths with old/ and new/::

            brz diff --prefix old/:new/

        Show the differences using a custom diff program with options::

            brz diff --using /usr/bin/diff --diff-options -wu
    """
    _see_also = ["status"]
    takes_args = ["file*"]
    takes_options = [
        Option(
            "diff-options",
            type=str,
            help="Pass these options to the external diff program.",
        ),
        Option(
            "prefix",
            type=str,
            short_name="p",
            help="Set prefixes added to old and new filenames, as "
            'two values separated by a colon. (eg "old/:new/").',
        ),
        Option(
            "old",
            help="Branch/tree to compare from.",
            type=str,
        ),
        Option(
            "new",
            help="Branch/tree to compare to.",
            type=str,
        ),
        "revision",
        "change",
        Option(
            "using",
            help="Use this command to compare files.",
            type=str,
        ),
        RegistryOption(
            "format",
            short_name="F",
            help="Diff format to use.",
            lazy_registry=("breezy.diff", "format_registry"),
            title="Diff format",
        ),
        Option(
            "context",
            help="How many lines of context to show.",
            type=int,
        ),
        RegistryOption.from_kwargs(
            "color",
            help="Color mode to use.",
            title="Color Mode",
            value_switches=False,
            enum_switch=True,
            never="Never colorize output.",
            auto="Only colorize output if terminal supports it and STDOUT is a TTY.",
            always="Always colorize output (default).",
        ),
        Option(
            "check-style",
            help=("Warn if trailing whitespace or spurious changes have been  added."),
        ),
    ]

    aliases = ["di", "dif"]
    encoding_type = "exact"

    @display_command
    def run(
        self,
        revision=None,
        file_list=None,
        diff_options=None,
        prefix=None,
        old=None,
        new=None,
        using=None,
        format=None,
        context=None,
        color="auto",
    ):
        from .diff import get_trees_and_branches_to_diff_locked, show_diff_trees

        if prefix == "0":
            # diff -p0 format
            old_label = ""
            new_label = ""
        elif prefix == "1" or prefix is None:
            old_label = "old/"
            new_label = "new/"
        elif ":" in prefix:
            old_label, new_label = prefix.split(":")
        else:
            raise errors.CommandError(
                gettext(
                    '--prefix expects two values separated by a colon (eg "old/:new/")'
                )
            )

        if revision and len(revision) > 2:
            raise errors.CommandError(
                gettext(
                    "brz diff --revision takes exactly one or two revision specifiers"
                )
            )

        if using is not None and format is not None:
            raise errors.CommandError(
                gettext("{0} and {1} are mutually exclusive").format(
                    "--using", "--format"
                )
            )

        (
            old_tree,
            new_tree,
            old_branch,
            new_branch,
            specific_files,
            extra_trees,
        ) = get_trees_and_branches_to_diff_locked(
            file_list, revision, old, new, self._exit_stack, apply_view=True
        )
        # GNU diff on Windows uses ANSI encoding for filenames
        path_encoding = osutils.get_diff_header_encoding()
        outf = self.outf
        if color == "auto":
            from .terminal import has_ansi_colors

            color = "always" if has_ansi_colors() else "never"
        if color == "always":
            from .colordiff import DiffWriter

            outf = DiffWriter(outf)
        return show_diff_trees(
            old_tree,
            new_tree,
            outf,
            specific_files=specific_files,
            external_diff_options=diff_options,
            old_label=old_label,
            new_label=new_label,
            extra_trees=extra_trees,
            path_encoding=path_encoding,
            using=using,
            context=context,
            format_cls=format,
        )


class cmd_deleted(Command):
    __doc__ = """List files deleted in the working tree.
    """
    # TODO: Show files deleted since a previous revision, or
    # between two revisions.
    # TODO: Much more efficient way to do this: read in new
    # directories with readdir, rather than stating each one.  Same
    # level of effort but possibly much less IO.  (Or possibly not,
    # if the directories are very large...)
    _see_also = ["status", "ls"]
    takes_options = ["directory", "show-ids"]

    @display_command
    def run(self, show_ids=False, directory="."):
        from .workingtree import WorkingTree

        tree = WorkingTree.open_containing(directory)[0]
        self.enter_context(tree.lock_read())
        old = tree.basis_tree()
        self.enter_context(old.lock_read())
        delta = tree.changes_from(old)
        for change in delta.removed:
            self.outf.write(change.path[0])
            if show_ids:
                self.outf.write(" ")
                self.outf.write(change.file_id)
            self.outf.write("\n")


class cmd_modified(Command):
    __doc__ = """List files modified in working tree.
    """

    hidden = True
    _see_also = ["status", "ls"]
    takes_options = ["directory", "null"]

    @display_command
    def run(self, null=False, directory="."):
        from .workingtree import WorkingTree

        tree = WorkingTree.open_containing(directory)[0]
        self.enter_context(tree.lock_read())
        td = tree.changes_from(tree.basis_tree())
        self.cleanup_now()
        for change in td.modified:
            if null:
                self.outf.write(change.path[1] + "\0")
            else:
                self.outf.write(osutils.quotefn(change.path[1]) + "\n")


class cmd_added(Command):
    __doc__ = """List files added in working tree.
    """

    hidden = True
    _see_also = ["status", "ls"]
    takes_options = ["directory", "null"]

    @display_command
    def run(self, null=False, directory="."):
        from .workingtree import WorkingTree

        wt = WorkingTree.open_containing(directory)[0]
        self.enter_context(wt.lock_read())
        basis = wt.basis_tree()
        self.enter_context(basis.lock_read())
        for path in wt.all_versioned_paths():
            if basis.has_filename(path):
                continue
            if path == "":
                continue
            if not os.access(osutils.pathjoin(wt.basedir, path), os.F_OK):
                continue
            if null:
                self.outf.write(path + "\0")
            else:
                self.outf.write(osutils.quotefn(path) + "\n")


class cmd_root(Command):
    __doc__ = """Show the tree root directory.

    The root is the nearest enclosing directory with a control
    directory."""

    takes_args = ["filename?"]

    @display_command
    def run(self, filename=None):
        """Print the branch root."""
        from .workingtree import WorkingTree

        tree = WorkingTree.open_containing(filename)[0]
        self.outf.write(tree.basedir + "\n")


def _parse_limit(limitstring):
    """Parse a limit string into an integer.

    Args:
        limitstring: String representation of a limit value.

    Returns:
        Integer value of the limit.

    Raises:
        CommandError: If limitstring cannot be parsed as an integer.
    """
    try:
        return int(limitstring)
    except ValueError as exc:
        msg = gettext("The limit argument must be an integer.")
        raise errors.CommandError(msg) from exc


def _parse_levels(s):
    """Parse a levels string into an integer.

    Args:
        s: String representation of a levels value.

    Returns:
        Integer value of the levels.

    Raises:
        CommandError: If s cannot be parsed as an integer.
    """
    try:
        return int(s)
    except ValueError as exc:
        msg = gettext("The levels argument must be an integer.")
        raise errors.CommandError(msg) from exc


class cmd_log(Command):
    __doc__ = """Show historical log for a branch or subset of a branch.

    log is brz's default tool for exploring the history of a branch.
    The branch to use is taken from the first parameter. If no parameters
    are given, the branch containing the working directory is logged.
    Here are some simple examples::

      brz log                       log the current branch
      brz log foo.py                log a file in its branch
      brz log http://server/branch  log a branch on a server

    The filtering, ordering and information shown for each revision can
    be controlled as explained below. By default, all revisions are
    shown sorted (topologically) so that newer revisions appear before
    older ones and descendants always appear before ancestors. If displayed,
    merged revisions are shown indented under the revision in which they
    were merged.

    :Output control:

      The log format controls how information about each revision is
      displayed. The standard log formats are called ``long``, ``short``
      and ``line``. The default is long. See ``brz help log-formats``
      for more details on log formats.

      The following options can be used to control what information is
      displayed::

        -l N        display a maximum of N revisions
        -n N        display N levels of revisions (0 for all, 1 for collapsed)
        -v          display a status summary (delta) for each revision
        -p          display a diff (patch) for each revision
        --show-ids  display revision-ids (and file-ids), not just revnos

      Note that the default number of levels to display is a function of the
      log format. If the -n option is not used, the standard log formats show
      just the top level (mainline).

      Status summaries are shown using status flags like A, M, etc. To see
      the changes explained using words like ``added`` and ``modified``
      instead, use the -vv option.

    :Ordering control:

      To display revisions from oldest to newest, use the --forward option.
      In most cases, using this option will have little impact on the total
      time taken to produce a log, though --forward does not incrementally
      display revisions like --reverse does when it can.

    :Revision filtering:

      The -r option can be used to specify what revision or range of revisions
      to filter against. The various forms are shown below::

        -rX      display revision X
        -rX..    display revision X and later
        -r..Y    display up to and including revision Y
        -rX..Y   display from X to Y inclusive

      See ``brz help revisionspec`` for details on how to specify X and Y.
      Some common examples are given below::

        -r-1                show just the tip
        -r-10..             show the last 10 mainline revisions
        -rsubmit:..         show what's new on this branch
        -rancestor:path..   show changes since the common ancestor of this
                            branch and the one at location path
        -rdate:yesterday..  show changes since yesterday

      When logging a range of revisions using -rX..Y, log starts at
      revision Y and searches back in history through the primary
      ("left-hand") parents until it finds X. When logging just the
      top level (using -n1), an error is reported if X is not found
      along the way. If multi-level logging is used (-n0), X may be
      a nested merge revision and the log will be truncated accordingly.

    :Path filtering:

      If parameters are given and the first one is not a branch, the log
      will be filtered to show only those revisions that changed the
      nominated files or directories.

      Filenames are interpreted within their historical context. To log a
      deleted file, specify a revision range so that the file existed at
      the end or start of the range.

      Historical context is also important when interpreting pathnames of
      renamed files/directories. Consider the following example:

      * revision 1: add tutorial.txt
      * revision 2: modify tutorial.txt
      * revision 3: rename tutorial.txt to guide.txt; add tutorial.txt

      In this case:

      * ``brz log guide.txt`` will log the file added in revision 1

      * ``brz log tutorial.txt`` will log the new file added in revision 3

      * ``brz log -r2 -p tutorial.txt`` will show the changes made to
        the original file in revision 2.

      * ``brz log -r2 -p guide.txt`` will display an error message as there
        was no file called guide.txt in revision 2.

      Renames are always followed by log. By design, there is no need to
      explicitly ask for this (and no way to stop logging a file back
      until it was last renamed).

    :Other filtering:

      The --match option can be used for finding revisions that match a
      regular expression in a commit message, committer, author or bug.
      Specifying the option several times will match any of the supplied
      expressions. --match-author, --match-bugs, --match-committer and
      --match-message can be used to only match a specific field.

    :Tips & tricks:

      GUI tools and IDEs are often better at exploring history than command
      line tools: you may prefer qlog from qbzr, or the Loggerhead web
      interface.  See the Breezy
      Plugin Guide <https://www.breezy-vcs.org/doc/plugins/en/> and
      <http://wiki.breezy-vcs.org/IDEIntegration>.

      You may find it useful to add the aliases below to ``breezy.conf``::

        [ALIASES]
        tip = log -r-1
        top = log -l10 --line
        show = log -v -p

      ``brz tip`` will then show the latest revision while ``brz top``
      will show the last 10 mainline revisions. To see the details of a
      particular revision X,  ``brz show -rX``.

      If you are interested in looking deeper into a particular merge X,
      use ``brz log -n0 -rX``.

      ``brz log -v`` on a branch with lots of history is currently
      very slow. A fix for this issue is currently under development.
      With or without that fix, it is recommended that a revision range
      be given when using the -v option.

      brz has a generic full-text matching plugin, brz-search, that can be
      used to find revisions matching user names, commit messages, etc.
      Among other features, this plugin can find all revisions containing
      a list of words but not others.

      When exploring non-mainline history on large projects with deep
      history, the performance of log can be greatly improved by installing
      the historycache plugin. This plugin buffers historical information
      trading disk space for faster speed.
    """
    takes_args = ["file*"]
    _see_also = ["log-formats", "revisionspec"]
    takes_options = [
        Option("forward", help="Show from oldest to newest."),
        "timezone",
        custom_help("verbose", help="Show files changed in each revision."),
        "show-ids",
        "revision",
        Option(
            "change",
            type=breezy.option._parse_revision_str,
            short_name="c",
            help='Show just the specified revision. See also "help revisionspec".',
        ),
        "log-format",
        RegistryOption(
            "authors",
            "What names to list as authors - first, all or committer.",
            title="Authors",
            lazy_registry=("breezy.log", "author_list_registry"),
        ),
        Option(
            "levels",
            short_name="n",
            help="Number of levels to display - 0 for all, 1 for flat.",
            argname="N",
            type=_parse_levels,
        ),
        Option(
            "message",
            help="Show revisions whose message matches this regular expression.",
            type=str,
            hidden=True,
        ),
        Option(
            "limit",
            short_name="l",
            help="Limit the output to the first N revisions.",
            argname="N",
            type=_parse_limit,
        ),
        Option(
            "show-diff",
            short_name="p",
            help="Show changes made in each revision as a patch.",
        ),
        Option("include-merged", help="Show merged revisions like --levels 0 does."),
        Option(
            "include-merges", hidden=True, help="Historical alias for --include-merged."
        ),
        Option("omit-merges", help="Do not report commits with more than one parent."),
        Option(
            "exclude-common-ancestry",
            help="Display only the revisions that are not part"
            " of both ancestries (require -rX..Y).",
        ),
        Option("signatures", help="Show digital signature validity."),
        ListOption(
            "match",
            short_name="m",
            help="Show revisions whose properties match this expression.",
            type=str,
        ),
        ListOption(
            "match-message",
            help="Show revisions whose message matches this expression.",
            type=str,
        ),
        ListOption(
            "match-committer",
            help="Show revisions whose committer matches this expression.",
            type=str,
        ),
        ListOption(
            "match-author",
            help="Show revisions whose authors match this expression.",
            type=str,
        ),
        ListOption(
            "match-bugs",
            help="Show revisions whose bugs match this expression.",
            type=str,
        ),
    ]
    encoding_type = "replace"

    @display_command
    def run(
        self,
        file_list=None,
        timezone="original",
        verbose=False,
        show_ids=False,
        forward=False,
        revision=None,
        change=None,
        log_format=None,
        levels=None,
        message=None,
        limit=None,
        show_diff=False,
        include_merged=None,
        authors=None,
        exclude_common_ancestry=False,
        signatures=False,
        match=None,
        match_message=None,
        match_committer=None,
        match_author=None,
        match_bugs=None,
        omit_merges=False,
    ):
        from .log import Logger, _get_info_for_log_files, make_log_request_dict

        direction = (forward and "forward") or "reverse"
        if include_merged is None:
            include_merged = False
        if exclude_common_ancestry and (revision is None or len(revision) != 2):
            raise errors.CommandError(
                gettext("--exclude-common-ancestry requires -r with two revisions")
            )
        if include_merged:
            if levels is None:
                levels = 0
            else:
                raise errors.CommandError(
                    gettext("{0} and {1} are mutually exclusive").format(
                        "--levels", "--include-merged"
                    )
                )

        if change is not None:
            if len(change) > 1:
                raise errors.RangeInChangeOption()
            if revision is not None:
                raise errors.CommandError(
                    gettext("{0} and {1} are mutually exclusive").format(
                        "--revision", "--change"
                    )
                )
            else:
                revision = change

        files = []
        filter_by_dir = False
        if file_list:
            # find the file ids to log and check for directory filtering
            b, file_info_list, rev1, rev2 = _get_info_for_log_files(
                revision, file_list, self._exit_stack
            )
            for relpath, kind in file_info_list:
                if not kind:
                    raise errors.CommandError(
                        gettext("Path unknown at end or start of revision range: %s")
                        % relpath
                    )
                # If the relpath is the top of the tree, we log everything
                if relpath == "":
                    files = []
                    break
                else:
                    files.append(relpath)
                filter_by_dir = filter_by_dir or (
                    kind in ["directory", "tree-reference"]
                )
        else:
            # log everything
            # FIXME ? log the current subdir only RBC 20060203
            if revision is not None and len(revision) > 0 and revision[0].get_branch():
                location = revision[0].get_branch()
            else:
                location = "."
            dir, relpath = controldir.ControlDir.open_containing(location)
            b = dir.open_branch()
            self.enter_context(b.lock_read())
            rev1, rev2 = _get_revision_range(revision, b, self.name())

        if b.get_config_stack().get("validate_signatures_in_log"):
            signatures = True

        if signatures and not gpg.GPGStrategy.verify_signatures_available():
            raise errors.GpgmeNotInstalled(None)

        # Decide on the type of delta & diff filtering to use
        # TODO: add an --all-files option to make this configurable & consistent
        delta_type = None if not verbose else "full"
        if not show_diff:
            diff_type = None
        elif files:
            diff_type = "partial"
        else:
            diff_type = "full"

        # Build the log formatter
        if log_format is None:
            log_format = log.log_formatter_registry.get_default(b)
        # Make a non-encoding output to include the diffs - bug 328007
        unencoded_output = ui.ui_factory.make_output_stream(encoding_type="exact")
        lf = log_format(
            show_ids=show_ids,
            to_file=self.outf,
            to_exact_file=unencoded_output,
            show_timezone=timezone,
            delta_format=get_verbosity_level(),
            levels=levels,
            show_advice=levels is None,
            author_list_handler=authors,
        )

        # Choose the algorithm for doing the logging. It's annoying
        # having multiple code paths like this but necessary until
        # the underlying repository format is faster at generating
        # deltas or can provide everything we need from the indices.
        # The default algorithm - match-using-deltas - works for
        # multiple files and directories and is faster for small
        # amounts of history (200 revisions say). However, it's too
        # slow for logging a single file in a repository with deep
        # history, i.e. > 10K revisions. In the spirit of "do no
        # evil when adding features", we continue to use the
        # original algorithm - per-file-graph - for the "single
        # file that isn't a directory without showing a delta" case.
        partial_history = revision and b.repository._format.supports_chks
        match_using_deltas = (
            len(files) != 1 or filter_by_dir or delta_type or partial_history
        )

        match_dict = {}
        if match:
            match_dict[""] = match
        if match_message:
            match_dict["message"] = match_message
        if match_committer:
            match_dict["committer"] = match_committer
        if match_author:
            match_dict["author"] = match_author
        if match_bugs:
            match_dict["bugs"] = match_bugs

        # Build the LogRequest and execute it
        if len(files) == 0:
            files = None
        rqst = make_log_request_dict(
            direction=direction,
            specific_files=files,
            start_revision=rev1,
            end_revision=rev2,
            limit=limit,
            message_search=message,
            delta_type=delta_type,
            diff_type=diff_type,
            _match_using_deltas=match_using_deltas,
            exclude_common_ancestry=exclude_common_ancestry,
            match=match_dict,
            signature=signatures,
            omit_merges=omit_merges,
        )
        Logger(b, rqst).show(lf)


def _get_revision_range(revisionspec_list, branch, command_name):
    """Take the input of a revision option and turn it into a revision range.

    It returns RevisionInfo objects which can be used to obtain the rev_id's
    of the desired revisions. It does some user input validations.
    """
    if revisionspec_list is None:
        rev1 = None
        rev2 = None
    elif len(revisionspec_list) == 1:
        rev1 = rev2 = revisionspec_list[0].in_history(branch)
    elif len(revisionspec_list) == 2:
        start_spec = revisionspec_list[0]
        end_spec = revisionspec_list[1]
        if end_spec.get_branch() != start_spec.get_branch():
            # b is taken from revision[0].get_branch(), and
            # show_log will use its revision_history. Having
            # different branches will lead to weird behaviors.
            raise errors.CommandError(
                gettext("brz %s doesn't accept two revisions in different branches.")
                % command_name
            )
        if start_spec.spec is None:
            # Avoid loading all the history.
            rev1 = RevisionInfo(branch, None, None)
        else:
            rev1 = start_spec.in_history(branch)
        # Avoid loading all of history when we know a missing
        # end of range means the last revision ...
        if end_spec.spec is None:
            last_revno, last_revision_id = branch.last_revision_info()
            rev2 = RevisionInfo(branch, last_revno, last_revision_id)
        else:
            rev2 = end_spec.in_history(branch)
    else:
        raise errors.CommandError(
            gettext("brz %s --revision takes one or two values.") % command_name
        )
    return rev1, rev2


def _revision_range_to_revid_range(revision_range):
    """Convert a revision range to a revision ID range.

    Args:
        revision_range: Tuple of (start_revision, end_revision), where each
            revision may be None or a revision object with rev_id attribute.

    Returns:
        Tuple of (start_rev_id, end_rev_id) where each may be None.
    """
    rev_id1 = None
    rev_id2 = None
    if revision_range[0] is not None:
        rev_id1 = revision_range[0].rev_id
    if revision_range[1] is not None:
        rev_id2 = revision_range[1].rev_id
    return rev_id1, rev_id2


def get_log_format(long=False, short=False, line=False, default="long"):
    """Determine log format based on boolean flags.

    Args:
        long: If True, use 'long' format.
        short: If True, use 'short' format.
        line: If True, use 'line' format.
        default: Default format to use if no flags are set.

    Returns:
        String indicating the selected log format. Format flags are
        processed in order: long, short, then line. Later flags override
        earlier ones.
    """
    log_format = default
    if long:
        log_format = "long"
    if short:
        log_format = "short"
    if line:
        log_format = "line"
    return log_format


class cmd_touching_revisions(Command):
    __doc__ = """Return revision-ids which affected a particular file.

    A more user-friendly interface is "brz log FILE".
    """

    hidden = True
    takes_args = ["filename"]

    @display_command
    def run(self, filename):
        from .workingtree import WorkingTree

        tree, relpath = WorkingTree.open_containing(filename)
        with tree.lock_read():
            touching_revs = log.find_touching_revisions(
                tree.branch.repository, tree.branch.last_revision(), tree, relpath
            )
            for revno, _revision_id, what in reversed(list(touching_revs)):
                self.outf.write("%6d %s\n" % (revno, what))


class cmd_ls(Command):
    __doc__ = """List files in a tree.
    """

    _see_also = ["status", "cat"]
    takes_args = ["path?"]
    takes_options = [
        "verbose",
        "revision",
        Option("recursive", short_name="R", help="Recurse into subdirectories."),
        Option("from-root", help="Print paths relative to the root of the branch."),
        Option("unknown", short_name="u", help="Print unknown files."),
        Option("versioned", help="Print versioned files.", short_name="V"),
        Option("ignored", short_name="i", help="Print ignored files."),
        Option(
            "kind",
            short_name="k",
            help=(
                "List entries of a particular kind: file, "
                "directory, symlink, tree-reference."
            ),
            type=str,
        ),
        "null",
        "show-ids",
        "directory",
    ]

    @display_command
    def run(
        self,
        revision=None,
        verbose=False,
        recursive=False,
        from_root=False,
        unknown=False,
        versioned=False,
        ignored=False,
        null=False,
        kind=None,
        show_ids=False,
        path=None,
        directory=None,
    ):
        from . import views
        from .workingtree import WorkingTree

        if kind and kind not in ("file", "directory", "symlink", "tree-reference"):
            raise errors.CommandError(gettext("invalid kind specified"))

        if verbose and null:
            raise errors.CommandError(gettext("Cannot set both --verbose and --null"))
        all = not (unknown or versioned or ignored)

        selection = {"I": ignored, "?": unknown, "V": versioned}

        if path is None:
            fs_path = "."
        else:
            if from_root:
                raise errors.CommandError(
                    gettext("cannot specify both --from-root and PATH")
                )
            fs_path = path
        tree, branch, relpath = _open_directory_or_containing_tree_or_branch(
            fs_path, directory
        )

        # Calculate the prefix to use
        prefix = None
        if from_root:
            if relpath:
                prefix = relpath + "/"
        elif fs_path != "." and not fs_path.endswith("/"):
            prefix = fs_path + "/"

        if revision is not None or tree is None:
            tree = _get_one_revision_tree("ls", revision, branch=branch)

        apply_view = False
        if isinstance(tree, WorkingTree) and tree.supports_views():
            view_files = tree.views.lookup_view()
            if view_files:
                apply_view = True
                view_str = views.view_display_str(view_files)
                note(gettext("Ignoring files outside view. View is %s") % view_str)

        self.enter_context(tree.lock_read())
        for fp, fc, fkind, entry in tree.list_files(
            include_root=False, from_dir=relpath, recursive=recursive
        ):
            # Apply additional masking
            if not all and not selection[fc]:
                continue
            if kind is not None and fkind != kind:
                continue
            if apply_view:
                try:
                    fullpath = osutils.pathjoin(relpath, fp) if relpath else fp
                    views.check_path_in_view(tree, fullpath)
                except views.FileOutsideView:
                    continue

            # Output the entry
            if prefix:
                fp = osutils.pathjoin(prefix, fp)
            kindch = entry.kind_character()
            outstring = fp + kindch
            ui.ui_factory.clear_term()
            if verbose:
                outstring = "%-8s %s" % (fc, outstring)
                if show_ids and getattr(entry, "file_id", None) is not None:
                    outstring = "%-50s %s" % (outstring, entry.file_id.decode("utf-8"))
                self.outf.write(outstring + "\n")
            elif null:
                self.outf.write(fp + "\0")
                if show_ids:
                    if getattr(entry, "file_id", None) is not None:
                        self.outf.write(entry.file_id.decode("utf-8"))
                    self.outf.write("\0")
                self.outf.flush()
            else:
                if show_ids:
                    if getattr(entry, "file_id", None) is not None:
                        my_id = entry.file_id.decode("utf-8")
                    else:
                        my_id = ""
                    self.outf.write("%-50s %s\n" % (outstring, my_id))
                else:
                    self.outf.write(outstring + "\n")


class cmd_unknowns(Command):
    __doc__ = """List unknown files.
    """

    hidden = True
    _see_also = ["ls"]
    takes_options = ["directory"]

    @display_command
    def run(self, directory="."):
        from .workingtree import WorkingTree

        for f in WorkingTree.open_containing(directory)[0].unknowns():
            self.outf.write(osutils.quotefn(f) + "\n")


class cmd_ignore(Command):
    __doc__ = """Ignore specified files or patterns.

    See ``brz help patterns`` for details on the syntax of patterns.

    If a .bzrignore file does not exist, the ignore command
    will create one and add the specified files or patterns to the newly
    created file. The ignore command will also automatically add the
    .bzrignore file to be versioned. Creating a .bzrignore file without
    the use of the ignore command will require an explicit add command.

    To remove patterns from the ignore list, edit the .bzrignore file.
    After adding, editing or deleting that file either indirectly by
    using this command or directly by using an editor, be sure to commit
    it.

    Breezy also supports a global ignore file ~/.config/breezy/ignore. On
    Windows the global ignore file can be found in the application data
    directory as
    C:\\Documents and Settings\\<user>\\Application Data\\Breezy\\3.0\\ignore.
    Global ignores are not touched by this command. The global ignore file
    can be edited directly using an editor.

    Patterns prefixed with '!' are exceptions to ignore patterns and take
    precedence over regular ignores.  Such exceptions are used to specify
    files that should be versioned which would otherwise be ignored.

    Patterns prefixed with '!!' act as regular ignore patterns, but have
    precedence over the '!' exception patterns.

    :Notes:

    * Ignore patterns containing shell wildcards must be quoted from
      the shell on Unix.

    * Ignore patterns starting with "#" act as comments in the ignore file.
      To ignore patterns that begin with that character, use the "RE:" prefix.

    :Examples:
        Ignore the top level Makefile::

            brz ignore ./Makefile

        Ignore .class files in all directories...::

            brz ignore "*.class"

        ...but do not ignore "special.class"::

            brz ignore "!special.class"

        Ignore files whose name begins with the "#" character::

            brz ignore "RE:^#"

        Ignore .o files under the lib directory::

            brz ignore "lib/**/*.o"

        Ignore .o files under the lib directory::

            brz ignore "RE:lib/.*\\.o"

        Ignore everything but the "debian" toplevel directory::

            brz ignore "RE:(?!debian/).*"

        Ignore everything except the "local" toplevel directory,
        but always ignore autosave files ending in ~, even under local/::

            brz ignore "*"
            brz ignore "!./local"
            brz ignore "!!*~"
    """

    _see_also = ["status", "ignored", "patterns"]
    takes_args = ["name_pattern*"]
    takes_options = [
        "directory",
        Option("default-rules", help="Display the default ignore rules that brz uses."),
    ]

    def run(self, name_pattern_list=None, default_rules=None, directory="."):
        from breezy import ignores

        from . import globbing, lazy_regex
        from .workingtree import WorkingTree

        if default_rules is not None:
            # dump the default rules and exit
            for pattern in ignores.USER_DEFAULTS:
                self.outf.write(f"{pattern}\n")
            return
        if not name_pattern_list:
            raise errors.CommandError(
                gettext("ignore requires at least one NAME_PATTERN or --default-rules.")
            )
        name_pattern_list = [globbing.normalize_pattern(p) for p in name_pattern_list]
        bad_patterns = ""
        bad_patterns_count = 0
        for p in name_pattern_list:
            if not globbing.Globster.is_pattern_valid(p):
                bad_patterns_count += 1
                bad_patterns += f"\n  {p}"
        if bad_patterns:
            msg = (
                ngettext(
                    "Invalid ignore pattern found. %s",
                    "Invalid ignore patterns found. %s",
                    bad_patterns_count,
                )
                % bad_patterns
            )
            ui.ui_factory.show_error(msg)
            raise lazy_regex.InvalidPattern("")
        for name_pattern in name_pattern_list:
            if name_pattern[0] == "/" or (
                len(name_pattern) > 1 and name_pattern[1] == ":"
            ):
                raise errors.CommandError(
                    gettext("NAME_PATTERN should not be an absolute path")
                )
        tree, relpath = WorkingTree.open_containing(directory)
        ignores.tree_ignores_add_patterns(tree, name_pattern_list)
        ignored = globbing.Globster(name_pattern_list)
        matches = []
        self.enter_context(tree.lock_read())
        for filename, _fc, _fkind, entry in tree.list_files():
            id = getattr(entry, "file_id", None)
            if id is not None and ignored.match(filename):
                matches.append(filename)
        if len(matches) > 0:
            self.outf.write(
                gettext(
                    "Warning: the following files are version "
                    "controlled and match your ignore pattern:\n%s"
                    "\nThese files will continue to be version controlled"
                    " unless you 'brz remove' them.\n"
                )
                % ("\n".join(matches),)
            )


class cmd_ignored(Command):
    __doc__ = """List ignored files and the patterns that matched them.

    List all the ignored files and the ignore pattern that caused the file to
    be ignored.

    Alternatively, to list just the files::

        brz ls --ignored
    """

    encoding_type = "replace"
    _see_also = ["ignore", "ls"]
    takes_options = ["directory"]

    @display_command
    def run(self, directory="."):
        from .workingtree import WorkingTree

        tree = WorkingTree.open_containing(directory)[0]
        self.enter_context(tree.lock_read())
        for path, file_class, _kind, _entry in tree.list_files():
            if file_class != "I":
                continue
            # XXX: Slightly inefficient since this was already calculated
            pat = tree.is_ignored(path)
            self.outf.write("%-50s %s\n" % (path, pat))


class cmd_lookup_revision(Command):
    __doc__ = """Lookup the revision-id from a revision-number

    :Examples:
        brz lookup-revision 33
    """
    hidden = True
    takes_args = ["revno"]
    takes_options = ["directory"]

    @display_command
    def run(self, revno, directory="."):
        from .workingtree import WorkingTree

        try:
            revno = int(revno)
        except ValueError as exc:
            raise errors.CommandError(
                gettext("not a valid revision-number: %r") % revno
            ) from exc
        revid = WorkingTree.open_containing(directory)[0].branch.get_rev_id(revno)
        self.outf.write(f"{revid.decode('utf-8')}\n")


class cmd_export(Command):
    __doc__ = """Export current or past revision to a destination directory or archive.

    If no revision is specified this exports the last committed revision.

    Format may be an "exporter" name, such as tar, tgz, tbz2.  If none is
    given, try to find the format with the extension. If no extension
    is found exports to a directory (equivalent to --format=dir).

    If root is supplied, it will be used as the root directory inside
    container formats (tar, zip, etc). If it is not supplied it will default
    to the exported filename. The root option has no effect for 'dir' format.

    If branch is omitted then the branch containing the current working
    directory will be used.

    Note: Export of tree with non-ASCII filenames to zip is not supported.

      =================       =========================
      Supported formats       Autodetected by extension
      =================       =========================
         dir                         (none)
         tar                          .tar
         tbz2                    .tar.bz2, .tbz2
         tgz                      .tar.gz, .tgz
         zip                          .zip
      =================       =========================
    """
    encoding = "exact"
    encoding_type = "exact"
    takes_args = ["dest", "branch_or_subdir?"]
    takes_options = [
        "directory",
        Option("format", help="Type of file to export to.", type=str),
        "revision",
        Option("filters", help="Apply content filters to export the convenient form."),
        Option(
            "root",
            type=str,
            help="Name of the root directory inside the exported file.",
        ),
        Option(
            "per-file-timestamps",
            help="Set modification time of files to that of the last "
            "revision in which it was changed.",
        ),
        Option(
            "uncommitted",
            help="Export the working tree contents rather than that of the "
            "last revision.",
        ),
        Option("recurse-nested", help="Include contents of nested trees."),
    ]

    def run(
        self,
        dest,
        branch_or_subdir=None,
        revision=None,
        format=None,
        root=None,
        filters=False,
        per_file_timestamps=False,
        uncommitted=False,
        directory=".",
        recurse_nested=False,
    ):
        from .export import export, get_root_name, guess_format

        if branch_or_subdir is None:
            branch_or_subdir = directory

        (tree, b, subdir) = controldir.ControlDir.open_containing_tree_or_branch(
            branch_or_subdir
        )
        if tree is not None:
            self.enter_context(tree.lock_read())

        if uncommitted:
            if tree is None:
                raise errors.CommandError(
                    gettext("--uncommitted requires a working tree")
                )
            export_tree = tree
        else:
            export_tree = _get_one_revision_tree(
                "export", revision, branch=b, tree=tree
            )

        if format is None:
            format = guess_format(dest)

        if root is None:
            root = get_root_name(dest)

        if not per_file_timestamps:
            time.time()
        else:
            pass

        if filters:
            from .filter_tree import ContentFilterTree

            export_tree = ContentFilterTree(
                export_tree, export_tree._content_filter_stack
            )

        try:
            export(
                export_tree,
                dest,
                format,
                root,
                subdir,
                per_file_timestamps=per_file_timestamps,
                recurse_nested=recurse_nested,
            )
        except errors.NoSuchExportFormat as exc:
            raise errors.CommandError(
                gettext("Unsupported export format: %s") % exc.format
            ) from exc


class cmd_cat(Command):
    __doc__ = """Write the contents of a file as of a given revision to standard output.

    If no revision is nominated, the last revision is used.

    Note: Take care to redirect standard output when using this command on a
    binary file.
    """

    _see_also = ["ls"]
    takes_options = [
        "directory",
        Option("name-from-revision", help="The path name in the old tree."),
        Option(
            "filters", help="Apply content filters to display the convenience form."
        ),
        "revision",
    ]
    takes_args = ["filename"]
    encoding_type = "exact"

    @display_command
    def run(
        self,
        filename,
        revision=None,
        name_from_revision=False,
        filters=False,
        directory=None,
    ):
        if revision is not None and len(revision) != 1:
            raise errors.CommandError(
                gettext("brz cat --revision takes exactly one revision specifier")
            )
        tree, branch, relpath = _open_directory_or_containing_tree_or_branch(
            filename, directory
        )
        self.enter_context(branch.lock_read())
        return self._run(
            tree, branch, relpath, filename, revision, name_from_revision, filters
        )

    def _run(self, tree, b, relpath, filename, revision, name_from_revision, filtered):
        import shutil

        if tree is None:
            tree = b.basis_tree()
        rev_tree = _get_one_revision_tree("cat", revision, branch=b)
        self.enter_context(rev_tree.lock_read())

        if name_from_revision:
            # Try in revision if requested
            if not rev_tree.is_versioned(relpath):
                raise errors.CommandError(
                    gettext("{0!r} is not present in revision {1}").format(
                        filename, rev_tree.get_revision_id()
                    )
                )
            rev_tree_path = relpath
        else:
            try:
                rev_tree_path = _mod_tree.find_previous_path(tree, rev_tree, relpath)
            except transport.NoSuchFile:
                rev_tree_path = None

            if rev_tree_path is None:
                # Path didn't exist in working tree
                if not rev_tree.is_versioned(relpath):
                    raise errors.CommandError(
                        gettext("{0!r} is not present in revision {1}").format(
                            filename, rev_tree.get_revision_id()
                        )
                    )
                else:
                    # Fall back to the same path in the basis tree, if present.
                    rev_tree_path = relpath

        if filtered:
            from .filter_tree import ContentFilterTree

            filter_tree = ContentFilterTree(rev_tree, rev_tree._content_filter_stack)
            fileobj = filter_tree.get_file(rev_tree_path)
        else:
            fileobj = rev_tree.get_file(rev_tree_path)
        shutil.copyfileobj(fileobj, self.outf)
        self.cleanup_now()


class cmd_local_time_offset(Command):
    __doc__ = """Show the offset in seconds from GMT to local time."""
    hidden = True

    @display_command
    def run(self):
        self.outf.write(f"{osutils.local_time_offset()}\n")


class cmd_commit(Command):
    __doc__ = """Commit changes into a new revision.

    An explanatory message needs to be given for each commit. This is
    often done by using the --message option (getting the message from the
    command line) or by using the --file option (getting the message from
    a file). If neither of these options is given, an editor is opened for
    the user to enter the message. To see the changed files in the
    boilerplate text loaded into the editor, use the --show-diff option.

    By default, the entire tree is committed and the person doing the
    commit is assumed to be the author. These defaults can be overridden
    as explained below.

    :Selective commits:

      If selected files are specified, only changes to those files are
      committed.  If a directory is specified then the directory and
      everything within it is committed.

      When excludes are given, they take precedence over selected files.
      For example, to commit only changes within foo, but not changes
      within foo/bar::

        brz commit foo -x foo/bar

      A selective commit after a merge is not yet supported.

    :Custom authors:

      If the author of the change is not the same person as the committer,
      you can specify the author's name using the --author option. The
      name should be in the same format as a committer-id, e.g.
      "John Doe <jdoe@example.com>". If there is more than one author of
      the change you can specify the option multiple times, once for each
      author.

    :Checks:

      A common mistake is to forget to add a new file or directory before
      running the commit command. The --strict option checks for unknown
      files and aborts the commit if any are found. More advanced pre-commit
      checks can be implemented by defining hooks. See ``brz help hooks``
      for details.

    :Things to note:

      If you accidentally commit the wrong changes or make a spelling
      mistake in the commit message say, you can use the uncommit command
      to undo it. See ``brz help uncommit`` for details.

      Hooks can also be configured to run after a commit. This allows you
      to trigger updates to external systems like bug trackers. The --fixes
      option can be used to record the association between a revision and
      one or more bugs. See ``brz help bugs`` for details.
    """

    _see_also = ["add", "bugs", "hooks", "uncommit"]
    takes_args = ["selected*"]
    takes_options = [
        ListOption(
            "exclude",
            type=str,
            short_name="x",
            help="Do not consider changes made to a given path.",
        ),
        Option(
            "message", type=str, short_name="m", help="Description of the new revision."
        ),
        "verbose",
        Option("unchanged", help="Commit even if nothing has changed."),
        Option(
            "file",
            type=str,
            short_name="F",
            argname="msgfile",
            help="Take commit message from this file.",
        ),
        Option(
            "strict",
            help="Refuse to commit if there are unknown files in the working tree.",
        ),
        Option(
            "commit-time",
            type=str,
            help="Manually set a commit time using commit date "
            "format, e.g. '2009-10-10 08:00:00 +0100'.",
        ),
        ListOption(
            "bugs", type=str, help='Link to a related bug. (see "brz help bugs").'
        ),
        ListOption(
            "fixes",
            type=str,
            help='Mark a bug as being fixed by this revision (see "brz help bugs").',
        ),
        ListOption(
            "author",
            type=str,
            help="Set the author's name, if it's different from the committer.",
        ),
        Option(
            "local",
            help="Perform a local commit in a bound "
            "branch.  Local commits are not pushed to "
            "the master branch until a normal commit "
            "is performed.",
        ),
        Option(
            "show-diff",
            short_name="p",
            help="When no message is supplied, show the diff along"
            " with the status summary in the message editor.",
        ),
        Option(
            "lossy",
            help="When committing to a foreign version control "
            "system do not push data that can not be natively "
            "represented.",
        ),
    ]
    aliases = ["ci", "checkin"]

    def _iter_bug_urls(self, bugs, branch, status):
        default_bugtracker = None
        # Configure the properties for bug fixing attributes.
        for bug in bugs:
            tokens = bug.split(":")
            if len(tokens) == 1:
                if default_bugtracker is None:
                    branch_config = branch.get_config_stack()
                    default_bugtracker = branch_config.get("bugtracker")
                if default_bugtracker is None:
                    raise errors.CommandError(
                        gettext(
                            "No tracker specified for bug %s. Use the form "
                            "'tracker:id' or specify a default bug tracker "
                            "using the `bugtracker` option.\nSee "
                            '"brz help bugs" for more information on this '
                            "feature. Commit refused."
                        )
                        % bug
                    )
                tag = default_bugtracker
                bug_id = tokens[0]
            elif len(tokens) != 2:
                raise errors.CommandError(
                    gettext(
                        "Invalid bug %s. Must be in the form of 'tracker:id'. "
                        'See "brz help bugs" for more information on this '
                        "feature.\nCommit refused."
                    )
                    % bug
                )
            else:
                tag, bug_id = tokens
            try:
                yield bugtracker.get_bug_url(tag, branch, bug_id), status
            except bugtracker.UnknownBugTrackerAbbreviation as exc:
                raise errors.CommandError(
                    gettext("Unrecognized bug %s. Commit refused.") % bug
                ) from exc
            except bugtracker.MalformedBugIdentifier as exc:
                raise errors.CommandError(
                    gettext("%s\nCommit refused.") % (exc,)
                ) from exc

    def run(
        self,
        message=None,
        file=None,
        verbose=False,
        selected_list=None,
        unchanged=False,
        strict=False,
        local=False,
        fixes=None,
        bugs=None,
        author=None,
        show_diff=False,
        exclude=None,
        commit_time=None,
        lossy=False,
    ):
        import itertools

        from .commit import PointlessCommit
        from .errors import ConflictsInTree, StrictCommitFailed
        from .msgeditor import (
            edit_commit_message_encoded,
            generate_commit_message_template,
            make_commit_message_template_encoded,
            set_commit_message,
        )
        from .workingtree import WorkingTree

        commit_stamp = offset = None
        if commit_time is not None:
            try:
                commit_stamp, offset = patch.parse_patch_date(commit_time)
            except ValueError as exc:
                raise errors.CommandError(
                    gettext("Could not parse --commit-time: " + str(exc))
                ) from exc

        properties = {}

        tree, selected_list = WorkingTree.open_containing_paths(selected_list)
        if selected_list == [""]:
            # workaround - commit of root of tree should be exactly the same
            # as just default commit in that tree, and succeed even though
            # selected-file merge commit is not done yet
            selected_list = []

        if fixes is None:
            fixes = []
        if bugs is None:
            bugs = []
        bug_property = bugtracker.encode_fixes_bug_urls(
            itertools.chain(
                self._iter_bug_urls(bugs, tree.branch, bugtracker.RELATED),
                self._iter_bug_urls(fixes, tree.branch, bugtracker.FIXED),
            )
        )
        if bug_property:
            properties["bugs"] = bug_property

        if local and not tree.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        if message is not None:
            try:
                file_exists = osutils.lexists(message)
            except UnicodeError:
                # The commit message contains unicode characters that can't be
                # represented in the filesystem encoding, so that can't be a
                # file.
                file_exists = False
            if file_exists:
                warning_msg = (
                    f'The commit message is a file name: "{message}".\n'
                    f'(use --file "{message}" to take commit message from that file)'
                )
                ui.ui_factory.show_warning(warning_msg)
            if "\r" in message:
                message = message.replace("\r\n", "\n")
                message = message.replace("\r", "\n")
            if file:
                raise errors.CommandError(
                    gettext("please specify either --message or --file")
                )

        def get_message(commit_obj):
            """Callback to get commit message."""
            if file:
                with open(file, "rb") as f:
                    my_message = f.read().decode(osutils.get_user_encoding())
            elif message is not None:
                my_message = message
            else:
                # No message supplied: make one up.
                # text is the status of the tree
                text = make_commit_message_template_encoded(
                    tree,
                    selected_list,
                    diff=show_diff,
                    output_encoding=osutils.get_user_encoding(),
                )
                # start_message is the template generated from hooks
                # XXX: Warning - looks like hooks return unicode,
                # make_commit_message_template_encoded returns user encoding.
                # We probably want to be using edit_commit_message instead to
                # avoid this.
                my_message = set_commit_message(commit_obj)
                if my_message is None:
                    start_message = generate_commit_message_template(commit_obj)
                    if start_message is not None:
                        start_message = start_message.encode(
                            osutils.get_user_encoding()
                        )
                    my_message = edit_commit_message_encoded(
                        text, start_message=start_message
                    )
                if my_message is None:
                    raise errors.CommandError(
                        gettext(
                            "please specify a commit"
                            " message with either --message or --file"
                        )
                    )
                if my_message == "":
                    raise errors.CommandError(
                        gettext(
                            "Empty commit message specified."
                            " Please specify a commit message with either"
                            " --message or --file or leave a blank message"
                            ' with --message "".'
                        )
                    )
            return my_message

        # The API permits a commit with a filter of [] to mean 'select nothing'
        # but the command line should not do that.
        if not selected_list:
            selected_list = None
        try:
            tree.commit(
                message_callback=get_message,
                specific_files=selected_list,
                allow_pointless=unchanged,
                strict=strict,
                local=local,
                reporter=None,
                verbose=verbose,
                revprops=properties,
                authors=author,
                timestamp=commit_stamp,
                timezone=offset,
                exclude=tree.safe_relpath_files(exclude),
                lossy=lossy,
            )
        except PointlessCommit as exc:
            raise errors.CommandError(
                gettext(
                    "No changes to commit."
                    " Please 'brz add' the files you want to commit, or use"
                    " --unchanged to force an empty commit."
                )
            ) from exc
        except ConflictsInTree as exc:
            raise errors.CommandError(
                gettext(
                    "Conflicts detected in working "
                    'tree.  Use "brz conflicts" to list, "brz resolve FILE" to'
                    " resolve."
                )
            ) from exc
        except StrictCommitFailed as exc:
            raise errors.CommandError(
                gettext(
                    "Commit refused because there are"
                    " unknown files in the working tree."
                )
            ) from exc
        except errors.BoundBranchOutOfDate as exc:
            exc.extra_help = gettext(
                "\n"
                "To commit to master branch, run update and then commit.\n"
                "You can also pass --local to commit to continue working "
                "disconnected."
            )
            raise


class cmd_check(Command):
    __doc__ = """Validate working tree structure, branch consistency and repository history.

    This command checks various invariants about branch and repository storage
    to detect data corruption or brz bugs.

    The working tree and branch checks will only give output if a problem is
    detected. The output fields of the repository check are:

    revisions
        This is just the number of revisions checked.  It doesn't
        indicate a problem.

    versionedfiles
        This is just the number of versionedfiles checked.  It
        doesn't indicate a problem.

    unreferenced ancestors
        Texts that are ancestors of other texts, but
        are not properly referenced by the revision ancestry.  This is a
        subtle problem that Breezy can work around.

    unique file texts
        This is the total number of unique file contents
        seen in the checked revisions.  It does not indicate a problem.

    repeated file texts
        This is the total number of repeated texts seen
        in the checked revisions.  Texts can be repeated when their file
        entries are modified, but the file contents are not.  It does not
        indicate a problem.

    If no restrictions are specified, all data that is found at the given
    location will be checked.

    :Examples:

        Check the tree and branch at 'foo'::

            brz check --tree --branch foo

        Check only the repository at 'bar'::

            brz check --repo bar

        Check everything at 'baz'::

            brz check baz
    """

    _see_also = ["reconcile"]
    takes_args = ["path?"]
    takes_options = [
        "verbose",
        Option("branch", help="Check the branch related to the current directory."),
        Option("repo", help="Check the repository related to the current directory."),
        Option("tree", help="Check the working tree related to the current directory."),
    ]

    def run(self, path=None, verbose=False, branch=False, repo=False, tree=False):
        from .check import check_dwim

        if path is None:
            path = "."
        if not branch and not repo and not tree:
            branch = repo = tree = True
        check_dwim(path, verbose, do_branch=branch, do_repo=repo, do_tree=tree)


class cmd_upgrade(Command):
    __doc__ = """Upgrade a repository, branch or working tree to a newer format.

    When the default format has changed after a major new release of
    Bazaar/Breezy, you may be informed during certain operations that you
    should upgrade. Upgrading to a newer format may improve performance
    or make new features available. It may however limit interoperability
    with older repositories or with older versions of Bazaar or Breezy.

    If you wish to upgrade to a particular format rather than the
    current default, that can be specified using the --format option.
    As a consequence, you can use the upgrade command this way to
    "downgrade" to an earlier format, though some conversions are
    a one way process (e.g. changing from the 1.x default to the
    2.x default) so downgrading is not always possible.

    A backup.bzr.~#~ directory is created at the start of the conversion
    process (where # is a number). By default, this is left there on
    completion. If the conversion fails, delete the new .bzr directory
    and rename this one back in its place. Use the --clean option to ask
    for the backup.bzr directory to be removed on successful conversion.
    Alternatively, you can delete it by hand if everything looks good
    afterwards.

    If the location given is a shared repository, dependent branches
    are also converted provided the repository converts successfully.
    If the conversion of a branch fails, remaining branches are still
    tried.

    For more information on upgrades, see the Breezy Upgrade Guide,
    https://www.breezy-vcs.org/doc/en/upgrade-guide/.
    """

    _see_also = ["check", "reconcile", "formats"]
    takes_args = ["url?"]
    takes_options = [
        RegistryOption(
            "format",
            help='Upgrade to a specific format.  See "brz help formats" for details.',
            lazy_registry=("breezy.controldir", "format_registry"),
            converter=lambda name: controldir.format_registry.make_controldir(  # type: ignore
                name
            ),
            value_switches=True,
            title="Branch format",
        ),
        Option("clean", help="Remove the backup.bzr directory if successful."),
        Option(
            "dry-run", help="Show what would be done, but don't actually do anything."
        ),
    ]

    def run(self, url=".", format=None, clean=False, dry_run=False):
        from .upgrade import upgrade

        exceptions = upgrade(url, format, clean_up=clean, dry_run=dry_run)
        if exceptions:
            if len(exceptions) == 1:
                # Compatibility with historical behavior
                raise exceptions[0]
            else:
                return 3


class cmd_whoami(Command):
    __doc__ = """Show or set brz user id.

    :Examples:
        Show the email of the current user::

            brz whoami --email

        Set the current user::

            brz whoami "Frank Chu <fchu@example.com>"
    """
    takes_options = [
        "directory",
        Option("email", help="Display email address only."),
        Option(
            "branch", help="Set identity for the current branch instead of globally."
        ),
    ]
    takes_args = ["name?"]
    encoding_type = "replace"

    @display_command
    def run(self, email=False, branch=False, name=None, directory=None):
        if name is None:
            if directory is None:
                # use branch if we're inside one; otherwise global config
                try:
                    c = Branch.open_containing(".")[0].get_config_stack()
                except errors.NotBranchError:
                    c = _mod_config.GlobalStack()
            else:
                c = Branch.open(directory).get_config_stack()
            identity = c.get("email")
            if email:
                self.outf.write(_mod_config.extract_email_address(identity) + "\n")
            else:
                self.outf.write(identity + "\n")
            return

        if email:
            raise errors.CommandError(
                gettext("--email can only be used to display existing identity")
            )

        # display a warning if an email address isn't included in the given name.
        try:
            _mod_config.extract_email_address(name)
        except _mod_config.NoEmailInUsername:
            warning(
                '"%s" does not seem to contain an email address.  '
                "This is allowed, but not recommended.",
                name,
            )

        # use global config unless --branch given
        if branch:
            if directory is None:
                c = Branch.open_containing(".")[0].get_config_stack()
            else:
                b = Branch.open(directory)
                self.enter_context(b.lock_write())
                c = b.get_config_stack()
        else:
            c = _mod_config.GlobalStack()
        c.set("email", name)


class cmd_nick(Command):
    __doc__ = """Print or set the branch nickname.

    If unset, the colocated branch name is used for colocated branches, and
    the branch directory name is used for other branches.  To print the
    current nickname, execute with no argument.

    Bound branches use the nickname of its master branch unless it is set
    locally.
    """

    _see_also = ["info"]
    takes_args = ["nickname?"]
    takes_options = ["directory"]

    def run(self, nickname=None, directory="."):
        branch = Branch.open_containing(directory)[0]
        if nickname is None:
            self.printme(branch)
        else:
            branch.nick = nickname

    @display_command
    def printme(self, branch):
        self.outf.write(f"{branch.nick}\n")


class cmd_alias(Command):
    __doc__ = """Set/unset and display aliases.

    :Examples:
        Show the current aliases::

            brz alias

        Show the alias specified for 'll'::

            brz alias ll

        Set an alias for 'll'::

            brz alias ll="log --line -r-10..-1"

        To remove an alias for 'll'::

            brz alias --remove ll

    """
    takes_args = ["name?"]
    takes_options = [
        Option("remove", help="Remove the alias."),
    ]

    def run(self, name=None, remove=False):
        if remove:
            self.remove_alias(name)
        elif name is None:
            self.print_aliases()
        else:
            equal_pos = name.find("=")
            if equal_pos == -1:
                self.print_alias(name)
            else:
                self.set_alias(name[:equal_pos], name[equal_pos + 1 :])

    def remove_alias(self, alias_name):
        if alias_name is None:
            raise errors.CommandError(
                gettext("brz alias --remove expects an alias to remove.")
            )
        # If alias is not found, print something like:
        # unalias: foo: not found
        c = _mod_config.GlobalConfig()
        c.unset_alias(alias_name)

    @display_command
    def print_aliases(self):
        """Print out the defined aliases in a similar format to bash."""
        aliases = _mod_config.GlobalConfig().get_aliases()
        for key, value in sorted(aliases.items()):
            self.outf.write(f'brz alias {key}="{value}"\n')

    @display_command
    def print_alias(self, alias_name):
        from .commands import get_alias

        alias = get_alias(alias_name)
        if alias is None:
            self.outf.write(f"brz alias: {alias_name}: not found\n")
        else:
            self.outf.write(f'brz alias {alias_name}="{" ".join(alias)}"\n')

    def set_alias(self, alias_name, alias_command):
        """Save the alias in the global config."""
        c = _mod_config.GlobalConfig()
        c.set_alias(alias_name, alias_command)


def get_transport_type(typestring):
    """Parse and return a transport specifier."""
    if typestring == "sftp":
        from .tests import stub_sftp

        return stub_sftp.SFTPAbsoluteServer
    elif typestring == "memory":
        from breezy.transport import memory

        from .tests import test_server

        return memory.MemoryServer
    elif typestring == "fakenfs":
        from .tests import test_server

        return test_server.FakeNFSServer
    msg = f"No known transport type {typestring}. Supported types are: sftp\n"
    raise errors.CommandError(msg)


class cmd_selftest(Command):
    __doc__ = """Run internal test suite.

    If arguments are given, they are regular expressions that say which tests
    should run.  Tests matching any expression are run, and other tests are
    not run.

    Alternatively if --first is given, matching tests are run first and then
    all other tests are run.  This is useful if you have been working in a
    particular area, but want to make sure nothing else was broken.

    If --exclude is given, tests that match that regular expression are
    excluded, regardless of whether they match --first or not.

    To help catch accidential dependencies between tests, the --randomize
    option is useful. In most cases, the argument used is the word 'now'.
    Note that the seed used for the random number generator is displayed
    when this option is used. The seed can be explicitly passed as the
    argument to this option if required. This enables reproduction of the
    actual ordering used if and when an order sensitive problem is encountered.

    If --list-only is given, the tests that would be run are listed. This is
    useful when combined with --first, --exclude and/or --randomize to
    understand their impact. The test harness reports "Listed nn tests in ..."
    instead of "Ran nn tests in ..." when list mode is enabled.

    If the global option '--no-plugins' is given, plugins are not loaded
    before running the selftests.  This has two effects: features provided or
    modified by plugins will not be tested, and tests provided by plugins will
    not be run.

    Tests that need working space on disk use a common temporary directory,
    typically inside $TMPDIR or /tmp.

    If you set BRZ_TEST_PDB=1 when running selftest, failing tests will drop
    into a pdb postmortem session.

    The --coverage=DIRNAME global option produces a report with covered code
    indicated.

    :Examples:
        Run only tests relating to 'ignore'::

            brz selftest ignore

        Disable plugins and list tests as they're run::

            brz --no-plugins selftest -v
    """

    hidden = True
    takes_args = ["testspecs*"]
    takes_options = [
        "verbose",
        Option(
            "one",
            help="Stop when one test fails.",
            short_name="1",
        ),
        Option(
            "transport",
            help="Use a different transport by default throughout the test suite.",
            type=get_transport_type,
        ),
        Option(
            "benchmark", help="Run the benchmarks rather than selftests.", hidden=True
        ),
        Option(
            "lsprof-timed",
            help="Generate lsprof output for benchmarked sections of code.",
        ),
        Option("lsprof-tests", help="Generate lsprof output for each test."),
        Option(
            "first",
            help="Run all tests, but run specified tests first.",
            short_name="f",
        ),
        Option("list-only", help="List the tests instead of running them."),
        RegistryOption(
            "parallel",
            help="Run the test suite in parallel.",
            lazy_registry=("breezy.tests", "parallel_registry"),
            value_switches=False,
        ),
        Option(
            "randomize",
            type=str,
            argname="SEED",
            help="Randomize the order of tests using the given"
            ' seed or "now" for the current time.',
        ),
        ListOption(
            "exclude",
            type=str,
            argname="PATTERN",
            short_name="x",
            help="Exclude tests that match this regular expression.",
        ),
        Option("subunit1", help="Output test progress via subunit v1."),
        Option("subunit2", help="Output test progress via subunit v2."),
        Option("strict", help="Fail on missing dependencies or known failures."),
        Option(
            "load-list",
            type=str,
            argname="TESTLISTFILE",
            help="Load a test id list from a text file.",
        ),
        ListOption(
            "debugflag", type=str, short_name="E", help="Turn on a selftest debug flag."
        ),
        ListOption(
            "starting-with",
            type=str,
            argname="TESTID",
            param_name="starting_with",
            short_name="s",
            help="Load only the tests starting with TESTID.",
        ),
        Option(
            "sync",
            help="By default we disable fsync and fdatasync"
            " while running the test suite.",
        ),
    ]
    encoding_type = "replace"

    def __init__(self):
        Command.__init__(self)
        self.additional_selftest_args = {}

    def run(
        self,
        testspecs_list=None,
        verbose=False,
        one=False,
        transport=None,
        benchmark=None,
        lsprof_timed=None,
        first=False,
        list_only=False,
        randomize=None,
        exclude=None,
        strict=False,
        load_list=None,
        debugflag=None,
        starting_with=None,
        subunit1=False,
        subunit2=False,
        parallel=None,
        lsprof_tests=False,
        sync=False,
    ):
        # During selftest, disallow proxying, as it can cause severe
        # performance penalties and is only needed for thread
        # safety. The selftest command is assumed to not use threads
        # too heavily. The call should be as early as possible, as
        # error reporting for past duplicate imports won't have useful
        # backtraces.

        try:
            from . import tests
        except ModuleNotFoundError as exc:
            raise errors.CommandError(
                "tests not available. Install the "
                "breezy tests to run the breezy testsuite."
            ) from exc

        pattern = "|".join(testspecs_list) if testspecs_list is not None else ".*"
        if subunit1:
            try:
                from .tests import SubUnitBzrRunnerv1
            except ImportError as exc:
                raise errors.CommandError(
                    gettext(
                        "subunit not available. subunit needs to be installed "
                        "to use --subunit."
                    )
                ) from exc
            self.additional_selftest_args["runner_class"] = SubUnitBzrRunnerv1
            # On Windows, disable automatic conversion of '\n' to '\r\n' in
            # stdout, which would corrupt the subunit stream.
            # FIXME: This has been fixed in subunit trunk (>0.0.5) so the
            # following code can be deleted when it's sufficiently deployed
            # -- vila/mgz 20100514
            if (
                sys.platform == "win32"
                and getattr(sys.stdout, "fileno", None) is not None
            ):
                import msvcrt

                msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        if subunit2:
            try:
                from .tests import SubUnitBzrRunnerv2
            except ModuleNotFoundError as exc:
                raise errors.CommandError(
                    gettext(
                        "subunit not available. subunit "
                        "needs to be installed to use --subunit2."
                    )
                ) from exc
            self.additional_selftest_args["runner_class"] = SubUnitBzrRunnerv2

        if parallel:
            self.additional_selftest_args.setdefault("suite_decorators", []).append(
                parallel
            )
        if benchmark:
            raise errors.CommandError(
                gettext(
                    "--benchmark is no longer supported from brz 2.2; "
                    "use bzr-usertest instead"
                )
            )
        test_suite_factory = None
        exclude_pattern = None if not exclude else "(" + "|".join(exclude) + ")"
        if not sync:
            self._disable_fsync()
        selftest_kwargs = {
            "verbose": verbose,
            "pattern": pattern,
            "stop_on_failure": one,
            "transport": transport,
            "test_suite_factory": test_suite_factory,
            "lsprof_timed": lsprof_timed,
            "lsprof_tests": lsprof_tests,
            "matching_tests_first": first,
            "list_only": list_only,
            "random_seed": randomize,
            "exclude_pattern": exclude_pattern,
            "strict": strict,
            "load_list": load_list,
            "debug_flags": debugflag,
            "starting_with": starting_with,
        }
        selftest_kwargs.update(self.additional_selftest_args)

        # Make deprecation warnings visible, unless -Werror is set
        cleanup = symbol_versioning.activate_deprecation_warnings(override=False)
        try:
            result = tests.selftest(**selftest_kwargs)
        finally:
            cleanup()
        return int(not result)

    def _disable_fsync(self):
        """Change the 'os' functionality to not synchronize."""
        self._orig_fsync = getattr(os, "fsync", None)
        if self._orig_fsync is not None:
            os.fsync = lambda filedes: None
        self._orig_fdatasync = getattr(os, "fdatasync", None)
        if self._orig_fdatasync is not None:
            os.fdatasync = lambda filedes: None


class cmd_version(Command):
    __doc__ = """Show version of brz."""

    encoding_type = "replace"
    takes_options = [
        Option("short", help="Print just the version number."),
    ]

    @display_command
    def run(self, short=False):
        from .version import show_version

        if short:
            self.outf.write(breezy.version_string + "\n")
        else:
            show_version(to_file=self.outf)


class cmd_rocks(Command):
    __doc__ = """Statement of optimism."""

    hidden = True

    @display_command
    def run(self):
        self.outf.write(gettext("It sure does!\n"))


class cmd_find_merge_base(Command):
    __doc__ = """Find and print a base revision for merging two branches."""
    # TODO: Options to specify revisions on either side, as if
    #       merging only part of the history.
    takes_args = ["branch", "other"]
    hidden = True

    @display_command
    def run(self, branch, other):
        branch1 = Branch.open_containing(branch)[0]
        branch2 = Branch.open_containing(other)[0]
        self.enter_context(branch1.lock_read())
        self.enter_context(branch2.lock_read())
        last1 = branch1.last_revision()
        last2 = branch2.last_revision()

        graph = branch1.repository.get_graph(branch2.repository)
        base_rev_id = graph.find_unique_lca(last1, last2)

        self.outf.write(
            gettext("merge base is revision %s\n") % base_rev_id.decode("utf-8")
        )


class cmd_merge(Command):
    __doc__ = """Perform a three-way merge.

    The source of the merge can be specified either in the form of a branch,
    or in the form of a path to a file containing a merge directive generated
    with brz send. If neither is specified, the default is the upstream branch
    or the branch most recently merged using --remember.  The source of the
    merge may also be specified in the form of a path to a file in another
    branch:  in this case, only the modifications to that file are merged into
    the current working tree.

    When merging from a branch, by default brz will try to merge in all new
    work from the other branch, automatically determining an appropriate base
    revision.  If this fails, you may need to give an explicit base.

    To pick a different ending revision, pass "--revision OTHER".  brz will
    try to merge in all new work up to and including revision OTHER.

    If you specify two values, "--revision BASE..OTHER", only revisions BASE
    through OTHER, excluding BASE but including OTHER, will be merged.  If this
    causes some revisions to be skipped, i.e. if the destination branch does
    not already contain revision BASE, such a merge is commonly referred to as
    a "cherrypick". Unlike a normal merge, Breezy does not currently track
    cherrypicks. The changes look like a normal commit, and the history of the
    changes from the other branch is not stored in the commit.

    Revision numbers are always relative to the source branch.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you can commit.

    Use brz resolve when you have fixed a problem.  See also brz conflicts.

    If there is no default branch set, the first merge will set it (use
    --no-remember to avoid setting it). After that, you can omit the branch
    to use the default.  To change the default, use --remember. The value will
    only be saved if the remote location can be accessed.

    The results of the merge are placed into the destination working
    directory, where they can be reviewed (with brz diff), tested, and then
    committed to record the result of the merge.

    merge refuses to run if there are any uncommitted changes, unless
    --force is given.  If --force is given, then the changes from the source
    will be merged with the current working tree, including any uncommitted
    changes in the tree.  The --force option can also be used to create a
    merge revision which has more than two parents.

    If one would like to merge changes from the working tree of the other
    branch without merging any committed revisions, the --uncommitted option
    can be given.

    To select only some changes to merge, use "merge -i", which will prompt
    you to apply each diff hunk and file change, similar to "shelve".

    :Examples:
        To merge all new revisions from brz.dev::

            brz merge ../brz.dev

        To merge changes up to and including revision 82 from brz.dev::

            brz merge -r 82 ../brz.dev

        To merge the changes introduced by 82, without previous changes::

            brz merge -r 81..82 ../brz.dev

        To apply a merge directive contained in /tmp/merge::

            brz merge /tmp/merge

        To create a merge revision with three parents from two branches
        feature1a and feature1b:

            brz merge ../feature1a
            brz merge ../feature1b --force
            brz commit -m 'revision with three parents'
    """

    encoding_type = "exact"
    _see_also = ["update", "remerge", "status-flags", "send"]
    takes_args = ["location?"]
    takes_options = [
        "change",
        "revision",
        Option(
            "force", help="Merge even if the destination tree has uncommitted changes."
        ),
        "merge-type",
        "reprocess",
        "remember",
        Option("show-base", help="Show base revision text in conflicts."),
        Option(
            "uncommitted",
            help="Apply uncommitted changes"
            " from a working copy, instead of branch changes.",
        ),
        Option(
            "pull",
            help="If the destination is already"
            " completely merged into the source, pull from the"
            " source rather than merging.  When this happens,"
            " you do not need to commit the result.",
        ),
        custom_help(
            "directory",
            help="Branch to merge into, "
            "rather than the one containing the working directory.",
        ),
        Option("preview", help="Instead of merging, show a diff of the merge."),
        Option("interactive", help="Select changes interactively.", short_name="i"),
    ]

    def run(
        self,
        location=None,
        revision=None,
        force=False,
        merge_type=None,
        show_base=False,
        reprocess=None,
        remember=None,
        uncommitted=False,
        pull=False,
        directory=None,
        preview=False,
        interactive=False,
    ):
        from . import mergeable as _mod_mergeable
        from .workingtree import WorkingTree

        if merge_type is None:
            merge_type = _mod_merge.Merge3Merger

        if directory is None:
            directory = "."
        possible_transports = []
        merger = None
        allow_pending = True
        verified = "inapplicable"

        tree = WorkingTree.open_containing(directory)[0]
        if tree.branch.last_revision() == _mod_revision.NULL_REVISION:
            raise errors.CommandError(
                gettext(
                    "Merging into empty branches not currently supported, "
                    "https://bugs.launchpad.net/bzr/+bug/308562"
                )
            )

        # die as quickly as possible if there are uncommitted changes
        if not force and tree.has_changes():
            raise errors.UncommittedChanges(tree)

        view_info = _get_view_info_for_change_reporter(tree)
        change_reporter = delta._ChangeReporter(
            unversioned_filter=tree.is_ignored, view_info=view_info
        )
        pb = ui.ui_factory.nested_progress_bar()
        self.enter_context(pb)
        self.enter_context(tree.lock_write())
        if location is not None:
            try:
                mergeable = _mod_mergeable.read_mergeable_from_url(
                    location, possible_transports=possible_transports
                )
            except errors.NotABundle:
                mergeable = None
            else:
                if uncommitted:
                    raise errors.CommandError(
                        gettext(
                            "Cannot use --uncommitted with bundles or merge directives."
                        )
                    )

                if revision is not None:
                    raise errors.CommandError(
                        gettext("Cannot use -r with merge directives or bundles")
                    )
                merger, verified = _mod_merge.Merger.from_mergeable(tree, mergeable)

        if merger is None and uncommitted:
            if revision is not None and len(revision) > 0:
                raise errors.CommandError(
                    gettext("Cannot use --uncommitted and --revision at the same time.")
                )
            merger = self.get_merger_from_uncommitted(tree, location, None)
            allow_pending = False

        if merger is None:
            merger, allow_pending = self._get_merger_from_branch(
                tree, location, revision, remember, possible_transports, None
            )

        merger.merge_type = merge_type
        merger.reprocess = reprocess
        merger.show_base = show_base
        self.sanity_check_merger(merger)
        if (
            merger.base_rev_id == merger.other_rev_id
            and merger.other_rev_id is not None
        ):
            # check if location is a nonexistent file (and not a branch) to
            # disambiguate the 'Nothing to do'
            if merger.interesting_files:
                if not merger.other_tree.has_filename(merger.interesting_files[0]):
                    note(gettext("merger: ") + str(merger))
                    raise errors.PathsDoNotExist([location])
            note(gettext("Nothing to do."))
            return 0
        if pull and not preview:
            if merger.interesting_files is not None:
                raise errors.CommandError(gettext("Cannot pull individual files"))
            if merger.base_rev_id == tree.last_revision():
                result = tree.pull(merger.other_branch, False, merger.other_rev_id)
                result.report(self.outf)
                return 0
        if merger.this_basis is None:
            raise errors.CommandError(
                gettext(
                    "This branch has no commits. (perhaps you would prefer 'brz pull')"
                )
            )
        if preview:
            return self._do_preview(merger)
        elif interactive:
            return self._do_interactive(merger)
        else:
            return self._do_merge(merger, change_reporter, allow_pending, verified)

    def _get_preview(self, merger):
        tree_merger = merger.make_merger()
        tt = tree_merger.make_preview_transform()
        self.enter_context(tt)
        result_tree = tt.get_preview_tree()
        return result_tree

    def _do_preview(self, merger):
        from .diff import show_diff_trees

        result_tree = self._get_preview(merger)
        path_encoding = osutils.get_diff_header_encoding()
        show_diff_trees(
            merger.this_tree,
            result_tree,
            self.outf,
            old_label="",
            new_label="",
            path_encoding=path_encoding,
        )

    def _do_merge(self, merger, change_reporter, allow_pending, verified):
        merger.change_reporter = change_reporter
        conflict_count = len(merger.do_merge())
        if allow_pending:
            merger.set_pending()
        if verified == "failed":
            warning("Preview patch does not match changes")
        if conflict_count != 0:
            return 1
        else:
            return 0

    def _do_interactive(self, merger):
        """Perform an interactive merge.

        This works by generating a preview tree of the merge, then using
        Shelver to selectively remove the differences between the working tree
        and the preview tree.
        """
        from . import shelf_ui

        result_tree = self._get_preview(merger)
        writer = breezy.option.diff_writer_registry.get()
        shelver = shelf_ui.Shelver(
            merger.this_tree,
            result_tree,
            destroy=True,
            reporter=shelf_ui.ApplyReporter(),
            diff_writer=writer(self.outf),
        )
        try:
            shelver.run()
        finally:
            shelver.finalize()

    def sanity_check_merger(self, merger):
        if merger.show_base and merger.merge_type is not _mod_merge.Merge3Merger:
            raise errors.CommandError(
                gettext("Show-base is not supported for this merge type. %s")
                % merger.merge_type
            )
        if merger.reprocess is None:
            if merger.show_base:
                merger.reprocess = False
            else:
                # Use reprocess if the merger supports it
                merger.reprocess = merger.merge_type.supports_reprocess
        if merger.reprocess and not merger.merge_type.supports_reprocess:
            raise errors.CommandError(
                gettext("Conflict reduction is not supported for merge type %s.")
                % merger.merge_type
            )
        if merger.reprocess and merger.show_base:
            raise errors.CommandError(
                gettext("Cannot do conflict reduction and show base.")
            )

        if merger.merge_type.requires_file_merge_plan and (
            not getattr(merger.this_tree, "plan_file_merge", None)
            or not getattr(merger.other_tree, "plan_file_merge", None)
            or (
                merger.base_tree is not None
                and not getattr(merger.base_tree, "plan_file_merge", None)
            )
        ):
            raise errors.CommandError(
                gettext(
                    "Plan file merge unsupported: "
                    "Merge type incompatible with tree formats."
                )
            )

    def _get_merger_from_branch(
        self, tree, location, revision, remember, possible_transports, pb
    ):
        """Produce a merger from a location, assuming it refers to a branch."""
        # find the branch locations
        other_loc, user_location = self._select_branch_location(
            tree, location, revision, -1
        )
        if revision is not None and len(revision) == 2:
            base_loc, _unused = self._select_branch_location(
                tree, location, revision, 0
            )
        else:
            base_loc = other_loc
        # Open the branches
        other_branch, other_path = Branch.open_containing(
            other_loc, possible_transports
        )
        if base_loc == other_loc:
            base_branch = other_branch
        else:
            base_branch, base_path = Branch.open_containing(
                base_loc, possible_transports
            )
        # Find the revision ids
        other_revision_id = None
        base_revision_id = None
        if revision is not None:
            if len(revision) >= 1:
                other_revision_id = revision[-1].as_revision_id(other_branch)
            if len(revision) == 2:
                base_revision_id = revision[0].as_revision_id(base_branch)
        if other_revision_id is None:
            other_revision_id = other_branch.last_revision()
        # Remember where we merge from. We need to remember if:
        # - user specify a location (and we don't merge from the parent
        #   branch)
        # - user ask to remember or there is no previous location set to merge
        #   from and user didn't ask to *not* remember
        if user_location is not None and (
            remember or (remember is None and tree.branch.get_submit_branch() is None)
        ):
            tree.branch.set_submit_branch(other_branch.base)
        # Merge tags (but don't set them in the master branch yet, the user
        # might revert this merge).  Commit will propagate them.
        other_branch.tags.merge_to(tree.branch.tags, ignore_master=True)
        merger = _mod_merge.Merger.from_revision_ids(
            tree, other_revision_id, base_revision_id, other_branch, base_branch
        )
        if other_path != "":
            allow_pending = False
            merger.interesting_files = [other_path]
        else:
            allow_pending = True
        return merger, allow_pending

    def get_merger_from_uncommitted(self, tree, location, pb):
        """Get a merger for uncommitted changes.

        :param tree: The tree the merger should apply to.
        :param location: The location containing uncommitted changes.
        :param pb: The progress bar to use for showing progress.
        """
        from .workingtree import WorkingTree

        location = self._select_branch_location(tree, location)[0]
        other_tree, other_path = WorkingTree.open_containing(location)
        merger = _mod_merge.Merger.from_uncommitted(tree, other_tree, pb)
        if other_path != "":
            merger.interesting_files = [other_path]
        return merger

    def _select_branch_location(self, tree, user_location, revision=None, index=None):
        """Select a branch location, according to possible inputs.

        If provided, branches from ``revision`` are preferred.  (Both
        ``revision`` and ``index`` must be supplied.)

        Otherwise, the ``location`` parameter is used.  If it is None, then the
        ``submit`` or ``parent`` location is used, and a note is printed.

        :param tree: The working tree to select a branch for merging into
        :param location: The location entered by the user
        :param revision: The revision parameter to the command
        :param index: The index to use for the revision parameter.  Negative
            indices are permitted.
        :return: (selected_location, user_location).  The default location
            will be the user-entered location.
        """
        if revision is not None and index is not None and revision[index] is not None:
            branch = revision[index].get_branch()
            if branch is not None:
                return branch, branch
        if user_location is None:
            location = self._get_remembered(tree, "Merging from")
        else:
            location = user_location
        return location, user_location

    def _get_remembered(self, tree, verb_string):
        """Use tree.branch's parent if none was supplied.

        Report if the remembered location was used.
        """
        stored_location = tree.branch.get_submit_branch()
        stored_location_type = "submit"
        if stored_location is None:
            stored_location = tree.branch.get_parent()
            stored_location_type = "parent"
        mutter("%s", stored_location)
        if stored_location is None:
            raise errors.CommandError(gettext("No location specified or remembered"))
        display_url = urlutils.unescape_for_display(stored_location, "utf-8")
        note(
            gettext("{0} remembered {1} location {2}").format(
                verb_string, stored_location_type, display_url
            )
        )
        return stored_location


class cmd_remerge(Command):
    __doc__ = """Redo a merge.

    Use this if you want to try a different merge technique while resolving
    conflicts.  Some merge techniques are better than others, and remerge
    lets you try different ones on different files.

    The options for remerge have the same meaning and defaults as the ones for
    merge.  The difference is that remerge can (only) be run when there is a
    pending merge, and it lets you specify particular files.

    :Examples:
        Re-do the merge of all conflicted files, and show the base text in
        conflict regions, in addition to the usual THIS and OTHER texts::

            brz remerge --show-base

        Re-do the merge of "foobar", using the weave merge algorithm, with
        additional processing to reduce the size of conflict regions::

            brz remerge --merge-type weave --reprocess foobar
    """
    takes_args = ["file*"]
    takes_options = [
        "merge-type",
        "reprocess",
        Option("show-base", help="Show base revision text in conflicts."),
    ]

    def run(self, file_list=None, merge_type=None, show_base=False, reprocess=False):
        from .conflicts import restore
        from .workingtree import WorkingTree

        if merge_type is None:
            merge_type = _mod_merge.Merge3Merger
        tree, file_list = WorkingTree.open_containing_paths(file_list)
        self.enter_context(tree.lock_write())
        parents = tree.get_parent_ids()
        if len(parents) != 2:
            raise errors.CommandError(
                gettext(
                    "Sorry, remerge only works after normal"
                    " merges.  Not cherrypicking or multi-merges."
                )
            )
        interesting_files = None
        new_conflicts = []
        conflicts = tree.conflicts()
        if file_list is not None:
            interesting_files = set()
            for filename in file_list:
                if not tree.is_versioned(filename):
                    raise errors.NotVersionedError(filename)
                interesting_files.add(filename)
                if tree.kind(filename) != "directory":
                    continue

                for path, _ie in tree.iter_entries_by_dir(specific_files=[filename]):
                    interesting_files.add(path)
            new_conflicts = conflicts.select_conflicts(tree, file_list)[0]
        else:
            # Remerge only supports resolving contents conflicts
            allowed_conflicts = ("text conflict", "contents conflict")
            restore_files = [
                c.path for c in conflicts if c.typestring in allowed_conflicts
            ]
        _mod_merge.transform_tree(tree, tree.basis_tree(), interesting_files)
        tree.set_conflicts(new_conflicts)
        if file_list is not None:
            restore_files = file_list
        for filename in restore_files:
            with contextlib.suppress(errors.NotConflicted):
                restore(tree.abspath(filename))
        # Disable pending merges, because the file texts we are remerging
        # have not had those merges performed.  If we use the wrong parents
        # list, we imply that the working tree text has seen and rejected
        # all the changes from the other tree, when in fact those changes
        # have not yet been seen.
        tree.set_parent_ids(parents[:1])
        try:
            merger = _mod_merge.Merger.from_revision_ids(tree, parents[1])
            merger.interesting_files = interesting_files
            merger.merge_type = merge_type
            merger.show_base = show_base
            merger.reprocess = reprocess
            conflicts = merger.do_merge()
        finally:
            tree.set_parent_ids(parents)
        if len(conflicts) > 0:
            return 1
        else:
            return 0


class cmd_revert(Command):
    __doc__ = """\
    Set files in the working tree back to the contents of a previous revision.

    Giving a list of files will revert only those files.  Otherwise, all files
    will be reverted.  If the revision is not specified with '--revision', the
    working tree basis revision is used. A revert operation affects only the
    working tree, not any revision history like the branch and repository or
    the working tree basis revision.

    To remove only some changes, without reverting to a prior version, use
    merge instead.  For example, "merge . -r -2..-3" (don't forget the ".")
    will remove the changes introduced by the second last commit (-2), without
    affecting the changes introduced by the last commit (-1).  To remove
    certain changes on a hunk-by-hunk basis, see the shelve command.
    To update the branch to a specific revision or the latest revision and
    update the working tree accordingly while preserving local changes, see the
    update command.

    Uncommitted changes to files that are reverted will be discarded.
    However, by default, any files that have been manually changed will be
    backed up first.  (Files changed only by merge are not backed up.)  Backup
    files have '.~#~' appended to their name, where # is a number.

    When you provide files, you can use their current pathname or the pathname
    from the target revision.  So you can use revert to "undelete" a file by
    name.  If you name a directory, all the contents of that directory will be
    reverted.

    If you have newly added files since the target revision, they will be
    removed.  If the files to be removed have been changed, backups will be
    created as above.  Directories containing unknown files will not be
    deleted.

    The working tree contains a list of revisions that have been merged but
    not yet committed. These revisions will be included as additional parents
    of the next commit.  Normally, using revert clears that list as well as
    reverting the files.  If any files are specified, revert leaves the list
    of uncommitted merges alone and reverts only the files.  Use ``brz revert
    .`` in the tree root to revert all files but keep the recorded merges,
    and ``brz revert --forget-merges`` to clear the pending merge list without
    reverting any files.

    Using "brz revert --forget-merges", it is possible to apply all of the
    changes from a branch in a single revision.  To do this, perform the merge
    as desired.  Then doing revert with the "--forget-merges" option will keep
    the content of the tree as it was, but it will clear the list of pending
    merges.  The next commit will then contain all of the changes that are
    present in the other branch, but without any other parent revisions.
    Because this technique forgets where these changes originated, it may
    cause additional conflicts on later merges involving the same source and
    target branches.
    """

    _see_also = ["cat", "export", "merge", "shelve"]
    takes_options = [
        "revision",
        Option("no-backup", "Do not save backups of reverted files."),
        Option(
            "forget-merges", "Remove pending merge marker, without changing any files."
        ),
    ]
    takes_args = ["file*"]

    def run(self, revision=None, no_backup=False, file_list=None, forget_merges=None):
        from .workingtree import WorkingTree

        tree, file_list = WorkingTree.open_containing_paths(file_list)
        self.enter_context(tree.lock_tree_write())
        if forget_merges:
            tree.set_parent_ids(tree.get_parent_ids()[:1])
        else:
            self._revert_tree_to_revision(tree, revision, file_list, no_backup)

    @staticmethod
    def _revert_tree_to_revision(tree, revision, file_list, no_backup):
        rev_tree = _get_one_revision_tree("revert", revision, tree=tree)
        tree.revert(file_list, rev_tree, not no_backup, None, report_changes=True)


class cmd_assert_fail(Command):
    __doc__ = """Test reporting of assertion failures"""
    # intended just for use in testing

    hidden = True

    def run(self):
        raise AssertionError("always fails")


class cmd_help(Command):
    __doc__ = """Show help on a command or other topic.
    """

    _see_also = ["topics"]
    takes_options = [
        Option("long", "Show help on all commands."),
    ]
    takes_args = ["topic?"]
    aliases = ["?", "--help", "-?", "-h"]

    @display_command
    def run(self, topic=None, long=False):
        import breezy.help

        if topic is None and long:
            topic = "commands"
        breezy.help.help(topic)


class cmd_shell_complete(Command):
    __doc__ = """Show appropriate completions for context.

    For a list of all available commands, say 'brz shell-complete'.
    """
    takes_args = ["context?"]
    aliases = ["s-c"]
    hidden = True

    @display_command
    def run(self, context=None):
        from . import shellcomplete

        shellcomplete.shellcomplete(context)


class cmd_missing(Command):
    __doc__ = """Show unmerged/unpulled revisions between two branches.

    OTHER_BRANCH may be local or remote.

    To filter on a range of revisions, you can use the command -r begin..end
    -r revision requests a specific revision, -r ..end or -r begin.. are
    also valid.

    :Exit values:
        1 - some missing revisions
        0 - no missing revisions

    :Examples:

        Determine the missing revisions between this and the branch at the
        remembered pull location::

            brz missing

        Determine the missing revisions between this and another branch::

            brz missing http://server/branch

        Determine the missing revisions up to a specific revision on the other
        branch::

            brz missing -r ..-10

        Determine the missing revisions up to a specific revision on this
        branch::

            brz missing --my-revision ..-10
    """

    _see_also = ["merge", "pull"]
    takes_args = ["other_branch?"]
    takes_options = [
        "directory",
        Option("reverse", "Reverse the order of revisions."),
        Option("mine-only", "Display changes in the local branch only."),
        Option("this", "Same as --mine-only."),
        Option("theirs-only", "Display changes in the remote branch only."),
        Option("other", "Same as --theirs-only."),
        "log-format",
        "show-ids",
        "verbose",
        custom_help(
            "revision",
            help="Filter on other branch revisions (inclusive). "
            'See "help revisionspec" for details.',
        ),
        Option(
            "my-revision",
            type=_parse_revision_str,
            help="Filter on local branch revisions (inclusive). "
            'See "help revisionspec" for details.',
        ),
        Option(
            "include-merged", "Show all revisions in addition to the mainline ones."
        ),
        Option(
            "include-merges", hidden=True, help="Historical alias for --include-merged."
        ),
    ]
    encoding_type = "replace"

    @display_command
    def run(
        self,
        other_branch=None,
        reverse=False,
        mine_only=False,
        theirs_only=False,
        log_format=None,
        long=False,
        short=False,
        line=False,
        show_ids=False,
        verbose=False,
        this=False,
        other=False,
        include_merged=None,
        revision=None,
        my_revision=None,
        directory=".",
    ):
        from .missing import find_unmerged, iter_log_revisions

        def message(s):
            if not is_quiet():
                self.outf.write(s)

        if include_merged is None:
            include_merged = False
        if this:
            mine_only = this
        if other:
            theirs_only = other
        # TODO: We should probably check that we don't have mine-only and
        #       theirs-only set, but it gets complicated because we also have
        #       this and other which could be used.
        restrict = "all"
        if mine_only:
            restrict = "local"
        elif theirs_only:
            restrict = "remote"

        local_branch = Branch.open_containing(directory)[0]
        self.enter_context(local_branch.lock_read())

        parent = local_branch.get_parent()
        if other_branch is None:
            other_branch = parent
            if other_branch is None:
                raise errors.CommandError(
                    gettext("No peer location known or specified.")
                )
            display_url = urlutils.unescape_for_display(parent, self.outf.encoding)
            message(gettext("Using saved parent location: {0}\n").format(display_url))

        remote_branch = Branch.open(other_branch)
        if remote_branch.base == local_branch.base:
            remote_branch = local_branch
        else:
            self.enter_context(remote_branch.lock_read())

        local_revid_range = _revision_range_to_revid_range(
            _get_revision_range(my_revision, local_branch, self.name())
        )

        remote_revid_range = _revision_range_to_revid_range(
            _get_revision_range(revision, remote_branch, self.name())
        )

        local_extra, remote_extra = find_unmerged(
            local_branch,
            remote_branch,
            restrict,
            backward=not reverse,
            include_merged=include_merged,
            local_revid_range=local_revid_range,
            remote_revid_range=remote_revid_range,
        )

        if log_format is None:
            registry = log.log_formatter_registry
            log_format = registry.get_default(local_branch)
        lf = log_format(to_file=self.outf, show_ids=show_ids, show_timezone="original")

        status_code = 0
        if local_extra and not theirs_only:
            message(
                ngettext(
                    "You have %d extra revision:\n",
                    "You have %d extra revisions:\n",
                    len(local_extra),
                )
                % len(local_extra)
            )
            rev_tag_dict = {}
            if local_branch.supports_tags():
                rev_tag_dict = local_branch.tags.get_reverse_tag_dict()
            for revision in iter_log_revisions(
                local_extra, local_branch.repository, verbose, rev_tag_dict
            ):
                lf.log_revision(revision)
            printed_local = True
            status_code = 1
        else:
            printed_local = False

        if remote_extra and not mine_only:
            if printed_local is True:
                message("\n\n\n")
            message(
                ngettext(
                    "You are missing %d revision:\n",
                    "You are missing %d revisions:\n",
                    len(remote_extra),
                )
                % len(remote_extra)
            )
            if remote_branch.supports_tags():
                rev_tag_dict = remote_branch.tags.get_reverse_tag_dict()
            for revision in iter_log_revisions(
                remote_extra, remote_branch.repository, verbose, rev_tag_dict
            ):
                lf.log_revision(revision)
            status_code = 1

        if mine_only and not local_extra:
            # We checked local, and found nothing extra
            message(gettext("This branch has no new revisions.\n"))
        elif theirs_only and not remote_extra:
            # We checked remote, and found nothing extra
            message(gettext("Other branch has no new revisions.\n"))
        elif not (mine_only or theirs_only or local_extra or remote_extra):
            # We checked both branches, and neither one had extra
            # revisions
            message(gettext("Branches are up to date.\n"))
        self.cleanup_now()
        if not status_code and parent is None and other_branch is not None:
            self.enter_context(local_branch.lock_write())
            # handle race conditions - a parent might be set while we run.
            if local_branch.get_parent() is None:
                local_branch.set_parent(remote_branch.base)
        return status_code


class cmd_pack(Command):
    __doc__ = """Compress the data within a repository.

    This operation compresses the data within a bazaar repository. As
    bazaar supports automatic packing of repository, this operation is
    normally not required to be done manually.

    During the pack operation, bazaar takes a backup of existing repository
    data, i.e. pack files. This backup is eventually removed by bazaar
    automatically when it is safe to do so. To save disk space by removing
    the backed up pack files, the --clean-obsolete-packs option may be
    used.

    Warning: If you use --clean-obsolete-packs and your machine crashes
    during or immediately after repacking, you may be left with a state
    where the deletion has been written to disk but the new packs have not
    been. In this case the repository may be unusable.
    """

    _see_also = ["repositories"]
    takes_args = ["branch_or_repo?"]
    takes_options = [
        Option("clean-obsolete-packs", "Delete obsolete packs to save disk space."),
    ]

    def run(self, branch_or_repo=".", clean_obsolete_packs=False):
        dir = controldir.ControlDir.open_containing(branch_or_repo)[0]
        try:
            branch = dir.open_branch()
            repository = branch.repository
        except errors.NotBranchError:
            repository = dir.open_repository()
        repository.pack(clean_obsolete_packs=clean_obsolete_packs)


class cmd_plugins(Command):
    __doc__ = """List the installed plugins.

    This command displays the list of installed plugins including
    version of plugin and a short description of each.

    --verbose shows the path where each plugin is located.

    A plugin is an external component for Breezy that extends the
    revision control system, by adding or replacing code in Breezy.
    Plugins can do a variety of things, including overriding commands,
    adding new commands, providing additional network transports and
    customizing log output.

    See the Breezy Plugin Guide <https://www.breezy-vcs.org/doc/plugins/en/>
    for further information on plugins including where to find them and how to
    install them. Instructions are also provided there on how to write new
    plugins using the Python programming language.
    """
    takes_options = ["verbose"]

    @display_command
    def run(self, verbose=False):
        from . import plugin

        # Don't give writelines a generator as some codecs don't like that
        self.outf.writelines(list(plugin.describe_plugins(show_paths=verbose)))


class cmd_testament(Command):
    __doc__ = """Show testament (signing-form) of a revision."""
    takes_options = [
        "revision",
        Option("long", help="Produce long-format testament."),
        Option("strict", help="Produce a strict-format testament."),
    ]
    takes_args = ["branch?"]
    encoding_type = "exact"

    @display_command
    def run(self, branch=".", revision=None, long=False, strict=False):
        from .bzr.testament import StrictTestament, Testament

        testament_class = StrictTestament if strict is True else Testament
        b = Branch.open_containing(branch)[0] if branch == "." else Branch.open(branch)
        self.enter_context(b.lock_read())
        if revision is None:
            rev_id = b.last_revision()
        else:
            rev_id = revision[0].as_revision_id(b)
        t = testament_class.from_revision(b.repository, rev_id)
        if long:
            self.outf.writelines(t.as_text_lines())
        else:
            self.outf.write(t.as_short_text())


class cmd_annotate(Command):
    __doc__ = """Show the origin of each line in a file.

    This prints out the given file with an annotation on the left side
    indicating which revision, author and date introduced the change.

    If the origin is the same for a run of consecutive lines, it is
    shown only at the top, unless the --all option is given.
    """
    # TODO: annotate directories; showing when each file was last changed
    # TODO: if the working copy is modified, show annotations on that
    #       with new uncommitted lines marked
    aliases = ["ann", "blame", "praise"]
    takes_args = ["filename"]
    takes_options = [
        Option("all", help="Show annotations on all lines."),
        Option("long", help="Show commit date in annotations."),
        "revision",
        "show-ids",
        "directory",
    ]
    encoding_type = "exact"

    @display_command
    def run(
        self,
        filename,
        all=False,
        long=False,
        revision=None,
        show_ids=False,
        directory=None,
    ):
        from .annotate import annotate_file_tree

        wt, branch, relpath = _open_directory_or_containing_tree_or_branch(
            filename, directory
        )
        if wt is not None:
            self.enter_context(wt.lock_read())
        else:
            self.enter_context(branch.lock_read())
        tree = _get_one_revision_tree("annotate", revision, branch=branch)
        self.enter_context(tree.lock_read())
        if wt is not None and revision is None:
            if not wt.is_versioned(relpath):
                raise errors.NotVersionedError(relpath)
            # If there is a tree and we're not annotating historical
            # versions, annotate the working tree's content.
            annotate_file_tree(wt, relpath, self.outf, long, all, show_ids=show_ids)
        else:
            if not tree.is_versioned(relpath):
                raise errors.NotVersionedError(relpath)
            annotate_file_tree(
                tree, relpath, self.outf, long, all, show_ids=show_ids, branch=branch
            )


class cmd_re_sign(Command):
    __doc__ = """Create a digital signature for an existing revision."""
    # TODO be able to replace existing ones.

    hidden = True  # is this right ?
    takes_args = ["revision_id*"]
    takes_options = ["directory", "revision"]

    def run(self, revision_id_list=None, revision=None, directory="."):
        from .workingtree import WorkingTree

        if revision_id_list is not None and revision is not None:
            raise errors.CommandError(
                gettext("You can only supply one of revision_id or --revision")
            )
        if revision_id_list is None and revision is None:
            raise errors.CommandError(
                gettext("You must supply either --revision or a revision_id")
            )
        b = WorkingTree.open_containing(directory)[0].branch
        self.enter_context(b.lock_write())
        return self._run(b, revision_id_list, revision)

    def _run(self, b, revision_id_list, revision):
        from .repository import WriteGroup

        gpg_strategy = gpg.GPGStrategy(b.get_config_stack())
        if revision_id_list is not None:
            with WriteGroup(b.repository):
                for revision_id in revision_id_list:
                    revision_id = revision_id.encode("utf-8")
                    b.repository.sign_revision(revision_id, gpg_strategy)
        elif revision is not None:
            if len(revision) == 1:
                revno, rev_id = revision[0].in_history(b)
                with WriteGroup(b.repository):
                    b.repository.sign_revision(rev_id, gpg_strategy)
            elif len(revision) == 2:
                # are they both on rh- if so we can walk between them
                # might be nice to have a range helper for arbitrary
                # revision paths. hmm.
                from_revno, from_revid = revision[0].in_history(b)
                to_revno, to_revid = revision[1].in_history(b)
                if to_revid is None:
                    to_revno = b.revno()
                if from_revno is None or to_revno is None:
                    raise errors.CommandError(
                        gettext("Cannot sign a range of non-revision-history revisions")
                    )
                with WriteGroup(b.repository):
                    for revno in range(from_revno, to_revno + 1):
                        b.repository.sign_revision(b.get_rev_id(revno), gpg_strategy)
            else:
                raise errors.CommandError(
                    gettext("Please supply either one revision, or a range.")
                )


class cmd_bind(Command):
    __doc__ = """Convert the current branch into a checkout of the supplied branch.
    If no branch is supplied, rebind to the last bound location.

    Once converted into a checkout, commits must succeed on the master branch
    before they will be applied to the local branch.

    Bound branches use the nickname of its master branch unless it is set
    locally, in which case binding will update the local nickname to be
    that of the master.
    """

    _see_also = ["checkouts", "unbind"]
    takes_args = ["location?"]
    takes_options = ["directory"]

    def run(self, location=None, directory="."):
        b, relpath = Branch.open_containing(directory)
        if location is None:
            try:
                location = b.get_old_bound_location()
            except errors.UpgradeRequired as exc:
                raise errors.CommandError(
                    gettext(
                        "No location supplied.  "
                        "This format does not remember old locations."
                    )
                ) from exc
            else:
                if location is None:
                    if b.get_bound_location() is not None:
                        raise errors.CommandError(gettext("Branch is already bound"))
                    else:
                        raise errors.CommandError(
                            gettext(
                                "No location supplied and no previous location known"
                            )
                        )
        b_other = Branch.open(location)
        try:
            b.bind(b_other)
        except errors.DivergedBranches as exc:
            raise errors.CommandError(
                gettext(
                    "These branches have diverged. Try merging, and then bind again."
                )
            ) from exc
        if b.get_config().has_explicit_nickname():
            b.nick = b_other.nick


class cmd_unbind(Command):
    __doc__ = """Convert the current checkout into a regular branch.

    After unbinding, the local branch is considered independent and subsequent
    commits will be local only.
    """

    _see_also = ["checkouts", "bind"]
    takes_options = ["directory"]

    def run(self, directory="."):
        b, relpath = Branch.open_containing(directory)
        if not b.unbind():
            raise errors.CommandError(gettext("Local branch is not bound"))


class cmd_uncommit(Command):
    __doc__ = """Remove the last committed revision.

    --verbose will print out what is being removed.
    --dry-run will go through all the motions, but not actually
    remove anything.

    If --revision is specified, uncommit revisions to leave the branch at the
    specified revision.  For example, "brz uncommit -r 15" will leave the
    branch at revision 15.

    Uncommit leaves the working tree ready for a new commit.  The only change
    it may make is to restore any pending merges that were present before
    the commit.
    """

    # TODO: jam 20060108 Add an option to allow uncommit to remove
    # unreferenced information in 'branch-as-repository' branches.
    # TODO: jam 20060108 Add the ability for uncommit to remove unreferenced
    # information in shared branches as well.
    _see_also = ["commit"]
    takes_options = [
        "verbose",
        "revision",
        Option("dry-run", help="Don't actually make changes."),
        Option("force", help="Say yes to all questions."),
        Option("keep-tags", help="Keep tags that point to removed revisions."),
        Option(
            "local",
            help="Only remove the commits from the local branch when in a checkout.",
        ),
    ]
    takes_args = ["location?"]
    encoding_type = "replace"

    def run(
        self,
        location=None,
        dry_run=False,
        verbose=False,
        revision=None,
        force=False,
        local=False,
        keep_tags=False,
    ):
        if location is None:
            location = "."
        control, relpath = controldir.ControlDir.open_containing(location)
        try:
            tree = control.open_workingtree()
            b = tree.branch
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            b = control.open_branch()

        if tree is not None:
            self.enter_context(tree.lock_write())
        else:
            self.enter_context(b.lock_write())
        return self._run(
            b, tree, dry_run, verbose, revision, force, local, keep_tags, location
        )

    def _run(
        self, b, tree, dry_run, verbose, revision, force, local, keep_tags, location
    ):
        from .log import log_formatter, show_log
        from .uncommit import uncommit

        last_revno, last_rev_id = b.last_revision_info()

        rev_id = None
        if revision is None:
            revno = last_revno
            rev_id = last_rev_id
        else:
            # 'brz uncommit -r 10' actually means uncommit
            # so that the final tree is at revno 10.
            # but breezy.uncommit.uncommit() actually uncommits
            # the revisions that are supplied.
            # So we need to offset it by one
            revno = revision[0].in_history(b).revno + 1
            if revno <= last_revno:
                rev_id = b.get_rev_id(revno)

        if rev_id is None or _mod_revision.is_null(rev_id):
            self.outf.write(gettext("No revisions to uncommit.\n"))
            return 1

        lf = log_formatter("short", to_file=self.outf, show_timezone="original")

        show_log(
            b,
            lf,
            verbose=False,
            direction="forward",
            start_revision=revno,
            end_revision=last_revno,
        )

        if dry_run:
            self.outf.write(
                gettext("Dry-run, pretending to remove the above revisions.\n")
            )
        else:
            self.outf.write(gettext("The above revision(s) will be removed.\n"))

        if not force and not ui.ui_factory.confirm_action(
            gettext("Uncommit these revisions"), "breezy.builtins.uncommit", {}
        ):
            self.outf.write(gettext("Canceled\n"))
            return 0

        mutter("Uncommitting from {%s} to {%s}", last_rev_id, rev_id)
        uncommit(
            b,
            tree=tree,
            dry_run=dry_run,
            verbose=verbose,
            revno=revno,
            local=local,
            keep_tags=keep_tags,
        )
        if location != ".":
            self.outf.write(
                gettext(
                    "You can restore the old tip by running:\n"
                    "  brz pull -d %s %s -r revid:%s\n"
                )
                % (location, location, last_rev_id.decode("utf-8"))
            )
        else:
            self.outf.write(
                gettext(
                    "You can restore the old tip by running:\n"
                    "  brz pull . -r revid:%s\n"
                )
                % last_rev_id.decode("utf-8")
            )


class cmd_break_lock(Command):
    __doc__ = """Break a dead lock.

    This command breaks a lock on a repository, branch, working directory or
    config file.

    CAUTION: Locks should only be broken when you are sure that the process
    holding the lock has been stopped.

    You can get information on what locks are open via the 'brz info
    [location]' command.

    :Examples:
        brz break-lock
        brz break-lock brz+ssh://example.com/brz/foo
        brz break-lock --conf ~/.config/breezy
    """

    takes_args = ["location?"]
    takes_options = [
        Option("config", help="LOCATION is the directory where the config lock is."),
        Option("force", help="Do not ask for confirmation before breaking the lock."),
    ]

    def run(self, location=None, config=False, force=False):
        if location is None:
            location = "."
        if force:
            ui.ui_factory = ui.ConfirmationUserInterfacePolicy(
                ui.ui_factory, None, {"breezy.lockdir.break": True}
            )
        if config:
            conf = _mod_config.LockableConfig(file_name=location)
            conf.break_lock()
        else:
            control, relpath = controldir.ControlDir.open_containing(location)
            with contextlib.suppress(NotImplementedError):
                control.break_lock()


class cmd_wait_until_signalled(Command):
    __doc__ = """Test helper for test_start_and_stop_brz_subprocess_send_signal.

    This just prints a line to signal when it is ready, then blocks on stdin.
    """

    hidden = True

    def run(self):
        self.outf.write("running\n")
        self.outf.flush()
        sys.stdin.readline()


class cmd_serve(Command):
    __doc__ = """Run the brz server."""

    aliases = ["server"]

    takes_options = [
        Option("inet", help="Serve on stdin/out for use from inetd or sshd."),
        RegistryOption(
            "protocol",
            help="Protocol to serve.",
            lazy_registry=("breezy.transport", "transport_server_registry"),
            value_switches=True,
        ),
        Option("listen", help="Listen for connections on nominated address.", type=str),
        Option(
            "port",
            help="Listen for connections on nominated port.  Passing 0 as "
            "the port number will result in a dynamically allocated "
            "port.  The default port depends on the protocol.",
            type=int,
        ),
        custom_help("directory", help="Serve contents of this directory."),
        Option(
            "allow-writes",
            help="By default the server is a readonly server.  Supplying "
            "--allow-writes enables write access to the contents of "
            "the served directory and below.  Note that ``brz serve`` "
            "does not perform authentication, so unless some form of "
            "external authentication is arranged supplying this "
            "option leads to global uncontrolled write access to your "
            "file system.",
        ),
        Option(
            "client-timeout",
            type=float,
            help="Override the default idle client timeout (5min).",
        ),
    ]

    def run(
        self,
        listen=None,
        port=None,
        inet=False,
        directory=None,
        allow_writes=False,
        protocol=None,
        client_timeout=None,
    ):
        from . import location, transport

        if directory is None:
            directory = osutils.getcwd()
        if protocol is None:
            protocol = transport.transport_server_registry.get()
        url = location.location_to_url(directory)
        if not allow_writes:
            url = "readonly+" + url
        t = transport.get_transport_from_url(url)
        protocol(t, listen, port, inet, client_timeout)


class cmd_join(Command):
    __doc__ = """Combine a tree into its containing tree.

    This command requires the target tree to be in a rich-root format.

    The TREE argument should be an independent tree, inside another tree, but
    not part of it.  (Such trees can be produced by "brz split", but also by
    running "brz branch" with the target inside a tree.)

    The result is a combined tree, with the subtree no longer an independent
    part.  This is marked as a merge of the subtree into the containing tree,
    and all history is preserved.
    """

    _see_also = ["split"]
    takes_args = ["tree"]
    takes_options = [
        Option("reference", help="Join by reference.", hidden=True),
    ]

    def run(self, tree, reference=False):
        from .mutabletree import BadReferenceTarget
        from .workingtree import WorkingTree

        sub_tree = WorkingTree.open(tree)
        parent_dir = osutils.dirname(sub_tree.basedir)
        containing_tree = WorkingTree.open_containing(parent_dir)[0]
        repo = containing_tree.branch.repository
        if not repo.supports_rich_root():
            raise errors.CommandError(
                gettext(
                    "Can't join trees because %s doesn't support rich root data.\n"
                    "You can use brz upgrade on the repository."
                )
                % (repo,)
            )
        if reference:
            try:
                containing_tree.add_reference(sub_tree)
            except BadReferenceTarget as exc:
                # XXX: Would be better to just raise a nicely printable
                # exception from the real origin.  Also below.  mbp 20070306
                raise errors.CommandError(
                    gettext("Cannot join {0}.  {1}").format(tree, exc.reason)
                ) from exc
        else:
            try:
                containing_tree.subsume(sub_tree)
            except errors.BadSubsumeSource as exc:
                raise errors.CommandError(
                    gettext("Cannot join {0}.  {1}").format(tree, exc.reason)
                ) from exc


class cmd_split(Command):
    __doc__ = """Split a subdirectory of a tree into a separate tree.

    This command will produce a target tree in a format that supports
    rich roots, like 'rich-root' or 'rich-root-pack'.  These formats cannot be
    converted into earlier formats like 'dirstate-tags'.

    The TREE argument should be a subdirectory of a working tree.  That
    subdirectory will be converted into an independent tree, with its own
    branch.  Commits in the top-level tree will not apply to the new subtree.
    """

    _see_also = ["join"]
    takes_args = ["tree"]

    def run(self, tree):
        from .workingtree import WorkingTree

        containing_tree, subdir = WorkingTree.open_containing(tree)
        if not containing_tree.is_versioned(subdir):
            raise errors.NotVersionedError(subdir)
        try:
            containing_tree.extract(subdir)
        except errors.RootNotRich as exc:
            raise errors.RichRootUpgradeRequired(containing_tree.branch.base) from exc


class cmd_merge_directive(Command):
    __doc__ = """Generate a merge directive for auto-merge tools.

    A directive requests a merge to be performed, and also provides all the
    information necessary to do so.  This means it must either include a
    revision bundle, or the location of a branch containing the desired
    revision.

    A submit branch (the location to merge into) must be supplied the first
    time the command is issued.  After it has been supplied once, it will
    be remembered as the default.

    A public branch is optional if a revision bundle is supplied, but required
    if --diff or --plain is specified.  It will be remembered as the default
    after the first use.
    """

    takes_args = ["submit_branch?", "public_branch?"]

    hidden = True

    _see_also = ["send"]

    takes_options = [
        "directory",
        RegistryOption.from_kwargs(
            "patch-type",
            "The type of patch to include in the directive.",
            title="Patch type",
            value_switches=True,
            enum_switch=False,
            bundle="Bazaar revision bundle (default).",
            diff="Normal unified diff.",
            plain="No patch, just directive.",
        ),
        Option("sign", help="GPG-sign the directive."),
        "revision",
        Option(
            "mail-to",
            type=str,
            help="Instead of printing the directive, email to this address.",
        ),
        Option(
            "message",
            type=str,
            short_name="m",
            help="Message to use when committing this merge.",
        ),
    ]

    encoding_type = "exact"

    def run(
        self,
        submit_branch=None,
        public_branch=None,
        patch_type="bundle",
        sign=False,
        revision=None,
        mail_to=None,
        message=None,
        directory=".",
    ):
        from . import merge_directive
        from .revision import NULL_REVISION

        include_patch, include_bundle = {
            "plain": (False, False),
            "diff": (True, False),
            "bundle": (True, True),
        }[patch_type]
        branch = Branch.open(directory)
        stored_submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = stored_submit_branch
        else:
            if stored_submit_branch is None:
                branch.set_submit_branch(submit_branch)
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.CommandError(gettext("No submit branch specified or known"))

        stored_public_branch = branch.get_public_branch()
        if public_branch is None:
            public_branch = stored_public_branch
        elif stored_public_branch is None:
            # FIXME: Should be done only if we succeed ? -- vila 2012-01-03
            branch.set_public_branch(public_branch)
        if not include_bundle and public_branch is None:
            raise errors.CommandError(gettext("No public branch specified or known"))
        base_revision_id = None
        if revision is not None:
            if len(revision) > 2:
                raise errors.CommandError(
                    gettext(
                        "brz merge-directive takes at most two one revision identifiers"
                    )
                )
            revision_id = revision[-1].as_revision_id(branch)
            if len(revision) == 2:
                base_revision_id = revision[0].as_revision_id(branch)
        else:
            revision_id = branch.last_revision()
        if revision_id == NULL_REVISION:
            raise errors.CommandError(gettext("No revisions to bundle."))
        directive = merge_directive.MergeDirective2.from_objects(
            repository=branch.repository,
            revision_id=revision_id,
            time=time.time(),
            timezone=osutils.local_time_offset(),
            target_branch=submit_branch,
            public_branch=public_branch,
            include_patch=include_patch,
            include_bundle=include_bundle,
            message=message,
            base_revision_id=base_revision_id,
        )
        if mail_to is None:
            if sign:
                self.outf.write(directive.to_signed(branch))
            else:
                self.outf.writelines(directive.to_lines())
        else:
            from .smtp_connection import SMTPConnection

            message = directive.to_email(mail_to, branch, sign)
            s = SMTPConnection(branch.get_config_stack())
            s.send_email(message)


class cmd_send(Command):
    __doc__ = """Mail or create a merge-directive for submitting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    `brz send` creates a compact data set that, when applied using brz
    merge, has the same effect as merging from the source branch.

    By default the merge directive is self-contained and can be applied to any
    branch containing submit_branch in its ancestory without needing access to
    the source branch.

    If --no-bundle is specified, then Breezy doesn't send the contents of the
    revisions, but only a structured request to merge from the
    public_location.  In that case the public_branch is needed and it must be
    up-to-date and accessible to the recipient.  The public_branch is always
    included if known, so that people can check it later.

    The submit branch defaults to the parent of the source branch, but can be
    overridden.  Both submit branch and public branch will be remembered in
    branch.conf the first time they are used for a particular branch.  The
    source branch defaults to that containing the working directory, but can
    be changed using --from.

    Both the submit branch and the public branch follow the usual behavior with
    respect to --remember: If there is no default location set, the first send
    will set it (use --no-remember to avoid setting it). After that, you can
    omit the location to use the default.  To change the default, use
    --remember. The value will only be saved if the location can be accessed.

    In order to calculate those changes, brz must analyse the submit branch.
    Therefore it is most efficient for the submit branch to be a local mirror.
    If a public location is known for the submit_branch, that location is used
    in the merge directive.

    The default behaviour is to send the merge directive by mail, unless -o is
    given, in which case it is sent to a file.

    Mail is sent using your preferred mail program.  This should be transparent
    on Windows (it uses MAPI).  On Unix, it requires the xdg-email utility.
    If the preferred client can't be found (or used), your editor will be used.

    To use a specific mail program, set the mail_client configuration option.
    Supported values for specific clients are "claws", "evolution", "kmail",
    "mail.app" (MacOS X's Mail.app), "mutt", and "thunderbird"; generic options
    are "default", "editor", "emacsclient", "mapi", and "xdg-email".  Plugins
    may also add supported clients.

    If mail is being sent, a to address is required.  This can be supplied
    either on the commandline, by setting the submit_to configuration
    option in the branch itself or the child_submit_to configuration option
    in the submit branch.

    The merge directives created by brz send may be applied using brz merge or
    brz pull by specifying a file containing a merge directive as the location.

    brz send makes extensive use of public locations to map local locations into
    URLs that can be used by other people.  See `brz help configuration` to
    set them, and use `brz info` to display them.
    """

    encoding_type = "exact"

    _see_also = ["merge", "pull"]

    takes_args = ["submit_branch?", "public_branch?"]

    takes_options = [
        Option("no-bundle", help="Do not include a bundle in the merge directive."),
        Option(
            "no-patch", help="Do not include a preview patch in the merge directive."
        ),
        Option("remember", help="Remember submit and public branch."),
        Option(
            "from",
            help="Branch to generate the submission from, "
            "rather than the one containing the working directory.",
            short_name="f",
            type=str,
        ),
        Option(
            "output",
            short_name="o",
            help="Write merge directive to this file or directory; use - for stdout.",
            type=str,
        ),
        Option(
            "strict",
            help="Refuse to send if there are uncommitted changes in"
            " the working tree, --no-strict disables the check.",
        ),
        Option("mail-to", help="Mail the request to this address.", type=str),
        "revision",
        "message",
        Option("body", help="Body for the email.", type=str),
        RegistryOption(
            "format",
            help="Use the specified output format.",
            lazy_registry=("breezy.send", "format_registry"),
        ),
    ]

    def run(
        self,
        submit_branch=None,
        public_branch=None,
        no_bundle=False,
        no_patch=False,
        revision=None,
        remember=None,
        output=None,
        format=None,
        mail_to=None,
        message=None,
        body=None,
        strict=None,
        **kwargs,
    ):
        from .send import send

        return send(
            submit_branch,
            revision,
            public_branch,
            remember,
            format,
            no_bundle,
            no_patch,
            output,
            kwargs.get("from", "."),
            mail_to,
            message,
            body,
            self.outf,
            strict=strict,
        )


class cmd_bundle_revisions(cmd_send):
    __doc__ = """Create a merge-directive for submitting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    If --no-bundle is specified, then public_branch is needed (and must be
    up-to-date), so that the receiver can perform the merge using the
    public_branch.  The public_branch is always included if known, so that
    people can check it later.

    The submit branch defaults to the parent, but can be overridden.  Both
    submit branch and public branch will be remembered if supplied.

    If a public_branch is known for the submit_branch, that public submit
    branch is used in the merge instructions.  This means that a local mirror
    can be used as your actual submit branch, once you have set public_branch
    for that mirror.
    """

    takes_options = [
        Option("no-bundle", help="Do not include a bundle in the merge directive."),
        Option(
            "no-patch", help="Do not include a preview patch in the merge directive."
        ),
        Option("remember", help="Remember submit and public branch."),
        Option(
            "from",
            help="Branch to generate the submission from, "
            "rather than the one containing the working directory.",
            short_name="f",
            type=str,
        ),
        Option(
            "output", short_name="o", help="Write directive to this file.", type=str
        ),
        Option(
            "strict",
            help="Refuse to bundle revisions if there are uncommitted"
            " changes in the working tree, --no-strict disables the check.",
        ),
        "revision",
        RegistryOption(
            "format",
            help="Use the specified output format.",
            lazy_registry=("breezy.send", "format_registry"),
        ),
    ]
    aliases = ["bundle"]

    _see_also = ["send", "merge"]

    hidden = True

    def run(
        self,
        submit_branch=None,
        public_branch=None,
        no_bundle=False,
        no_patch=False,
        revision=None,
        remember=False,
        output=None,
        format=None,
        strict=None,
        **kwargs,
    ):
        if output is None:
            output = "-"
        from .send import send

        return send(
            submit_branch,
            revision,
            public_branch,
            remember,
            format,
            no_bundle,
            no_patch,
            output,
            kwargs.get("from", "."),
            None,
            None,
            None,
            self.outf,
            strict=strict,
        )


class cmd_tag(Command):
    __doc__ = """Create, remove or modify a tag naming a revision.

    Tags give human-meaningful names to revisions.  Commands that take a -r
    (--revision) option can be given -rtag:X, where X is any previously
    created tag.

    Tags are stored in the branch.  Tags are copied from one branch to another
    along when you branch, push, pull or merge.

    It is an error to give a tag name that already exists unless you pass
    --force, in which case the tag is moved to point to the new revision.

    To rename a tag (change the name but keep it on the same revsion), run ``brz
    tag new-name -r tag:old-name`` and then ``brz tag --delete oldname``.

    If no tag name is specified it will be determined through the
    'automatic_tag_name' hook. This can e.g. be used to automatically tag
    upstream releases by reading configure.ac. See ``brz help hooks`` for
    details.
    """

    _see_also = ["commit", "tags"]
    takes_args = ["tag_name?"]
    takes_options = [
        Option(
            "delete",
            help="Delete this tag rather than placing it.",
        ),
        custom_help("directory", help="Branch in which to place the tag."),
        Option(
            "force",
            help="Replace existing tags.",
        ),
        "revision",
    ]

    def run(
        self,
        tag_name=None,
        delete=None,
        directory=".",
        force=None,
        revision=None,
    ):
        branch, relpath = Branch.open_containing(directory)
        self.enter_context(branch.lock_write())
        if delete:
            if tag_name is None:
                raise errors.CommandError(gettext("No tag specified to delete."))
            branch.tags.delete_tag(tag_name)
            note(gettext("Deleted tag %s.") % tag_name)
        else:
            if revision:
                if len(revision) != 1:
                    raise errors.CommandError(
                        gettext(
                            "Tags can only be placed on a single revision, "
                            "not on a range"
                        )
                    )
                revision_id = revision[0].as_revision_id(branch)
            else:
                revision_id = branch.last_revision()
            if tag_name is None:
                tag_name = branch.automatic_tag_name(revision_id)
                if tag_name is None:
                    raise errors.CommandError(gettext("Please specify a tag name."))
            try:
                existing_target = branch.tags.lookup_tag(tag_name)
            except errors.NoSuchTag:
                existing_target = None
            if not force and existing_target not in (None, revision_id):
                raise errors.TagAlreadyExists(tag_name)
            if existing_target == revision_id:
                note(gettext("Tag %s already exists for that revision.") % tag_name)
            else:
                branch.tags.set_tag(tag_name, revision_id)
                if existing_target is None:
                    note(gettext("Created tag %s.") % tag_name)
                else:
                    note(gettext("Updated tag %s.") % tag_name)


class cmd_tags(Command):
    __doc__ = """List tags.

    This command shows a table of tag names and the revisions they reference.
    """

    _see_also = ["tag"]
    takes_options = [
        custom_help("directory", help="Branch whose tags should be displayed."),
        RegistryOption(
            "sort",
            "Sort tags by different criteria.",
            title="Sorting",
            lazy_registry=("breezy.tag", "tag_sort_methods"),
        ),
        "show-ids",
        "revision",
    ]

    @display_command
    def run(self, directory=".", sort=None, show_ids=False, revision=None):
        from .tag import tag_sort_methods

        branch, relpath = Branch.open_containing(directory)

        tags = list(branch.tags.get_tag_dict().items())
        if not tags:
            return

        self.enter_context(branch.lock_read())
        if revision:
            # Restrict to the specified range
            tags = self._tags_for_range(branch, revision)
        if sort is None:
            sort = tag_sort_methods.get()
        sort(branch, tags)
        if not show_ids:
            # [ (tag, revid), ... ] -> [ (tag, dotted_revno), ... ]
            for index, (tag, revid) in enumerate(tags):
                try:
                    revno = branch.revision_id_to_dotted_revno(revid)
                    if isinstance(revno, tuple):
                        revno = ".".join(map(str, revno))
                except (
                    errors.NoSuchRevision,
                    errors.GhostRevisionsHaveNoRevno,
                    errors.UnsupportedOperation,
                ):
                    # Bad tag data/merges can lead to tagged revisions
                    # which are not in this branch. Fail gracefully ...
                    revno = "?"
                tags[index] = (tag, revno)
        else:
            tags = [(tag, revid.decode("utf-8")) for (tag, revid) in tags]
        self.cleanup_now()
        for tag, revspec in tags:
            self.outf.write("%-20s %s\n" % (tag, revspec))

    def _tags_for_range(self, branch, revision):
        rev1, rev2 = _get_revision_range(revision, branch, self.name())
        revid1, revid2 = rev1.rev_id, rev2.rev_id
        # _get_revision_range will always set revid2 if it's not specified.
        # If revid1 is None, it means we want to start from the branch
        # origin which is always a valid ancestor. If revid1 == revid2, the
        # ancestry check is useless.
        if revid1 and revid1 != revid2:
            # FIXME: We really want to use the same graph than
            # branch.iter_merge_sorted_revisions below, but this is not
            # easily available -- vila 2011-09-23
            if branch.repository.get_graph().is_ancestor(revid2, revid1):
                # We don't want to output anything in this case...
                return []
        # only show revisions between revid1 and revid2 (inclusive)
        tagged_revids = branch.tags.get_reverse_tag_dict()
        found = []
        for r in branch.iter_merge_sorted_revisions(
            start_revision_id=revid2, stop_revision_id=revid1, stop_rule="include"
        ):
            revid_tags = tagged_revids.get(r[0], None)
            if revid_tags:
                found.extend([(tag, r[0]) for tag in revid_tags])
        return found


class cmd_reconfigure(Command):
    __doc__ = """Reconfigure the type of a brz directory.

    A target configuration must be specified.

    For checkouts, the bind-to location will be auto-detected if not specified.
    The order of preference is
    1. For a lightweight checkout, the current bound location.
    2. For branches that used to be checkouts, the previously-bound location.
    3. The push location.
    4. The parent location.
    If none of these is available, --bind-to must be specified.
    """

    _see_also = ["branches", "checkouts", "standalone-trees", "working-trees"]
    takes_args = ["location?"]
    takes_options = [
        RegistryOption.from_kwargs(
            "tree_type",
            title="Tree type",
            help="The relation between branch and tree.",
            value_switches=True,
            enum_switch=False,
            branch="Reconfigure to be an unbound branch with no working tree.",
            tree="Reconfigure to be an unbound branch with a working tree.",
            checkout="Reconfigure to be a bound branch with a working tree.",
            lightweight_checkout="Reconfigure to be a lightweight"
            " checkout (with no local history).",
        ),
        RegistryOption.from_kwargs(
            "repository_type",
            title="Repository type",
            help="Location fo the repository.",
            value_switches=True,
            enum_switch=False,
            standalone="Reconfigure to be a standalone branch "
            "(i.e. stop using shared repository).",
            use_shared="Reconfigure to use a shared repository.",
        ),
        RegistryOption.from_kwargs(
            "repository_trees",
            title="Trees in Repository",
            help="Whether new branches in the repository have trees.",
            value_switches=True,
            enum_switch=False,
            with_trees="Reconfigure repository to create "
            "working trees on branches by default.",
            with_no_trees="Reconfigure repository to not create "
            "working trees on branches by default.",
        ),
        Option("bind-to", help="Branch to bind checkout to.", type=str),
        Option(
            "force",
            help="Perform reconfiguration even if local changes will be lost.",
        ),
        Option(
            "stacked-on",
            help="Reconfigure a branch to be stacked on another branch.",
            type=str,
        ),
        Option(
            "unstacked",
            help="Reconfigure a branch to be unstacked.  This "
            "may require copying substantial data into it.",
        ),
    ]

    def run(
        self,
        location=None,
        bind_to=None,
        force=False,
        tree_type=None,
        repository_type=None,
        repository_trees=None,
        stacked_on=None,
        unstacked=None,
    ):
        from . import reconfigure

        directory = controldir.ControlDir.open(location)
        if stacked_on and unstacked:
            raise errors.CommandError(
                gettext("Can't use both --stacked-on and --unstacked")
            )
        elif stacked_on is not None:
            reconfigure.ReconfigureStackedOn().apply(directory, stacked_on)
        elif unstacked:
            reconfigure.ReconfigureUnstacked().apply(directory)
        # At the moment you can use --stacked-on and a different
        # reconfiguration shape at the same time; there seems no good reason
        # to ban it.
        if tree_type is None and repository_type is None and repository_trees is None:
            if stacked_on or unstacked:
                return
            else:
                raise errors.CommandError(gettext("No target configuration specified"))
        reconfiguration = None
        if tree_type == "branch":
            reconfiguration = reconfigure.Reconfigure.to_branch(directory)
        elif tree_type == "tree":
            reconfiguration = reconfigure.Reconfigure.to_tree(directory)
        elif tree_type == "checkout":
            reconfiguration = reconfigure.Reconfigure.to_checkout(directory, bind_to)
        elif tree_type == "lightweight-checkout":
            reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
                directory, bind_to
            )
        if reconfiguration:
            reconfiguration.apply(force)
            reconfiguration = None
        if repository_type == "use-shared":
            reconfiguration = reconfigure.Reconfigure.to_use_shared(directory)
        elif repository_type == "standalone":
            reconfiguration = reconfigure.Reconfigure.to_standalone(directory)
        if reconfiguration:
            reconfiguration.apply(force)
            reconfiguration = None
        if repository_trees == "with-trees":
            reconfiguration = reconfigure.Reconfigure.set_repository_trees(
                directory, True
            )
        elif repository_trees == "with-no-trees":
            reconfiguration = reconfigure.Reconfigure.set_repository_trees(
                directory, False
            )
        if reconfiguration:
            reconfiguration.apply(force)
            reconfiguration = None


class cmd_switch(Command):
    __doc__ = """Set the branch of a checkout and update.

    For lightweight checkouts, this changes the branch being referenced.
    For heavyweight checkouts, this checks that there are no local commits
    versus the current bound branch, then it makes the local branch a mirror
    of the new location and binds to it.

    In both cases, the working tree is updated and uncommitted changes
    are merged. The user can commit or revert these as they desire.

    Pending merges need to be committed or reverted before using switch.

    The path to the branch to switch to can be specified relative to the parent
    directory of the current branch. For example, if you are currently in a
    checkout of /path/to/branch, specifying 'newbranch' will find a branch at
    /path/to/newbranch.

    Bound branches use the nickname of its master branch unless it is set
    locally, in which case switching will update the local nickname to be
    that of the master.
    """

    takes_args = ["to_location?"]
    takes_options = [
        "directory",
        Option("force", help="Switch even if local commits will be lost."),
        "revision",
        Option(
            "create-branch",
            short_name="b",
            help="Create the target branch from this one before switching to it.",
        ),
        Option("store", help="Store and restore uncommitted changes in the branch."),
    ]

    def run(
        self,
        to_location=None,
        force=False,
        create_branch=False,
        revision=None,
        directory=".",
        store=False,
    ):
        from . import switch

        tree_location = directory
        revision = _get_one_revision("switch", revision)
        control_dir = controldir.ControlDir.open_containing(tree_location)[0]
        possible_transports = [control_dir.root_transport]
        if to_location is None:
            if revision is None:
                raise errors.CommandError(
                    gettext("You must supply either a revision or a location")
                )
            to_location = tree_location
        try:
            branch = control_dir.open_branch(possible_transports=possible_transports)
            had_explicit_nick = branch.get_config().has_explicit_nickname()
        except errors.NotBranchError:
            branch = None
            had_explicit_nick = False
        else:
            possible_transports.append(branch.user_transport)
        if create_branch:
            if branch is None:
                raise errors.CommandError(
                    gettext("cannot create branch without source branch")
                )
            to_location = lookup_new_sibling_branch(
                control_dir, to_location, possible_transports=possible_transports
            )
            if revision is not None:
                revision = revision.as_revision_id(branch)
            to_branch = branch.controldir.sprout(
                to_location,
                possible_transports=possible_transports,
                revision_id=revision,
                source_branch=branch,
            ).open_branch()
        else:
            try:
                to_branch = Branch.open(
                    to_location, possible_transports=possible_transports
                )
            except errors.NotBranchError:
                to_branch = open_sibling_branch(
                    control_dir, to_location, possible_transports=possible_transports
                )
            if revision is not None:
                revision = revision.as_revision_id(to_branch)
        possible_transports.append(to_branch.user_transport)
        try:
            switch.switch(
                control_dir,
                to_branch,
                force,
                revision_id=revision,
                store_uncommitted=store,
                possible_transports=possible_transports,
            )
        except controldir.BranchReferenceLoop as exc:
            raise errors.CommandError(
                gettext(
                    "switching would create a branch reference loop. "
                    'Use the "bzr up" command to switch to a '
                    "different revision."
                )
            ) from exc
        if had_explicit_nick:
            branch = control_dir.open_branch()  # get the new branch!
            branch.nick = to_branch.nick
        if to_branch.name:
            if to_branch.controldir.control_url != control_dir.control_url:
                note(
                    gettext("Switched to branch %s at %s"),
                    to_branch.name,
                    urlutils.unescape_for_display(to_branch.base, "utf-8"),
                )
            else:
                note(gettext("Switched to branch %s"), to_branch.name)
        else:
            note(
                gettext("Switched to branch at %s"),
                urlutils.unescape_for_display(to_branch.base, "utf-8"),
            )


class cmd_view(Command):
    __doc__ = """Manage filtered views.

    Views provide a mask over the tree so that users can focus on
    a subset of a tree when doing their work. After creating a view,
    commands that support a list of files - status, diff, commit, etc -
    effectively have that list of files implicitly given each time.
    An explicit list of files can still be given but those files
    must be within the current view.

    In most cases, a view has a short life-span: it is created to make
    a selected change and is deleted once that change is committed.
    At other times, you may wish to create one or more named views
    and switch between them.

    To disable the current view without deleting it, you can switch to
    the pseudo view called ``off``. This can be useful when you need
    to see the whole tree for an operation or two (e.g. merge) but
    want to switch back to your view after that.

    :Examples:
      To define the current view::

        brz view file1 dir1 ...

      To list the current view::

        brz view

      To delete the current view::

        brz view --delete

      To disable the current view without deleting it::

        brz view --switch off

      To define a named view and switch to it::

        brz view --name view-name file1 dir1 ...

      To list a named view::

        brz view --name view-name

      To delete a named view::

        brz view --name view-name --delete

      To switch to a named view::

        brz view --switch view-name

      To list all views defined::

        brz view --all

      To delete all views::

        brz view --delete --all
    """

    takes_args = ["file*"]
    takes_options = [
        Option(
            "all",
            help="Apply list or delete action to all views.",
        ),
        Option(
            "delete",
            help="Delete the view.",
        ),
        Option(
            "name",
            help="Name of the view to define, list or delete.",
            type=str,
        ),
        Option(
            "switch",
            help="Name of the view to switch to.",
            type=str,
        ),
    ]

    def run(
        self,
        file_list,
        all=False,
        delete=False,
        name=None,
        switch=None,
    ):
        from . import views
        from .workingtree import WorkingTree

        tree, file_list = WorkingTree.open_containing_paths(file_list, apply_view=False)
        current_view, view_dict = tree.views.get_view_info()
        if name is None:
            name = current_view
        if delete:
            if file_list:
                raise errors.CommandError(
                    gettext("Both --delete and a file list specified")
                )
            elif switch:
                raise errors.CommandError(
                    gettext("Both --delete and --switch specified")
                )
            elif all:
                tree.views.set_view_info(None, {})
                self.outf.write(gettext("Deleted all views.\n"))
            elif name is None:
                raise errors.CommandError(gettext("No current view to delete"))
            else:
                tree.views.delete_view(name)
                self.outf.write(gettext("Deleted '%s' view.\n") % name)
        elif switch:
            if file_list:
                raise errors.CommandError(
                    gettext("Both --switch and a file list specified")
                )
            elif all:
                raise errors.CommandError(gettext("Both --switch and --all specified"))
            elif switch == "off":
                if current_view is None:
                    raise errors.CommandError(gettext("No current view to disable"))
                tree.views.set_view_info(None, view_dict)
                self.outf.write(gettext("Disabled '%s' view.\n") % (current_view))
            else:
                tree.views.set_view_info(switch, view_dict)
                view_str = views.view_display_str(tree.views.lookup_view())
                self.outf.write(
                    gettext("Using '{0}' view: {1}\n").format(switch, view_str)
                )
        elif all:
            if view_dict:
                self.outf.write(gettext("Views defined:\n"))
                for view in sorted(view_dict):
                    active = "=>" if view == current_view else "  "
                    view_str = views.view_display_str(view_dict[view])
                    self.outf.write("%s %-20s %s\n" % (active, view, view_str))
            else:
                self.outf.write(gettext("No views defined.\n"))
        elif file_list:
            if name is None:
                # No name given and no current view set
                name = "my"
            elif name == "off":
                raise errors.CommandError(
                    gettext("Cannot change the 'off' pseudo view")
                )
            tree.views.set_view(name, sorted(file_list))
            view_str = views.view_display_str(tree.views.lookup_view())
            self.outf.write(gettext("Using '{0}' view: {1}\n").format(name, view_str))
        else:
            # list the files
            if name is None:
                # No name given and no current view set
                self.outf.write(gettext("No current view.\n"))
            else:
                view_str = views.view_display_str(tree.views.lookup_view(name))
                self.outf.write(gettext("'{0}' view is: {1}\n").format(name, view_str))


class cmd_hooks(Command):
    __doc__ = """Show hooks."""

    hidden = True

    def run(self):
        for hook_key in sorted(hooks.known_hooks.keys()):
            some_hooks = hooks.known_hooks_key_to_object(hook_key)
            self.outf.write(f"{type(some_hooks).__name__}:\n")
            for hook_name, hook_point in sorted(some_hooks.items()):
                self.outf.write(f"  {hook_name}:\n")
                found_hooks = list(hook_point)
                if found_hooks:
                    for hook in found_hooks:
                        self.outf.write(f"    {some_hooks.get_hook_name(hook)}\n")
                else:
                    self.outf.write(gettext("    <no hooks installed>\n"))


class cmd_remove_branch(Command):
    __doc__ = """Remove a branch.

    This will remove the branch from the specified location but
    will keep any working tree or repository in place.

    :Examples:

      Remove the branch at repo/trunk::

        brz remove-branch repo/trunk

    """

    takes_args = ["location?"]

    takes_options = [
        "directory",
        Option("force", help="Remove branch even if it is the active branch."),
    ]

    aliases = ["rmbranch"]

    def run(self, directory=None, location=None, force=False):
        br = open_nearby_branch(near=directory, location=location)
        if not force and br.controldir.has_workingtree():
            try:
                active_branch = br.controldir.open_branch(name="")
            except errors.NotBranchError:
                active_branch = None
            if (
                active_branch is not None
                and br.control_url == active_branch.control_url
            ):
                raise errors.CommandError(
                    gettext("Branch is active. Use --force to remove it.")
                )
        br.controldir.destroy_branch(br.name)


class cmd_shelve(Command):
    __doc__ = """Temporarily set aside some changes from the current tree.

    Shelve allows you to temporarily put changes you've made "on the shelf",
    ie. out of the way, until a later time when you can bring them back from
    the shelf with the 'unshelve' command.  The changes are stored alongside
    your working tree, and so they aren't propagated along with your branch nor
    will they survive its deletion.

    If shelve --list is specified, previously-shelved changes are listed.

    Shelve is intended to help separate several sets of changes that have
    been inappropriately mingled.  If you just want to get rid of all changes
    and you don't need to restore them later, use revert.  If you want to
    shelve all text changes at once, use shelve --all.

    If filenames are specified, only the changes to those files will be
    shelved. Other files will be left untouched.

    If a revision is specified, changes since that revision will be shelved.

    You can put multiple items on the shelf, and by default, 'unshelve' will
    restore the most recently shelved changes.

    For complicated changes, it is possible to edit the changes in a separate
    editor program to decide what the file remaining in the working copy
    should look like.  To do this, add the configuration option

        change_editor = PROGRAM {new_path} {old_path}

    where {new_path} is replaced with the path of the new version of the
    file and {old_path} is replaced with the path of the old version of
    the file.  The PROGRAM should save the new file with the desired
    contents of the file in the working tree.

    """

    takes_args = ["file*"]

    takes_options = [
        "directory",
        "revision",
        Option("all", help="Shelve all changes."),
        "message",
        RegistryOption(
            "writer",
            "Method to use for writing diffs.",
            breezy.option.diff_writer_registry,
            value_switches=True,
            enum_switch=False,
        ),
        Option("list", help="List shelved changes."),
        Option("destroy", help="Destroy removed changes instead of shelving them."),
    ]
    _see_also = ["unshelve", "configuration"]

    def run(
        self,
        revision=None,
        all=False,
        file_list=None,
        message=None,
        writer=None,
        list=False,
        destroy=False,
        directory=None,
    ):
        if list:
            return self.run_for_list(directory=directory)
        from .shelf_ui import Shelver

        if writer is None:
            writer = breezy.option.diff_writer_registry.get()
        try:
            shelver = Shelver.from_args(
                writer(self.outf),
                revision,
                all,
                file_list,
                message,
                destroy=destroy,
                directory=directory,
            )
            try:
                shelver.run()
            finally:
                shelver.finalize()
        except errors.UserAbort:
            return 0

    def run_for_list(self, directory=None):
        from .workingtree import WorkingTree

        if directory is None:
            directory = "."
        tree = WorkingTree.open_containing(directory)[0]
        self.enter_context(tree.lock_read())
        manager = tree.get_shelf_manager()
        shelves = manager.active_shelves()
        if len(shelves) == 0:
            note(gettext("No shelved changes."))
            return 0
        for shelf_id in reversed(shelves):
            message = manager.get_metadata(shelf_id).get(b"message")
            if message is None:
                message = "<no message>"
            self.outf.write("%3d: %s\n" % (shelf_id, message))
        return 1


class cmd_unshelve(Command):
    __doc__ = """Restore shelved changes.

    By default, the most recently shelved changes are restored. However if you
    specify a shelf by id those changes will be restored instead.  This works
    best when the changes don't depend on each other.
    """

    takes_args = ["shelf_id?"]
    takes_options = [
        "directory",
        RegistryOption.from_kwargs(
            "action",
            help="The action to perform.",
            enum_switch=False,
            value_switches=True,
            apply="Apply changes and remove from the shelf.",
            dry_run="Show changes, but do not apply or remove them.",
            preview="Instead of unshelving the changes, show the diff that "
            "would result from unshelving.",
            delete_only="Delete changes without applying them.",
            keep="Apply changes but don't delete them.",
        ),
    ]
    _see_also = ["shelve"]

    def run(self, shelf_id=None, action="apply", directory="."):
        from .shelf_ui import Unshelver

        unshelver = Unshelver.from_args(shelf_id, action, directory=directory)
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()


class cmd_clean_tree(Command):
    __doc__ = """Remove unwanted files from working tree.

    By default, only unknown files, not ignored files, are deleted.  Versioned
    files are never deleted.

    Another class is 'detritus', which includes files emitted by brz during
    normal operations and selftests.  (The value of these files decreases with
    time.)

    If no options are specified, unknown files are deleted.  Otherwise, option
    flags are respected, and may be combined.

    To check what clean-tree will do, use --dry-run.
    """
    takes_options = [
        "directory",
        Option("ignored", help="Delete all ignored files."),
        Option(
            "detritus",
            help="Delete conflict files, merge and revert"
            " backups, and failed selftest dirs.",
        ),
        Option("unknown", help="Delete files unknown to brz (default)."),
        Option("dry-run", help="Show files to delete instead of deleting them."),
        Option("force", help="Do not prompt before deleting."),
    ]

    def run(
        self,
        unknown=False,
        ignored=False,
        detritus=False,
        dry_run=False,
        force=False,
        directory=".",
    ):
        from .clean_tree import clean_tree

        if not (unknown or ignored or detritus):
            unknown = True
        if dry_run:
            force = True
        clean_tree(
            directory,
            unknown=unknown,
            ignored=ignored,
            detritus=detritus,
            dry_run=dry_run,
            no_prompt=force,
        )


class cmd_reference(Command):
    __doc__ = """list, view and set branch locations for nested trees.

    If no arguments are provided, lists the branch locations for nested trees.
    If one argument is provided, display the branch location for that tree.
    If two arguments are provided, set the branch location for that tree.
    """

    hidden = True

    takes_args = ["path?", "location?"]
    takes_options = [
        "directory",
        Option(
            "force-unversioned", help="Set reference even if path is not versioned."
        ),
    ]

    def run(self, path=None, directory=".", location=None, force_unversioned=False):
        tree, branch, relpath = controldir.ControlDir.open_containing_tree_or_branch(
            directory
        )
        if tree is None:
            tree = branch.basis_tree()
        if path is None:
            with tree.lock_read():
                info = [
                    (path, tree.get_reference_info(path, branch))
                    for path in tree.iter_references()
                ]
                self._display_reference_info(tree, branch, info)
        else:
            if not tree.is_versioned(path) and not force_unversioned:
                raise errors.NotVersionedError(path)
            if location is None:
                info = [(path, tree.get_reference_info(path, branch))]
                self._display_reference_info(tree, branch, info)
            else:
                tree.set_reference_info(path, location)

    def _display_reference_info(self, tree, branch, info):
        ref_list = []
        for path, location in info:
            ref_list.append((path, location))
        for path, location in sorted(ref_list):
            self.outf.write(f"{path} {location}\n")


class cmd_export_pot(Command):
    __doc__ = """Export command helps and error messages in po format."""

    hidden = True
    takes_options = [
        Option(
            "plugin",
            help="Export help text from named command "
            "(defaults to all built in commands).",
            type=str,
        ),
        Option(
            "include-duplicates",
            help="Output multiple copies of the same msgid "
            "string if it appears more than once.",
        ),
    ]

    def run(self, plugin=None, include_duplicates=False):
        from .export_pot import export_pot

        export_pot(self.outf, plugin, include_duplicates)


class cmd_import(Command):
    __doc__ = """Import sources from a directory, tarball or zip file

    This command will import a directory, tarball or zip file into a bzr
    tree, replacing any versioned files already present.  If a directory is
    specified, it is used as the target.  If the directory does not exist, or
    is not versioned, it is created.

    Tarballs may be gzip or bzip2 compressed.  This is autodetected.

    If the tarball or zip has a single root directory, that directory is
    stripped when extracting the tarball.  This is not done for directories.
    """

    takes_args = ["source", "tree?"]

    def run(self, source, tree=None):
        from .upstream_import import do_import

        do_import(source, tree)


class cmd_link_tree(Command):
    __doc__ = """Hardlink matching files to another tree.

    Only files with identical content and execute bit will be linked.
    """

    takes_args = ["location"]

    def run(self, location):
        from .transform import link_tree
        from .workingtree import WorkingTree

        target_tree = WorkingTree.open_containing(".")[0]
        source_tree = WorkingTree.open(location)
        with target_tree.lock_write(), source_tree.lock_read():
            link_tree(target_tree, source_tree)


class cmd_fetch_ghosts(Command):
    __doc__ = """Attempt to retrieve ghosts from another branch.

    If the other branch is not supplied, the last-pulled branch is used.
    """

    hidden = True
    aliases = ["fetch-missing"]
    takes_args = ["branch?"]
    takes_options = [Option("no-fix", help="Skip additional synchonization.")]

    def run(self, branch=None, no_fix=False):
        from .fetch_ghosts import GhostFetcher

        installed, failed = GhostFetcher.from_cmdline(branch).run()
        if len(installed) > 0:
            self.outf.write("Installed:\n")
            for rev in installed:
                self.outf.write(rev.decode("utf-8") + "\n")
        if len(failed) > 0:
            self.outf.write("Still missing:\n")
            for rev in failed:
                self.outf.write(rev.decode("utf-8") + "\n")
        if not no_fix and len(installed) > 0:
            cmd_reconcile().run(".")


class cmd_grep(Command):
    r"""Print lines matching PATTERN for specified files and revisions.

    This command searches the specified files and revisions for a given
    pattern.  The pattern is specified as a Python regular expressions[1].

    If the file name is not specified, the revisions starting with the
    current directory are searched recursively. If the revision number is
    not specified, the working copy is searched. To search the last committed
    revision, use the '-r -1' or '-r last:1' option.

    Unversioned files are not searched unless explicitly specified on the
    command line. Unversioned directores are not searched.

    When searching a pattern, the output is shown in the 'filepath:string'
    format. If a revision is explicitly searched, the output is shown as
    'filepath~N:string', where N is the revision number.

    --include and --exclude options can be used to search only (or exclude
    from search) files with base name matches the specified Unix style GLOB
    pattern.  The GLOB pattern an use *, ?, and [...] as wildcards, and \
    to quote wildcard or backslash character literally. Note that the glob
    pattern is not a regular expression.

    [1] http://docs.python.org/library/re.html#regular-expression-syntax
    """

    encoding_type = "replace"
    takes_args = ["pattern", "path*"]
    takes_options = [
        "verbose",
        "revision",
        Option(
            "color",
            type=str,
            argname="when",
            help="Show match in color. WHEN is never, always or auto.",
        ),
        Option(
            "diff",
            short_name="p",
            help="Grep for pattern in changeset for each revision.",
        ),
        ListOption(
            "exclude",
            type=str,
            argname="glob",
            short_name="X",
            help="Skip files whose base name matches GLOB.",
        ),
        ListOption(
            "include",
            type=str,
            argname="glob",
            short_name="I",
            help="Search only files whose base name matches GLOB.",
        ),
        Option(
            "files-with-matches",
            short_name="l",
            help="Print only the name of each input file in which PATTERN is found.",
        ),
        Option(
            "files-without-match",
            short_name="L",
            help="Print only the name of each input file in "
            "which PATTERN is not found.",
        ),
        Option(
            "fixed-string",
            short_name="F",
            help="Interpret PATTERN is a single fixed string (not regex).",
        ),
        Option(
            "from-root",
            help="Search for pattern starting from the root of the branch. "
            "(implies --recursive)",
        ),
        Option(
            "ignore-case",
            short_name="i",
            help="Ignore case distinctions while matching.",
        ),
        Option(
            "levels",
            help="Number of levels to display - 0 for all, 1 for collapsed "
            "(1 is default).",
            argname="N",
            type=_parse_levels,
        ),
        Option("line-number", short_name="n", help="Show 1-based line number."),
        Option(
            "no-recursive",
            help="Don't recurse into subdirectories. (default is --recursive)",
        ),
        Option(
            "null",
            short_name="Z",
            help="Write an ASCII NUL (\\0) separator "
            "between output lines rather than a newline.",
        ),
    ]

    @display_command
    def run(
        self,
        verbose=False,
        ignore_case=False,
        no_recursive=False,
        from_root=False,
        null=False,
        levels=None,
        line_number=False,
        path_list=None,
        revision=None,
        pattern=None,
        include=None,
        exclude=None,
        fixed_string=False,
        files_with_matches=False,
        files_without_match=False,
        color=None,
        diff=False,
    ):
        import re

        from breezy import terminal

        from . import grep

        if path_list is None:
            path_list = ["."]
        else:
            if from_root:
                raise errors.CommandError("cannot specify both --from-root and PATH.")

        if files_with_matches and files_without_match:
            raise errors.CommandError(
                "cannot specify both "
                "-l/--files-with-matches and -L/--files-without-matches."
            )

        global_config = _mod_config.GlobalConfig()

        if color is None:
            color = global_config.get_user_option("grep_color")

        if color is None:
            color = "auto"

        if color not in ["always", "never", "auto"]:
            raise errors.CommandError(
                'Valid values for --color are "always", "never" or "auto".'
            )

        if levels is None:
            levels = 1

        print_revno = False
        if revision is not None or levels == 0:
            # print revision numbers as we may be showing multiple revisions
            print_revno = True

        eol_marker = "\n"
        if null:
            eol_marker = "\0"

        if not ignore_case and grep.is_fixed_string(pattern):
            # if the pattern isalnum, implicitly use to -F for faster grep
            fixed_string = True
        elif ignore_case and fixed_string:
            # GZ 2010-06-02: Fall back to regexp rather than lowercasing
            #                pattern and text which will cause pain later
            fixed_string = False
            pattern = re.escape(pattern)

        patternc = None
        re_flags = re.MULTILINE
        if ignore_case:
            re_flags |= re.IGNORECASE

        if not fixed_string:
            patternc = grep.compile_pattern(
                pattern.encode(grep._user_encoding), re_flags
            )

        if color == "always":
            show_color = True
        elif color == "never":
            show_color = False
        elif color == "auto":
            show_color = terminal.has_ansi_colors()

        opts = grep.GrepOptions()

        opts.verbose = verbose
        opts.ignore_case = ignore_case
        opts.no_recursive = no_recursive
        opts.from_root = from_root
        opts.null = null
        opts.levels = levels
        opts.line_number = line_number
        opts.path_list = path_list
        opts.revision = revision
        opts.pattern = pattern
        opts.include = include
        opts.exclude = exclude
        opts.fixed_string = fixed_string
        opts.files_with_matches = files_with_matches
        opts.files_without_match = files_without_match
        opts.color = color
        opts.diff = False

        opts.eol_marker = eol_marker
        opts.print_revno = print_revno
        opts.patternc = patternc
        opts.recursive = not no_recursive
        opts.fixed_string = fixed_string
        opts.outf = self.outf
        opts.show_color = show_color

        if diff:
            # options not used:
            # files_with_matches, files_without_match
            # levels(?), line_number, from_root
            # include, exclude
            # These are silently ignored.
            grep.grep_diff(opts)
        elif revision is None:
            grep.workingtree_grep(opts)
        else:
            grep.versioned_grep(opts)


class cmd_patch(Command):
    """Apply a named patch to the current tree."""

    takes_args = ["filename?"]
    takes_options = [
        Option(
            "strip",
            type=int,
            short_name="p",
            help=(
                "Strip the smallest prefix containing num "
                "leading slashes from filenames."
            ),
        ),
        Option("silent", help="Suppress chatter."),
    ]

    def run(self, filename=None, strip=None, silent=False):
        from .workingtree import WorkingTree, patch_tree

        wt = WorkingTree.open_containing(".")[0]
        if strip is None:
            strip = 1
        my_file = None
        if filename is None:
            my_file = getattr(sys.stdin, "buffer", sys.stdin)
        else:
            my_file = open(filename, "rb")
        with my_file:
            patches = [my_file.read()]
        from io import BytesIO

        b = BytesIO()
        patch_tree(wt, patches, strip, quiet=is_quiet(), out=b)
        self.outf.write(b.getvalue().decode("utf-8", "replace"))


class cmd_resolve_location(Command):
    __doc__ = """Expand a location to a full URL.

    :Examples:
        Look up a Launchpad URL.

            brz resolve-location lp:brz
    """
    takes_args = ["location"]
    hidden = True

    def run(self, location):
        from .location import location_to_url

        url = location_to_url(location)
        display_url = urlutils.unescape_for_display(url, self.outf.encoding)
        self.outf.write(f"{display_url}\n")


def _register_lazy_builtins():
    """Register lazy builtin commands from other modules.

    This function registers commands that are implemented in separate modules
    to be loaded on demand. Called at startup and should be only called once.

    Note:
        This lazy loading approach helps reduce startup time by deferring
        the import of command implementation modules until they are actually
        needed.
    """
    # register lazy builtins from other modules; called at startup and should
    # be only called once.
    for name, aliases, module_name in [
        ("cmd_bisect", [], "breezy.bisect"),
        ("cmd_bundle_info", [], "breezy.bzr.bundle.commands"),
        ("cmd_config", [], "breezy.config"),
        ("cmd_dump_btree", [], "breezy.bzr.debug_commands"),
        ("cmd_file_id", [], "breezy.bzr.debug_commands"),
        ("cmd_file_path", [], "breezy.bzr.debug_commands"),
        ("cmd_version_info", [], "breezy.cmd_version_info"),
        ("cmd_resolve", ["resolved"], "breezy.conflicts"),
        ("cmd_conflicts", [], "breezy.conflicts"),
        ("cmd_ping", [], "breezy.bzr.smart.ping"),
        ("cmd_sign_my_commits", [], "breezy.commit_signature_commands"),
        ("cmd_verify_signatures", [], "breezy.commit_signature_commands"),
        ("cmd_test_script", [], "breezy.cmd_test_script"),
    ]:
        builtin_command_registry.register_lazy(name, aliases, module_name)
