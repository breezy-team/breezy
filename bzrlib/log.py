# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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



"""Code to show logs of changes.

Various flavors of log can be produced:

* for one file, or the whole tree, and (not done yet) for
  files in a given directory

* in "verbose" mode with a description of what changed from one
  version to the next

* with file-ids and revision-ids shown

Logs are actually written out through an abstract LogFormatter
interface, which allows for different preferred formats.  Plugins can
register formats too.

Logs can be produced in either forward (oldest->newest) or reverse
(newest->oldest) order.

Logs can be filtered to show only revisions matching a particular
search string, or within a particular range of revisions.  The range
can be given as date/times, which are reduced to revisions before
calling in here.

In verbose mode we show a summary of what changed in each particular
revision.  Note that this is the delta for changes in that revision
relative to its left-most parent, not the delta relative to the last
logged revision.  So for example if you ask for a verbose log of
changes touching hello.c you will get a list of those revisions also
listing other things that were changed in the same revision, but not
all the changes since the previous revision that touched hello.c.
"""

import codecs
from itertools import (
    izip,
    )
import re
import sys
from warnings import (
    warn,
    )

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """

from bzrlib import (
    config,
    errors,
    repository as _mod_repository,
    revision as _mod_revision,
    revisionspec,
    trace,
    tsort,
    )
""")

from bzrlib import (
    registry,
    )
from bzrlib.osutils import (
    format_date,
    get_terminal_encoding,
    terminal_width,
    )


def find_touching_revisions(branch, file_id):
    """Yield a description of revisions which affect the file_id.

    Each returned element is (revno, revision_id, description)

    This is the list of revisions where the file is either added,
    modified, renamed or deleted.

    TODO: Perhaps some way to limit this to only particular revisions,
    or to traverse a non-mainline set of revisions?
    """
    last_ie = None
    last_path = None
    revno = 1
    for revision_id in branch.revision_history():
        this_inv = branch.repository.get_revision_inventory(revision_id)
        if file_id in this_inv:
            this_ie = this_inv[file_id]
            this_path = this_inv.id2path(file_id)
        else:
            this_ie = this_path = None

        # now we know how it was last time, and how it is in this revision.
        # are those two states effectively the same or not?

        if not this_ie and not last_ie:
            # not present in either
            pass
        elif this_ie and not last_ie:
            yield revno, revision_id, "added " + this_path
        elif not this_ie and last_ie:
            # deleted here
            yield revno, revision_id, "deleted " + last_path
        elif this_path != last_path:
            yield revno, revision_id, ("renamed %s => %s" % (last_path, this_path))
        elif (this_ie.text_size != last_ie.text_size
              or this_ie.text_sha1 != last_ie.text_sha1):
            yield revno, revision_id, "modified " + this_path

        last_ie = this_ie
        last_path = this_path
        revno += 1


def _enumerate_history(branch):
    rh = []
    revno = 1
    for rev_id in branch.revision_history():
        rh.append((revno, rev_id))
        revno += 1
    return rh


def show_log(branch,
             lf,
             specific_fileid=None,
             verbose=False,
             direction='reverse',
             start_revision=None,
             end_revision=None,
             search=None,
             limit=None,
             strict=False):
    """Write out human-readable log of commits to this branch.

    :param lf: The LogFormatter object showing the output.

    :param specific_fileid: If not None, list only the commits affecting the
        specified file, rather than all commits.

    :param verbose: If True show added/changed/deleted/renamed files.

    :param direction: 'reverse' (default) is latest to earliest; 'forward' is
        earliest to latest.

    :param start_revision: If not None, only show revisions >= start_revision

    :param end_revision: If not None, only show revisions <= end_revision

    :param search: If not None, only show revisions with matching commit
        messages

    :param limit: If set, shows only 'limit' revisions, all revisions are shown
        if None or 0.

    :param strict: If True, check that revision limits are on the mainline if
       the LogFormatter requires this
    """
    branch.lock_read()
    try:
        if getattr(lf, 'begin_log', None):
            lf.begin_log()

        _show_log(branch, lf, specific_fileid, verbose, direction,
                  start_revision, end_revision, search, limit, strict)

        if getattr(lf, 'end_log', None):
            lf.end_log()
    finally:
        branch.unlock()


