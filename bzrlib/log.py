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
             limit=None):
    """Write out human-readable log of commits to this branch.

    lf
        LogFormatter object to show the output.

    specific_fileid
        If true, list only the commits affecting the specified
        file, rather than all commits.

    verbose
        If true show added/changed/deleted/renamed files.

    direction
        'reverse' (default) is latest to earliest;
        'forward' is earliest to latest.

    start_revision
        If not None, only show revisions >= start_revision

    end_revision
        If not None, only show revisions <= end_revision

    search
        If not None, only show revisions with matching commit messages

    limit
        If not None or 0, only show limit revisions
    """
    branch.lock_read()
    try:
        if getattr(lf, 'begin_log', None):
            lf.begin_log()

        _show_log(branch, lf, specific_fileid, verbose, direction,
                  start_revision, end_revision, search, limit)

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
             limit=None):
    """Worker function for show_log - see show_log."""
    if not isinstance(lf, LogFormatter):
        warn("not a LogFormatter instance: %r" % lf)

    if specific_fileid:
        trace.mutter('get log for file_id %r', specific_fileid)
    generate_merge_revisions = getattr(lf, 'supports_merge_revisions', False)
    allow_single_merge_revision = getattr(lf,
        'supports_single_merge_revision', False)
    view_revisions = calculate_view_revisions(branch, start_revision,
                                              end_revision, direction,
                                              specific_fileid,
                                              generate_merge_revisions,
                                              allow_single_merge_revision)
    if search is not None:
        searchRE = re.compile(search, re.IGNORECASE)
    else:
        searchRE = None

    rev_tag_dict = {}
    generate_tags = getattr(lf, 'supports_tags', False)
    if generate_tags:
        if branch.supports_tags():
            rev_tag_dict = branch.tags.get_reverse_tag_dict()

    generate_delta = verbose and getattr(lf, 'supports_delta', False)

    # now we just print all the revisions
    log_count = 0
    for (rev_id, revno, merge_depth), rev, delta in _iter_revisions(
        branch.repository, view_revisions, generate_delta):
        if searchRE:
            if not searchRE.search(rev.message):
                continue

        lr = LogRevision(rev, revno, merge_depth, delta,
                         rev_tag_dict.get(rev_id))
        lf.log_revision(lr)
        if limit:
            log_count += 1
            if log_count >= limit:
                break


def calculate_view_revisions(branch, start_revision, end_revision, direction,
                             specific_fileid, generate_merge_revisions,
                             allow_single_merge_revision):
    if (not generate_merge_revisions and start_revision is end_revision is
        None and direction == 'reverse' and specific_fileid is None):
        return _linear_view_revisions(branch)

    mainline_revs, rev_nos, start_rev_id, end_rev_id = \
        _get_mainline_revs(branch, start_revision, end_revision)
    if not mainline_revs:
        return []

    if direction == 'reverse':
        start_rev_id, end_rev_id = end_rev_id, start_rev_id

    generate_single_revision = False
    if ((not generate_merge_revisions)
        and ((start_rev_id and (start_rev_id not in rev_nos))
            or (end_rev_id and (end_rev_id not in rev_nos)))):
        generate_single_revision = ((start_rev_id == end_rev_id)
            and allow_single_merge_revision)
        if not generate_single_revision:
            raise errors.BzrCommandError('Selected log formatter only supports'
                ' mainline revisions.')
        generate_merge_revisions = generate_single_revision
    view_revs_iter = get_view_revisions(mainline_revs, rev_nos, branch,
                          direction, include_merges=generate_merge_revisions)
    view_revisions = _filter_revision_range(list(view_revs_iter),
                                            start_rev_id,
                                            end_rev_id)
    if view_revisions and generate_single_revision:
        view_revisions = view_revisions[0:1]
    if specific_fileid:
        view_revisions = _filter_revisions_touching_file_id(branch,
                                                         specific_fileid,
                                                         mainline_revs,
                                                         view_revisions)

    # rebase merge_depth - unless there are no revisions or 
    # either the first or last revision have merge_depth = 0.
    if view_revisions and view_revisions[0][2] and view_revisions[-1][2]:
        min_depth = min([d for r,n,d in view_revisions])
        if min_depth != 0:
            view_revisions = [(r,n,d-min_depth) for r,n,d in view_revisions]
    return view_revisions


def _linear_view_revisions(branch):
    start_revno, start_revision_id = branch.last_revision_info()
    repo = branch.repository
    revision_ids = repo.iter_reverse_revision_history(start_revision_id)
    for num, revision_id in enumerate(revision_ids):
        yield revision_id, str(start_revno - num), 0


def _iter_revisions(repository, view_revisions, generate_delta):
    num = 9
    view_revisions = iter(view_revisions)
    while True:
        cur_view_revisions = [d for x, d in zip(range(num), view_revisions)]
        if len(cur_view_revisions) == 0:
            break
        cur_deltas = {}
        # r = revision, n = revno, d = merge depth
        revision_ids = [r for (r, n, d) in cur_view_revisions]
        revisions = repository.get_revisions(revision_ids)
        if generate_delta:
            deltas = repository.get_deltas_for_revisions(revisions)
            cur_deltas = dict(izip((r.revision_id for r in revisions),
                                   deltas))
        for view_data, revision in izip(cur_view_revisions, revisions):
            yield view_data, revision, cur_deltas.get(revision.revision_id)
        num = min(int(num * 1.5), 200)


