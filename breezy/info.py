# Copyright (C) 2005-2010 Canonical Ltd
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

__all__ = ["show_bzrdir_info"]

import sys
import time
from io import StringIO

from . import branch as _mod_branch
from . import controldir, errors, osutils, urlutils
from . import hooks as _mod_hooks
from .bzr import bzrdir
from .errors import NoRepositoryPresent, NotBranchError, NotLocalUrl, NoWorkingTree
from .i18n import gettext
from .missing import find_unmerged


def plural(n, base="", pl=None):
    if n == 1:
        return base
    elif pl is not None:
        return pl
    else:
        return "s"


class LocationList:
    def __init__(self, base_path):
        self.locs = []
        self.base_path = base_path

    def add_url(self, label, url):
        """Add a URL to the list, converting it to a path if possible."""
        if url is None:
            return
        try:
            path = urlutils.local_path_from_url(url)
        except urlutils.InvalidURL:
            self.locs.append((label, url))
        else:
            self.add_path(label, path)

    def add_path(self, label, path):
        """Add a path, converting it to a relative path if possible."""
        try:
            path = osutils.relpath(self.base_path, path)
        except errors.PathNotChild:
            pass
        else:
            if path == "":
                path = "."
        if path != "/":
            path = path.rstrip("/")
        self.locs.append((label, path))

    def get_lines(self):
        max_len = max(len(l) for l, u in self.locs)
        return ["  %*s: %s\n" % (max_len, l, u) for l, u in self.locs]


def gather_location_info(repository=None, branch=None, working=None, control=None):
    locs = {}
    if branch is not None:
        branch_path = branch.user_url
        master_path = branch.get_bound_location()
        if master_path is None:
            master_path = branch_path
    else:
        branch_path = None
        master_path = None
        try:
            if control is not None and control.get_branch_reference():
                locs["checkout of branch"] = control.get_branch_reference()
        except NotBranchError:
            pass
    if working:
        working_path = working.user_url
        if working_path != branch_path:
            locs["light checkout root"] = working_path
        if master_path != branch_path:
            if repository.is_shared():
                locs["repository checkout root"] = branch_path
            else:
                locs["checkout root"] = branch_path
        if working_path != master_path:
            (master_path_base, params) = urlutils.split_segment_parameters(master_path)
            if working_path == master_path_base:
                locs["checkout of co-located branch"] = params["branch"]
            elif "branch" in params:
                locs["checkout of branch"] = "{}, branch {}".format(
                    master_path_base, params["branch"]
                )
            else:
                locs["checkout of branch"] = master_path
        elif repository.is_shared():
            locs["repository branch"] = branch_path
        elif branch_path is not None:
            # standalone
            locs["branch root"] = branch_path
    else:
        working_path = None
        if repository is not None and repository.is_shared():
            # lightweight checkout of branch in shared repository
            if branch_path is not None:
                locs["repository branch"] = branch_path
        elif branch_path is not None:
            # standalone
            locs["branch root"] = branch_path
        elif repository is not None:
            locs["repository"] = repository.user_url
        elif control is not None:
            locs["control directory"] = control.user_url
        else:
            # Really, at least a control directory should be
            # passed in for this method to be useful.
            pass
        if master_path != branch_path:
            locs["bound to branch"] = master_path
    if repository is not None and repository.is_shared():
        # lightweight checkout of branch in shared repository
        locs["shared repository"] = repository.user_url
    order = [
        "control directory",
        "light checkout root",
        "repository checkout root",
        "checkout root",
        "checkout of branch",
        "checkout of co-located branch",
        "shared repository",
        "repository",
        "repository branch",
        "branch root",
        "bound to branch",
    ]
    return [(n, locs[n]) for n in order if n in locs]


def _show_location_info(locs, outfile):
    """Show known locations for working, branch and repository."""
    outfile.write("Location:\n")
    path_list = LocationList(osutils.getcwd())
    for name, loc in locs:
        path_list.add_url(name, loc)
    outfile.writelines(path_list.get_lines())


