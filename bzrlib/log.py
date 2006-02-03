# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

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
relative to its mainline parent, not the delta relative to the last
logged revision.  So for example if you ask for a verbose log of
changes touching hello.c you will get a list of those revisions also
listing other things that were changed in the same revision, but not
all the changes since the previous revision that touched hello.c.
"""


# TODO: option to show delta summaries for merged-in revisions

import bzrlib.errors as errors
from bzrlib.tree import EmptyTree
from bzrlib.delta import compare_trees
from bzrlib.trace import mutter
import re


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


def _get_revision_delta(branch, revno):
    """Return the delta for a mainline revision.
    
    This is used to show summaries in verbose logs, and also for finding 
    revisions which touch a given file."""
    # XXX: What are we supposed to do when showing a summary for something 
    # other than a mainline revision.  The delta to it's first parent, or
    # (more useful) the delta to a nominated other revision.
    return branch.get_revision_delta(revno)


def show_log(branch,
             lf,
             specific_fileid=None,
             verbose=False,
             direction='reverse',
             start_revision=None,
             end_revision=None,
             search=None):
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
    """
    branch.lock_read()
    try:
        _show_log(branch, lf, specific_fileid, verbose, direction,
                  start_revision, end_revision, search)
    finally:
        branch.unlock()
    
def _show_log(branch,
             lf,
             specific_fileid=None,
             verbose=False,
             direction='reverse',
             start_revision=None,
             end_revision=None,
             search=None):
    """Worker function for show_log - see show_log."""
    from bzrlib.osutils import format_date
    from bzrlib.errors import BzrCheckError
    from bzrlib.textui import show_status
    
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

    which_revs = _enumerate_history(branch)
    
    if start_revision is None:
        start_revision = 1
    else:
        branch.check_real_revno(start_revision)
    
    if end_revision is None:
        end_revision = len(which_revs)
    else:
        branch.check_real_revno(end_revision)

    # list indexes are 0-based; revisions are 1-based
    cut_revs = which_revs[(start_revision-1):(end_revision)]

    if direction == 'reverse':
        cut_revs.reverse()
    elif direction == 'forward':
        pass
    else:
        raise ValueError('invalid direction %r' % direction)

    revision_history = branch.revision_history()
    for revno, rev_id in cut_revs:
        if verbose or specific_fileid:
            delta = _get_revision_delta(branch, revno)
            
        if specific_fileid:
            if not delta.touches_file_id(specific_fileid):
                continue

        if not verbose:
            # although we calculated it, throw it away without display
            delta = None

        rev = branch.repository.get_revision(rev_id)

        if searchRE:
            if not searchRE.search(rev.message):
                continue

        lf.show(revno, rev, delta)
        if hasattr(lf, 'show_merge'):
            if revno == 1:
                excludes = set()
            else:
                # revno is 1 based, so -2 to get back 1 less.
                repository = branch.repository
                excludes = repository.get_ancestry(revision_history[revno - 2])
                excludes = set(excludes)
            pending = list(rev.parent_ids)
            while pending:
                rev_id = pending.pop()
                if rev_id in excludes:
                    continue
                # prevent showing merged revs twice if they multi-path.
                excludes.add(rev_id)
                try:
                    rev = branch.repository.get_revision(rev_id)
                except errors.NoSuchRevision:
                    continue
                pending.extend(rev.parent_ids)
                lf.show_merge(rev)


def deltas_for_log_dummy(branch, which_revs):
    """Return all the revisions without intermediate deltas.

    Useful for log commands that won't need the delta information.
    """
    
    for revno, revision_id in which_revs:
        yield revno, branch.get_revision(revision_id), None


def deltas_for_log_reverse(branch, which_revs):
    """Compute deltas for display in latest-to-earliest order.

    branch
        Branch to traverse

    which_revs
        Sequence of (revno, revision_id) for the subset of history to examine

    returns 
        Sequence of (revno, rev, delta)

    The delta is from the given revision to the next one in the
    sequence, which makes sense if the log is being displayed from
    newest to oldest.
    """
    last_revno = last_revision_id = last_tree = None
    for revno, revision_id in which_revs:
        this_tree = branch.revision_tree(revision_id)
        this_revision = branch.get_revision(revision_id)
        
        if last_revno:
            yield last_revno, last_revision, compare_trees(this_tree, last_tree, False)

        this_tree = EmptyTree(branch.get_root_id())

        last_revno = revno
        last_revision = this_revision
        last_tree = this_tree

    if last_revno:
        if last_revno == 1:
            this_tree = EmptyTree(branch.get_root_id())
        else:
            this_revno = last_revno - 1
            this_revision_id = branch.revision_history()[this_revno]
            this_tree = branch.revision_tree(this_revision_id)
        yield last_revno, last_revision, compare_trees(this_tree, last_tree, False)


def deltas_for_log_forward(branch, which_revs):
    """Compute deltas for display in forward log.

    Given a sequence of (revno, revision_id) pairs, return
    (revno, rev, delta).

    The delta is from the given revision to the next one in the
    sequence, which makes sense if the log is being displayed from
    newest to oldest.
    """
    last_revno = last_revision_id = last_tree = None
    prev_tree = EmptyTree(branch.get_root_id())

    for revno, revision_id in which_revs:
        this_tree = branch.revision_tree(revision_id)
        this_revision = branch.get_revision(revision_id)

        if not last_revno:
            if revno == 1:
                last_tree = EmptyTree(branch.get_root_id())
            else:
                last_revno = revno - 1
                last_revision_id = branch.revision_history()[last_revno]
                last_tree = branch.revision_tree(last_revision_id)

        yield revno, this_revision, compare_trees(last_tree, this_tree, False)

        last_revno = revno
        last_revision = this_revision
        last_tree = this_tree


