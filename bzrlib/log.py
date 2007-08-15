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

from itertools import izip
import re

from bzrlib import (
    registry,
    symbol_versioning,
    )
import bzrlib.errors as errors
from bzrlib.revisionspec import(
    RevisionInfo
    )
from bzrlib.symbol_versioning import (
    deprecated_method,
    zero_eleven,
    zero_seventeen,
    )
from bzrlib.trace import mutter
from bzrlib.tsort import (
    merge_sort,
    topo_sort,
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
    from bzrlib.osutils import format_date
    from bzrlib.errors import BzrCheckError
    
    from warnings import warn

    if not isinstance(lf, LogFormatter):
        warn("not a LogFormatter instance: %r" % lf)

    if specific_fileid:
        mutter('get log for file_id %r', specific_fileid)

    if search is not None:
        import re
        searchRE = re.compile(search, re.IGNORECASE)
    else:
        searchRE = None

    mainline_revs, rev_nos, start_rev_id, end_rev_id = \
        _get_mainline_revs(branch, start_revision, end_revision)
    if not mainline_revs:
        return

    if direction == 'reverse':
        start_rev_id, end_rev_id = end_rev_id, start_rev_id
        
    legacy_lf = getattr(lf, 'log_revision', None) is None
    if legacy_lf:
        # pre-0.17 formatters use show for mainline revisions.
        # how should we show merged revisions ?
        #   pre-0.11 api: show_merge
        #   0.11-0.16 api: show_merge_revno
        show_merge_revno = getattr(lf, 'show_merge_revno', None)
        show_merge = getattr(lf, 'show_merge', None)
        if show_merge is None and show_merge_revno is None:
            # no merged-revno support
            generate_merge_revisions = False
        else:
            generate_merge_revisions = True
        # tell developers to update their code
        symbol_versioning.warn('LogFormatters should provide log_revision '
            'instead of show and show_merge_revno since bzr 0.17.',
            DeprecationWarning, stacklevel=3)
    else:
        generate_merge_revisions = getattr(lf, 'supports_merge_revisions', 
                                           False)
    view_revs_iter = get_view_revisions(mainline_revs, rev_nos, branch,
                          direction, include_merges=generate_merge_revisions)
    view_revisions = _filter_revision_range(list(view_revs_iter),
                                            start_rev_id,
                                            end_rev_id)
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
        
    rev_tag_dict = {}
    generate_tags = getattr(lf, 'supports_tags', False)
    if generate_tags:
        if branch.supports_tags():
            rev_tag_dict = branch.tags.get_reverse_tag_dict()

    generate_delta = verbose and getattr(lf, 'supports_delta', False)

    def iter_revisions():
        # r = revision, n = revno, d = merge depth
        revision_ids = [r for r, n, d in view_revisions]
        num = 9
        repository = branch.repository
        while revision_ids:
            cur_deltas = {}
            revisions = repository.get_revisions(revision_ids[:num])
            if generate_delta:
                deltas = repository.get_deltas_for_revisions(revisions)
                cur_deltas = dict(izip((r.revision_id for r in revisions),
                                       deltas))
            for revision in revisions:
                yield revision, cur_deltas.get(revision.revision_id)
            revision_ids  = revision_ids[num:]
            num = min(int(num * 1.5), 200)

    # now we just print all the revisions
    log_count = 0
    for ((rev_id, revno, merge_depth), (rev, delta)) in \
         izip(view_revisions, iter_revisions()):

        if searchRE:
            if not searchRE.search(rev.message):
                continue

        if not legacy_lf:
            lr = LogRevision(rev, revno, merge_depth, delta,
                             rev_tag_dict.get(rev_id))
            lf.log_revision(lr)
        else:
            # support for legacy (pre-0.17) LogFormatters
            if merge_depth == 0:
                if generate_tags:
                    lf.show(revno, rev, delta, rev_tag_dict.get(rev_id))
                else:
                    lf.show(revno, rev, delta)
            else:
                if show_merge_revno is None:
                    lf.show_merge(rev, merge_depth)
                else:
                    if generate_tags:
                        lf.show_merge_revno(rev, merge_depth, revno,
                                            rev_tag_dict.get(rev_id))
                    else:
                        lf.show_merge_revno(rev, merge_depth, revno)
        if limit:
            log_count += 1
            if log_count >= limit:
                break


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
    which_revs = _enumerate_history(branch)
    if not which_revs:
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
        if isinstance(start_revision,RevisionInfo):
            start_rev_id = start_revision.rev_id
            start_revno = start_revision.revno or 1
        else:
            branch.check_real_revno(start_revision)
            start_revno = start_revision
    
    end_rev_id = None
    if end_revision is None:
        end_revno = len(which_revs)
    else:
        if isinstance(end_revision,RevisionInfo):
            end_rev_id = end_revision.rev_id
            end_revno = end_revision.revno or len(which_revs)
        else:
            branch.check_real_revno(end_revision)
            end_revno = end_revision

    if start_revno > end_revno:
        from bzrlib.errors import BzrCommandError
        raise BzrCommandError("Start revision must be older than "
                              "the end revision.")

    # list indexes are 0-based; revisions are 1-based
    cut_revs = which_revs[(start_revno-1):(end_revno)]
    if not cut_revs:
        return None, None, None, None

    # convert the revision history to a dictionary:
    rev_nos = dict((k, v) for v, k in cut_revs)

    # override the mainline to look like the revision history.
    mainline_revs = [revision_id for index, revision_id in cut_revs]
    if cut_revs[0][0] == 1:
        mainline_revs.insert(0, None)
    else:
        mainline_revs.insert(0, which_revs[start_revno-2][1])
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
    file_weave = branch.repository.weave_store.get_weave(file_id,
                branch.repository.get_transaction())
    weave_modifed_revisions = set(file_weave.versions())
    # build the ancestry of each revision in the graph
    # - only listing the ancestors that change the specific file.
    rev_graph = branch.repository.get_revision_graph(mainline_revisions[-1])
    sorted_rev_list = topo_sort(rev_graph)
    ancestry = {}
    for rev in sorted_rev_list:
        parents = rev_graph[rev]
        if rev not in weave_modifed_revisions and len(parents) == 1:
            # We will not be adding anything new, so just use a reference to
            # the parent ancestry.
            rev_ancestry = ancestry[parents[0]]
        else:
            rev_ancestry = set()
            if rev in weave_modifed_revisions:
                rev_ancestry.add(rev)
            for parent in parents:
                rev_ancestry = rev_ancestry.union(ancestry[parent])
        ancestry[rev] = rev_ancestry

    def is_merging_rev(r):
        parents = rev_graph[r]
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
            if r in weave_modifed_revisions or is_merging_rev(r)]


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
    merge_sorted_revisions = merge_sort(
        branch.repository.get_revision_graph(mainline_revs[-1]),
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
            assert val[2] > _depth
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
        merge revisions.  If not, only mainline revisions (those 
        with merge_depth == 0) will be passed to the formatter.
    - supports_tags must be True if this log formatter supports tags.
        Otherwise the tags attribute may not be populated.
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

    @deprecated_method(zero_seventeen)
    def show(self, revno, rev, delta):
        raise NotImplementedError('not implemented in abstract base')

    def short_committer(self, rev):
        return re.sub('<.*@.*>', '', rev.committer).strip(' ')


class LongLogFormatter(LogFormatter):

    supports_merge_revisions = True
    supports_delta = True
    supports_tags = True

    @deprecated_method(zero_seventeen)
    def show(self, revno, rev, delta, tags=None):
        lr = LogRevision(rev, revno, 0, delta, tags)
        return self.log_revision(lr)

    @deprecated_method(zero_eleven)
    def show_merge(self, rev, merge_depth):
        lr = LogRevision(rev, merge_depth=merge_depth)
        return self.log_revision(lr)

    @deprecated_method(zero_seventeen)
    def show_merge_revno(self, rev, merge_depth, revno, tags=None):
        """Show a merged revision rev, with merge_depth and a revno."""
        lr = LogRevision(rev, revno, merge_depth, tags=tags)
        return self.log_revision(lr)

    def log_revision(self, revision):
        """Log a revision, either merged or not."""
        from bzrlib.osutils import format_date
        indent = '    ' * revision.merge_depth
        to_file = self.to_file
        print >>to_file, indent + '-' * 60
        if revision.revno is not None:
            print >>to_file, indent + 'revno:', revision.revno
        if revision.tags:
            print >>to_file, indent + 'tags: %s' % (', '.join(revision.tags))
        if self.show_ids:
            print >>to_file, indent + 'revision-id:', revision.rev.revision_id
            for parent_id in revision.rev.parent_ids:
                print >>to_file, indent + 'parent:', parent_id
        print >>to_file, indent + 'committer:', revision.rev.committer

        author = revision.rev.properties.get('author', None)
        if author is not None:
            print >>to_file, indent + 'author:', author

        branch_nick = revision.rev.properties.get('branch-nick', None)
        if branch_nick is not None:
            print >>to_file, indent + 'branch nick:', branch_nick

        date_str = format_date(revision.rev.timestamp,
                               revision.rev.timezone or 0,
                               self.show_timezone)
        print >>to_file, indent + 'timestamp: %s' % date_str

        print >>to_file, indent + 'message:'
        if not revision.rev.message:
            print >>to_file, indent + '  (no message)'
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                print >>to_file, indent + '  ' + l
        if revision.delta is not None:
            revision.delta.show(to_file, self.show_ids, indent=indent)


class ShortLogFormatter(LogFormatter):

    supports_delta = True

    @deprecated_method(zero_seventeen)
    def show(self, revno, rev, delta):
        lr = LogRevision(rev, revno, 0, delta)
        return self.log_revision(lr)

    def log_revision(self, revision):
        from bzrlib.osutils import format_date

        to_file = self.to_file
        date_str = format_date(revision.rev.timestamp,
                               revision.rev.timezone or 0,
                               self.show_timezone)
        is_merge = ''
        if len(revision.rev.parent_ids) > 1:
            is_merge = ' [merge]'
        print >>to_file, "%5s %s\t%s%s" % (revision.revno,
                self.short_committer(revision.rev),
                format_date(revision.rev.timestamp,
                            revision.rev.timezone or 0,
                            self.show_timezone, date_fmt="%Y-%m-%d",
                            show_offset=False),
                is_merge)
        if self.show_ids:
            print >>to_file,  '      revision-id:', revision.rev.revision_id
        if not revision.rev.message:
            print >>to_file,  '      (no message)'
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                print >>to_file,  '      ' + l

        # TODO: Why not show the modified files in a shorter form as
        # well? rewrap them single lines of appropriate length
        if revision.delta is not None:
            revision.delta.show(to_file, self.show_ids)
        print >>to_file, ''


class LineLogFormatter(LogFormatter):

    def __init__(self, *args, **kwargs):
        from bzrlib.osutils import terminal_width
        super(LineLogFormatter, self).__init__(*args, **kwargs)
        self._max_chars = terminal_width() - 1

    def truncate(self, str, max_len):
        if len(str) <= max_len:
            return str
        return str[:max_len-3]+'...'

    def date_string(self, rev):
        from bzrlib.osutils import format_date
        return format_date(rev.timestamp, rev.timezone or 0, 
                           self.show_timezone, date_fmt="%Y-%m-%d",
                           show_offset=False)

    def message(self, rev):
        if not rev.message:
            return '(no message)'
        else:
            return rev.message

    @deprecated_method(zero_seventeen)
    def show(self, revno, rev, delta):
        from bzrlib.osutils import terminal_width
        print >> self.to_file, self.log_string(revno, rev, terminal_width()-1)

    def log_revision(self, revision):
        print >>self.to_file, self.log_string(revision.revno, revision.rev,
                                              self._max_chars)

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
        out.append(self.truncate(self.short_committer(rev), 20))
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
    from bzrlib.errors import BzrCommandError
    try:
        return log_formatter_registry.make_formatter(name, *args, **kwargs)
    except KeyError:
        raise BzrCommandError("unknown log formatter: %r" % name)


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
        import sys
        import codecs
        import bzrlib
        to_file = codecs.getwriter(bzrlib.user_encoding)(sys.stdout,
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

