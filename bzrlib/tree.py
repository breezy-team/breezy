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
from collections import deque
from cStringIO import StringIO

import bzrlib
from bzrlib import (
    conflicts as _mod_conflicts,
    delta,
    osutils,
    revision as _mod_revision,
    rules,
    symbol_versioning,
    )
from bzrlib.decorators import needs_read_lock
from bzrlib.errors import BzrError, BzrCheckError
from bzrlib import errors
from bzrlib.inventory import Inventory, InventoryFile
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
        extra_trees=None, require_versioned=False, include_root=False,
        want_unversioned=False):
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
        :param want_unversioned: Scan for unversioned paths.

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
            include_root=include_root,
            want_unversioned=want_unversioned,
            )

    @symbol_versioning.deprecated_method(symbol_versioning.one_three)
    def _iter_changes(self, *args, **kwargs):
        return self.iter_changes(*args, **kwargs)

    def iter_changes(self, from_tree, include_unchanged=False,
                     specific_files=None, pb=None, extra_trees=None,
                     require_versioned=True, want_unversioned=False):
        intertree = InterTree.get(from_tree, self)
        return intertree.iter_changes(include_unchanged, specific_files, pb,
            extra_trees, require_versioned, want_unversioned=want_unversioned)
    
    def conflicts(self):
        """Get a list of the conflicts in the tree.

        Each conflict is an instance of bzrlib.conflicts.Conflict.
        """
        return _mod_conflicts.ConflictList()

    def extras(self):
        """For trees that can have unversioned files, return all such paths."""
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
        raise NotImplementedError(self.has_filename)

    def has_id(self, file_id):
        return self.inventory.has_id(file_id)

    __contains__ = has_id

    def has_or_had_id(self, file_id):
        if file_id == self.inventory.root.file_id:
            return True
        return self.inventory.has_id(file_id)

    def is_ignored(self, filename):
        """Check whether the filename is ignored by this tree.

        :param filename: The relative filename within the tree.
        :return: True if the filename is ignored.
        """
        return False

    def __iter__(self):
        return iter(self.inventory)

    def all_file_ids(self):
        """Iterate through all file ids, including ids for missing files."""
        return set(self.inventory)

    def id2path(self, file_id):
        """Return the path for a file id.

        :raises NoSuchId:
        """
        return self.inventory.id2path(file_id)

    def is_control_filename(self, filename):
        """True if filename is the name of a control file in this tree.
        
        :param filename: A filename within the tree. This is a relative path
        from the root of this tree.

        This is true IF and ONLY IF the filename is part of the meta data
        that bzr controls in this tree. I.E. a random .bzr directory placed
        on disk will not be a control file for this tree.
        """
        return self.bzrdir.is_control_filename(filename)

    @needs_read_lock
    def iter_entries_by_dir(self, specific_file_ids=None):
        """Walk the tree in 'by_dir' order.

        This will yield each entry in the tree as a (path, entry) tuple.
        The order that they are yielded is:

        Directories are walked in a depth-first lexicographical order,
        however, whenever a directory is reached, all of its direct child
        nodes are yielded in  lexicographical order before yielding the
        grandchildren.

        For example, in the tree::

           a/
             b/
               c
             d/
               e
           f/
             g

        The yield order (ignoring root) would be::
          a, f, a/b, a/d, a/b/c, a/d/e, f/g
        """
        return self.inventory.iter_entries_by_dir(
            specific_file_ids=specific_file_ids)

    def iter_references(self):
        for path, entry in self.iter_entries_by_dir():
            if entry.kind == 'tree-reference':
                yield path, entry.file_id

    def kind(self, file_id):
        raise NotImplementedError("Tree subclass %s must implement kind"
            % self.__class__.__name__)

    def stored_kind(self, file_id):
        """File kind stored for this file_id.

        May not match kind on disk for working trees.  Always available
        for versioned files, even when the file itself is missing.
        """
        return self.kind(file_id)

    def path_content_summary(self, path):
        """Get a summary of the information about path.
        
        :param path: A relative path within the tree.
        :return: A tuple containing kind, size, exec, sha1-or-link.
            Kind is always present (see tree.kind()).
            size is present if kind is file, None otherwise.
            exec is None unless kind is file and the platform supports the 'x'
                bit.
            sha1-or-link is the link target if kind is symlink, or the sha1 if
                it can be obtained without reading the file.
        """
        raise NotImplementedError(self.path_content_summary)

    def get_reference_revision(self, file_id, path=None):
        raise NotImplementedError("Tree subclass %s must implement "
                                  "get_reference_revision"
            % self.__class__.__name__)

    def _comparison_data(self, entry, path):
        """Return a tuple of kind, executable, stat_value for a file.

        entry may be None if there is no inventory entry for the file, but
        path must always be supplied.

        kind is None if there is no file present (even if an inventory id is
        present).  executable is False for non-file entries.
        """
        raise NotImplementedError(self._comparison_data)

    def _file_size(self, entry, stat_value):
        raise NotImplementedError(self._file_size)

    def _get_inventory(self):
        return self._inventory
    
    def get_file(self, file_id, path=None):
        """Return a file object for the file file_id in the tree.
        
        If both file_id and path are defined, it is implementation defined as
        to which one is used.
        """
        raise NotImplementedError(self.get_file)

    def get_file_mtime(self, file_id, path=None):
        """Return the modification time for a file.

        :param file_id: The handle for this file.
        :param path: The path that this file can be found at.
            These must point to the same object.
        """
        raise NotImplementedError(self.get_file_mtime)

    def get_file_size(self, file_id):
        """Return the size of a file in bytes.

        This applies only to regular files.  If invoked on directories or
        symlinks, it will return None.
        :param file_id: The file-id of the file
        """
        raise NotImplementedError(self.get_file_size)

    def get_file_by_path(self, path):
        return self.get_file(self._inventory.path2id(path), path)

    def iter_files_bytes(self, desired_files):
        """Iterate through file contents.

        Files will not necessarily be returned in the order they occur in
        desired_files.  No specific order is guaranteed.

        Yields pairs of identifier, bytes_iterator.  identifier is an opaque
        value supplied by the caller as part of desired_files.  It should
        uniquely identify the file version in the caller's context.  (Examples:
        an index number or a TreeTransform trans_id.)

        bytes_iterator is an iterable of bytestrings for the file.  The
        kind of iterable and length of the bytestrings are unspecified, but for
        this implementation, it is a tuple containing a single bytestring with
        the complete text of the file.

        :param desired_files: a list of (file_id, identifier) pairs
        """
        for file_id, identifier in desired_files:
            # We wrap the string in a tuple so that we can return an iterable
            # of bytestrings.  (Technically, a bytestring is also an iterable
            # of bytestrings, but iterating through each character is not
            # performant.)
            cur_file = (self.get_file_text(file_id),)
            yield identifier, cur_file

    def get_symlink_target(self, file_id):
        """Get the target for a given file_id.

        It is assumed that the caller already knows that file_id is referencing
        a symlink.
        :param file_id: Handle for the symlink entry.
        :return: The path the symlink points to.
        """
        raise NotImplementedError(self.get_symlink_target)

    def get_root_id(self):
        """Return the file_id for the root of this tree."""
        raise NotImplementedError(self.get_root_id)

    def annotate_iter(self, file_id,
                      default_revision=_mod_revision.CURRENT_REVISION):
        """Return an iterator of revision_id, line tuples.

        For working trees (and mutable trees in general), the special
        revision_id 'current:' will be used for lines that are new in this
        tree, e.g. uncommitted changes.
        :param file_id: The file to produce an annotated version from
        :param default_revision: For lines that don't match a basis, mark them
            with this revision id. Not all implementations will make use of
            this value.
        """
        raise NotImplementedError(self.annotate_iter)

    def _get_plan_merge_data(self, file_id, other, base):
        from bzrlib import merge, versionedfile
        vf = versionedfile._PlanMergeVersionedFile(file_id)
        last_revision_a = self._get_file_revision(file_id, vf, 'this:')
        last_revision_b = other._get_file_revision(file_id, vf, 'other:')
        if base is None:
            last_revision_base = None
        else:
            last_revision_base = base._get_file_revision(file_id, vf, 'base:')
        return vf, last_revision_a, last_revision_b, last_revision_base

    def plan_file_merge(self, file_id, other, base=None):
        """Generate a merge plan based on annotations.

        If the file contains uncommitted changes in this tree, they will be
        attributed to the 'current:' pseudo-revision.  If the file contains
        uncommitted changes in the other tree, they will be assigned to the
        'other:' pseudo-revision.
        """
        data = self._get_plan_merge_data(file_id, other, base)
        vf, last_revision_a, last_revision_b, last_revision_base = data
        return vf.plan_merge(last_revision_a, last_revision_b,
                             last_revision_base)

    def plan_file_lca_merge(self, file_id, other, base=None):
        """Generate a merge plan based lca-newness.

        If the file contains uncommitted changes in this tree, they will be
        attributed to the 'current:' pseudo-revision.  If the file contains
        uncommitted changes in the other tree, they will be assigned to the
        'other:' pseudo-revision.
        """
        data = self._get_plan_merge_data(file_id, other, base)
        vf, last_revision_a, last_revision_b, last_revision_base = data
        return vf.plan_lca_merge(last_revision_a, last_revision_b,
                                 last_revision_base)

    def _iter_parent_trees(self):
        """Iterate through parent trees, defaulting to Tree.revision_tree."""
        for revision_id in self.get_parent_ids():
            try:
                yield self.revision_tree(revision_id)
            except errors.NoSuchRevisionInTree:
                yield self.repository.revision_tree(revision_id)

    @staticmethod
    def _file_revision(revision_tree, file_id):
        """Determine the revision associated with a file in a given tree."""
        revision_tree.lock_read()
        try:
            return revision_tree.inventory[file_id].revision
        finally:
            revision_tree.unlock()

    def _get_file_revision(self, file_id, vf, tree_revision):
        """Ensure that file_id, tree_revision is in vf to plan the merge."""

        if getattr(self, '_repository', None) is None:
            last_revision = tree_revision
            parent_keys = [(file_id, self._file_revision(t, file_id)) for t in
                self._iter_parent_trees()]
            vf.add_lines((file_id, last_revision), parent_keys,
                         self.get_file(file_id).readlines())
            repo = self.branch.repository
            base_vf = repo.texts
        else:
            last_revision = self._file_revision(self, file_id)
            base_vf = self._repository.texts
        if base_vf not in vf.fallback_versionedfiles:
            vf.fallback_versionedfiles.append(base_vf)
        return last_revision

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

    @needs_read_lock
    def path2id(self, path):
        """Return the id for path in this tree."""
        return self._inventory.path2id(path)

    def paths2ids(self, paths, trees=[], require_versioned=True):
        """Return all the ids that can be reached by walking from paths.
        
        Each path is looked up in this tree and any extras provided in
        trees, and this is repeated recursively: the children in an extra tree
        of a directory that has been renamed under a provided path in this tree
        are all returned, even if none exist under a provided path in this
        tree, and vice versa.

        :param paths: An iterable of paths to start converting to ids from.
            Alternatively, if paths is None, no ids should be calculated and None
            will be returned. This is offered to make calling the api unconditional
            for code that *might* take a list of files.
        :param trees: Additional trees to consider.
        :param require_versioned: If False, do not raise NotVersionedError if
            an element of paths is not versioned in this tree and all of trees.
        """
        return find_ids_across_trees(paths, [self] + list(trees), require_versioned)

    @symbol_versioning.deprecated_method(symbol_versioning.one_six)
    def print_file(self, file_id):
        """Print file with id `file_id` to stdout."""
        import sys
        sys.stdout.write(self.get_file_text(file_id))

    def lock_read(self):
        pass

    def revision_tree(self, revision_id):
        """Obtain a revision tree for the revision revision_id.

        The intention of this method is to allow access to possibly cached
        tree data. Implementors of this method should raise NoSuchRevision if
        the tree is not locally available, even if they could obtain the 
        tree via a repository or some other means. Callers are responsible 
        for finding the ultimate source for a revision tree.

        :param revision_id: The revision_id of the requested tree.
        :return: A Tree.
        :raises: NoSuchRevision if the tree cannot be obtained.
        """
        raise errors.NoSuchRevisionInTree(self, revision_id)

    def unknowns(self):
        """What files are present in this tree and unknown.
        
        :return: an iterator over the unknown files.
        """
        return iter([])

    def unlock(self):
        pass

    def filter_unversioned_files(self, paths):
        """Filter out paths that are versioned.

        :return: set of paths.
        """
        # NB: we specifically *don't* call self.has_filename, because for
        # WorkingTrees that can indicate files that exist on disk but that 
        # are not versioned.
        pred = self.inventory.has_filename
        return set((p for p in paths if not pred(p)))

    def walkdirs(self, prefix=""):
        """Walk the contents of this tree from path down.

        This yields all the data about the contents of a directory at a time.
        After each directory has been yielded, if the caller has mutated the
        list to exclude some directories, they are then not descended into.
        
        The data yielded is of the form:
        ((directory-relpath, directory-path-from-root, directory-fileid),
        [(relpath, basename, kind, lstat, path_from_tree_root, file_id, 
          versioned_kind), ...]),
         - directory-relpath is the containing dirs relpath from prefix
         - directory-path-from-root is the containing dirs path from /
         - directory-fileid is the id of the directory if it is versioned.
         - relpath is the relative path within the subtree being walked.
         - basename is the basename
         - kind is the kind of the file now. If unknonwn then the file is not
           present within the tree - but it may be recorded as versioned. See
           versioned_kind.
         - lstat is the stat data *if* the file was statted.
         - path_from_tree_root is the path from the root of the tree.
         - file_id is the file_id if the entry is versioned.
         - versioned_kind is the kind of the file as last recorded in the 
           versioning system. If 'unknown' the file is not versioned.
        One of 'kind' and 'versioned_kind' must not be 'unknown'.

        :param prefix: Start walking from prefix within the tree rather than
        at the root. This allows one to walk a subtree but get paths that are
        relative to a tree rooted higher up.
        :return: an iterator over the directory data.
        """
        raise NotImplementedError(self.walkdirs)

    def iter_search_rules(self, path_names, pref_names=None,
        _default_searcher=rules._per_user_searcher):
        """Find the preferences for filenames in a tree.

        :param path_names: an iterable of paths to find attributes for.
          Paths are given relative to the root of the tree.
        :param pref_names: the list of preferences to lookup - None for all
        :param _default_searcher: private parameter to assist testing - don't use
        :return: an iterator of tuple sequences, one per path-name.
          See _RulesSearcher.get_items for details on the tuple sequence.
        """
        searcher = self._get_rules_searcher(_default_searcher)
        if searcher is not None:
            if pref_names is not None:
                for path in path_names:
                    yield searcher.get_selected_items(path, pref_names)
            else:
                for path in path_names:
                    yield searcher.get_items(path)

    @needs_read_lock
    def _get_rules_searcher(self, default_searcher):
        """Get the RulesSearcher for this tree given the default one."""
        searcher = default_searcher
        return searcher


