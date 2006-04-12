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
        for conflict in wt.conflicts():
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
        if all:
            if file_list:
                raise BzrCommandError("If --all is specified, no FILE may be provided")
            tree = WorkingTree.open_containing('.')[0]
            resolve(tree)
        else:
            if file_list is None:
                raise BzrCommandError("command 'resolve' needs one or more FILE, or --all")
            tree = WorkingTree.open_containing(file_list[0])[0]
            to_resolve = [tree.relpath(p) for p in file_list]
            resolve(tree, to_resolve)


def resolve(tree, paths=None, ignore_misses=False):
    tree.lock_write()
    try:
        tree_conflicts = tree.conflicts()
        if paths is None:
            new_conflicts = ConflictList()
            selected_conflicts = tree_conflicts
        else:
            new_conflicts, selected_conflicts = \
                tree_conflicts.select_conflicts(tree, paths, ignore_misses)
        try:
            tree.set_conflicts(new_conflicts)
        except UnsupportedOperation:
            pass
        selected_conflicts.remove_files(tree)
    finally:
        tree.unlock()


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


class ConflictList(object):
    """List of conflicts.

    Typically obtained from WorkingTree.conflicts()

    Can be instantiated from stanzas or from Conflict subclasses.
    """

    def __init__(self, conflicts=None):
        object.__init__(self)
        if conflicts is None:
            self.__list = []
        else:
            self.__list = conflicts

    def is_empty(self):
        return len(self.__list) == 0

    def __len__(self):
        return len(self.__list)

    def __iter__(self):
        return iter(self.__list)

    def __getitem__(self, key):
        return self.__list[key]

    def append(self, conflict):
        return self.__list.append(conflict)

    def __eq__(self, other_list):
        return list(self) == list(other_list)

    def __ne__(self, other_list):
        return not (self == other_list)

    def __repr__(self):
        return "ConflictList(%r)" % self.__list

    @staticmethod
    def from_stanzas(stanzas):
        """Produce a new ConflictList from an iterable of stanzas"""
        conflicts = ConflictList()
        for stanza in stanzas:
            conflicts.append(Conflict.factory(**stanza.as_dict()))
        return conflicts

    def to_stanzas(self):
        """Generator of stanzas"""
        for conflict in self:
            yield conflict.as_stanza()
            
    def to_strings(self):
        """Generate strings for the provided conflicts"""
        for conflict in self:
            yield str(conflict)

    def remove_files(self, tree):
        """Remove the THIS, BASE and OTHER files for listed conflicts"""
        for conflict in self:
            if not conflict.has_files:
                continue
            for suffix in CONFLICT_SUFFIXES:
                try:
                    os.unlink(tree.abspath(conflict.path+suffix))
                except OSError, e:
                    if e.errno != errno.ENOENT:
                        raise

    def select_conflicts(self, tree, paths, ignore_misses=False):
        """Select the conflicts associated with paths in a tree.
        
        File-ids are also used for this.
        """
        path_set = set(paths)
        ids = {}
        selected_paths = set()
        new_conflicts = ConflictList()
        selected_conflicts = ConflictList()
        for path in paths:
            file_id = tree.path2id(path)
            if file_id is not None:
                ids[file_id] = path

        for conflict in self:
            selected = False
            for key in ('path', 'conflict_path'):
                cpath = getattr(conflict, key, None)
                if cpath is None:
                    continue
                if cpath in path_set:
                    selected = True
                    selected_paths.add(cpath)
            for key in ('file_id', 'conflict_file_id'):
                cfile_id = getattr(conflict, key, None)
                if cfile_id is None:
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

 
class Conflict(object):
    """Base class for all types of conflict"""

    has_files = False

    def __init__(self, path, file_id=None):
        self.path = path
        self.file_id = file_id

    def as_stanza(self):
        s = Stanza(type=self.typestring, path=self.path)
        if self.file_id is not None:
            s.add('file_id', self.file_id)
        return s

    def _cmp_list(self):
        return [type(self), self.path, self.file_id]

    def __cmp__(self, other):
        if getattr(other, "_cmp_list", None) is None:
            return -1
        return cmp(self._cmp_list(), other._cmp_list())

    def __eq__(self, other):
        return self.__cmp__(other) == 0

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.format % self.__dict__

    def __repr__(self):
        rdict = dict(self.__dict__)
        rdict['class'] = self.__class__.__name__
        return self.rformat % rdict

    @staticmethod
    def factory(type, **kwargs):
        global ctype
        return ctype[type](**kwargs)