def _gather_related_branches(branch):
    locs = LocationList(osutils.getcwd())
    locs.add_url("public branch", branch.get_public_branch())
    locs.add_url("push branch", branch.get_push_location())
    locs.add_url("parent branch", branch.get_parent())
    locs.add_url("submit branch", branch.get_submit_branch())
    try:
        locs.add_url("stacked on", branch.get_stacked_on_url())
    except (
        _mod_branch.UnstackableBranchFormat,
        errors.UnstackableRepositoryFormat,
        errors.NotStacked,
    ):
        pass
    return locs


def _show_related_info(branch, outfile):
    """Show parent and push location of branch."""
    locs = _gather_related_branches(branch)
    if len(locs.locs) > 0:
        outfile.write("\n")
        outfile.write("Related branches:\n")
        outfile.writelines(locs.get_lines())


def _show_control_dir_info(control, outfile):
    """Show control dir information."""
    if control._format.colocated_branches:
        outfile.write("\n")
        outfile.write("Control directory:\n")
        outfile.write(f"         {len(control.list_branches())} branches\n")


def _show_format_info(
    control=None, repository=None, branch=None, working=None, outfile=None
):
    """Show known formats for control, working, branch and repository."""
    outfile.write("\n")
    outfile.write("Format:\n")
    if control:
        outfile.write(
            "       control: {}\n".format(control._format.get_format_description())
        )
    if working:
        outfile.write(
            "  working tree: {}\n".format(working._format.get_format_description())
        )
    if branch:
        outfile.write(
            "        branch: {}\n".format(branch._format.get_format_description())
        )
    if repository:
        outfile.write(
            "    repository: {}\n".format(repository._format.get_format_description())
        )


def _show_locking_info(repository=None, branch=None, working=None, outfile=None):
    """Show locking status of working, branch and repository."""
    if (
        (repository and repository.get_physical_lock_status())
        or (branch and branch.get_physical_lock_status())
        or (working and working.get_physical_lock_status())
    ):
        outfile.write("\n")
        outfile.write("Lock status:\n")
        if working:
            if working.get_physical_lock_status():
                status = "locked"
            else:
                status = "unlocked"
            outfile.write("  working tree: {}\n".format(status))
        if branch:
            if branch.get_physical_lock_status():
                status = "locked"
            else:
                status = "unlocked"
            outfile.write("        branch: {}\n".format(status))
        if repository:
            if repository.get_physical_lock_status():
                status = "locked"
            else:
                status = "unlocked"
            outfile.write("    repository: {}\n".format(status))


def _show_missing_revisions_branch(branch, outfile):
    """Show missing master revisions in branch."""
    # Try with inaccessible branch ?
    master = branch.get_master_branch()
    if master:
        _local_extra, remote_extra = find_unmerged(branch, master)
        if remote_extra:
            outfile.write("\n")
            outfile.write(
                gettext("Branch is out of date: missing %d revision%s.\n")
                % (len(remote_extra), plural(len(remote_extra)))
            )


def _show_missing_revisions_working(working, outfile):
    """Show missing revisions in working tree."""
    branch = working.branch
    try:
        branch_revno, branch_last_revision = branch.last_revision_info()
    except errors.UnsupportedOperation:
        return
    try:
        tree_last_id = working.get_parent_ids()[0]
    except IndexError:
        tree_last_id = None

    if branch_revno and tree_last_id != branch_last_revision:
        tree_last_revno = branch.revision_id_to_revno(tree_last_id)
        missing_count = branch_revno - tree_last_revno
        outfile.write("\n")
        outfile.write(
            gettext("Working tree is out of date: missing %d revision%s.\n")
            % (missing_count, plural(missing_count))
        )