def _show_log(branch,
             lf,
             specific_fileid=None,
             verbose=False,
             direction='reverse',
             start_revision=None,
             end_revision=None,
             search=None,
             limit=None,
             strict=False):
    """Worker function for show_log - see show_log."""
    if not isinstance(lf, LogFormatter):
        warn("not a LogFormatter instance: %r" % lf)
    if specific_fileid:
        trace.mutter('get log for file_id %r', specific_fileid)

    # Consult the LogFormatter about what it needs and can handle
    generate_merge_revisions = getattr(lf, 'supports_merge_revisions', False)
    allow_single_merge_revision = getattr(lf,
        'supports_single_merge_revision', False)
    generate_tags = getattr(lf, 'supports_tags', False)
    if generate_tags and branch.supports_tags():
        rev_tag_dict = branch.tags.get_reverse_tag_dict()
    else:
        rev_tag_dict = {}
    generate_delta = verbose and getattr(lf, 'supports_delta', False)

    # Find and print the interesting revisions
    log_count = 0
    revision_iterator = _create_log_revision_iterator(branch, start_revision,
        end_revision, direction, specific_fileid, search,
        generate_merge_revisions, allow_single_merge_revision, generate_delta,
        strict)
    for revs in revision_iterator:
        for (rev_id, revno, merge_depth), rev, delta in revs:
            lr = LogRevision(rev, revno, merge_depth, delta,
                             rev_tag_dict.get(rev_id))
            lf.log_revision(lr)
            if limit:
                log_count += 1
                if log_count >= limit:
                    return


def _create_log_revision_iterator(branch, start_revision, end_revision,
    direction, specific_fileid, search, generate_merge_revisions,
    allow_single_merge_revision, generate_delta, strict):
    """Create a revision iterator for log.

    :param branch: The branch being logged.
    :param start_revision: If not None, only show revisions >= start_revision
    :param end_revision: If not None, only show revisions <= end_revision
    :param direction: 'reverse' (default) is latest to earliest; 'forward' is
        earliest to latest.
    :param specific_fileid: If not None, list only the commits affecting the
        specified file.
    :param search: If not None, only show revisions with matching commit
        messages.
    :param generate_merge_revisions: If False, show only mainline revisions.
    :param allow_single_merge_revision: If True, logging of a single
        revision off the mainline is to be allowed
    :param generate_delta: Whether to generate a delta for each revision.
    :param strict: If True, check that revision limits are on the mainline if
       the LogFormatter requires this

    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    view_revisions = calculate_view_revisions(branch, start_revision,
        end_revision, direction, specific_fileid, generate_merge_revisions,
        allow_single_merge_revision, strict)
    return make_log_rev_iterator(branch, view_revisions, generate_delta, search)


def calculate_view_revisions(branch, start_revision, end_revision, direction,
                             specific_fileid, generate_merge_revisions,
                             allow_single_merge_revision, strict=True):
    """Calculate the revisions to view.

    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples OR
             a list of the same tuples.
    """
    rev_limits = _get_revision_limits(branch, start_revision, end_revision)
    br_revno, _, start_revno, start_rev_id, end_revno, end_rev_id = rev_limits
    if br_revno == 0:
        return []

    # If we only want to see mainline revisions, we can iterate ...
    # NOTE: The specific_fileid check will go once _mainline_view_revisions()
    # supports filtering by that parameter
    if not strict and not generate_merge_revisions and specific_fileid is None:
        result = _mainline_view_revisions(branch, rev_limits)
        if direction == 'forward':
            result = reversed(list(result))
        return result

    # Otherwise, the algorithm is O(history) for now ...

    # Get the revision history, if any
    mainline_revs, rev_nos = _get_mainline_revs(branch, rev_limits)
    if not mainline_revs:
        return []

    # If a single revision is requested and it's not on the mainline,
    # make sure we're generating the merge revisions (unless we can't)
    generate_single_revision = False
    if (strict and not generate_merge_revisions
        and ((start_rev_id and (start_rev_id not in rev_nos))
            or (end_rev_id and (end_rev_id not in rev_nos)))):
        generate_single_revision = ((start_rev_id == end_rev_id)
            and allow_single_merge_revision)
        if not generate_single_revision:
            raise errors.BzrCommandError('Selected log formatter only supports'
                ' mainline revisions.')
        generate_merge_revisions = True

    # Do the filtering
    view_revs_iter = get_view_revisions(mainline_revs, rev_nos, branch,
                          direction, include_merges=generate_merge_revisions)
    if direction == 'reverse':
        start_rev_id, end_rev_id = end_rev_id, start_rev_id
    view_revisions = _filter_revision_range(list(view_revs_iter),
                                            start_rev_id,
                                            end_rev_id)
    if view_revisions and generate_single_revision:
        view_revisions = view_revisions[0:1]
    if specific_fileid:
        view_revisions = _filter_revisions_touching_file_id(branch,
                                                            specific_fileid,
                                                            view_revisions)

    # Rebase merge_depth - unless there are no revisions or 
    # either the first or last revision have merge_depth = 0.
    if view_revisions and view_revisions[0][2] and view_revisions[-1][2]:
        min_depth = min([d for r,n,d in view_revisions])
        if min_depth != 0:
            view_revisions = [(r,n,d-min_depth) for r,n,d in view_revisions]
    return view_revisions


def _mainline_view_revisions(branch, revision_limits):
    """Calculate the mainline revisions to view, newest to oldest.

    :param revision_limits: a tuple as returned by _get_revision_limits()
    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples.
    """
    br_revno, br_rev_id, start_revno, _, end_revno, _ = revision_limits
    repo = branch.repository
    cur_revno = br_revno
    for revision_id in repo.iter_reverse_revision_history(br_rev_id):
        if cur_revno < start_revno:
            break
        if cur_revno <= end_revno:
            yield revision_id, str(cur_revno), 0
        cur_revno -= 1


def make_log_rev_iterator(branch, view_revisions, generate_delta, search):
    """Create a revision iterator for log.

    :param branch: The branch being logged.
    :param view_revisions: The revisions being viewed.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    # Convert view_revisions into (view, None, None) groups to fit with
    # the standard interface here.
    if type(view_revisions) == list:
        # A single batch conversion is faster than many incremental ones.
        # As we have all the data, do a batch conversion.
        nones = [None] * len(view_revisions)
        log_rev_iterator = iter([zip(view_revisions, nones, nones)])
    else:
        def _convert():
            for view in view_revisions:
                yield (view, None, None)
        log_rev_iterator = iter([_convert()])
    for adapter in log_adapters:
        log_rev_iterator = adapter(branch, generate_delta, search,
            log_rev_iterator)
    return log_rev_iterator


