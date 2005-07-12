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

* from last to first or (not anymore) from first to last;
  the default is "reversed" because it shows the likely most
  relevant and interesting information first

* (not yet) in XML format
"""


from trace import mutter

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
        this_inv = branch.get_revision_inventory(revision_id)
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
    from bzrlib.osutils import format_date
    from bzrlib.errors import BzrCheckError
    from bzrlib.textui import show_status
    
    from warnings import warn

    if not isinstance(lf, LogFormatter):
        warn("not a LogFormatter instance: %r" % lf)

    if specific_fileid:
        mutter('get log for file_id %r' % specific_fileid)

    if search is not None:
        import re
        searchRE = re.compile(search, re.IGNORECASE)
    else:
        searchRE = None

    which_revs = branch.enum_history(direction)
    which_revs = [x for x in which_revs if (
            (start_revision is None or x[0] >= start_revision)
            and (end_revision is None or x[0] <= end_revision))]

    if not (verbose or specific_fileid):
        # no need to know what changed between revisions
        with_deltas = deltas_for_log_dummy(branch, which_revs)
    elif direction == 'reverse':
        with_deltas = deltas_for_log_reverse(branch, which_revs)
    else:        
        with_deltas = deltas_for_log_forward(branch, which_revs)

    for revno, rev, delta in with_deltas:
        if specific_fileid:
            if not delta.touches_file_id(specific_fileid):
                continue

        if not verbose:
            # although we calculated it, throw it away without display
            delta = None

        if searchRE is None or searchRE.search(rev.message):
            lf.show(revno, rev, delta)



def deltas_for_log_dummy(branch, which_revs):
    for revno, revision_id in which_revs:
        yield revno, branch.get_revision(revision_id), None


def deltas_for_log_reverse(branch, which_revs):
    """Compute deltas for display in reverse log.

    Given a sequence of (revno, revision_id) pairs, return
    (revno, rev, delta).

    The delta is from the given revision to the next one in the
    sequence, which makes sense if the log is being displayed from
    newest to oldest.
    """
    from tree import EmptyTree
    from diff import compare_trees
    
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
    from tree import EmptyTree
    from diff import compare_trees

    last_revno = last_revision_id = last_tree = None
    prev_tree = EmptyTree(branch.get_root_id())

    for revno, revision_id in which_revs:
        this_tree = branch.revision_tree(revision_id)
        this_revision = branch.get_revision(revision_id)

        if not last_revno:
            if revno == 1:
                last_tree = EmptyTree()
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
    def __init__(self, to_file, show_ids=False, show_timezone=False):
        self.to_file = to_file
        self.show_ids = show_ids
        self.show_timezone = show_timezone
        





class LongLogFormatter(LogFormatter):
    def show(self, revno, rev, delta):
        from osutils import format_date

        to_file = self.to_file

        print >>to_file,  '-' * 60
        print >>to_file,  'revno:', revno
        if self.show_ids:
            print >>to_file,  'revision-id:', rev.revision_id
        print >>to_file,  'committer:', rev.committer
        print >>to_file,  'timestamp: %s' % (format_date(rev.timestamp, rev.timezone or 0,
                                             self.show_timezone))

        print >>to_file,  'message:'
        if not rev.message:
            print >>to_file,  '  (no message)'
        else:
            for l in rev.message.split('\n'):
                print >>to_file,  '  ' + l

        if delta != None:
            delta.show(to_file, self.show_ids)



class ShortLogFormatter(LogFormatter):
    def show(self, revno, rev, delta):
        from bzrlib.osutils import format_date

        to_file = self.to_file

        print >>to_file, "%5d %s\t%s" % (revno, rev.committer,
                format_date(rev.timestamp, rev.timezone or 0,
                            self.show_timezone))
        if self.show_ids:
            print >>to_file,  '      revision-id:', rev.revision_id
        if not rev.message:
            print >>to_file,  '      (no message)'
        else:
            for l in rev.message.split('\n'):
                print >>to_file,  '      ' + l

        if delta != None:
            delta.show(to_file, self.show_ids)
        print



FORMATTERS = {'long': LongLogFormatter,
              'short': ShortLogFormatter,
              }


def log_formatter(name, *args, **kwargs):
    from bzrlib.errors import BzrCommandError
    
    try:
        return FORMATTERS[name](*args, **kwargs)
    except IndexError:
        raise BzrCommandError("unknown log formatter: %r" % name)
