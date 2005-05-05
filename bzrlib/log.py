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

def show_log(branch, show_timezone='original', verbose=False,
             show_ids=False,
             to_file=None):
    """Write out human-readable log of commits to this branch.

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
    from diff import diff_trees
    from textui import show_status

    if to_file == None:
        import sys
        to_file = sys.stdout
        
    branch._need_readlock()
    revno = 1
    precursor = None
    for revision_id in branch.revision_history():
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

        ## opportunistic consistency check, same as check_patch_chaining
        if rev.precursor != precursor:
            raise BzrCheckError("mismatched precursor!")

        print >>to_file,  'message:'
        if not rev.message:
            print >>to_file,  '  (no message)'
        else:
            for l in rev.message.split('\n'):
                print >>to_file,  '  ' + l

        if verbose and precursor:
            # TODO: Group as added/deleted/renamed instead
            # TODO: Show file ids
            print >>to_file, 'changed files:'
            tree = branch.revision_tree(revision_id)
            prevtree = branch.revision_tree(precursor)

            for file_state, fid, old_name, new_name, kind in \
                                    diff_trees(prevtree, tree, ):
                if file_state == 'A' or file_state == 'M':
                    show_status(file_state, kind, new_name)
                elif file_state == 'D':
                    show_status(file_state, kind, old_name)
                elif file_state == 'R':
                    show_status(file_state, kind,
                        old_name + ' => ' + new_name)

        revno += 1
        precursor = revision_id