def _make_search_filter(branch, generate_delta, search, log_rev_iterator):
    """Create a filtered iterator of log_rev_iterator matching on a regex.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    if search is None:
        return log_rev_iterator
    # Compile the search now to get early errors.
    searchRE = re.compile(search, re.IGNORECASE)
    return _filter_message_re(searchRE, log_rev_iterator)


def _filter_message_re(searchRE, log_rev_iterator):
    for revs in log_rev_iterator:
        new_revs = []
        for (rev_id, revno, merge_depth), rev, delta in revs:
            if searchRE.search(rev.message):
                new_revs.append(((rev_id, revno, merge_depth), rev, delta))
        yield new_revs


def _make_delta_filter(branch, generate_delta, search, log_rev_iterator):
    """Add revision deltas to a log iterator if needed.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    if not generate_delta:
        return log_rev_iterator
    return _generate_deltas(branch.repository, log_rev_iterator)


def _generate_deltas(repository, log_rev_iterator):
    """Create deltas for each batch of revisions in log_rev_iterator."""
    for revs in log_rev_iterator:
        revisions = [rev[1] for rev in revs]
        deltas = repository.get_deltas_for_revisions(revisions)
        revs = [(rev[0], rev[1], delta) for rev, delta in izip(revs, deltas)]
        yield revs


def _make_revision_objects(branch, generate_delta, search, log_rev_iterator):
    """Extract revision objects from the repository

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    repository = branch.repository
    for revs in log_rev_iterator:
        # r = revision_id, n = revno, d = merge depth
        revision_ids = [view[0] for view, _, _ in revs]
        revisions = repository.get_revisions(revision_ids)
        revs = [(rev[0], revision, rev[2]) for rev, revision in
            izip(revs, revisions)]
        yield revs


def _make_batch_filter(branch, generate_delta, search, log_rev_iterator):
    """Group up a single large batch into smaller ones.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    repository = branch.repository
    num = 9
    for batch in log_rev_iterator:
        batch = iter(batch)
        while True:
            step = [detail for _, detail in zip(range(num), batch)]
            if len(step) == 0:
                break
            yield step
            num = min(int(num * 1.5), 200)


