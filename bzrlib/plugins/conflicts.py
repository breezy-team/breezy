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

import bzrlib.status
from bzrlib.branch import Branch
from bzrlib.errors import BzrCommandError
from bzrlib.commands import register_command
import os
import errno

SUFFIXES = ('.THIS', '.BASE', '.OTHER')
def get_conflicted_stem(path):
    for suffix in SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)]

def iter_conflicts(tree):
    conflicted = set()
    for path in (s[0] for s in tree.list_files()):
        stem = get_conflicted_stem(path)
        if stem is None:
            continue
        if stem not in conflicted:
            conflicted.add(stem)
            yield stem

class cmd_conflicts(bzrlib.commands.Command):
    """List files with conflicts.
    (conflicts are determined by the presence of .BASE .TREE, and .OTHER 
    files.)
    """
    def run(self):
        for path in iter_conflicts(Branch.open_containing('.').working_tree()):
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
            file_list = list(iter_conflicts(tree))
        else:
            if all:
                raise BzrCommandError(
                    "If --all is specified, no FILE may be provided")
        for filename in file_list:
            failures = 0
            for suffix in SUFFIXES:
                try:
                    os.unlink(filename+suffix)
                except OSError, e:
                    if e.errno != errno.ENOENT:
                        raise
                    else:
                        failures += 1
            if failures == len(SUFFIXES):
                if not os.path.exists(filename):
                    print "%s does not exist" % filename
                else:
                    print "%s is not conflicted" % filename
                        
register_command(cmd_resolve)

# monkey-patch the standard 'status' to give us conflicts, too.
def _show_status(branch, **kwargs):
    old_show_status(branch, **kwargs)
    conflicted = list(iter_conflicts(branch.working_tree()))
    if len(conflicted) > 0:
        print "conflicts:"
        for f in conflicted:
            print " ", f

old_show_status = bzrlib.status.show_status
bzrlib.status.show_status = _show_status 
