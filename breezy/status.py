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

import sys

from . import delta as _mod_delta
from . import errors as errors
from . import hooks as _mod_hooks
from . import log, osutils, tsort
from . import revision as _mod_revision
from .trace import mutter, warning
from .workingtree import ShelvingUnsupported

# TODO: when showing single-line logs, truncate to the width of the terminal
# if known, but only if really going to the terminal (not into a file)


def report_changes(
    to_file,
    old,
    new,
    specific_files,
    show_short_reporter,
    show_long_callback,
    short=False,
    want_unchanged=False,
    want_unversioned=False,
    show_ids=False,
    classify=True,
):
    """Display summary of changes.

    This compares two trees with regards to a list of files, and delegates
    the display to underlying elements.

    For short output, it creates an iterator on all changes, and lets a given
    reporter display these changes.

    For stantard output, it creates a delta of the changes, and forwards it
    to a callback

    :param to_file: If set, write to this file (default stdout.)
    :param old: Start tree for the comparison
    :param end: End tree for the comparison
    :param specific_files: If set, a list of filenames whose status should be
        shown.  It is an error to give a filename that is not in the working
        tree, or in the working inventory or in the basis inventory.
    :param show_short_reporter: Reporter in charge of display for short output
    :param show_long_callback: Callback in charge of display for normal output
    :param short: If True, gives short SVN-style status lines.
    :param want_unchanged: Deprecated parameter. If set, includes unchanged
        files.
    :param show_ids: If set, includes each file's id.
    :param want_unversioned: If False, only shows versioned files.
    :param classify: Add special symbols to indicate file kind.
    """
    if short:
        changes = new.iter_changes(
            old,
            want_unchanged,
            specific_files,
            require_versioned=False,
            want_unversioned=want_unversioned,
        )
        _mod_delta.report_changes(changes, show_short_reporter)
    else:
        delta = new.changes_from(
            old,
            want_unchanged=want_unchanged,
            specific_files=specific_files,
            want_unversioned=want_unversioned,
        )
        # filter out unknown files. We may want a tree method for
        # this
        delta.unversioned = [
            change for change in delta.unversioned if not new.is_ignored(change.path[1])
        ]
        show_long_callback(
            to_file,
            delta,
            show_ids=show_ids,
            show_unchanged=want_unchanged,
            classify=classify,
        )


