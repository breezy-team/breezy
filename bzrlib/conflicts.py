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

import os
import errno

import bzrlib.status
from bzrlib.commands import register_command
from bzrlib.errors import BzrCommandError, NotConflicted
from bzrlib.option import Option
from bzrlib.workingtree import CONFLICT_SUFFIXES, WorkingTree
from bzrlib.osutils import rename

class cmd_conflicts(bzrlib.commands.Command):
    """List files with conflicts.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you should commit.

    Use bzr resolve when you have fixed a problem.

    (conflicts are determined by the presence of .BASE .TREE, and .OTHER 
    files.)

    See also bzr resolve.
    """
    def run(self):
        for path in WorkingTree.open_containing(u'.')[0].iter_conflicts():
            print path

class cmd_resolve(bzrlib.commands.Command):
    """Mark a conflict as resolved.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you should commit.

    Once you have fixed a problem, use "bzr resolve FILE.." to mark
    individual files as fixed, or "bzr resolve --all" to mark all conflicts as
    resolved.

    See also bzr conflicts.
    """
    aliases = ['resolved']
    takes_args = ['file*']
    takes_options = [Option('all', help='Resolve all conflicts in this tree')]
    def run(self, file_list=None, all=False):
        if file_list is None:
            if not all:
                raise BzrCommandError(
                    "command 'resolve' needs one or more FILE, or --all")
            tree = WorkingTree.open_containing(u'.')[0]
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

def restore(filename):
    """\
    Restore a conflicted file to the state it was in before merging.
    Only text restoration supported at present.
    """
    conflicted = False
    try:
        rename(filename + ".THIS", filename)
        conflicted = True
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
    try:
        os.unlink(filename + ".BASE")
        conflicted = True
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
    try:
        os.unlink(filename + ".OTHER")
        conflicted = True
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
    if not conflicted:
        raise NotConflicted(filename)
