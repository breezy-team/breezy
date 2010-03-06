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

from bzrlib import (
    delta as _mod_delta,
    log,
    osutils,
    tree,
    tsort,
    revision as _mod_revision,
    )
import bzrlib.errors as errors
from bzrlib.osutils import is_inside_any
from bzrlib.symbol_versioning import (deprecated_function,
        )
from bzrlib.trace import mutter, warning

# TODO: when showing single-line logs, truncate to the width of the terminal
# if known, but only if really going to the terminal (not into a file)


def show(to_file, delta, show_ids=False, show_unchanged=False,
         indent='', filter=None):
    """Output given delta in status-like form to to_file.

    :param to_file: A file-like object where the output is displayed.

    :param delta: A TreeDelta containing the changes to be displayed

    :param show_ids: Output the file ids if True.

    :param show_unchanged: Output the unchanged files if True.

    :param indent: Added at the beginning of all output lines (for merged
        revisions).

    :param filter: A callable receiving a path and a file id and
        returning True if the path should be displayed.
    """

    def decorate_path(path, kind, meta_modified=None):
        if kind == 'directory':
            path += '/'
        elif kind == 'symlink':
            path += '@'
        if meta_modified:
            path += '*'
        return path

    def show_more_renamed(item):
        (oldpath, file_id, kind,
         text_modified, meta_modified, newpath) = item
        dec_new_path = decorate_path(newpath, kind, meta_modified)
        to_file.write(' => %s' % dec_new_path)
        if text_modified or meta_modified:
            extra_modified.append((newpath, file_id, kind,
                                   text_modified, meta_modified))

    def show_more_kind_changed(item):
        (path, file_id, old_kind, new_kind) = item
        to_file.write(' (%s => %s)' % (old_kind, new_kind))

    def show_path(path, file_id, kind, meta_modified,
                  default_format, with_file_id_format):
        dec_path = decorate_path(path, kind, meta_modified)
        if show_ids:
            to_file.write(with_file_id_format % dec_path)
        else:
            to_file.write(default_format % dec_path)

    def show_list(files, long_status_name, default_format='%s', 
                  with_file_id_format='%-30s', show_more=None):
        if files:
            header_shown = False
            prefix = indent + '  '

            for item in files:
                path, file_id, kind = item[:3]
                if (filter is not None and not filter(path, file_id)):
                    continue
                if not header_shown:
                    to_file.write(indent + long_status_name + ':\n')
                    header_shown = True
                meta_modified = None
                if len(item) == 5:
                    meta_modified = item[4]

                to_file.write(prefix)
                show_path(path, file_id, kind, meta_modified,
                          default_format, with_file_id_format)
                if show_more is not None:
                    show_more(item)
                if show_ids:
                    to_file.write(' %s' % file_id)
                to_file.write('\n')

    show_list(delta.removed, 'removed')
    show_list(delta.added, 'added')
    extra_modified = []
    # Reorder delta.renamed tuples so that all lists share the same
    # order for their 3 first fields and that they also begin like
    # the delta.modified tuples
    renamed = [(p, i, k, tm, mm, np)
               for  p, np, i, k, tm, mm  in delta.renamed]
    show_list(renamed, 'renamed', with_file_id_format='%s',
              show_more=show_more_renamed)
    show_list(delta.kind_changed, 'kind changed', 
              with_file_id_format='%s',
              show_more=show_more_kind_changed)
    show_list(delta.modified + extra_modified, 'modified')
    if show_unchanged:
        show_list(delta.unchanged, 'unchanged')

    show_list(delta.unversioned, 'unknown')