class EmptyTree(Tree):

    def __init__(self):
        self._inventory = Inventory(root_id=None)
        symbol_versioning.warn('EmptyTree is deprecated as of bzr 0.9 please'
                               ' use repository.revision_tree instead.',
                               DeprecationWarning, stacklevel=2)

    def get_parent_ids(self):
        return []

    def get_symlink_target(self, file_id):
        return None

    def has_filename(self, filename):
        return False

    def kind(self, file_id):
        return "directory"

    def list_files(self, include_root=False):
        return iter([])
    
    def __contains__(self, file_id):
        return (file_id in self._inventory)

    def get_file_sha1(self, file_id, path=None, stat_value=None):
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

    :param filenames: The filenames to find file_ids for (if None, returns
        None)
    :param trees: The trees to find file_ids within
    :param require_versioned: if true, all specified filenames must occur in
    at least one tree.
    :return: a set of file ids for the specified filenames and their children.
    """
    if not filenames:
        return None
    specified_path_ids = _find_ids_across_trees(filenames, trees,
        require_versioned)
    return _find_children_across_trees(specified_path_ids, trees)


def _find_ids_across_trees(filenames, trees, require_versioned):
    """Find the ids corresponding to specified filenames.
    
    All matches in all trees will be used, but subdirectories are not scanned.

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
            file_id = tree.path2id(tree_path)
            if file_id is not None:
                interesting_ids.add(file_id)
                not_found = False
        if not_found:
            not_versioned.append(tree_path)
    if len(not_versioned) > 0 and require_versioned:
        raise errors.PathsNotVersionedError(not_versioned)
    return interesting_ids


