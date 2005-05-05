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




def find_touching_revisions(branch, file_id):
    """Yield a description of revisions which affect the file_id.

    Each returned element is (revno, revision_id, description)

    This is the list of revisions where the file is either added,
    modified, renamed or deleted.

    Revisions are returned in chronological order.

    TODO: Perhaps some way to limit this to only particular revisions,
    or to traverse a non-branch set of revisions?

    TODO: If a directory is given, then by default look for all
    changes under that directory.
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
             filename=None,
             show_timezone='original',
             verbose=False,
             show_ids=False,
             to_file=None):
    """Write out human-readable log of commits to this branch.

    filename
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
    """
    from osutils import format_date
    from errors import BzrCheckError
    from diff import compare_inventories
    from textui import show_status
    from inventory import Inventory

    if to_file == None:
        import sys
        to_file = sys.stdout

    if filename:
        file_id = branch.read_working_inventory().path2id(filename)
        def which_revs():
            for revno, revid, why in find_touching_revisions(branch, file_id):
                yield revno, revid
    else:
        def which_revs():
            for i, revid in enumerate(branch.revision_history()):
                yield i+1, revid
        
    branch._need_readlock()
    precursor = None
    if verbose:
        prev_inv = Inventory()
    for revno, revision_id in which_revs():
        print >>to_file,  '-' * 60
        print >>to_file,  'revno:', revno
        rev = branch.get_revision(revision_id)
        if show_ids:
            print >>to_file,  'revision-id:', revision_id
        print >>to_file,  'committer:', rev.committer
        print >>to_file,  'timestamp: %s' % (format_date(rev.timestamp, rev.timezone or 0,
                                             show_timezone))

        if revision_id != rev.revision_id:
            raise BzrCheckError("retrieved wrong revision: %r"
                                % (revision_id, rev.revision_id))

        print >>to_file,  'message:'
        if not rev.message:
            print >>to_file,  '  (no message)'
        else:
            for l in rev.message.split('\n'):
                print >>to_file,  '  ' + l

        # Don't show a list of changed files if we were asked about
        # one specific file.

        if verbose and not filename:
            this_inv = branch.get_inventory(rev.inventory_id)
            delta = compare_inventories(prev_inv, this_inv)

            if delta.removed:
                print >>to_file, 'removed files:'
                for path, fid in delta.removed:
                    if show_ids:
                        print >>to_file, '  %-30s %s' % (path, fid)
                    else:
                        print >>to_file, ' ', path
            if delta.added:
                print >>to_file, 'added files:'
                for path, fid in delta.added:
                    if show_ids:
                        print >>to_file, '  %-30s %s' % (path, fid)
                    else:
                        print >>to_file, '  ' + path
            if delta.renamed:
                print >>to_file, 'renamed files:'
                for oldpath, newpath, fid in delta.renamed:
                    if show_ids:
                        print >>to_file, '  %s => %s %s' % (oldpath, newpath, fid)
                    else:
                        print >>to_file, '  %s => %s' % (oldpath, newpath)
            if delta.modified:
                print >>to_file, 'modified files:'
                for path, fid in delta.modified:
                    if show_ids:
                        print >>to_file, '  %-30s %s' % (path, fid)
                    else:
                        print >>to_file, '  ' + path

            prev_inv = this_inv

        precursor = revision_id

