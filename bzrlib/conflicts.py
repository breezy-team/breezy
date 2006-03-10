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
from bzrlib.osutils import rename
from bzrlib.rio import Stanza


CONFLICT_SUFFIXES = ('.THIS', '.BASE', '.OTHER')


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
        from bzrlib.workingtree import WorkingTree
        from transform import conflicts_strings
        wt = WorkingTree.open_containing(u'.')[0]
        for conflict in conflicts_strings(wt.conflict_lines()):
            print conflict

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
        from bzrlib.workingtree import WorkingTree
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


def conflict_stanzas(conflicts):
    for conflict in conflicts:
        if conflict[0] in ('text conflict', 'path conflict', 
                           'contents conflict'):
            s = Stanza(type=conflict[0], path=conflict[2])
            if conflict[1] is not None:
                s.add('file_id', conflict[1]) 
            yield s
        else:
            mydict = {'type': conflict[0], 'action': conflict[1], 
                      'path': conflict[2]}
            if conflict[3] is not None:
                mydict['file_id'] = conflict[3]
            if len(conflict) > 4:
                mydict['conflict_path'] = conflict[4]
                if conflict[5] is not None:
                    mydict['conflict_file_id'] = conflict[5]
            yield Stanza(**mydict)

def stanza_conflicts(stanzas):
    for stanza in stanzas:
        try:
            file_id = stanza['file_id']
        except KeyError:
            file_id = None
        try:
            conflict_file_id = stanza['conflict_file_id']
        except KeyError:
            conflict_file_id = None
        if stanza.get('type') in ('text conflict', 'path conflict', 
                                  'contents conflict'):
            yield (stanza['type'], file_id, stanza['path'])
        else:
            my_list = [stanza['type'], stanza['action'],
                       stanza['path'], file_id]
            try:
                my_list.extend((stanza['conflict_path'], conflict_file_id))
            except KeyError:
                pass
            yield tuple(my_list) 