def _get_revision_limits(branch, start_revision, end_revision):
    """Get and check revision limits.

    :param  branch: The branch containing the revisions. 

    :param  start_revision: The first revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :param  end_revision: The last revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :return: (br_revno, br_rev_id, start_revno, start_rev_id, end_revno,
        end_rev_id) tuple.
    """
    branch_revno, branch_rev_id = branch.last_revision_info()
    start_rev_id = None
    if start_revision is None:
        start_revno = 1
    else:
        if isinstance(start_revision, revisionspec.RevisionInfo):
            start_rev_id = start_revision.rev_id
            start_revno = start_revision.revno or 1
        else:
            branch.check_real_revno(start_revision)
            start_revno = start_revision

    end_rev_id = None
    if end_revision is None:
        end_revno = branch_revno
    else:
        if isinstance(end_revision, revisionspec.RevisionInfo):
            end_rev_id = end_revision.rev_id
            end_revno = end_revision.revno or branch_revno
        else:
            branch.check_real_revno(end_revision)
            end_revno = end_revision

    if branch_revno != 0:
        if (start_rev_id == _mod_revision.NULL_REVISION
            or end_rev_id == _mod_revision.NULL_REVISION):
            raise errors.BzrCommandError('Logging revision 0 is invalid.')
        if start_revno > end_revno:
            raise errors.BzrCommandError("Start revision must be older than "
                                         "the end revision.")
    return (branch_revno, branch_rev_id, start_revno, start_rev_id, end_revno,
        end_rev_id)


def _get_mainline_revs(branch, revision_limits):
    """Get the mainline revisions from the branch.
    
    Generates the list of mainline revisions for the branch. Also map the
    revisions to rev_ids, to be used in the later filtering stage.
    
    :param  branch: The branch containing the revisions. 
    :param revision_limits: a tuple as returned by _get_revision_limits()

    :return: A (mainline_revs, rev_nos) tuple.
    """
    (br_revno, br_rev_id, start_revno, start_rev_id, end_revno, end_rev_id) = \
        revision_limits
    cur_revno = br_revno
    rev_nos = {}
    mainline_revs = []
    for revision_id in branch.repository.iter_reverse_revision_history(
                        br_rev_id):
        if cur_revno < start_revno:
            # We have gone far enough, but we always add 1 more revision
            rev_nos[revision_id] = cur_revno
            mainline_revs.append(revision_id)
            break
        if cur_revno <= end_revno:
            rev_nos[revision_id] = cur_revno
            mainline_revs.append(revision_id)
        cur_revno -= 1
    else:
        # We walked off the edge of all revisions, so we add a 'None' marker
        mainline_revs.append(None)

    mainline_revs.reverse()

    # override the mainline to look like the revision history.
    return mainline_revs, rev_nos


def _filter_revision_range(view_revisions, start_rev_id, end_rev_id):
    """Filter view_revisions based on revision ranges.

    :param view_revisions: A list of (revision_id, dotted_revno, merge_depth) 
            tuples to be filtered.

    :param start_rev_id: If not NONE specifies the first revision to be logged.
            If NONE then all revisions up to the end_rev_id are logged.

    :param end_rev_id: If not NONE specifies the last revision to be logged.
            If NONE then all revisions up to the end of the log are logged.

    :return: The filtered view_revisions.
    """
    if start_rev_id or end_rev_id:
        revision_ids = [r for r, n, d in view_revisions]
        if start_rev_id:
            start_index = revision_ids.index(start_rev_id)
        else:
            start_index = 0
        if start_rev_id == end_rev_id:
            end_index = start_index
        else:
            if end_rev_id:
                end_index = revision_ids.index(end_rev_id)
            else:
                end_index = len(view_revisions) - 1
        # To include the revisions merged into the last revision, 
        # extend end_rev_id down to, but not including, the next rev
        # with the same or lesser merge_depth
        end_merge_depth = view_revisions[end_index][2]
        try:
            for index in xrange(end_index+1, len(view_revisions)+1):
                if view_revisions[index][2] <= end_merge_depth:
                    end_index = index - 1
                    break
        except IndexError:
            # if the search falls off the end then log to the end as well
            end_index = len(view_revisions) - 1
        view_revisions = view_revisions[start_index:end_index+1]
    return view_revisions


