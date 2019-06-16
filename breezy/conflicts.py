# Copyright (C) 2005, 2006, 2007, 2009, 2010, 2011 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# TODO: 'brz resolve' should accept a directory name and work from that
# point down

from __future__ import absolute_import

import os
import re

from .lazy_import import lazy_import
lazy_import(globals(), """
import errno

from breezy import (
    cleanup,
    errors,
    osutils,
    rio,
    trace,
    transform,
    workingtree,
    )
from breezy.i18n import gettext, ngettext
""")
from . import (
    cache_utf8,
    commands,
    option,
    registry,
    )
from .sixish import text_type


CONFLICT_SUFFIXES = ('.THIS', '.BASE', '.OTHER')


class cmd_conflicts(commands.Command):
    __doc__ = """List files with conflicts.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you can commit.

    Conflicts normally are listed as short, human-readable messages.  If --text
    is supplied, the pathnames of files with text conflicts are listed,
    instead.  (This is useful for editing all files with text conflicts.)

    Use brz resolve when you have fixed a problem.
    """
    takes_options = [
        'directory',
        option.Option('text',
                      help='List paths of files with text conflicts.'),
        ]
    _see_also = ['resolve', 'conflict-types']

    def run(self, text=False, directory=u'.'):
        wt = workingtree.WorkingTree.open_containing(directory)[0]
        for conflict in wt.conflicts():
            if text:
                if conflict.typestring != 'text conflict':
                    continue
                self.outf.write(conflict.path + '\n')
            else:
                self.outf.write(text_type(conflict) + '\n')


resolve_action_registry = registry.Registry()


resolve_action_registry.register(
    'auto', 'auto', 'Detect whether conflict has been resolved by user.')
resolve_action_registry.register(
    'done', 'done', 'Marks the conflict as resolved.')
resolve_action_registry.register(
    'take-this', 'take_this',
    'Resolve the conflict preserving the version in the working tree.')
resolve_action_registry.register(
    'take-other', 'take_other',
    'Resolve the conflict taking the merged version into account.')
resolve_action_registry.default_key = 'done'


class ResolveActionOption(option.RegistryOption):

    def __init__(self):
        super(ResolveActionOption, self).__init__(
            'action', 'How to resolve the conflict.',
            value_switches=True,
            registry=resolve_action_registry)


class cmd_resolve(commands.Command):
    __doc__ = """Mark a conflict as resolved.

    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you can commit.

    Once you have fixed a problem, use "brz resolve" to automatically mark
    text conflicts as fixed, "brz resolve FILE" to mark a specific conflict as
    resolved, or "brz resolve --all" to mark all conflicts as resolved.
    """
    aliases = ['resolved']
    takes_args = ['file*']
    takes_options = [
        'directory',
        option.Option('all', help='Resolve all conflicts in this tree.'),
        ResolveActionOption(),
        ]
    _see_also = ['conflicts']

    def run(self, file_list=None, all=False, action=None, directory=None):
        if all:
            if file_list:
                raise errors.BzrCommandError(gettext("If --all is specified,"
                                                     " no FILE may be provided"))
            if directory is None:
                directory = u'.'
            tree = workingtree.WorkingTree.open_containing(directory)[0]
            if action is None:
                action = 'done'
        else:
            tree, file_list = workingtree.WorkingTree.open_containing_paths(
                file_list, directory)
            if action is None:
                if file_list is None:
                    action = 'auto'
                else:
                    action = 'done'
        before, after = resolve(tree, file_list, action=action)
        # GZ 2012-07-27: Should unify UI below now that auto is less magical.
        if action == 'auto' and file_list is None:
            if after > 0:
                trace.note(
                    ngettext('%d conflict auto-resolved.',
                             '%d conflicts auto-resolved.', before - after),
                    before - after)
                trace.note(gettext('Remaining conflicts:'))
                for conflict in tree.conflicts():
                    trace.note(text_type(conflict))
                return 1
            else:
                trace.note(gettext('All conflicts resolved.'))
                return 0
        else:
            trace.note(ngettext('{0} conflict resolved, {1} remaining',
                                '{0} conflicts resolved, {1} remaining',
                                before - after).format(before - after, after))