class LogFormatter(object):
    """Abstract class to display log messages."""
    def __init__(self, to_file, show_ids=False, show_timezone='original'):
        self.to_file = to_file
        self.show_ids = show_ids
        self.show_timezone = show_timezone


    def show(self, revno, rev, delta):
        raise NotImplementedError('not implemented in abstract base')

    def short_committer(self, rev):
        return re.sub('<.*@.*>', '', rev.committer).strip(' ')
    
    
class LongLogFormatter(LogFormatter):
    def show(self, revno, rev, delta):
        return self._show_helper(revno=revno, rev=rev, delta=delta)

    def show_merge(self, rev):
        return self._show_helper(rev=rev, indent='    ', merged=True, delta=None)

    def _show_helper(self, rev=None, revno=None, indent='', merged=False, delta=None):
	"""Show a revision, either merged or not."""
        from bzrlib.osutils import format_date
        to_file = self.to_file
        print >>to_file,  indent+'-' * 60
        if revno is not None:
            print >>to_file,  'revno:', revno
        if merged:
            print >>to_file,  indent+'merged:', rev.revision_id
        elif self.show_ids:
            print >>to_file,  indent+'revision-id:', rev.revision_id
        if self.show_ids:
            for parent_id in rev.parent_ids:
                print >>to_file, indent+'parent:', parent_id
        print >>to_file,  indent+'committer:', rev.committer
        try:
            print >>to_file, indent+'branch nick: %s' % \
                rev.properties['branch-nick']
        except KeyError:
            pass
        date_str = format_date(rev.timestamp,
                               rev.timezone or 0,
                               self.show_timezone)
        print >>to_file,  indent+'timestamp: %s' % date_str

        print >>to_file,  indent+'message:'
        if not rev.message:
            print >>to_file,  indent+'  (no message)'
        else:
            message = rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                print >>to_file,  indent+'  ' + l
        if delta != None:
            delta.show(to_file, self.show_ids)


class ShortLogFormatter(LogFormatter):
    def show(self, revno, rev, delta):
        from bzrlib.osutils import format_date

        to_file = self.to_file
        date_str = format_date(rev.timestamp, rev.timezone or 0,
                            self.show_timezone)
        print >>to_file, "%5d %s\t%s" % (revno, self.short_committer(rev),
                format_date(rev.timestamp, rev.timezone or 0,
                            self.show_timezone, date_fmt="%Y-%m-%d",
                           show_offset=False))
        if self.show_ids:
            print >>to_file,  '      revision-id:', rev.revision_id
        if not rev.message:
            print >>to_file,  '      (no message)'
        else:
            message = rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                print >>to_file,  '      ' + l

        # TODO: Why not show the modified files in a shorter form as
        # well? rewrap them single lines of appropriate length
        if delta != None:
            delta.show(to_file, self.show_ids)
        print >>to_file, ''

class LineLogFormatter(LogFormatter):
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

    def show(self, revno, rev, delta):
        print >> self.to_file, self.log_string(rev, 79) 

    def log_string(self, rev, max_chars):
        out = [self.truncate(self.short_committer(rev), 20)]
        out.append(self.date_string(rev))
        out.append(self.message(rev).replace('\n', ' '))
        return self.truncate(" ".join(out).rstrip('\n'), max_chars)

def line_log(rev, max_chars):
    lf = LineLogFormatter(None)
    return lf.log_string(rev, max_chars)

FORMATTERS = {'default': LongLogFormatter,
              'long': LongLogFormatter,
              'short': ShortLogFormatter,
              'line': LineLogFormatter,
              }

def register_formatter(name, formatter):
    FORMATTERS[name] = formatter

def set_default_formatter(formatter):
    FORMATTERS['default'] = formatter


def log_formatter(name, *args, **kwargs):
    """Construct a formatter from arguments.

    name -- Name of the formatter to construct; currently 'long', 'short' and
        'line' are supported.
    """
    from bzrlib.errors import BzrCommandError
    try:
        return FORMATTERS[name](*args, **kwargs)
    except KeyError:
        raise BzrCommandError("unknown log formatter: %r" % name)

def show_one_log(revno, rev, delta, verbose, to_file, show_timezone):
    # deprecated; for compatability
    lf = LongLogFormatter(to_file=to_file, show_timezone=show_timezone)
    lf.show(revno, rev, delta)

def show_changed_revisions(branch, old_rh, new_rh, to_file=None, log_format='long'):
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
        to_file = codecs.getwriter(bzrlib.user_encoding)(sys.stdout, errors='replace')
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
            lf.show(i+1, rev, None)
        to_file.write('*'*60)
        to_file.write('\n\n')
    if base_idx < len(new_rh):
        to_file.write('Added Revisions:\n')
        show_log(branch,
                 lf,
                 None,
                 verbose=True,
                 direction='forward',
                 start_revision=base_idx+1,
                 end_revision=len(new_rh),
                 search=None)