def _filter_revisions_touching_file_id(branch, file_id, view_revisions):
    r"""Return the list of revision ids which touch a given file id.

    The function filters view_revisions and returns a subset.
    This includes the revisions which directly change the file id,
    and the revisions which merge these changes. So if the
    revision graph is::
        A-.
        |\ \
        B C E
        |/ /
        D |
        |\|
        | F
        |/
        G

    And 'C' changes a file, then both C and D will be returned. F will not be
    returned even though it brings the changes to C into the branch starting
    with E. (Note that if we were using F as the tip instead of G, then we
    would see C, D, F.)

    This will also be restricted based on a subset of the mainline.

    :param branch: The branch where we can get text revision information.

    :param file_id: Filter out revisions that do not touch file_id.

    :param view_revisions: A list of (revision_id, dotted_revno, merge_depth)
        tuples. This is the list of revisions which will be filtered. It is
        assumed that view_revisions is in merge_sort order (i.e. newest
        revision first ).

    :return: A list of (revision_id, dotted_revno, merge_depth) tuples.
    """
    # Lookup all possible text keys to determine which ones actually modified
    # the file.
    text_keys = [(file_id, rev_id) for rev_id, revno, depth in view_revisions]
    # Looking up keys in batches of 1000 can cut the time in half, as well as
    # memory consumption. GraphIndex *does* like to look for a few keys in
    # parallel, it just doesn't like looking for *lots* of keys in parallel.
    # TODO: This code needs to be re-evaluated periodically as we tune the
    #       indexing layer. We might consider passing in hints as to the known
    #       access pattern (sparse/clustered, high success rate/low success
    #       rate). This particular access is clustered with a low success rate.
    get_parent_map = branch.repository.texts.get_parent_map
    modified_text_revisions = set()
    chunk_size = 1000
    for start in xrange(0, len(text_keys), chunk_size):
        next_keys = text_keys[start:start + chunk_size]
        # Only keep the revision_id portion of the key
        modified_text_revisions.update(
            [k[1] for k in get_parent_map(next_keys)])
    del text_keys, next_keys

    result = []
    # Track what revisions will merge the current revision, replace entries
    # with 'None' when they have been added to result
    current_merge_stack = [None]
    for info in view_revisions:
        rev_id, revno, depth = info
        if depth == len(current_merge_stack):
            current_merge_stack.append(info)
        else:
            del current_merge_stack[depth + 1:]
            current_merge_stack[-1] = info

        if rev_id in modified_text_revisions:
            # This needs to be logged, along with the extra revisions
            for idx in xrange(len(current_merge_stack)):
                node = current_merge_stack[idx]
                if node is not None:
                    result.append(node)
                    current_merge_stack[idx] = None
    return result


def get_view_revisions(mainline_revs, rev_nos, branch, direction,
                       include_merges=True):
    """Produce an iterator of revisions to show
    :return: an iterator of (revision_id, revno, merge_depth)
    (if there is no revno for a revision, None is supplied)
    """
    if include_merges is False:
        revision_ids = mainline_revs[1:]
        if direction == 'reverse':
            revision_ids.reverse()
        for revision_id in revision_ids:
            yield revision_id, str(rev_nos[revision_id]), 0
        return
    graph = branch.repository.get_graph()
    # This asks for all mainline revisions, which means we only have to spider
    # sideways, rather than depth history. That said, its still size-of-history
    # and should be addressed.
    # mainline_revisions always includes an extra revision at the beginning, so
    # don't request it.
    parent_map = dict(((key, value) for key, value in
        graph.iter_ancestry(mainline_revs[1:]) if value is not None))
    # filter out ghosts; merge_sort errors on ghosts.
    rev_graph = _mod_repository._strip_NULL_ghosts(parent_map)
    merge_sorted_revisions = tsort.merge_sort(
        rev_graph,
        mainline_revs[-1],
        mainline_revs,
        generate_revno=True)

    if direction == 'forward':
        # forward means oldest first.
        merge_sorted_revisions = reverse_by_depth(merge_sorted_revisions)
    elif direction != 'reverse':
        raise ValueError('invalid direction %r' % direction)

    for (sequence, rev_id, merge_depth, revno, end_of_merge
         ) in merge_sorted_revisions:
        yield rev_id, '.'.join(map(str, revno)), merge_depth


def reverse_by_depth(merge_sorted_revisions, _depth=0):
    """Reverse revisions by depth.

    Revisions with a different depth are sorted as a group with the previous
    revision of that depth.  There may be no topological justification for this,
    but it looks much nicer.
    """
    # Add a fake revision at start so that we can always attach sub revisions
    merge_sorted_revisions = [(None, None, _depth)] + merge_sorted_revisions
    zd_revisions = []
    for val in merge_sorted_revisions:
        if val[2] == _depth:
            # Each revision at the current depth becomes a chunk grouping all
            # higher depth revisions.
            zd_revisions.append([val])
        else:
            zd_revisions[-1].append(val)
    for revisions in zd_revisions:
        if len(revisions) > 1:
            # We have higher depth revisions, let reverse them locally
            revisions[1:] = reverse_by_depth(revisions[1:], _depth + 1)
    zd_revisions.reverse()
    result = []
    for chunk in zd_revisions:
        result.extend(chunk)
    if _depth == 0:
        # Top level call, get rid of the fake revisions that have been added
        result = [r for r in result if r[0] is not None and r[1] is not None]
    return result


class LogRevision(object):
    """A revision to be logged (by LogFormatter.log_revision).

    A simple wrapper for the attributes of a revision to be logged.
    The attributes may or may not be populated, as determined by the 
    logging options and the log formatter capabilities.
    """

    def __init__(self, rev=None, revno=None, merge_depth=0, delta=None,
                 tags=None):
        self.rev = rev
        self.revno = revno
        self.merge_depth = merge_depth
        self.delta = delta
        self.tags = tags