def resolve(tree, paths=None, ignore_misses=False, recursive=False,
            action='done'):
    """Resolve some or all of the conflicts in a working tree.

    :param paths: If None, resolve all conflicts.  Otherwise, select only
        specified conflicts.
    :param recursive: If True, then elements of paths which are directories
        have all their children resolved, etc.  When invoked as part of
        recursive commands like revert, this should be True.  For commands
        or applications wishing finer-grained control, like the resolve
        command, this should be False.
    :param ignore_misses: If False, warnings will be printed if the supplied
        paths do not have conflicts.
    :param action: How the conflict should be resolved,
    """
    nb_conflicts_after = None
    with tree.lock_tree_write():
        tree_conflicts = tree.conflicts()
        nb_conflicts_before = len(tree_conflicts)
        if paths is None:
            new_conflicts = ConflictList()
            to_process = tree_conflicts
        else:
            new_conflicts, to_process = tree_conflicts.select_conflicts(
                tree, paths, ignore_misses, recursive)
        for conflict in to_process:
            try:
                conflict._do(action, tree)
                conflict.cleanup(tree)
            except NotImplementedError:
                new_conflicts.append(conflict)
        try:
            nb_conflicts_after = len(new_conflicts)
            tree.set_conflicts(new_conflicts)
        except errors.UnsupportedOperation:
            pass
    if nb_conflicts_after is None:
        nb_conflicts_after = nb_conflicts_before
    return nb_conflicts_before, nb_conflicts_after


