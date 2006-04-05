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

import os
import errno

import bzrlib
from bzrlib.commands import register_command
from bzrlib.errors import BzrCommandError, NotConflicted, UnsupportedOperation
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
        wt = WorkingTree.open_containing(u'.')[0]
        for conflict in conflicts_to_strings(wt.conflict_lines()):
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
        else:
            if all:
                raise BzrCommandError(
                    "If --all is specified, no FILE may be provided")
        tree = WorkingTree.open_containing(u'.')[0]
        resolve(tree, file_list)


def resolve(tree, paths=None, ignore_misses=False):
    tree.lock_write()
    try:
        tree_conflicts = list(tree.conflict_lines())
        if paths is None:
            new_conflicts = []
            selected_conflicts = tree_conflicts
        else:
            new_conflicts, selected_conflicts = \
                select_conflicts(tree, paths, tree_conflicts, ignore_misses)
        try:
            tree.set_conflict_lines(new_conflicts)
        except UnsupportedOperation:
            pass
        remove_conflict_files(tree, selected_conflicts)
    finally:
        tree.unlock()


def select_conflicts(tree, paths, tree_conflicts, ignore_misses=False):
    path_set = set(paths)
    ids = {}
    selected_paths = set()
    new_conflicts = []
    selected_conflicts = []
    for path in paths:
        file_id = tree.path2id(path)
        if file_id is not None:
            ids[file_id] = path

    for conflict, stanza in zip(tree_conflicts, 
        conflicts_to_stanzas(tree_conflicts)):
        selected = False
        for key in ('path', 'conflict_path'):
            try:
                cpath = stanza[key]
            except KeyError:
                continue
            if cpath in path_set:
                selected = True
                selected_paths.add(cpath)
        for key in ('file_id', 'conflict_file_id'):
            try:
                cfile_id = stanza[key]
            except KeyError:
                continue
            try:
                cpath = ids[cfile_id]
            except KeyError:
                continue
            selected = True
            selected_paths.add(cpath)
        if selected:
            selected_conflicts.append(conflict)
        else:
            new_conflicts.append(conflict)
    if ignore_misses is not True:
        for path in [p for p in paths if p not in selected_paths]:
            if not os.path.exists(tree.abspath(path)):
                print "%s does not exist" % path
            else:
                print "%s is not conflicted" % path
    return new_conflicts, selected_conflicts

def remove_conflict_files(tree, conflicts):
    for stanza in conflicts_to_stanzas(conflicts):
        if stanza['type'] in ("text conflict", "contents conflict"):
            for suffix in CONFLICT_SUFFIXES:
                try:
                    os.unlink(tree.abspath(stanza['path']+suffix))
                except OSError, e:
                    if e.errno != errno.ENOENT:
                        raise
    

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


def conflicts_to_stanzas(conflicts):
    for conflict in conflicts:
        yield conflict.as_stanza()

def stanzas_to_conflicts(stanzas):
    for stanza in stanzas:
        yield Conflict.factory(**stanza.as_dict())


def conflicts_to_strings(conflicts):
    """Generate strings for the provided conflicts"""
    for conflict in conflicts:
        yield str(conflict)


class Conflict(object):
    """Base class for all types of conflict"""
    def __init__(self, path, file_id=None):
        self.path = path
        self.file_id = file_id

    def as_stanza(self):
        s = Stanza(type=self.typestring, path=self.path)
        if self.file_id is not None:
            s.add('file_id', self.file_id)
        return s

    def __cmp__(self, other):
        result = cmp(type(self), type(other))
        if result != 0:
            return result
        result = cmp(self.path, other.path)
        if result != 0:
            return result
        return cmp(self.file_id, other.file_id)

    def __eq__(self, other):
        return self.__cmp__(other) == 0

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.format % self.__dict__

    @staticmethod
    def factory(type, **kwargs):
        global ctype
        return ctype[type](**kwargs)


class PathConflict(Conflict):
    typestring = 'path conflict'
    format = 'Path conflict: %(path)s / %(conflict_path)s'
    def __init__(self, path, conflict_path=None, file_id=None):
        Conflict.__init__(self, path, file_id)
        self.conflict_path = conflict_path

    def as_stanza(self):
        s = Conflict.as_stanza(self)
        if self.conflict_path is not None:
            s.add('conflict_path', self.conflict_path)
        return s


class ContentsConflict(PathConflict):
    typestring = 'contents conflict'
    format = 'Contents conflict in %(path)s'


class TextConflict(PathConflict):
    typestring = 'text conflict'
    format = 'Text conflict in %(path)s'


class HandledConflict(Conflict):
    def __init__(self, action, path, file_id=None):
        Conflict.__init__(self, path, file_id)
        self.action = action

    def as_stanza(self):
        s = Conflict.as_stanza(self)
        s.add('action', self.action)
        return s


class HandledPathConflict(HandledConflict):
    def __init__(self, action, path, conflict_path, file_id=None,
                 conflict_file_id=None):
        HandledConflict.__init__(self, action, path, file_id)
        self.conflict_path = conflict_path 
        self.conflict_file_id = conflict_file_id
        
    def as_stanza(self):
        s = HandledConflict.as_stanza(self)
        s.add('conflict_path', self.conflict_path)
        if self.conflict_file_id is not None:
            s.add('conflict_file_id', self.conflict_file_id)
            
        return s


class DuplicateID(HandledPathConflict):
    typestring = 'duplicate id'
    format = 'Conflict adding id to %(conflict_path)s.  %(action)s %(path)s.'


class DuplicateEntry(HandledPathConflict):
    typestring = 'duplicate'
    format = 'Conflict adding file %(conflict_path)s.  %(action)s %(path)s.'


class ParentLoop(HandledPathConflict):
    typestring = 'parent loop'
    format = 'Conflict moving %(conflict_path)s into %(path)s.  %(action)s.'


class UnversionedParent(HandledConflict):
    typestring = 'unversioned parent'
    format = 'Conflict adding versioned files to %(path)s.  %(action)s.'


class MissingParent(HandledConflict):
    typestring = 'missing parent'
    format = 'Conflict adding files to %(path)s.  %(action)s.'



ctype = {}


def register_types(*conflict_types):
    """Register a Conflict subclass for serialization purposes"""
    global ctype
    for conflict_type in conflict_types:
        ctype[conflict_type.typestring] = conflict_type


register_types(ContentsConflict, TextConflict, PathConflict, DuplicateID,
               DuplicateEntry, ParentLoop, UnversionedParent, MissingParent,)