class LogFormatter(object):
    """Abstract class to display log messages.

    At a minimum, a derived class must implement the log_revision method.

    If the LogFormatter needs to be informed of the beginning or end of
    a log it should implement the begin_log and/or end_log hook methods.

    A LogFormatter should define the following supports_XXX flags 
    to indicate which LogRevision attributes it supports:

    - supports_delta must be True if this log formatter supports delta.
        Otherwise the delta attribute may not be populated.  The 'delta_format'
        attribute describes whether the 'short_status' format (1) or the long
        one (2) should be used.
 
    - supports_merge_revisions must be True if this log formatter supports 
        merge revisions.  If not, and if supports_single_merge_revision is
        also not True, then only mainline revisions will be passed to the 
        formatter.
    - supports_single_merge_revision must be True if this log formatter
        supports logging only a single merge revision.  This flag is
        only relevant if supports_merge_revisions is not True.
    - supports_tags must be True if this log formatter supports tags.
        Otherwise the tags attribute may not be populated.

    Plugins can register functions to show custom revision properties using
    the properties_handler_registry. The registered function
    must respect the following interface description:
        def my_show_properties(properties_dict):
            # code that returns a dict {'name':'value'} of the properties 
            # to be shown
    """

    def __init__(self, to_file, show_ids=False, show_timezone='original',
                 delta_format=None):
        self.to_file = to_file
        self.show_ids = show_ids
        self.show_timezone = show_timezone
        if delta_format is None:
            # Ensures backward compatibility
            delta_format = 2 # long format
        self.delta_format = delta_format

# TODO: uncomment this block after show() has been removed.
# Until then defining log_revision would prevent _show_log calling show() 
# in legacy formatters.
#    def log_revision(self, revision):
#        """Log a revision.
#
#        :param  revision:   The LogRevision to be logged.
#        """
#        raise NotImplementedError('not implemented in abstract base')

    def short_committer(self, rev):
        name, address = config.parse_username(rev.committer)
        if name:
            return name
        return address

    def short_author(self, rev):
        name, address = config.parse_username(rev.get_apparent_author())
        if name:
            return name
        return address

    def show_properties(self, revision, indent):
        """Displays the custom properties returned by each registered handler.
        
        If a registered handler raises an error it is propagated.
        """
        for key, handler in properties_handler_registry.iteritems():
            for key, value in handler(revision).items():
                self.to_file.write(indent + key + ': ' + value + '\n')


class LongLogFormatter(LogFormatter):

    supports_merge_revisions = True
    supports_delta = True
    supports_tags = True

    def log_revision(self, revision):
        """Log a revision, either merged or not."""
        indent = '    ' * revision.merge_depth
        to_file = self.to_file
        to_file.write(indent + '-' * 60 + '\n')
        if revision.revno is not None:
            to_file.write(indent + 'revno: %s\n' % (revision.revno,))
        if revision.tags:
            to_file.write(indent + 'tags: %s\n' % (', '.join(revision.tags)))
        if self.show_ids:
            to_file.write(indent + 'revision-id: ' + revision.rev.revision_id)
            to_file.write('\n')
            for parent_id in revision.rev.parent_ids:
                to_file.write(indent + 'parent: %s\n' % (parent_id,))
        self.show_properties(revision.rev, indent)

        author = revision.rev.properties.get('author', None)
        if author is not None:
            to_file.write(indent + 'author: %s\n' % (author,))
        to_file.write(indent + 'committer: %s\n' % (revision.rev.committer,))

        branch_nick = revision.rev.properties.get('branch-nick', None)
        if branch_nick is not None:
            to_file.write(indent + 'branch nick: %s\n' % (branch_nick,))

        date_str = format_date(revision.rev.timestamp,
                               revision.rev.timezone or 0,
                               self.show_timezone)
        to_file.write(indent + 'timestamp: %s\n' % (date_str,))

        to_file.write(indent + 'message:\n')
        if not revision.rev.message:
            to_file.write(indent + '  (no message)\n')
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                to_file.write(indent + '  %s\n' % (l,))
        if revision.delta is not None:
            # We don't respect delta_format for compatibility
            revision.delta.show(to_file, self.show_ids, indent=indent,
                                short_status=False)