def _show_working_stats(working, outfile):
    """Show statistics about a working tree."""
    basis = working.basis_tree()
    delta = working.changes_from(basis, want_unchanged=True)

    outfile.write("\n")
    outfile.write("In the working tree:\n")
    outfile.write("  %8s unchanged\n" % len(delta.unchanged))
    outfile.write("  %8d modified\n" % len(delta.modified))
    outfile.write("  %8d added\n" % len(delta.added))
    outfile.write("  %8d removed\n" % len(delta.removed))
    outfile.write("  %8d renamed\n" % len(delta.renamed))
    outfile.write("  %8d copied\n" % len(delta.copied))

    ignore_cnt = unknown_cnt = 0
    for path in working.extras():
        if working.is_ignored(path):
            ignore_cnt += 1
        else:
            unknown_cnt += 1
    outfile.write("  %8d unknown\n" % unknown_cnt)
    outfile.write("  %8d ignored\n" % ignore_cnt)

    dir_cnt = 0
    for path, entry in working.iter_entries_by_dir():
        if entry.kind == "directory" and path != "":
            dir_cnt += 1
    outfile.write(
        "  %8d versioned %s\n"
        % (dir_cnt, plural(dir_cnt, "subdirectory", "subdirectories"))
    )


def _show_branch_stats(branch, verbose, outfile):
    """Show statistics about a branch."""
    try:
        revno, head = branch.last_revision_info()
    except errors.UnsupportedOperation:
        return {}
    outfile.write("\n")
    outfile.write("Branch history:\n")
    outfile.write("  %8d revision%s\n" % (revno, plural(revno)))
    stats = branch.repository.gather_stats(head, committers=verbose)
    if verbose:
        committers = stats["committers"]
        outfile.write("  %8d committer%s\n" % (committers, plural(committers)))
    if revno:
        timestamp, timezone = stats["firstrev"]
        age = int((time.time() - timestamp) / 3600 / 24)
        outfile.write("  %8d day%s old\n" % (age, plural(age)))
        outfile.write(
            "   first revision: {}\n".format(osutils.format_date(timestamp, timezone))
        )
        timestamp, timezone = stats["latestrev"]
        outfile.write(
            "  latest revision: {}\n".format(osutils.format_date(timestamp, timezone))
        )
    return stats


def _show_repository_info(repository, outfile):
    """Show settings of a repository."""
    if repository.make_working_trees():
        outfile.write("\n")
        outfile.write("Create working tree for new branches inside the repository.\n")


def _show_repository_stats(repository, stats, outfile):
    """Show statistics about a repository."""
    f = StringIO()
    if "revisions" in stats:
        revisions = stats["revisions"]
        f.write("  %8d revision%s\n" % (revisions, plural(revisions)))
    if "size" in stats:
        f.write("  %8d KiB\n" % (stats["size"] / 1024))
    for hook in hooks["repository"]:
        hook(repository, stats, f)
    if f.getvalue() != "":
        outfile.write("\n")
        outfile.write("Repository:\n")
        outfile.write(f.getvalue())


def show_bzrdir_info(a_controldir, verbose=False, outfile=None):
    """Output to stdout the 'info' for a_controldir."""
    if outfile is None:
        outfile = sys.stdout
    try:
        tree = a_controldir.open_workingtree(recommend_upgrade=False)
    except (NoWorkingTree, NotLocalUrl, NotBranchError):
        tree = None
        try:
            branch = a_controldir.open_branch(name="")
        except NotBranchError:
            branch = None
            try:
                repository = a_controldir.open_repository()
            except NoRepositoryPresent:
                lockable = None
                repository = None
            else:
                lockable = repository
        else:
            repository = branch.repository
            lockable = branch
    else:
        branch = tree.branch
        repository = branch.repository
        lockable = tree

    if lockable is not None:
        lockable.lock_read()
    try:
        show_component_info(a_controldir, repository, branch, tree, verbose, outfile)
    finally:
        if lockable is not None:
            lockable.unlock()