def show_tree_status(wt, show_unchanged=None,
                     specific_files=None,
                     show_ids=False,
                     to_file=None,
                     show_pending=True,
                     revision=None,
                     short=False,
                     verbose=False,
                     versioned=False,
                     show_callback=show):
    """Display summary of changes.

    By default this compares the working tree to a previous revision.
    If the revision argument is given, summarizes changes between the
    working tree and another, or between two revisions.

    The result is written out as Unicode and to_file should be able
    to encode that.

    If showing the status of a working tree, extra information is included
    about unknown files, conflicts, and pending merges.

    :param show_unchanged: Deprecated parameter. If set, includes unchanged
        files.
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
    :param show_callback: A callback: message = show_callback(to_file, delta, show_ids, show_unchanged, indent, filter)
    """
    if show_unchanged is not None:
        warn("show_tree_status with show_unchanged has been deprecated "
             "since bzrlib 0.9", DeprecationWarning, stacklevel=2)

    if to_file is None:
        to_file = sys.stdout

    wt.lock_read()
    try:
        new_is_working_tree = True
        if revision is None:
            if wt.last_revision() != wt.branch.last_revision():
                warning("working tree is out of date, run 'bzr update'")
            new = wt
            old = new.basis_tree()
        elif len(revision) > 0:
            try:
                old = revision[0].as_tree(wt.branch)
            except errors.NoSuchRevision, e:
                raise errors.BzrCommandError(str(e))
            if (len(revision) > 1) and (revision[1].spec is not None):
                try:
                    new = revision[1].as_tree(wt.branch)
                    new_is_working_tree = False
                except errors.NoSuchRevision, e:
                    raise errors.BzrCommandError(str(e))
            else:
                new = wt
        old.lock_read()
        new.lock_read()
        try:
            specific_files, nonexistents \
                = _filter_nonexistent(specific_files, old, new)
            want_unversioned = not versioned
            if short:
                changes = new.iter_changes(old, show_unchanged, specific_files,
                    require_versioned=False, want_unversioned=want_unversioned)
                reporter = _mod_delta._ChangeReporter(output_file=to_file,
                    unversioned_filter=new.is_ignored)
                _mod_delta.report_changes(changes, reporter)
            else:
                delta = new.changes_from(old, want_unchanged=show_unchanged,
                                      specific_files=specific_files,
                                      want_unversioned=want_unversioned)
                # filter out unknown files. We may want a tree method for
                # this
                delta.unversioned = [unversioned for unversioned in
                    delta.unversioned if not new.is_ignored(unversioned[0])]
                show_callback(to_file, delta, 
                              show_ids=show_ids,
                              show_unchanged=show_unchanged)
            # show the new conflicts only for now. XXX: get them from the
            # delta.
            conflicts = new.conflicts()
            if specific_files is not None:
                conflicts = conflicts.select_conflicts(new, specific_files,
                    ignore_misses=True, recurse=True)[1]
            if len(conflicts) > 0 and not short:
                to_file.write("conflicts:\n")
            for conflict in conflicts:
                if short:
                    prefix = 'C  '
                else:
                    prefix = ' '
                to_file.write("%s %s\n" % (prefix, conflict))
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
                if short:
                    prefix = 'X  '
                else:
                    prefix = ' '
                to_file.write("%s %s\n" % (prefix, nonexistent))
            if (new_is_working_tree and show_pending):
                show_pending_merges(new, to_file, short, verbose=verbose)
            if nonexistents:
                raise errors.PathsDoNotExist(nonexistents)
        finally:
            old.unlock()
            new.unlock()
    finally:
        wt.unlock()


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
        if revision_id not in parent_map: # ghost
            parent_graph[revision_id] = []
        else:
            # Only include parents which are in this sub-graph
            parent_graph[revision_id] = [p for p in parent_map[revision_id]
                                            if p in revision_ids]
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
        first_prefix = 'P   '
        sub_prefix = 'P.   '
    else:
        first_prefix = '  '
        sub_prefix = '    '

    def show_log_message(rev, prefix):
        if term_width is None:
            width = term_width
        else:
            width = term_width - len(prefix)
        log_message = log_formatter.log_string(None, rev, width, prefix=prefix)
        to_file.write(log_message + '\n')

    pending = parents[1:]
    branch = new.branch
    last_revision = parents[0]
    if not short:
        if verbose:
            to_file.write('pending merges:\n')
        else:
            to_file.write('pending merge tips:'
                          ' (use -v to see all merge revisions)\n')
    graph = branch.repository.get_graph()
    other_revisions = [last_revision]
    log_formatter = log.LineLogFormatter(to_file)
    for merge in pending:
        try:
            rev = branch.repository.get_revisions([merge])[0]
        except errors.NoSuchRevision:
            # If we are missing a revision, just print out the revision id
            to_file.write(first_prefix + '(ghost) ' + merge + '\n')
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
        try:
            revisions = dict((rev.revision_id, rev) for rev in
                             branch.repository.get_revisions(merge_extra))
        except errors.NoSuchRevision:
            # One of the sub nodes is a ghost, check each one
            revisions = {}
            for revision_id in merge_extra:
                try:
                    rev = branch.repository.get_revisions([revision_id])[0]
                except errors.NoSuchRevision:
                    revisions[revision_id] = None
                else:
                    revisions[revision_id] = rev

        # Display the revisions brought in by this merge.
        rev_id_iterator = _get_sorted_revisions(merge, merge_extra,
                            branch.repository.get_parent_map(merge_extra))
        # Skip the first node
        num, first, depth, eom = rev_id_iterator.next()
        if first != merge:
            raise AssertionError('Somehow we misunderstood how'
                ' iter_topo_order works %s != %s' % (first, merge))
        for num, sub_merge, depth, eom in rev_id_iterator:
            rev = revisions[sub_merge]
            if rev is None:
                to_file.write(sub_prefix + '(ghost) ' + sub_merge + '\n')
                continue
            show_log_message(revisions[sub_merge], sub_prefix)


def _filter_nonexistent(orig_paths, old_tree, new_tree):
    """Convert orig_paths to two sorted lists and return them.

    The first is orig_paths paths minus the items in the second list,
    and the second list is paths that are not in either inventory or
    tree (they don't qualify if they exist in the tree's inventory, or
    if they exist in the tree but are not versioned.)

    If either of the two lists is empty, return it as an empty list.

    This can be used by operations such as bzr status that can accept
    unknown or ignored files.
    """
    mutter("check paths: %r", orig_paths)
    if not orig_paths:
        return orig_paths, []
    s = old_tree.filter_unversioned_files(orig_paths)
    s = new_tree.filter_unversioned_files(s)
    nonexistent = [path for path in s if not new_tree.has_filename(path)]
    remaining   = [path for path in orig_paths if not path in nonexistent]
    # Sorting the 'remaining' list doesn't have much effect in
    # practice, since the various status output sections will sort
    # their groups individually.  But for consistency of this
    # function's API, it's better to sort both than just 'nonexistent'.
    return sorted(remaining), sorted(nonexistent)