class ShortLogFormatter(LogFormatter):

    supports_delta = True
    supports_single_merge_revision = True

    def log_revision(self, revision):
        to_file = self.to_file
        is_merge = ''
        if len(revision.rev.parent_ids) > 1:
            is_merge = ' [merge]'
        to_file.write("%5s %s\t%s%s\n" % (revision.revno,
                self.short_author(revision.rev),
                format_date(revision.rev.timestamp,
                            revision.rev.timezone or 0,
                            self.show_timezone, date_fmt="%Y-%m-%d",
                            show_offset=False),
                is_merge))
        if self.show_ids:
            to_file.write('      revision-id:%s\n'
                          % (revision.rev.revision_id,))
        if not revision.rev.message:
            to_file.write('      (no message)\n')
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                to_file.write('      %s\n' % (l,))

        if revision.delta is not None:
            revision.delta.show(to_file, self.show_ids,
                                short_status=self.delta_format==1)
        to_file.write('\n')


class LineLogFormatter(LogFormatter):

    supports_single_merge_revision = True

    def __init__(self, *args, **kwargs):
        super(LineLogFormatter, self).__init__(*args, **kwargs)
        self._max_chars = terminal_width() - 1

    def truncate(self, str, max_len):
        if len(str) <= max_len:
            return str
        return str[:max_len-3]+'...'

    def date_string(self, rev):
        return format_date(rev.timestamp, rev.timezone or 0,
                           self.show_timezone, date_fmt="%Y-%m-%d",
                           show_offset=False)

    def message(self, rev):
        if not rev.message:
            return '(no message)'
        else:
            return rev.message

    def log_revision(self, revision):
        self.to_file.write(self.log_string(revision.revno, revision.rev,
                                              self._max_chars))
        self.to_file.write('\n')

    def log_string(self, revno, rev, max_chars):
        """Format log info into one string. Truncate tail of string
        :param  revno:      revision number or None.
                            Revision numbers counts from 1.
        :param  rev:        revision info object
        :param  max_chars:  maximum length of resulting string
        :return:            formatted truncated string
        """
        out = []
        if revno:
            # show revno only when is not None
            out.append("%s:" % revno)
        out.append(self.truncate(self.short_author(rev), 20))
        out.append(self.date_string(rev))
        out.append(rev.get_summary())
        return self.truncate(" ".join(out).rstrip('\n'), max_chars)


def line_log(rev, max_chars):
    lf = LineLogFormatter(None)
    return lf.log_string(None, rev, max_chars)


class LogFormatterRegistry(registry.Registry):
    """Registry for log formatters"""

    def make_formatter(self, name, *args, **kwargs):
        """Construct a formatter from arguments.

        :param name: Name of the formatter to construct.  'short', 'long' and
            'line' are built-in.
        """
        return self.get(name)(*args, **kwargs)

    def get_default(self, branch):
        return self.get(branch.get_config().log_format())


log_formatter_registry = LogFormatterRegistry()


log_formatter_registry.register('short', ShortLogFormatter,
                                'Moderately short log format')
log_formatter_registry.register('long', LongLogFormatter,
                                'Detailed log format')
log_formatter_registry.register('line', LineLogFormatter,
                                'Log format with one line per revision')


def register_formatter(name, formatter):
    log_formatter_registry.register(name, formatter)


def log_formatter(name, *args, **kwargs):
    """Construct a formatter from arguments.

    name -- Name of the formatter to construct; currently 'long', 'short' and
        'line' are supported.
    """
    try:
        return log_formatter_registry.make_formatter(name, *args, **kwargs)
    except KeyError:
        raise errors.BzrCommandError("unknown log formatter: %r" % name)


def show_one_log(revno, rev, delta, verbose, to_file, show_timezone):
    # deprecated; for compatibility
    lf = LongLogFormatter(to_file=to_file, show_timezone=show_timezone)
    lf.show(revno, rev, delta)


def show_changed_revisions(branch, old_rh, new_rh, to_file=None,
                           log_format='long'):
    """Show the change in revision history comparing the old revision history to the new one.

    :param branch: The branch where the revisions exist
    :param old_rh: The old revision history
    :param new_rh: The new revision history
    :param to_file: A file to write the results to. If None, stdout will be used
    """
    if to_file is None:
        to_file = codecs.getwriter(get_terminal_encoding())(sys.stdout,
            errors='replace')
    lf = log_formatter(log_format,
                       show_ids=False,
                       to_file=to_file,
                       show_timezone='original')

    # This is the first index which is different between
    # old and new
    base_idx = None
    for i in xrange(max(len(new_rh),
                        len(old_rh))):
        if (len(new_rh) <= i
            or len(old_rh) <= i
            or new_rh[i] != old_rh[i]):
            base_idx = i
            break

    if base_idx is None:
        to_file.write('Nothing seems to have changed\n')
        return
    ## TODO: It might be nice to do something like show_log
    ##       and show the merged entries. But since this is the
    ##       removed revisions, it shouldn't be as important
    if base_idx < len(old_rh):
        to_file.write('*'*60)
        to_file.write('\nRemoved Revisions:\n')
        for i in range(base_idx, len(old_rh)):
            rev = branch.repository.get_revision(old_rh[i])
            lr = LogRevision(rev, i+1, 0, None)
            lf.log_revision(lr)
        to_file.write('*'*60)
        to_file.write('\n\n')
    if base_idx < len(new_rh):
        to_file.write('Added Revisions:\n')
        show_log(branch,
                 lf,
                 None,
                 verbose=False,
                 direction='forward',
                 start_revision=base_idx+1,
                 end_revision=len(new_rh),
                 search=None)


