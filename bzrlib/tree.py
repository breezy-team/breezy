# Copyright (C) 2005 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tree classes, representing directory at point in time.
"""

import os
from cStringIO import StringIO
from warnings import warn

import bzrlib
from bzrlib import delta, osutils
from bzrlib.decorators import needs_read_lock
from bzrlib.errors import BzrError, BzrCheckError
from bzrlib import errors
from bzrlib.inventory import Inventory
from bzrlib.inter import InterObject
from bzrlib.osutils import fingerprint_file
import bzrlib.revision
from bzrlib.trace import mutter, note


class Tree(object):
    """Abstract file tree.

    There are several subclasses:
    
    * `WorkingTree` exists as files on disk editable by the user.

    * `RevisionTree` is a tree as recorded at some point in the past.

    Trees contain an `Inventory` object, and also know how to retrieve
    file texts mentioned in the inventory, either from a working
    directory or from a store.

    It is possible for trees to contain files that are not described
    in their inventory or vice versa; for this use `filenames()`.

    Trees can be compared, etc, regardless of whether they are working
    trees or versioned trees.
    """
    
    def changes_from(self, other, want_unchanged=False, specific_files=None,
        extra_trees=None, require_versioned=False):
        """Return a TreeDelta of the changes from other to this tree.

        :param other: A tree to compare with.
        :param specific_files: An optional list of file paths to restrict the
            comparison to. When mapping filenames to ids, all matches in all
            trees (including optional extra_trees) are used, and all children of
            matched directories are included.
        :param want_unchanged: An optional boolean requesting the inclusion of
            unchanged entries in the result.
        :param extra_trees: An optional list of additional trees to use when
            mapping the contents of specific_files (paths) to file_ids.
        :param require_versioned: An optional boolean (defaults to False). When
            supplied and True all the 'specific_files' must be versioned, or
            a PathsNotVersionedError will be thrown.

        The comparison will be performed by an InterTree object looked up on 
        self and other.
        """
        # Martin observes that Tree.changes_from returns a TreeDelta and this
        # may confuse people, because the class name of the returned object is
        # a synonym of the object referenced in the method name.
        return InterTree.get(other, self).compare(
            want_unchanged=want_unchanged,
            specific_files=specific_files,
            extra_trees=extra_trees,
            require_versioned=require_versioned,
            )

    def iter_changes(self, from_tree, include_unchanged=False):
        return InterTree.get(from_tree, self).iter_changes(from_tree, self,
                                                           include_unchanged)
    
    def conflicts(self):
        """Get a list of the conflicts in the tree.

        Each conflict is an instance of bzrlib.conflicts.Conflict.
        """
        return []

    def get_parent_ids(self):
        """Get the parent ids for this tree. 

        :return: a list of parent ids. [] is returned to indicate
        a tree with no parents.
        :raises: BzrError if the parents are not known.
        """
        raise NotImplementedError(self.get_parent_ids)
    
    def has_filename(self, filename):
        """True if the tree has given filename."""
        raise NotImplementedError()

    def has_id(self, file_id):
        return self.inventory.has_id(file_id)

    __contains__ = has_id

    def has_or_had_id(self, file_id):
        if file_id == self.inventory.root.file_id:
            return True
        return self.inventory.has_id(file_id)

    def __iter__(self):
        return iter(self.inventory)

    def id2path(self, file_id):
        return self.inventory.id2path(file_id)

    def iter_entries_by_dir(self):
        """Walk the tree in 'by_dir' order.

        This will yield each entry in the tree as a (path, entry) tuple. The
        order that they are yielded is: the contents of a directory are 
        preceeded by the parent of a directory, and all the contents of a 
        directory are grouped together.
        """
        return self.inventory.iter_entries_by_dir()

    def kind(self, file_id):
        raise NotImplementedError("subclasses must implement kind")

    def _get_inventory(self):
        return self._inventory
    
    def get_file_by_path(self, path):
        return self.get_file(self._inventory.path2id(path))

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def _check_retrieved(self, ie, f):
        if not __debug__:
            return  
        fp = fingerprint_file(f)
        f.seek(0)
        
        if ie.text_size is not None:
            if ie.text_size != fp['size']:
                raise BzrError("mismatched size for file %r in %r" % (ie.file_id, self._store),
                        ["inventory expects %d bytes" % ie.text_size,
                         "file is actually %d bytes" % fp['size'],
                         "store is probably damaged/corrupt"])

        if ie.text_sha1 != fp['sha1']:
            raise BzrError("wrong SHA-1 for file %r in %r" % (ie.file_id, self._store),
                    ["inventory expects %s" % ie.text_sha1,
                     "file is actually %s" % fp['sha1'],
                     "store is probably damaged/corrupt"])


    def print_file(self, file_id):
        """Print file with id `file_id` to stdout."""
        import sys
        sys.stdout.write(self.get_file_text(file_id))

    def lock_read(self):
        pass

    def unknowns(self):
        """What files are present in this tree and unknown.
        
        :return: an iterator over the unknown files.
        """
        return iter([])

    def unlock(self):
        pass

    def filter_unversioned_files(self, paths):
        """Filter out paths that are not versioned.

        :return: set of paths.
        """
        # NB: we specifically *don't* call self.has_filename, because for
        # WorkingTrees that can indicate files that exist on disk but that 
        # are not versioned.
        pred = self.inventory.has_filename
        return set((p for p in paths if not pred(p)))


# for compatibility
from bzrlib.revisiontree import RevisionTree
 

class EmptyTree(Tree):

    def __init__(self):
        self._inventory = Inventory()
        warn('EmptyTree is deprecated as of bzr 0.9 please use '
            'repository.revision_tree instead.',
            DeprecationWarning, stacklevel=2)

    def get_parent_ids(self):
        return []

    def get_symlink_target(self, file_id):
        return None

    def has_filename(self, filename):
        return False

    def kind(self, file_id):
        assert self._inventory[file_id].kind == "directory"
        return "directory"

    def list_files(self):
        return iter([])
    
    def __contains__(self, file_id):
        return (file_id in self._inventory)

    def get_file_sha1(self, file_id, path=None):
        return None


######################################################################
# diff

# TODO: Merge these two functions into a single one that can operate
# on either a whole tree or a set of files.

# TODO: Return the diff in order by filename, not by category or in
# random order.  Can probably be done by lock-stepping through the
# filenames from both trees.


def file_status(filename, old_tree, new_tree):
    """Return single-letter status, old and new names for a file.

    The complexity here is in deciding how to represent renames;
    many complex cases are possible.
    """
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory
    new_id = new_inv.path2id(filename)
    old_id = old_inv.path2id(filename)

    if not new_id and not old_id:
        # easy: doesn't exist in either; not versioned at all
        if new_tree.is_ignored(filename):
            return 'I', None, None
        else:
            return '?', None, None
    elif new_id:
        # There is now a file of this name, great.
        pass
    else:
        # There is no longer a file of this name, but we can describe
        # what happened to the file that used to have
        # this name.  There are two possibilities: either it was
        # deleted entirely, or renamed.
        assert old_id
        if new_inv.has_id(old_id):
            return 'X', old_inv.id2path(old_id), new_inv.id2path(old_id)
        else:
            return 'D', old_inv.id2path(old_id), None

    # if the file_id is new in this revision, it is added
    if new_id and not old_inv.has_id(new_id):
        return 'A'

    # if there used to be a file of this name, but that ID has now
    # disappeared, it is deleted
    if old_id and not new_inv.has_id(old_id):
        return 'D'

    return 'wtf?'

    

def find_renames(old_inv, new_inv):
    for file_id in old_inv:
        if file_id not in new_inv:
            continue
        old_name = old_inv.id2path(file_id)
        new_name = new_inv.id2path(file_id)
        if old_name != new_name:
            yield (old_name, new_name)
            

def find_ids_across_trees(filenames, trees, require_versioned=True):
    """Find the ids corresponding to specified filenames.
    
    All matches in all trees will be used, and all children of matched
    directories will be used.

    :param filenames: The filenames to find file_ids for
    :param trees: The trees to find file_ids within
    :param require_versioned: if true, all specified filenames must occur in
    at least one tree.
    :return: a set of file ids for the specified filenames and their children.
    """
    if not filenames:
        return None
    specified_ids = _find_filename_ids_across_trees(filenames, trees, 
                                                    require_versioned)
    return _find_children_across_trees(specified_ids, trees)


def _find_filename_ids_across_trees(filenames, trees, require_versioned):
    """Find the ids corresponding to specified filenames.
    
    All matches in all trees will be used.

    :param filenames: The filenames to find file_ids for
    :param trees: The trees to find file_ids within
    :param require_versioned: if true, all specified filenames must occur in
    at least one tree.
    :return: a set of file ids for the specified filenames
    """
    not_versioned = []
    interesting_ids = set()
    for tree_path in filenames:
        not_found = True
        for tree in trees:
            file_id = tree.inventory.path2id(tree_path)
            if file_id is not None:
                interesting_ids.add(file_id)
                not_found = False
        if not_found:
            not_versioned.append(tree_path)
    if len(not_versioned) > 0 and require_versioned:
        raise errors.PathsNotVersionedError(not_versioned)
    return interesting_ids


def _find_children_across_trees(specified_ids, trees):
    """Return a set including specified ids and their children
    
    All matches in all trees will be used.

    :param trees: The trees to find file_ids within
    :return: a set containing all specified ids and their children 
    """
    interesting_ids = set(specified_ids)
    pending = interesting_ids
    # now handle children of interesting ids
    # we loop so that we handle all children of each id in both trees
    while len(pending) > 0:
        new_pending = set()
        for file_id in pending:
            for tree in trees:
                if file_id not in tree:
                    continue
                entry = tree.inventory[file_id]
                for child in getattr(entry, 'children', {}).itervalues():
                    if child.file_id not in interesting_ids:
                        new_pending.add(child.file_id)
        interesting_ids.update(new_pending)
        pending = new_pending
    return interesting_ids


class InterTree(InterObject):
    """This class represents operations taking place between two Trees.

    Its instances have methods like 'compare' and contain references to the
    source and target trees these operations are to be carried out on.

    clients of bzrlib should not need to use InterTree directly, rather they
    should use the convenience methods on Tree such as 'Tree.compare()' which
    will pass through to InterTree as appropriate.
    """

    _optimisers = []

    @needs_read_lock
    def compare(self, want_unchanged=False, specific_files=None,
        extra_trees=None, require_versioned=False):
        """Return the changes from source to target.

        :return: A TreeDelta.
        :param specific_files: An optional list of file paths to restrict the
            comparison to. When mapping filenames to ids, all matches in all
            trees (including optional extra_trees) are used, and all children of
            matched directories are included.
        :param want_unchanged: An optional boolean requesting the inclusion of
            unchanged entries in the result.
        :param extra_trees: An optional list of additional trees to use when
            mapping the contents of specific_files (paths) to file_ids.
        :param require_versioned: An optional boolean (defaults to False). When
            supplied and True all the 'specific_files' must be versioned, or
            a PathsNotVersionedError will be thrown.
        """
        # NB: show_status depends on being able to pass in non-versioned files and
        # report them as unknown
        trees = (self.source, self.target)
        if extra_trees is not None:
            trees = trees + tuple(extra_trees)
        specific_file_ids = find_ids_across_trees(specific_files,
            trees, require_versioned=require_versioned)
        if specific_files and not specific_file_ids:
            # All files are unversioned, so just return an empty delta
            # _compare_trees would think we want a complete delta
            return delta.TreeDelta()
        return delta._compare_trees(self.source, self.target, want_unchanged,
            specific_file_ids)

    def iter_changes(self, from_tree, to_tree, include_unchanged):
        """Generate an iterator of changes between trees.

        A tuple is returned:
        (file_id, path, changed_content, versioned, parent, name, kind,
         executable)

        file_id and path are always returned.  Path is relative to the to_tree.
        changed_content is True if the file's content has changed.  This
        includes changes to its kind.

        versioned, parent, name, kind, executable are None if unchanged, or
        tuples of (from, to) if changed.  If a file is missing in a tree, its
        kind is None.

        Iteration is done in parent-to-child order, relative to the to_tree.
        """
        def get_versioned_kind(tree, file_id):
            try:
                return tree.kind(file_id)
            except errors.NoSuchFile:
                return None

        def compared(from_value, to_value):
            if from_value != to_value:
                return (from_value, to_value)
            else:
                return None

        to_paths = {}
        for path, to_entry in to_tree.iter_entries_by_dir():
            file_id = to_entry.file_id
            to_paths[file_id] = path
            changed_content = False
            from_versioned = (file_id in from_tree)
            versioned = compared(from_versioned, True)
            if from_versioned:
                from_kind = get_versioned_kind(from_tree, file_id)
                from_entry = from_tree.inventory[file_id]
                from_parent = from_entry.parent_id
                from_name = from_entry.name
                from_executable = from_tree.is_executable(file_id)
            else:
                from_kind = None
                from_parent = None
                from_name = None
                from_executable = None
            kind = compared(from_kind, get_versioned_kind(to_tree, file_id))
            if kind is not None:
                changed_content = True
            elif (from_tree.get_file_sha1(file_id) != 
                  to_tree.get_file_sha1(file_id)):
                changed_content = True
            parent = compared(from_parent, to_entry.parent_id)
            name = compared(from_name, to_entry.name)
            executable = compared(from_executable,
                                  to_tree.is_executable(file_id))
            if (changed_content is not False or versioned is not None or
                parent is not None or name is not None or executable is not
                None or include_unchanged):
                yield (file_id, path, changed_content, versioned, parent,
                       name, kind, executable)

        for path, from_entry in from_tree.iter_entries_by_dir():
            file_id = from_entry.file_id
            if file_id in to_paths:
                continue
            versioned = (True, False)
            parent = (from_entry.parent_id, None)
            name = (from_entry.name, None)
            kind = (get_versioned_kind(from_tree, file_id), None)
            executable = (from_tree.is_executable(file_id), None)
            changed_content = True
            # the parent's path is necessarily known at this point.
            to_path = osutils.pathjoin(to_paths[from_entry.parent_id],
                                       from_entry.name)
            to_paths[file_id] = to_path
            yield(file_id, to_path, changed_content, versioned, parent,
                  name, kind, executable)
