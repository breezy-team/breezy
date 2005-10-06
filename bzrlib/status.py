# (C) 2005 Canonical Ltd

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



def show_status(branch, show_unchanged=False,
                specific_files=None,
                show_ids=False,
                to_file=None,
                show_pending=True,
                revision=None):
    """Display status for non-ignored working files.

    show_unchanged
        If set, includes unchanged files.

    specific_files
        If set, only show the status of files in this list.

    show_ids
        If set, includes each file's id.

    to_file
        If set, write to this file (default stdout.)

    show_pending
        If set, write pending merges.

    revision
        If None the compare latest revision with working tree
        If one revision show compared it with working tree.
        If two revisions show status between first and second.
    """
    import sys
    from bzrlib.osutils import is_inside_any
    from bzrlib.delta import compare_trees

    if to_file == None:
        to_file = sys.stdout
    
    branch.lock_read()
    try:
        new_is_working_tree = True
        if revision is None:
            old = branch.basis_tree()
            new = branch.working_tree()
        elif len(revision) > 0:
            try:
                rev_id = revision[0].in_history(branch).rev_id
                old = branch.revision_tree(rev_id)
            except NoSuchRevision, e:
                raise BzrCommandError(str(e))
            if len(revision) > 1:
                try:
                    rev_id = revision[1].in_history(branch).rev_id
                    new = branch.revision_tree(rev_id)
                    new_is_working_tree = False
                except NoSuchRevision, e:
                    raise BzrCommandError(str(e))
            else:
                new = branch.working_tree()
                

        delta = compare_trees(old, new, want_unchanged=show_unchanged,
                              specific_files=specific_files)

        delta.show(to_file,
                   show_ids=show_ids,
                   show_unchanged=show_unchanged)

        if new_is_working_tree:
            conflicts = new.iter_conflicts()
            unknowns = new.unknowns()
            list_paths('unknown', unknowns, specific_files, to_file)
            list_paths('conflicts', conflicts, specific_files, to_file)
            if show_pending and len(branch.pending_merges()) > 0:
                print >>to_file, 'pending merges:'
                for merge in branch.pending_merges():
                    print >> to_file, ' ', merge
    finally:
        branch.unlock()
        
def list_paths(header, paths, specific_files, to_file):
    done_header = False
    for path in paths:
        if specific_files and not is_inside_any(specific_files, path):
            continue
        if not done_header:
            print >>to_file, '%s:' % header
            done_header = True
        print >>to_file, ' ', path