def get_history_change(old_revision_id, new_revision_id, repository):
    """Calculate the uncommon lefthand history between two revisions.

    :param old_revision_id: The original revision id.
    :param new_revision_id: The new revision id.
    :param repository: The repository to use for the calculation.

    return old_history, new_history
    """
    old_history = []
    old_revisions = set()
    new_history = []
    new_revisions = set()
    new_iter = repository.iter_reverse_revision_history(new_revision_id)
    old_iter = repository.iter_reverse_revision_history(old_revision_id)
    stop_revision = None
    do_old = True
    do_new = True
    while do_new or do_old:
        if do_new:
            try:
                new_revision = new_iter.next()
            except StopIteration:
                do_new = False
            else:
                new_history.append(new_revision)
                new_revisions.add(new_revision)
                if new_revision in old_revisions:
                    stop_revision = new_revision
                    break
        if do_old:
            try:
                old_revision = old_iter.next()
            except StopIteration:
                do_old = False
            else:
                old_history.append(old_revision)
                old_revisions.add(old_revision)
                if old_revision in new_revisions:
                    stop_revision = old_revision
                    break
    new_history.reverse()
    old_history.reverse()
    if stop_revision is not None:
        new_history = new_history[new_history.index(stop_revision) + 1:]
        old_history = old_history[old_history.index(stop_revision) + 1:]
    return old_history, new_history


def show_branch_change(branch, output, old_revno, old_revision_id):
    """Show the changes made to a branch.

    :param branch: The branch to show changes about.
    :param output: A file-like object to write changes to.
    :param old_revno: The revno of the old tip.
    :param old_revision_id: The revision_id of the old tip.
    """
    new_revno, new_revision_id = branch.last_revision_info()
    old_history, new_history = get_history_change(old_revision_id,
                                                  new_revision_id,
                                                  branch.repository)
    if old_history == [] and new_history == []:
        output.write('Nothing seems to have changed\n')
        return

    log_format = log_formatter_registry.get_default(branch)
    lf = log_format(show_ids=False, to_file=output, show_timezone='original')
    if old_history != []:
        output.write('*'*60)
        output.write('\nRemoved Revisions:\n')
        show_flat_log(branch.repository, old_history, old_revno, lf)
        output.write('*'*60)
        output.write('\n\n')
    if new_history != []:
        output.write('Added Revisions:\n')
        start_revno = new_revno - len(new_history) + 1
        show_log(branch, lf, None, verbose=False, direction='forward',
                 start_revision=start_revno,)


def show_flat_log(repository, history, last_revno, lf):
    """Show a simple log of the specified history.

    :param repository: The repository to retrieve revisions from.
    :param history: A list of revision_ids indicating the lefthand history.
    :param last_revno: The revno of the last revision_id in the history.
    :param lf: The log formatter to use.
    """
    start_revno = last_revno - len(history) + 1
    revisions = repository.get_revisions(history)
    for i, rev in enumerate(revisions):
        lr = LogRevision(rev, i + last_revno, 0, None)
        lf.log_revision(lr)


properties_handler_registry = registry.Registry()
properties_handler_registry.register_lazy("foreign",
                                          "bzrlib.foreign",
                                          "show_foreign_properties")


# adapters which revision ids to log are filtered. When log is called, the
# log_rev_iterator is adapted through each of these factory methods.
# Plugins are welcome to mutate this list in any way they like - as long
# as the overall behaviour is preserved. At this point there is no extensible
# mechanism for getting parameters to each factory method, and until there is
# this won't be considered a stable api.
log_adapters = [
    # core log logic
    _make_batch_filter,
    # read revision objects
    _make_revision_objects,
    # filter on log messages
    _make_search_filter,
    # generate deltas for things we will show
    _make_delta_filter
    ]