def show_tree_status(
    wt,
    specific_files=None,
    show_ids=False,
    to_file=None,
    show_pending=True,
    revision=None,
    short=False,
    verbose=False,
    versioned=False,
    classify=True,
    show_long_callback=_mod_delta.report_delta,
):
    """Display summary of changes.

    By default this compares the working tree to a previous revision.
    If the revision argument is given, summarizes changes between the
    working tree and another, or between two revisions.

    The result is written out as Unicode and to_file should be able
    to encode that.

    If showing the status of a working tree, extra information is included
    about unknown files, conflicts, and pending merges.

    :param specific_files: If set, a list of filenames whose status should be
        shown.  It is an error to give a filename that is not in the working
        tree, or in the working inventory or in the basis inventory.
    :param show_ids: If set, includes each file's id.
    :param to_file: If set, write to this file (default stdout.)
    :param show_pending: If set, write pending merges.
    :param revision: If None, compare latest revision with working tree
        If not None, it must be a RevisionSpec list.
        If one revision, compare with working tree.
        If two revisions, show status between first and second.
    :param short: If True, gives short SVN-style status lines.
    :param verbose: If True, show all merged revisions, not just
        the merge tips
    :param versioned: If True, only shows versioned files.
    :param classify: Add special symbols to indicate file kind.
    :param show_long_callback: A callback: message = show_long_callback(to_file, delta,
        show_ids, show_unchanged, indent, filter), only used with the long output
    """
    if to_file is None:
        to_file = sys.stdout

    with wt.lock_read():
        new_is_working_tree = True
        if revision is None:
            if wt.last_revision() != wt.branch.last_revision():
                warning("working tree is out of date, run 'brz update'")
            new = wt
            old = new.basis_tree()
        elif len(revision) > 0:
            try:
                old = revision[0].as_tree(wt.branch)
            except errors.NoSuchRevision as e:
                raise errors.CommandError(str(e)) from e
            if (len(revision) > 1) and (revision[1].spec is not None):
                try:
                    new = revision[1].as_tree(wt.branch)
                    new_is_working_tree = False
                except errors.NoSuchRevision as e:
                    raise errors.CommandError(str(e)) from e
            else:
                new = wt
        with old.lock_read(), new.lock_read():
            for hook in hooks["pre_status"]:
                hook(
                    StatusHookParams(
                        old,
                        new,
                        to_file,
                        versioned,
                        show_ids,
                        short,
                        verbose,
                        specific_files=specific_files,
                    )
                )

            specific_files, nonexistents = _filter_nonexistent(specific_files, old, new)
            want_unversioned = not versioned

            # Reporter used for short outputs
            reporter = _mod_delta._ChangeReporter(
                output_file=to_file,
                unversioned_filter=new.is_ignored,
                classify=classify,
            )
            report_changes(
                to_file,
                old,
                new,
                specific_files,
                reporter,
                show_long_callback,
                short=short,
                want_unversioned=want_unversioned,
                show_ids=show_ids,
                classify=classify,
            )

            # show the ignored files among specific files (i.e. show the files
            # identified from input that we choose to ignore).
            if specific_files is not None:
                # Ignored files is sorted because specific_files is already sorted
                ignored_files = [
                    specific for specific in specific_files if new.is_ignored(specific)
                ]
                if len(ignored_files) > 0 and not short:
                    to_file.write("ignored:\n")
                    prefix = " "
                else:
                    prefix = "I  "
                for ignored_file in ignored_files:
                    to_file.write(f"{prefix} {ignored_file}\n")

            # show the new conflicts only for now. XXX: get them from the
            # delta.
            conflicts = new.conflicts()
            if specific_files is not None:
                conflicts = conflicts.select_conflicts(
                    new, specific_files, ignore_misses=True, recurse=True
                )[1]
            if len(conflicts) > 0 and not short:
                to_file.write("conflicts:\n")
            for conflict in conflicts:
                prefix = "C  " if short else " "
                to_file.write(f"{prefix} {conflict.describe()}\n")
            # Show files that were requested but don't exist (and are
            # not versioned).  We don't involve delta in this; these
            # paths are really the province of just the status
            # command, since they have more to do with how it was
            # invoked than with the tree it's operating on.
            if nonexistents and not short:
                to_file.write("nonexistent:\n")
            for nonexistent in nonexistents:
                # We could calculate prefix outside the loop but, given
                # how rarely this ought to happen, it's OK and arguably
                # slightly faster to do it here (ala conflicts above)
                prefix = "X  " if short else " "
                to_file.write(f"{prefix} {nonexistent}\n")
            if new_is_working_tree and show_pending:
                show_pending_merges(new, to_file, short, verbose=verbose)
            if nonexistents:
                raise errors.PathsDoNotExist(nonexistents)
            for hook in hooks["post_status"]:
                hook(
                    StatusHookParams(
                        old,
                        new,
                        to_file,
                        versioned,
                        show_ids,
                        short,
                        verbose,
                        specific_files=specific_files,
                    )
                )