class PathConflict(Conflict):
    """A conflict was encountered merging file paths"""

    typestring = 'path conflict'

    format = 'Path conflict: %(path)s / %(conflict_path)s'

    rformat = '%(class)s(%(path)r, %(conflict_path)r, %(file_id)r)'
    def __init__(self, path, conflict_path=None, file_id=None):
        Conflict.__init__(self, path, file_id)
        self.conflict_path = conflict_path

    def as_stanza(self):
        s = Conflict.as_stanza(self)
        if self.conflict_path is not None:
            s.add('conflict_path', self.conflict_path)
        return s


class ContentsConflict(PathConflict):
    """The files are of different types, or not present"""

    has_files = True

    typestring = 'contents conflict'

    format = 'Contents conflict in %(path)s'


class TextConflict(PathConflict):
    """The merge algorithm could not resolve all differences encountered."""

    has_files = True

    typestring = 'text conflict'

    format = 'Text conflict in %(path)s'


class HandledConflict(Conflict):
    """A path problem that has been provisionally resolved.
    This is intended to be a base class.
    """

    rformat = "%(class)s(%(action)r, %(path)r, %(file_id)r)"
    
    def __init__(self, action, path, file_id=None):
        Conflict.__init__(self, path, file_id)
        self.action = action

    def _cmp_list(self):
        return Conflict._cmp_list(self) + [self.action]

    def as_stanza(self):
        s = Conflict.as_stanza(self)
        s.add('action', self.action)
        return s


class HandledPathConflict(HandledConflict):
    """A provisionally-resolved path problem involving two paths.
    This is intended to be a base class.
    """

    rformat = "%(class)s(%(action)r, %(path)r, %(conflict_path)r,"\
        " %(file_id)r, %(conflict_file_id)r)"

    def __init__(self, action, path, conflict_path, file_id=None,
                 conflict_file_id=None):
        HandledConflict.__init__(self, action, path, file_id)
        self.conflict_path = conflict_path 
        self.conflict_file_id = conflict_file_id
        
    def _cmp_list(self):
        return HandledConflict._cmp_list(self) + [self.conflict_path, 
                                                  self.conflict_file_id]

    def as_stanza(self):
        s = HandledConflict.as_stanza(self)
        s.add('conflict_path', self.conflict_path)
        if self.conflict_file_id is not None:
            s.add('conflict_file_id', self.conflict_file_id)
            
        return s


class DuplicateID(HandledPathConflict):
    """Two files want the same file_id."""

    typestring = 'duplicate id'

    format = 'Conflict adding id to %(conflict_path)s.  %(action)s %(path)s.'


class DuplicateEntry(HandledPathConflict):
    """Two directory entries want to have the same name."""

    typestring = 'duplicate'

    format = 'Conflict adding file %(conflict_path)s.  %(action)s %(path)s.'


class ParentLoop(HandledPathConflict):
    """An attempt to create an infinitely-looping directory structure.
    This is rare, but can be produced like so:

    tree A:
      mv foo/bar
    tree B:
      mv bar/foo
    merge A and B
    """

    typestring = 'parent loop'

    format = 'Conflict moving %(conflict_path)s into %(path)s.  %(action)s.'


class UnversionedParent(HandledConflict):
    """An attempt to version an file whose parent directory is not versioned.
    Typically, the result of a merge where one tree unversioned the directory
    and the other added a versioned file to it.
    """

    typestring = 'unversioned parent'

    format = 'Conflict adding versioned files to %(path)s.  %(action)s.'


class MissingParent(HandledConflict):
    """An attempt to add files to a directory that is not present.
    Typically, the result of a merge where one tree deleted the directory and
    the other added a file to it.
    """

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