def _get_mainline_revs(branch, start_revision, end_revision):
    """Get the mainline revisions from the branch.
    
    Generates the list of mainline revisions for the branch.
    
    :param  branch: The branch containing the revisions. 

    :param  start_revision: The first revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :param  end_revision: The last revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :return: A (mainline_revs, rev_nos, start_rev_id, end_rev_id) tuple.
    """
    branch_revno, branch_last_revision = branch.last_revision_info()
    if branch_revno == 0:
        return None, None, None, None

    # For mainline generation, map start_revision and end_revision to 
    # mainline revnos. If the revision is not on the mainline choose the 
    # appropriate extreme of the mainline instead - the extra will be 
    # filtered later.
    # Also map the revisions to rev_ids, to be used in the later filtering
    # stage.
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

    if ((start_rev_id == _mod_revision.NULL_REVISION)
        or (end_rev_id == _mod_revision.NULL_REVISION)):
        raise errors.BzrCommandError('Logging revision 0 is invalid.')
    if start_revno > end_revno:
        raise errors.BzrCommandError("Start revision must be older than "
                                     "the end revision.")

    if end_revno < start_revno:
        return None, None, None, None
    cur_revno = branch_revno
    rev_nos = {}
    mainline_revs = []
    for revision_id in branch.repository.iter_reverse_revision_history(
                        branch_last_revision):
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
    return mainline_revs, rev_nos, start_rev_id, end_rev_id


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


def _filter_revisions_touching_file_id(branch, file_id, mainline_revisions,
                                       view_revs_iter):
    """Return the list of revision ids which touch a given file id.

    The function filters view_revisions and returns a subset.
    This includes the revisions which directly change the file id,
    and the revisions which merge these changes. So if the
    revision graph is::
        A
        |\
        B C
        |/
        D

    And 'C' changes a file, then both C and D will be returned.

    This will also can be restricted based on a subset of the mainline.

    :return: A list of (revision_id, dotted_revno, merge_depth) tuples.
    """
    # find all the revisions that change the specific file
    # build the ancestry of each revision in the graph
    # - only listing the ancestors that change the specific file.
    graph = branch.repository.get_graph()
    # This asks for all mainline revisions, which means we only have to spider
    # sideways, rather than depth history. That said, its still size-of-history
    # and should be addressed.
    # mainline_revisions always includes an extra revision at the beginning, so
    # don't request it.
    parent_map = dict(((key, value) for key, value in
        graph.iter_ancestry(mainline_revisions[1:]) if value is not None))
    sorted_rev_list = tsort.topo_sort(parent_map.items())
    text_keys = [(file_id, rev_id) for rev_id in sorted_rev_list]
    modified_text_versions = branch.repository.texts.get_parent_map(text_keys)
    ancestry = {}
    for rev in sorted_rev_list:
        text_key = (file_id, rev)
        parents = parent_map[rev]
        if text_key not in modified_text_versions and len(parents) == 1:
            # We will not be adding anything new, so just use a reference to
            # the parent ancestry.
            rev_ancestry = ancestry[parents[0]]
        else:
            rev_ancestry = set()
            if text_key in modified_text_versions:
                rev_ancestry.add(rev)
            for parent in parents:
                if parent not in ancestry:
                    # parent is a Ghost, which won't be present in
                    # sorted_rev_list, but we may access it later, so create an
                    # empty node for it
                    ancestry[parent] = set()
                rev_ancestry = rev_ancestry.union(ancestry[parent])
        ancestry[rev] = rev_ancestry

    def is_merging_rev(r):
        parents = parent_map[r]
        if len(parents) > 1:
            leftparent = parents[0]
            for rightparent in parents[1:]:
                if not ancestry[leftparent].issuperset(
                        ancestry[rightparent]):
                    return True
        return False

    # filter from the view the revisions that did not change or merge 
    # the specific file
    return [(r, n, d) for r, n, d in view_revs_iter
            if (file_id, r) in modified_text_versions or is_merging_rev(r)]


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

    for sequence, rev_id, merge_depth, revno, end_of_merge in merge_sorted_revisions:
        yield rev_id, '.'.join(map(str, revno)), merge_depth


def reverse_by_depth(merge_sorted_revisions, _depth=0):
    """Reverse revisions by depth.

    Revisions with a different depth are sorted as a group with the previous
    revision of that depth.  There may be no topological justification for this,
    but it looks much nicer.
    """
    zd_revisions = []
    for val in merge_sorted_revisions:
        if val[2] == _depth:
            zd_revisions.append([val])
        else:
            zd_revisions[-1].append(val)
    for revisions in zd_revisions:
        if len(revisions) > 1:
            revisions[1:] = reverse_by_depth(revisions[1:], _depth + 1)
    zd_revisions.reverse()
    result = []
    for chunk in zd_revisions:
        result.extend(chunk)
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
        Otherwise the delta attribute may not be populated.
    - supports_merge_revisions must be True if this log formatter supports 
        merge revisions.  If not, and if supports_single_merge_revisions is
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

    def __init__(self, to_file, show_ids=False, show_timezone='original'):
        self.to_file = to_file
        self.show_ids = show_ids
        self.show_timezone = show_timezone

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
            revision.delta.show(to_file, self.show_ids, indent=indent)


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
            to_file.write('      revision-id:%s\n' % (revision.rev.revision_id,))
        if not revision.rev.message:
            to_file.write('      (no message)\n')
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                to_file.write('      %s\n' % (l,))

        # TODO: Why not show the modified files in a shorter form as
        # well? rewrap them single lines of appropriate length
        if revision.delta is not None:
            revision.delta.show(to_file, self.show_ids)
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
        :param  revno:      revision number (int) or None.
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


properties_handler_registry = registry.Registry()
