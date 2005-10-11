# Copyright (C) 2005 by Aaron Bentley

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

# TODO: Move this into builtins

# TODO: 'bzr resolve' should accept a directory name and work from that 
# point down

# TODO: bzr revert should resolve; even when reverting the whole tree
# or particular directories

import bzrlib.status
from bzrlib.branch import Branch
from bzrlib.errors import BzrCommandError
from bzrlib.commands import register_command
from bzrlib.workingtree import CONFLICT_SUFFIXES
import os
import errno

class cmd_conflicts(bzrlib.commands.Command):
    """List files with conflicts.
    (conflicts are determined by the presence of .BASE .TREE, and .OTHER 
    files.)
    """
    def run(self):
        for path in Branch.open_containing('.').working_tree().iter_conflicts():
            print path

register_command(cmd_conflicts)

class cmd_resolve(bzrlib.commands.Command):
    """Mark a conflict as resolved.
    """
    takes_args = ['file*']
    takes_options = ['all']
    def run(self, file_list=None, all=False):
        if file_list is None:
            if not all:
                raise BzrCommandError(
                    "command 'resolve' needs one or more FILE, or --all")
            tree = Branch.open_containing('.').working_tree()
            file_list = list(tree.abspath(f) for f in tree.iter_conflicts())
        else:
            if all:
                raise BzrCommandError(
                    "If --all is specified, no FILE may be provided")
        for filename in file_list:
            failures = 0
            for suffix in CONFLICT_SUFFIXES:
                try:
                    os.unlink(filename+suffix)
                except OSError, e:
                    if e.errno != errno.ENOENT:
                        raise
                    else:
                        failures += 1
            if failures == len(CONFLICT_SUFFIXES):
                if not os.path.exists(filename):
                    print "%s does not exist" % filename
                else:
                    print "%s is not conflicted" % filename
                        
register_command(cmd_resolve)