def restore(filename):
    """Restore a conflicted file to the state it was in before merging.

    Only text restoration is supported at present.
    """
    conflicted = False
    try:
        osutils.rename(filename + ".THIS", filename)
        conflicted = True
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    try:
        os.unlink(filename + ".BASE")
        conflicted = True
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    try:
        os.unlink(filename + ".OTHER")
        conflicted = True
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    if not conflicted:
        raise errors.NotConflicted(filename)


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
            yield text_type(conflict)

    def remove_files(self, tree):
        """Remove the THIS, BASE and OTHER files for listed conflicts"""
        for conflict in self:
            if not conflict.has_files:
                continue
            conflict.cleanup(tree)

    def select_conflicts(self, tree, paths, ignore_misses=False,
                         recurse=False):
        """Select the conflicts associated with paths in a tree.

        File-ids are also used for this.
        :return: a pair of ConflictLists: (not_selected, selected)
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
                if recurse:
                    if osutils.is_inside_any(path_set, cpath):
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
                    print("%s does not exist" % path)
                else:
                    print("%s is not conflicted" % path)
        return new_conflicts, selected_conflicts


class Conflict(object):
    """Base class for all types of conflict"""

    # FIXME: cleanup should take care of that ? -- vila 091229
    has_files = False

    def __init__(self, path, file_id=None):
        self.path = path
        # the factory blindly transfers the Stanza values to __init__ and
        # Stanza is purely a Unicode api.
        if isinstance(file_id, text_type):
            file_id = cache_utf8.encode(file_id)
        self.file_id = osutils.safe_file_id(file_id)

    def as_stanza(self):
        s = rio.Stanza(type=self.typestring, path=self.path)
        if self.file_id is not None:
            # Stanza requires Unicode apis
            s.add('file_id', self.file_id.decode('utf8'))
        return s

    def _cmp_list(self):
        return [type(self), self.path, self.file_id]

    def __cmp__(self, other):
        if getattr(other, "_cmp_list", None) is None:
            return -1
        x = self._cmp_list()
        y = other._cmp_list()
        return (x > y) - (x < y)

    def __hash__(self):
        return hash((type(self), self.path, self.file_id))

    def __eq__(self, other):
        return self.__cmp__(other) == 0

    def __ne__(self, other):
        return not self.__eq__(other)

    def __unicode__(self):
        return self.describe()

    def __str__(self):
        return self.describe()

    def describe(self):
        return self.format % self.__dict__

    def __repr__(self):
        rdict = dict(self.__dict__)
        rdict['class'] = self.__class__.__name__
        return self.rformat % rdict

    @staticmethod
    def factory(type, **kwargs):
        global ctype
        return ctype[type](**kwargs)

    @staticmethod
    def sort_key(conflict):
        if conflict.path is not None:
            return conflict.path, conflict.typestring
        elif getattr(conflict, "conflict_path", None) is not None:
            return conflict.conflict_path, conflict.typestring
        else:
            return None, conflict.typestring

    def _do(self, action, tree):
        """Apply the specified action to the conflict.

        :param action: The method name to call.

        :param tree: The tree passed as a parameter to the method.
        """
        meth = getattr(self, 'action_%s' % action, None)
        if meth is None:
            raise NotImplementedError(self.__class__.__name__ + '.' + action)
        meth(tree)

    def associated_filenames(self):
        """The names of the files generated to help resolve the conflict."""
        raise NotImplementedError(self.associated_filenames)

    def cleanup(self, tree):
        for fname in self.associated_filenames():
            try:
                osutils.delete_any(tree.abspath(fname))
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

    def action_auto(self, tree):
        raise NotImplementedError(self.action_auto)

    def action_done(self, tree):
        """Mark the conflict as solved once it has been handled."""
        # This method does nothing but simplifies the design of upper levels.
        pass

    def action_take_this(self, tree):
        raise NotImplementedError(self.action_take_this)

    def action_take_other(self, tree):
        raise NotImplementedError(self.action_take_other)

    def _resolve_with_cleanups(self, tree, *args, **kwargs):
        tt = transform.TreeTransform(tree)
        op = cleanup.OperationWithCleanups(self._resolve)
        op.add_cleanup(tt.finalize)
        op.run_simple(tt, *args, **kwargs)


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

    def associated_filenames(self):
        # No additional files have been generated here
        return []

    def _resolve(self, tt, file_id, path, winner):
        """Resolve the conflict.

        :param tt: The TreeTransform where the conflict is resolved.
        :param file_id: The retained file id.
        :param path: The retained path.
        :param winner: 'this' or 'other' indicates which side is the winner.
        """
        path_to_create = None
        if winner == 'this':
            if self.path == '<deleted>':
                return  # Nothing to do
            if self.conflict_path == '<deleted>':
                path_to_create = self.path
                revid = tt._tree.get_parent_ids()[0]
        elif winner == 'other':
            if self.conflict_path == '<deleted>':
                return  # Nothing to do
            if self.path == '<deleted>':
                path_to_create = self.conflict_path
                # FIXME: If there are more than two parents we may need to
                # iterate. Taking the last parent is the safer bet in the mean
                # time. -- vila 20100309
                revid = tt._tree.get_parent_ids()[-1]
        else:
            # Programmer error
            raise AssertionError('bad winner: %r' % (winner,))
        if path_to_create is not None:
            tid = tt.trans_id_tree_path(path_to_create)
            tree = self._revision_tree(tt._tree, revid)
            transform.create_from_tree(
                tt, tid, tree, tree.id2path(file_id), file_id=file_id)
            tt.version_file(file_id, tid)
        else:
            tid = tt.trans_id_file_id(file_id)
        # Adjust the path for the retained file id
        parent_tid = tt.get_tree_parent(tid)
        tt.adjust_path(osutils.basename(path), parent_tid, tid)
        tt.apply()

    def _revision_tree(self, tree, revid):
        return tree.branch.repository.revision_tree(revid)

    def _infer_file_id(self, tree):
        # Prior to bug #531967, file_id wasn't always set, there may still be
        # conflict files in the wild so we need to cope with them
        # Establish which path we should use to find back the file-id
        possible_paths = []
        for p in (self.path, self.conflict_path):
            if p == '<deleted>':
                # special hard-coded path
                continue
            if p is not None:
                possible_paths.append(p)
        # Search the file-id in the parents with any path available
        file_id = None
        for revid in tree.get_parent_ids():
            revtree = self._revision_tree(tree, revid)
            for p in possible_paths:
                file_id = revtree.path2id(p)
                if file_id is not None:
                    return revtree, file_id
        return None, None

    def action_take_this(self, tree):
        if self.file_id is not None:
            self._resolve_with_cleanups(tree, self.file_id, self.path,
                                        winner='this')
        else:
            # Prior to bug #531967 we need to find back the file_id and restore
            # the content from there
            revtree, file_id = self._infer_file_id(tree)
            tree.revert([revtree.id2path(file_id)],
                        old_tree=revtree, backups=False)

    def action_take_other(self, tree):
        if self.file_id is not None:
            self._resolve_with_cleanups(tree, self.file_id,
                                        self.conflict_path,
                                        winner='other')
        else:
            # Prior to bug #531967 we need to find back the file_id and restore
            # the content from there
            revtree, file_id = self._infer_file_id(tree)
            tree.revert([revtree.id2path(file_id)],
                        old_tree=revtree, backups=False)


class ContentsConflict(PathConflict):
    """The files are of different types (or both binary), or not present"""

    has_files = True

    typestring = 'contents conflict'

    format = 'Contents conflict in %(path)s'

    def associated_filenames(self):
        return [self.path + suffix for suffix in ('.BASE', '.OTHER')]

    def _resolve(self, tt, suffix_to_remove):
        """Resolve the conflict.

        :param tt: The TreeTransform where the conflict is resolved.
        :param suffix_to_remove: Either 'THIS' or 'OTHER'

        The resolution is symmetric: when taking THIS, OTHER is deleted and
        item.THIS is renamed into item and vice-versa.
        """
        try:
            # Delete 'item.THIS' or 'item.OTHER' depending on
            # suffix_to_remove
            tt.delete_contents(
                tt.trans_id_tree_path(self.path + '.' + suffix_to_remove))
        except errors.NoSuchFile:
            # There are valid cases where 'item.suffix_to_remove' either
            # never existed or was already deleted (including the case
            # where the user deleted it)
            pass
        try:
            this_path = tt._tree.id2path(self.file_id)
        except errors.NoSuchId:
            # The file is not present anymore. This may happen if the user
            # deleted the file either manually or when resolving a conflict on
            # the parent.  We may raise some exception to indicate that the
            # conflict doesn't exist anymore and as such doesn't need to be
            # resolved ? -- vila 20110615
            this_tid = None
        else:
            this_tid = tt.trans_id_tree_path(this_path)
        if this_tid is not None:
            # Rename 'item.suffix_to_remove' (note that if
            # 'item.suffix_to_remove' has been deleted, this is a no-op)
            parent_tid = tt.get_tree_parent(this_tid)
            tt.adjust_path(osutils.basename(self.path), parent_tid, this_tid)
            tt.apply()

    def action_take_this(self, tree):
        self._resolve_with_cleanups(tree, 'OTHER')

    def action_take_other(self, tree):
        self._resolve_with_cleanups(tree, 'THIS')


# TODO: There should be a base revid attribute to better inform the user about
# how the conflicts were generated.
class TextConflict(Conflict):
    """The merge algorithm could not resolve all differences encountered."""

    has_files = True

    typestring = 'text conflict'

    format = 'Text conflict in %(path)s'

    rformat = '%(class)s(%(path)r, %(file_id)r)'

    _conflict_re = re.compile(b'^(<{7}|={7}|>{7})')

    def associated_filenames(self):
        return [self.path + suffix for suffix in CONFLICT_SUFFIXES]

    def _resolve(self, tt, winner_suffix):
        """Resolve the conflict by copying one of .THIS or .OTHER into file.

        :param tt: The TreeTransform where the conflict is resolved.
        :param winner_suffix: Either 'THIS' or 'OTHER'

        The resolution is symmetric, when taking THIS, item.THIS is renamed
        into item and vice-versa. This takes one of the files as a whole
        ignoring every difference that could have been merged cleanly.
        """
        # To avoid useless copies, we switch item and item.winner_suffix, only
        # item will exist after the conflict has been resolved anyway.
        item_tid = tt.trans_id_file_id(self.file_id)
        item_parent_tid = tt.get_tree_parent(item_tid)
        winner_path = self.path + '.' + winner_suffix
        winner_tid = tt.trans_id_tree_path(winner_path)
        winner_parent_tid = tt.get_tree_parent(winner_tid)
        # Switch the paths to preserve the content
        tt.adjust_path(osutils.basename(self.path),
                       winner_parent_tid, winner_tid)
        tt.adjust_path(osutils.basename(winner_path),
                       item_parent_tid, item_tid)
        # Associate the file_id to the right content
        tt.unversion_file(item_tid)
        tt.version_file(self.file_id, winner_tid)
        tt.apply()

    def action_auto(self, tree):
        # GZ 2012-07-27: Using NotImplementedError to signal that a conflict
        #                can't be auto resolved does not seem ideal.
        try:
            kind = tree.kind(self.path)
        except errors.NoSuchFile:
            return
        if kind != 'file':
            raise NotImplementedError("Conflict is not a file")
        conflict_markers_in_line = self._conflict_re.search
        # GZ 2012-07-27: What if not tree.has_id(self.file_id) due to removal?
        with tree.get_file(self.path) as f:
            for line in f:
                if conflict_markers_in_line(line):
                    raise NotImplementedError("Conflict markers present")

    def action_take_this(self, tree):
        self._resolve_with_cleanups(tree, 'THIS')

    def action_take_other(self, tree):
        self._resolve_with_cleanups(tree, 'OTHER')


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

    def associated_filenames(self):
        # Nothing has been generated here
        return []


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
        # the factory blindly transfers the Stanza values to __init__,
        # so they can be unicode.
        if isinstance(conflict_file_id, text_type):
            conflict_file_id = cache_utf8.encode(conflict_file_id)
        self.conflict_file_id = osutils.safe_file_id(conflict_file_id)

    def _cmp_list(self):
        return HandledConflict._cmp_list(self) + [self.conflict_path,
                                                  self.conflict_file_id]

    def as_stanza(self):
        s = HandledConflict.as_stanza(self)
        s.add('conflict_path', self.conflict_path)
        if self.conflict_file_id is not None:
            s.add('conflict_file_id', self.conflict_file_id.decode('utf8'))

        return s


class DuplicateID(HandledPathConflict):
    """Two files want the same file_id."""

    typestring = 'duplicate id'

    format = 'Conflict adding id to %(conflict_path)s.  %(action)s %(path)s.'


class DuplicateEntry(HandledPathConflict):
    """Two directory entries want to have the same name."""

    typestring = 'duplicate'

    format = 'Conflict adding file %(conflict_path)s.  %(action)s %(path)s.'

    def action_take_this(self, tree):
        tree.remove([self.conflict_path], force=True, keep_files=False)
        tree.rename_one(self.path, self.conflict_path)

    def action_take_other(self, tree):
        tree.remove([self.path], force=True, keep_files=False)


class ParentLoop(HandledPathConflict):
    """An attempt to create an infinitely-looping directory structure.
    This is rare, but can be produced like so:

    tree A:
      mv foo bar
    tree B:
      mv bar foo
    merge A and B
    """

    typestring = 'parent loop'

    format = 'Conflict moving %(path)s into %(conflict_path)s. %(action)s.'

    def action_take_this(self, tree):
        # just acccept brz proposal
        pass

    def action_take_other(self, tree):
        tt = transform.TreeTransform(tree)
        try:
            p_tid = tt.trans_id_file_id(self.file_id)
            parent_tid = tt.get_tree_parent(p_tid)
            cp_tid = tt.trans_id_file_id(self.conflict_file_id)
            cparent_tid = tt.get_tree_parent(cp_tid)
            tt.adjust_path(osutils.basename(self.path), cparent_tid, cp_tid)
            tt.adjust_path(osutils.basename(self.conflict_path),
                           parent_tid, p_tid)
            tt.apply()
        finally:
            tt.finalize()


class UnversionedParent(HandledConflict):
    """An attempt to version a file whose parent directory is not versioned.
    Typically, the result of a merge where one tree unversioned the directory
    and the other added a versioned file to it.
    """

    typestring = 'unversioned parent'

    format = 'Conflict because %(path)s is not versioned, but has versioned'\
             ' children.  %(action)s.'

    # FIXME: We silently do nothing to make tests pass, but most probably the
    # conflict shouldn't exist (the long story is that the conflict is
    # generated with another one that can be resolved properly) -- vila 091224
    def action_take_this(self, tree):
        pass

    def action_take_other(self, tree):
        pass


class MissingParent(HandledConflict):
    """An attempt to add files to a directory that is not present.
    Typically, the result of a merge where THIS deleted the directory and
    the OTHER added a file to it.
    See also: DeletingParent (same situation, THIS and OTHER reversed)
    """

    typestring = 'missing parent'

    format = 'Conflict adding files to %(path)s.  %(action)s.'

    def action_take_this(self, tree):
        tree.remove([self.path], force=True, keep_files=False)

    def action_take_other(self, tree):
        # just acccept brz proposal
        pass


class DeletingParent(HandledConflict):
    """An attempt to add files to a directory that is not present.
    Typically, the result of a merge where one OTHER deleted the directory and
    the THIS added a file to it.
    """

    typestring = 'deleting parent'

    format = "Conflict: can't delete %(path)s because it is not empty.  "\
             "%(action)s."

    # FIXME: It's a bit strange that the default action is not coherent with
    # MissingParent from the *user* pov.

    def action_take_this(self, tree):
        # just acccept brz proposal
        pass

    def action_take_other(self, tree):
        tree.remove([self.path], force=True, keep_files=False)


class NonDirectoryParent(HandledConflict):
    """An attempt to add files to a directory that is not a directory or
    an attempt to change the kind of a directory with files.
    """

    typestring = 'non-directory parent'

    format = "Conflict: %(path)s is not a directory, but has files in it."\
             "  %(action)s."

    # FIXME: .OTHER should be used instead of .new when the conflict is created

    def action_take_this(self, tree):
        # FIXME: we should preserve that path when the conflict is generated !
        if self.path.endswith('.new'):
            conflict_path = self.path[:-(len('.new'))]
            tree.remove([self.path], force=True, keep_files=False)
            tree.add(conflict_path)
        else:
            raise NotImplementedError(self.action_take_this)

    def action_take_other(self, tree):
        # FIXME: we should preserve that path when the conflict is generated !
        if self.path.endswith('.new'):
            conflict_path = self.path[:-(len('.new'))]
            tree.remove([conflict_path], force=True, keep_files=False)
            tree.rename_one(self.path, conflict_path)
        else:
            raise NotImplementedError(self.action_take_other)


ctype = {}


def register_types(*conflict_types):
    """Register a Conflict subclass for serialization purposes"""
    global ctype
    for conflict_type in conflict_types:
        ctype[conflict_type.typestring] = conflict_type


register_types(ContentsConflict, TextConflict, PathConflict, DuplicateID,
               DuplicateEntry, ParentLoop, UnversionedParent, MissingParent,
               DeletingParent, NonDirectoryParent)