def _get_sorted_revisions(tip_revision, revision_ids, parent_map):
    """Get an iterator which will return the revisions in merge sorted order.

    This will build up a list of all nodes, such that only nodes in the list
    are referenced. It then uses MergeSorter to return them in 'merge-sorted'
    order.

    :param revision_ids: A set of revision_ids
    :param parent_map: The parent information for each node. Revisions which
        are considered ghosts should not be present in the map.
    :return: iterator from MergeSorter.iter_topo_order()
    """
    # MergeSorter requires that all nodes be present in the graph, so get rid
    # of any references pointing outside of this graph.
    parent_graph = {}
    for revision_id in revision_ids:
        if revision_id not in parent_map:  # ghost
            parent_graph[revision_id] = []
        else:
            # Only include parents which are in this sub-graph
            parent_graph[revision_id] = [
                p for p in parent_map[revision_id] if p in revision_ids
            ]
    sorter = tsort.MergeSorter(parent_graph, tip_revision)
    return sorter.iter_topo_order()


def show_pending_merges(new, to_file, short=False, verbose=False):
    """Write out a display of pending merges in a working tree."""
    parents = new.get_parent_ids()
    if len(parents) < 2:
        return

    term_width = osutils.terminal_width()
    if term_width is not None:
        # we need one extra space for terminals that wrap on last char
        term_width = term_width - 1
    if short:
        first_prefix = "P   "
        sub_prefix = "P.   "
    else:
        first_prefix = "  "
        sub_prefix = "    "

    def show_log_message(rev, prefix):
        width = term_width if term_width is None else term_width - len(prefix)
        log_message = log_formatter.log_string(None, rev, width, prefix=prefix)
        to_file.write(log_message + "\n")

    pending = parents[1:]
    branch = new.branch
    last_revision = parents[0]
    if not short:
        if verbose:
            to_file.write("pending merges:\n")
        else:
            to_file.write("pending merge tips: (use -v to see all merge revisions)\n")
    graph = branch.repository.get_graph()
    other_revisions = [last_revision]
    log_formatter = log.LineLogFormatter(to_file)
    for merge in pending:
        try:
            rev = branch.repository.get_revision(merge)
        except errors.NoSuchRevision:
            # If we are missing a revision, just print out the revision id
            to_file.write(first_prefix + "(ghost) " + merge.decode("utf-8") + "\n")
            other_revisions.append(merge)
            continue

        # Log the merge, as it gets a slightly different formatting
        show_log_message(rev, first_prefix)
        if not verbose:
            continue

        # Find all of the revisions in the merge source, which are not in the
        # last committed revision.
        merge_extra = graph.find_unique_ancestors(merge, other_revisions)
        other_revisions.append(merge)
        merge_extra.discard(_mod_revision.NULL_REVISION)

        # Get a handle to all of the revisions we will need
        revisions = dict(branch.repository.iter_revisions(merge_extra))

        # Display the revisions brought in by this merge.
        rev_id_iterator = _get_sorted_revisions(
            merge, merge_extra, branch.repository.get_parent_map(merge_extra)
        )
        # Skip the first node
        num, first, depth, eom = next(rev_id_iterator)
        if first != merge:
            raise AssertionError(
                f"Somehow we misunderstood how iter_topo_order works {first} != {merge}"
            )
        for _num, sub_merge, _depth, _eom in rev_id_iterator:
            rev = revisions[sub_merge]
            if rev is None:
                to_file.write(
                    sub_prefix + "(ghost) " + sub_merge.decode("utf-8") + "\n"
                )
                continue
            show_log_message(revisions[sub_merge], sub_prefix)


def _filter_nonexistent(orig_paths, old_tree, new_tree):
    """Convert orig_paths to two sorted lists and return them.

    The first is orig_paths paths minus the items in the second list,
    and the second list is paths that are not in either inventory or
    tree (they don't qualify if they exist in the tree's inventory, or
    if they exist in the tree but are not versioned.)

    If either of the two lists is empty, return it as an empty list.

    This can be used by operations such as brz status that can accept
    unknown or ignored files.
    """
    mutter("check paths: %r", orig_paths)
    if not orig_paths:
        return orig_paths, []
    s = old_tree.filter_unversioned_files(orig_paths)
    s = new_tree.filter_unversioned_files(s)
    nonexistent = [path for path in s if not new_tree.has_filename(path)]
    remaining = [path for path in orig_paths if path not in nonexistent]
    # Sorting the 'remaining' list doesn't have much effect in
    # practice, since the various status output sections will sort
    # their groups individually.  But for consistency of this
    # function's API, it's better to sort both than just 'nonexistent'.
    return sorted(remaining), sorted(nonexistent)


