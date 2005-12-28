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

"""\
Routines for extracting all version information from a bzr branch.
"""

import sys
import time

from bzrlib.rio import RioReader, RioWriter, Stanza
from bzrlib.errors import NoWorkingTree
from errors import UncleanError

def is_clean(branch):
    """
    Raise an UncleanError if there is anything unclean about this
    branch.

    :param branch: The branch to check for changes
    TODO: jam 20051228 This might be better to ask for a WorkingTree
            instead of a Branch.
    """
    try:
        new_tree = branch.working_tree()
    except NoWorkingTree:
        # Trees without a working tree can't be dirty :)
        return 

    # Look for unknown files in the new tree
    for info in new_tree.list_files():
        path = info[0]
        file_class = info[1]
        if file_class == '?':
            raise UncleanError(branch, 'path %s is unknown' % (path,))

    from bzrlib.diff import compare_trees
    # See if there is anything that has been changed
    old_tree = branch.basis_tree()
    delta = compare_trees(old_tree, new_tree, want_unchanged=False)
    if len(delta.added) > 0:
        raise UncleanError(branch, 'have added files: %r' % (delta.added,))
    if len(delta.removed) > 0:
        raise UncleanError(branch, 'have removed files: %r' % (delta.removed,))
    if len(delta.modified) > 0:
        raise UncleanError(branch, 'have modified files: %r' % (delta.modified,))
    if len(delta.renamed) > 0:
        raise UncleanError(branch, 'have renamed files: %r' % (delta.renamed,))


def generate_rio_version(branch, to_file=sys.stdout,
        check_for_clean=False,
        include_revision_history=False,
        include_log_info=False,
        include_log_deltas=False):
    """Create the version file for this project.

    :param branch: The branch to write information about
    :param to_file: The file to write the information
    :param check_for_clean: If true, check if the branch is clean.
        This can be expensive for large trees. This is also only
        valid for branches with working trees.
    :param include_revision_history: Write out the list of revisions
    :param include_log_info: Include log information (log summary, etc),
        only valid if include_revision_history is also True
    :param include_log_deltas: Include information about what changed in
        each revision. Only valid if include_log_info is also True
    """
    info = Stanza()
    # TODO: jam 20051228 This might be better as the datestamp 
    #       of the last commit
    info.add('date', time.strftime('%Y-%m-%d %H:%M:%S (%A, %B %d, %Y, %Z)'))
    info.add('revno', branch.revno())
    info.add('revision_id', branch.last_revision())
    info.add('branch_nick', branch.nick)
    if check_for_clean:
        try:
            wt = branch.working_tree()
        except NoWorkingTree:
            pass
        else:
            pass
    info.update(_get_bzr_info(path=path, full=full))
    if info['branch_nick'] is not None:
        info['version'] = '%(branch_nick)s-%(revno)s' % info
    elif info['revno'] is not None:
        info['version'] = str(info['revno'])
    else:
        info['version'] = 'unknown'

    f = open(version_fn, 'wb')
    f.write(_version_template % info)
    f.close()

