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
             specific_fileid=None,
             show_timezone='original',
             verbose=False,
             show_ids=False,
             to_file=None,
             direction='reverse'):
    """Write out human-readable log of commits to this branch.

    specific_fileid
        If true, list only the commits affecting the specified
        file, rather than all commits.

    show_timezone
        'original' (committer's timezone),
        'utc' (universal time), or
        'local' (local user's timezone)

    verbose
        If true show added/changed/deleted/renamed files.

    show_ids
        If true, show revision and file ids.

    to_file
        File to send log to; by default stdout.

    direction
        'reverse' (default) is latest to earliest;
        'forward' is earliest to latest.
    """
    from osutils import format_date
    from errors import BzrCheckError
    from textui import show_status


    if specific_fileid:
        mutter('get log for file_id %r' % specific_fileid)

    if to_file == None:
        import sys
        to_file = sys.stdout

    which_revs = branch.enum_history(direction)

    if not (verbose or specific_fileid):
        # no need to know what changed between revisions
        with_deltas = deltas_for_log_dummy(branch, which_revs)
    elif direction == 'reverse':
        with_deltas = deltas_for_log_reverse(branch, which_revs)
    else:        
        raise NotImplementedError("sorry, verbose forward logs not done yet")

    for revno, rev, delta in with_deltas:
        if specific_fileid:
            if not delta.touches_file_id(specific_fileid):
                continue
        
        if not verbose:
            # although we calculated it, throw it away without display
            delta = None
            
        show_one_log(revno, rev, delta, show_ids, to_file, show_timezone)



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

        last_revno = revno
        last_revision = this_revision
        last_tree = this_tree

    if last_revno:
        this_tree = EmptyTree()
        yield last_revno, last_revision, compare_trees(this_tree, last_tree, False)



def junk():
    precursor = None
    if verbose:
        from tree import EmptyTree
        prev_tree = EmptyTree()
    for revno, revision_id in which_revs:
        precursor = revision_id

    if revision_id != rev.revision_id:
        raise BzrCheckError("retrieved wrong revision: %r"
                            % (revision_id, rev.revision_id))

    if verbose:
        this_tree = branch.revision_tree(revision_id)
        delta = compare_trees(prev_tree, this_tree, want_unchanged=False)
        prev_tree = this_tree
    else:
        delta = None    



def show_one_log(revno, rev, delta, show_ids, to_file, show_timezone):
    from osutils import format_date
    
    print >>to_file,  '-' * 60
    print >>to_file,  'revno:', revno
    if show_ids:
        print >>to_file,  'revision-id:', rev.revision_id
    print >>to_file,  'committer:', rev.committer
    print >>to_file,  'timestamp: %s' % (format_date(rev.timestamp, rev.timezone or 0,
                                         show_timezone))

    print >>to_file,  'message:'
    if not rev.message:
        print >>to_file,  '  (no message)'
    else:
        for l in rev.message.split('\n'):
            print >>to_file,  '  ' + l

    if delta != None:
        delta.show(to_file, show_ids)