class StatusHooks(_mod_hooks.Hooks):
    """A dictionary mapping hook name to a list of callables for status hooks.

    e.g. ['post_status'] Is the list of items to be called when the
    status command has finished printing the status.
    """

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        _mod_hooks.Hooks.__init__(self, "breezy.status", "hooks")
        self.add_hook(
            "post_status",
            "Called with argument StatusHookParams after Breezy has "
            "displayed the status. StatusHookParams has the attributes "
            "(old_tree, new_tree, to_file, versioned, show_ids, short, "
            "verbose). The last four arguments correspond to the command "
            "line options specified by the user for the status command. "
            "to_file is the output stream for writing.",
            (2, 3),
        )
        self.add_hook(
            "pre_status",
            "Called with argument StatusHookParams before Breezy "
            "displays the status. StatusHookParams has the attributes "
            "(old_tree, new_tree, to_file, versioned, show_ids, short, "
            "verbose). The last four arguments correspond to the command "
            "line options specified by the user for the status command. "
            "to_file is the output stream for writing.",
            (2, 3),
        )


class StatusHookParams:
    """Object holding parameters passed to post_status hooks.

    :ivar old_tree: Start tree (basis tree) for comparison.
    :ivar new_tree: Working tree.
    :ivar to_file: If set, write to this file.
    :ivar versioned: Show only versioned files.
    :ivar show_ids: Show internal object ids.
    :ivar short: Use short status indicators.
    :ivar verbose: Verbose flag.
    """

    def __init__(
        self,
        old_tree,
        new_tree,
        to_file,
        versioned,
        show_ids,
        short,
        verbose,
        specific_files=None,
    ):
        """Create a group of post_status hook parameters.

        :param old_tree: Start tree (basis tree) for comparison.
        :param new_tree: Working tree.
        :param to_file: If set, write to this file.
        :param versioned: Show only versioned files.
        :param show_ids: Show internal object ids.
        :param short: Use short status indicators.
        :param verbose: Verbose flag.
        :param specific_files: If set, a list of filenames whose status should be
            shown.  It is an error to give a filename that is not in the
            working tree, or in the working inventory or in the basis inventory.
        """
        self.old_tree = old_tree
        self.new_tree = new_tree
        self.to_file = to_file
        self.versioned = versioned
        self.show_ids = show_ids
        self.short = short
        self.verbose = verbose
        self.specific_files = specific_files

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return "<{}({}, {}, {}, {}, {}, {}, {}, {})>".format(
            self.__class__.__name__,
            self.old_tree,
            self.new_tree,
            self.to_file,
            self.versioned,
            self.show_ids,
            self.short,
            self.verbose,
            self.specific_files,
        )


def _show_shelve_summary(params):
    """post_status hook to display a summary of shelves.

    :param params: StatusHookParams.
    """
    # Don't show shelves if status of specific files is being shown, only if
    # no file arguments have been passed
    if params.specific_files:
        return
    get_shelf_manager = getattr(params.new_tree, "get_shelf_manager", None)
    if get_shelf_manager is None:
        return
    try:
        manager = get_shelf_manager()
    except ShelvingUnsupported:
        mutter("shelving not supported by tree, not displaying shelves.")
    else:
        shelves = manager.active_shelves()
        if shelves:
            singular = "%d shelf exists. "
            plural = "%d shelves exist. "
            fmt = singular if len(shelves) == 1 else plural
            params.to_file.write(fmt % len(shelves))
            params.to_file.write('See "brz shelve --list" for details.\n')


hooks = StatusHooks()


hooks.install_named_hook("post_status", _show_shelve_summary, "brz status")