def show_component_info(
    control, repository, branch=None, working=None, verbose=1, outfile=None
):
    """Write info about all bzrdir components to stdout."""
    if outfile is None:
        outfile = sys.stdout
    if verbose is False:
        verbose = 1
    if verbose is True:
        verbose = 2
    layout = describe_layout(repository, branch, working, control)
    format = describe_format(control, repository, branch, working)
    outfile.write("{} (format: {})\n".format(layout, format))
    _show_location_info(
        gather_location_info(
            control=control, repository=repository, branch=branch, working=working
        ),
        outfile,
    )
    if branch is not None:
        _show_related_info(branch, outfile)
    if verbose == 0:
        return
    _show_format_info(control, repository, branch, working, outfile)
    _show_locking_info(repository, branch, working, outfile)
    _show_control_dir_info(control, outfile)
    if branch is not None:
        _show_missing_revisions_branch(branch, outfile)
    if working is not None:
        _show_missing_revisions_working(working, outfile)
        _show_working_stats(working, outfile)
    elif branch is not None:
        _show_missing_revisions_branch(branch, outfile)
    if branch is not None:
        show_committers = verbose >= 2
        stats = _show_branch_stats(branch, show_committers, outfile)
    elif repository is not None:
        stats = repository.gather_stats()
    if branch is None and working is None and repository is not None:
        _show_repository_info(repository, outfile)
    if repository is not None:
        _show_repository_stats(repository, stats, outfile)


def describe_layout(repository=None, branch=None, tree=None, control=None):
    """Convert a control directory layout into a user-understandable term.

    Common outputs include "Standalone tree", "Repository branch" and
    "Checkout".  Uncommon outputs include "Unshared repository with trees"
    and "Empty control directory"
    """
    if branch is None and control is not None:
        try:
            branch_reference = control.get_branch_reference()
        except NotBranchError:
            pass
        else:
            if branch_reference is not None:
                return "Dangling branch reference"
    if repository is None:
        return "Empty control directory"
    if branch is None and tree is None:
        if repository.is_shared():
            phrase = "Shared repository"
        else:
            phrase = "Unshared repository"
        extra = []
        if repository.make_working_trees():
            extra.append("trees")
        if len(control.branch_names()) > 0:
            extra.append("colocated branches")
        if extra:
            phrase += " with " + " and ".join(extra)
        return phrase
    else:
        if repository.is_shared():
            independence = "Repository "
        else:
            independence = "Standalone "
        if tree is not None:
            phrase = "tree"
        else:
            phrase = "branch"
        if branch is None and tree is not None:
            phrase = "branchless tree"
        else:
            if (
                tree is not None
                and tree.controldir.control_url != branch.controldir.control_url
            ):
                independence = ""
                phrase = "Lightweight checkout"
            elif branch.get_bound_location() is not None:
                if independence == "Standalone ":
                    independence = ""
                if tree is None:
                    phrase = "Bound branch"
                else:
                    phrase = "Checkout"
        if independence != "":
            phrase = phrase.lower()
        return "{}{}".format(independence, phrase)


def describe_format(control, repository, branch, tree):
    """Determine the format of an existing control directory.

    Several candidates may be found.  If so, the names are returned as a
    single string, separated by ' or '.

    If no matching candidate is found, "unnamed" is returned.
    """
    candidates = []
    if branch is not None and tree is not None and branch.user_url != tree.user_url:
        branch = None
        repository = None
    non_aliases = set(controldir.format_registry.keys())
    non_aliases.difference_update(controldir.format_registry.aliases())
    for key in non_aliases:
        format = controldir.format_registry.make_controldir(key)
        if isinstance(format, bzrdir.BzrDirMetaFormat1):
            if tree and format.workingtree_format != tree._format:
                continue
            if branch and format.get_branch_format() != branch._format:
                continue
            if repository and format.repository_format != repository._format:
                continue
        if format.__class__ is not control._format.__class__:
            continue
        candidates.append(key)
    if len(candidates) == 0:
        return "unnamed"
    candidates.sort()
    new_candidates = [
        c for c in candidates if not controldir.format_registry.get_info(c).hidden
    ]
    if len(new_candidates) > 0:
        # If there are any non-hidden formats that match, only return those to
        # avoid listing hidden formats except when only a hidden format will
        # do.
        candidates = new_candidates
    return " or ".join(candidates)


class InfoHooks(_mod_hooks.Hooks):
    """Hooks for the info command."""

    def __init__(self):
        super().__init__("breezy.info", "hooks")
        self.add_hook(
            "repository",
            "Invoked when displaying the statistics for a repository. "
            "repository is called with a statistics dictionary as returned "
            "by the repository and a file-like object to write to.",
            (1, 15),
        )


hooks = InfoHooks()