def _find_children_across_trees(specified_ids, trees):
    """Return a set including specified ids and their children.
    
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
                if not tree.has_id(file_id):
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

    Clients of bzrlib should not need to use InterTree directly, rather they
    should use the convenience methods on Tree such as 'Tree.compare()' which
    will pass through to InterTree as appropriate.
    """

    _optimisers = []

    @needs_read_lock
    def compare(self, want_unchanged=False, specific_files=None,
        extra_trees=None, require_versioned=False, include_root=False,
        want_unversioned=False):
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
        :param want_unversioned: Scan for unversioned paths.
        """
        # NB: show_status depends on being able to pass in non-versioned files
        # and report them as unknown
        trees = (self.source,)
        if extra_trees is not None:
            trees = trees + tuple(extra_trees)
        # target is usually the newer tree:
        specific_file_ids = self.target.paths2ids(specific_files, trees,
            require_versioned=require_versioned)
        if specific_files and not specific_file_ids:
            # All files are unversioned, so just return an empty delta
            # _compare_trees would think we want a complete delta
            result = delta.TreeDelta()
            fake_entry = InventoryFile('unused', 'unused', 'unused')
            result.unversioned = [(path, None,
                self.target._comparison_data(fake_entry, path)[0]) for path in
                specific_files]
            return result
        return delta._compare_trees(self.source, self.target, want_unchanged,
            specific_files, include_root, extra_trees=extra_trees,
            require_versioned=require_versioned,
            want_unversioned=want_unversioned)

    def iter_changes(self, include_unchanged=False,
                      specific_files=None, pb=None, extra_trees=[],
                      require_versioned=True, want_unversioned=False):
        """Generate an iterator of changes between trees.

        A tuple is returned:
        (file_id, (path_in_source, path_in_target),
         changed_content, versioned, parent, name, kind,
         executable)

        Changed_content is True if the file's content has changed.  This
        includes changes to its kind, and to a symlink's target.

        versioned, parent, name, kind, executable are tuples of (from, to).
        If a file is missing in a tree, its kind is None.

        Iteration is done in parent-to-child order, relative to the target
        tree.

        There is no guarantee that all paths are in sorted order: the
        requirement to expand the search due to renames may result in children
        that should be found early being found late in the search, after
        lexically later results have been returned.
        :param require_versioned: Raise errors.PathsNotVersionedError if a
            path in the specific_files list is not versioned in one of
            source, target or extra_trees.
        :param want_unversioned: Should unversioned files be returned in the
            output. An unversioned file is defined as one with (False, False)
            for the versioned pair.
        """
        result = []
        lookup_trees = [self.source]
        if extra_trees:
             lookup_trees.extend(extra_trees)
        if specific_files == []:
            specific_file_ids = []
        else:
            specific_file_ids = self.target.paths2ids(specific_files,
                lookup_trees, require_versioned=require_versioned)
        if want_unversioned:
            all_unversioned = sorted([(p.split('/'), p) for p in
                                     self.target.extras()
                if specific_files is None or
                    osutils.is_inside_any(specific_files, p)])
            all_unversioned = deque(all_unversioned)
        else:
            all_unversioned = deque()
        to_paths = {}
        from_entries_by_dir = list(self.source.inventory.iter_entries_by_dir(
            specific_file_ids=specific_file_ids))
        from_data = dict((e.file_id, (p, e)) for p, e in from_entries_by_dir)
        to_entries_by_dir = list(self.target.inventory.iter_entries_by_dir(
            specific_file_ids=specific_file_ids))
        num_entries = len(from_entries_by_dir) + len(to_entries_by_dir)
        entry_count = 0
        # the unversioned path lookup only occurs on real trees - where there 
        # can be extras. So the fake_entry is solely used to look up
        # executable it values when execute is not supported.
        fake_entry = InventoryFile('unused', 'unused', 'unused')
        for to_path, to_entry in to_entries_by_dir:
            while all_unversioned and all_unversioned[0][0] < to_path.split('/'):
                unversioned_path = all_unversioned.popleft()
                to_kind, to_executable, to_stat = \
                    self.target._comparison_data(fake_entry, unversioned_path[1])
                yield (None, (None, unversioned_path[1]), True, (False, False),
                    (None, None),
                    (None, unversioned_path[0][-1]),
                    (None, to_kind),
                    (None, to_executable))
            file_id = to_entry.file_id
            to_paths[file_id] = to_path
            entry_count += 1
            changed_content = False
            from_path, from_entry = from_data.get(file_id, (None, None))
            from_versioned = (from_entry is not None)
            if from_entry is not None:
                from_versioned = True
                from_name = from_entry.name
                from_parent = from_entry.parent_id
                from_kind, from_executable, from_stat = \
                    self.source._comparison_data(from_entry, from_path)
                entry_count += 1
            else:
                from_versioned = False
                from_kind = None
                from_parent = None
                from_name = None
                from_executable = None
            versioned = (from_versioned, True)
            to_kind, to_executable, to_stat = \
                self.target._comparison_data(to_entry, to_path)
            kind = (from_kind, to_kind)
            if kind[0] != kind[1]:
                changed_content = True
            elif from_kind == 'file':
                from_size = self.source._file_size(from_entry, from_stat)
                to_size = self.target._file_size(to_entry, to_stat)
                if from_size != to_size:
                    changed_content = True
                elif (self.source.get_file_sha1(file_id, from_path, from_stat) !=
                    self.target.get_file_sha1(file_id, to_path, to_stat)):
                    changed_content = True
            elif from_kind == 'symlink':
                if (self.source.get_symlink_target(file_id) !=
                    self.target.get_symlink_target(file_id)):
                    changed_content = True
                elif from_kind == 'tree-reference':
                    if (self.source.get_reference_revision(file_id, from_path)
                        != self.target.get_reference_revision(file_id, to_path)):
                        changed_content = True 
            parent = (from_parent, to_entry.parent_id)
            name = (from_name, to_entry.name)
            executable = (from_executable, to_executable)
            if pb is not None:
                pb.update('comparing files', entry_count, num_entries)
            if (changed_content is not False or versioned[0] != versioned[1]
                or parent[0] != parent[1] or name[0] != name[1] or 
                executable[0] != executable[1] or include_unchanged):
                yield (file_id, (from_path, to_path), changed_content,
                    versioned, parent, name, kind, executable)

        while all_unversioned:
            # yield any trailing unversioned paths
            unversioned_path = all_unversioned.popleft()
            to_kind, to_executable, to_stat = \
                self.target._comparison_data(fake_entry, unversioned_path[1])
            yield (None, (None, unversioned_path[1]), True, (False, False),
                (None, None),
                (None, unversioned_path[0][-1]),
                (None, to_kind),
                (None, to_executable))

        def get_to_path(to_entry):
            if to_entry.parent_id is None:
                to_path = '' # the root
            else:
                if to_entry.parent_id not in to_paths:
                    # recurse up
                    return get_to_path(self.target.inventory[to_entry.parent_id])
                to_path = osutils.pathjoin(to_paths[to_entry.parent_id],
                                           to_entry.name)
            to_paths[to_entry.file_id] = to_path
            return to_path

        for path, from_entry in from_entries_by_dir:
            file_id = from_entry.file_id
            if file_id in to_paths:
                # already returned
                continue
            if not file_id in self.target.inventory:
                # common case - paths we have not emitted are not present in
                # target.
                to_path = None
            else:
                to_path = get_to_path(self.target.inventory[file_id])
            entry_count += 1
            if pb is not None:
                pb.update('comparing files', entry_count, num_entries)
            versioned = (True, False)
            parent = (from_entry.parent_id, None)
            name = (from_entry.name, None)
            from_kind, from_executable, stat_value = \
                self.source._comparison_data(from_entry, path)
            kind = (from_kind, None)
            executable = (from_executable, None)
            changed_content = True
            # the parent's path is necessarily known at this point.
            yield(file_id, (path, to_path), changed_content, versioned, parent,
                  name, kind, executable)


class MultiWalker(object):
    """Walk multiple trees simultaneously, getting combined results."""

    # Note: This could be written to not assume you can do out-of-order
    #       lookups. Instead any nodes that don't match in all trees could be
    #       marked as 'deferred', and then returned in the final cleanup loop.
    #       For now, I think it is "nicer" to return things as close to the
    #       "master_tree" order as we can.

    def __init__(self, master_tree, other_trees):
        """Create a new MultiWalker.

        All trees being walked must implement "iter_entries_by_dir()", such
        that they yield (path, object) tuples, where that object will have a
        '.file_id' member, that can be used to check equality.

        :param master_tree: All trees will be 'slaved' to the master_tree such
            that nodes in master_tree will be used as 'first-pass' sync points.
            Any nodes that aren't in master_tree will be merged in a second
            pass.
        :param other_trees: A list of other trees to walk simultaneously.
        """
        self._master_tree = master_tree
        self._other_trees = other_trees

        # Keep track of any nodes that were properly processed just out of
        # order, that way we don't return them at the end, we don't have to
        # track *all* processed file_ids, just the out-of-order ones
        self._out_of_order_processed = set()

    @staticmethod
    def _step_one(iterator):
        """Step an iter_entries_by_dir iterator.

        :return: (has_more, path, ie)
            If has_more is False, path and ie will be None.
        """
        try:
            path, ie = iterator.next()
        except StopIteration:
            return False, None, None
        else:
            return True, path, ie

    @staticmethod
    def _cmp_path_by_dirblock(path1, path2):
        """Compare two paths based on what directory they are in.

        This generates a sort order, such that all children of a directory are
        sorted together, and grandchildren are in the same order as the
        children appear. But all grandchildren come after all children.

        :param path1: first path
        :param path2: the second path
        :return: negative number if ``path1`` comes first,
            0 if paths are equal
            and a positive number if ``path2`` sorts first
        """
        # Shortcut this special case
        if path1 == path2:
            return 0
        # This is stolen from _dirstate_helpers_py.py, only switching it to
        # Unicode objects. Consider using encode_utf8() and then using the
        # optimized versions, or maybe writing optimized unicode versions.
        if not isinstance(path1, unicode):
            raise TypeError("'path1' must be a unicode string, not %s: %r"
                            % (type(path1), path1))
        if not isinstance(path2, unicode):
            raise TypeError("'path2' must be a unicode string, not %s: %r"
                            % (type(path2), path2))
        return cmp(MultiWalker._path_to_key(path1),
                   MultiWalker._path_to_key(path2))

    @staticmethod
    def _path_to_key(path):
        dirname, basename = osutils.split(path)
        return (dirname.split(u'/'), basename)

    def _lookup_by_file_id(self, extra_entries, other_tree, file_id):
        """Lookup an inventory entry by file_id.

        This is called when an entry is missing in the normal order.
        Generally this is because a file was either renamed, or it was
        deleted/added. If the entry was found in the inventory and not in
        extra_entries, it will be added to self._out_of_order_processed

        :param extra_entries: A dictionary of {file_id: (path, ie)}.  This
            should be filled with entries that were found before they were
            used. If file_id is present, it will be removed from the
            dictionary.
        :param other_tree: The Tree to search, in case we didn't find the entry
            yet.
        :param file_id: The file_id to look for
        :return: (path, ie) if found or (None, None) if not present.
        """
        if file_id in extra_entries:
            return extra_entries.pop(file_id)
        # TODO: Is id2path better as the first call, or is
        #       inventory[file_id] better as a first check?
        try:
            cur_path = other_tree.id2path(file_id)
        except errors.NoSuchId:
            cur_path = None
        if cur_path is None:
            return (None, None)
        else:
            self._out_of_order_processed.add(file_id)
            cur_ie = other_tree.inventory[file_id]
            return (cur_path, cur_ie)

    def iter_all(self):
        """Match up the values in the different trees."""
        for result in self._walk_master_tree():
            yield result
        self._finish_others()
        for result in self._walk_others():
            yield result

    def _walk_master_tree(self):
        """First pass, walk all trees in lock-step.
        
        When we are done, all nodes in the master_tree will have been
        processed. _other_walkers, _other_entries, and _others_extra will be
        set on 'self' for future processing.
        """
        # This iterator has the most "inlining" done, because it tends to touch
        # every file in the tree, while the others only hit nodes that don't
        # match.
        master_iterator = self._master_tree.iter_entries_by_dir()

        other_walkers = [other.iter_entries_by_dir()
                         for other in self._other_trees]
        other_entries = [self._step_one(walker) for walker in other_walkers]
        # Track extra nodes in the other trees
        others_extra = [{} for i in xrange(len(self._other_trees))]

        master_has_more = True
        step_one = self._step_one
        lookup_by_file_id = self._lookup_by_file_id
        out_of_order_processed = self._out_of_order_processed

        while master_has_more:
            (master_has_more, path, master_ie) = step_one(master_iterator)
            if not master_has_more:
                break

            file_id = master_ie.file_id
            other_values = []
            other_values_append = other_values.append
            next_other_entries = []
            next_other_entries_append = next_other_entries.append
            for idx, (other_has_more, other_path, other_ie) in enumerate(other_entries):
                if not other_has_more:
                    other_values_append(lookup_by_file_id(
                        others_extra[idx], self._other_trees[idx], file_id))
                    next_other_entries_append((False, None, None))
                elif file_id == other_ie.file_id:
                    # This is the critical code path, as most of the entries
                    # should match between most trees.
                    other_values_append((other_path, other_ie))
                    next_other_entries_append(step_one(other_walkers[idx]))
                else:
                    # This walker did not match, step it until it either
                    # matches, or we know we are past the current walker.
                    other_walker = other_walkers[idx]
                    other_extra = others_extra[idx]
                    while (other_has_more and
                           self._cmp_path_by_dirblock(other_path, path) < 0):
                        other_file_id = other_ie.file_id
                        if other_file_id not in out_of_order_processed:
                            other_extra[other_file_id] = (other_path, other_ie)
                        other_has_more, other_path, other_ie = \
                            step_one(other_walker)
                    if other_has_more and other_ie.file_id == file_id:
                        # We ended up walking to this point, match and step
                        # again
                        other_values_append((other_path, other_ie))
                        other_has_more, other_path, other_ie = \
                            step_one(other_walker)
                    else:
                        # This record isn't in the normal order, see if it
                        # exists at all.
                        other_values_append(lookup_by_file_id(
                            other_extra, self._other_trees[idx], file_id))
                    next_other_entries_append((other_has_more, other_path,
                                               other_ie))
            other_entries = next_other_entries

            # We've matched all the walkers, yield this datapoint
            yield path, file_id, master_ie, other_values
        self._other_walkers = other_walkers
        self._other_entries = other_entries
        self._others_extra = others_extra

    def _finish_others(self):
        """Finish walking the other iterators, so we get all entries."""
        for idx, info in enumerate(self._other_entries):
            other_extra = self._others_extra[idx]
            (other_has_more, other_path, other_ie) = info
            while other_has_more:
                other_file_id = other_ie.file_id
                if other_file_id not in self._out_of_order_processed:
                    other_extra[other_file_id] = (other_path, other_ie)
                other_has_more, other_path, other_ie = \
                    self._step_one(self._other_walkers[idx])
        del self._other_entries

    def _walk_others(self):
        """Finish up by walking all the 'deferred' nodes."""
        # TODO: One alternative would be to grab all possible unprocessed
        #       file_ids, and then sort by path, and then yield them. That
        #       might ensure better ordering, in case a caller strictly
        #       requires parents before children.
        for idx, other_extra in enumerate(self._others_extra):
            others = sorted(other_extra.itervalues(),
                            key=lambda x: self._path_to_key(x[0]))
            for other_path, other_ie in others:
                file_id = other_ie.file_id
                # We don't need to check out_of_order_processed here, because
                # the lookup_by_file_id will be removing anything processed
                # from the extras cache
                other_extra.pop(file_id)
                other_values = [(None, None) for i in xrange(idx)]
                other_values.append((other_path, other_ie))
                for alt_idx, alt_extra in enumerate(self._others_extra[idx+1:]):
                    alt_idx = alt_idx + idx + 1
                    alt_extra = self._others_extra[alt_idx]
                    alt_tree = self._other_trees[alt_idx]
                    other_values.append(self._lookup_by_file_id(
                                            alt_extra, alt_tree, file_id))
                yield other_path, file_id, None, other_values
