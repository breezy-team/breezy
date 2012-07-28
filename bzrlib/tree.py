# Copyright (C) 2005-2011 Canonical Ltd
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

"""Tree classes, representing directory at point in time.
"""

from __future__ import absolute_import

import os

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import collections

from bzrlib import (
    conflicts as _mod_conflicts,
    debug,
    delta,
    errors,
    filters,
    inventory,
    osutils,
    revision as _mod_revision,
    rules,
    trace,
    )
from bzrlib.i18n import gettext
""")

from bzrlib.decorators import needs_read_lock
from bzrlib.inter import InterObject
from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )


class Tree(object):
    """Abstract file tree.

    There are several subclasses:

    * `WorkingTree` exists as files on disk editable by the user.

    * `RevisionTree` is a tree as recorded at some point in the past.

    Trees can be compared, etc, regardless of whether they are working
    trees or versioned trees.
    """

    def has_versioned_directories(self):
        """Whether this tree can contain explicitly versioned directories.

        This defaults to True, but some implementations may want to override
        it.
        """
        return True

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

    def iter_changes(self, from_tree, include_unchanged=False,
                     specific_files=None, pb=None, extra_trees=None,
                     require_versioned=True, want_unversioned=False):
        """See InterTree.iter_changes"""
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
        raise NotImplementedError(self.has_id)

    @deprecated_method(deprecated_in((2, 4, 0)))
    def __contains__(self, file_id):
        return self.has_id(file_id)

    def has_or_had_id(self, file_id):
        raise NotImplementedError(self.has_or_had_id)

    def is_ignored(self, filename):
        """Check whether the filename is ignored by this tree.

        :param filename: The relative filename within the tree.
        :return: True if the filename is ignored.
        """
        return False

    def all_file_ids(self):
        """Iterate through all file ids, including ids for missing files."""
        raise NotImplementedError(self.all_file_ids)

    def id2path(self, file_id):
        """Return the path for a file id.

        :raises NoSuchId:
        """
        raise NotImplementedError(self.id2path)

    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
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

        :param yield_parents: If True, yield the parents from the root leading
            down to specific_file_ids that have been requested. This has no
            impact if specific_file_ids is None.
        """
        raise NotImplementedError(self.iter_entries_by_dir)

    def iter_child_entries(self, file_id, path=None):
        """Iterate over the children of a directory or tree reference.

        :param file_id: File id of the directory/tree-reference
        :param path: Optional path of the directory
        :raise NoSuchId: When the file_id does not exist
        :return: Iterator over entries in the directory
        """
        raise NotImplementedError(self.iter_child_entries)

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        """List all files in this tree.

        :param include_root: Whether to include the entry for the tree root
        :param from_dir: Directory under which to list files
        :param recursive: Whether to list files recursively
        :return: iterator over tuples of (path, versioned, kind, file_id,
            inventory entry)
        """
        raise NotImplementedError(self.list_files)

    def iter_references(self):
        if self.supports_tree_reference():
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

        All the attributes returned are for the canonical form, not the
        convenient form (if content filters are in use.)

        :param path: A relative path within the tree.
        :return: A tuple containing kind, size, exec, sha1-or-link.
            Kind is always present (see tree.kind()).
            size is present if kind is file and the size of the 
                canonical form can be cheaply determined, None otherwise.
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

    def get_file(self, file_id, path=None):
        """Return a file object for the file file_id in the tree.

        If both file_id and path are defined, it is implementation defined as
        to which one is used.
        """
        raise NotImplementedError(self.get_file)

    def get_file_with_stat(self, file_id, path=None):
        """Get a file handle and stat object for file_id.

        The default implementation returns (self.get_file, None) for backwards
        compatibility.

        :param file_id: The file id to read.
        :param path: The path of the file, if it is known.
        :return: A tuple (file_handle, stat_value_or_None). If the tree has
            no stat facility, or need for a stat cache feedback during commit,
            it may return None for the second element of the tuple.
        """
        return (self.get_file(file_id, path), None)

    def get_file_text(self, file_id, path=None):
        """Return the byte content of a file.

        :param file_id: The file_id of the file.
        :param path: The path of the file.

        If both file_id and path are supplied, an implementation may use
        either one.

        :returns: A single byte string for the whole file.
        """
        my_file = self.get_file(file_id, path)
        try:
            return my_file.read()
        finally:
            my_file.close()

    def get_file_lines(self, file_id, path=None):
        """Return the content of a file, as lines.

        :param file_id: The file_id of the file.
        :param path: The path of the file.

        If both file_id and path are supplied, an implementation may use
        either one.
        """
        return osutils.split_lines(self.get_file_text(file_id, path))

    def get_file_verifier(self, file_id, path=None, stat_value=None):
        """Return a verifier for a file.

        The default implementation returns a sha1.

        :param file_id: The handle for this file.
        :param path: The path that this file can be found at.
            These must point to the same object.
        :param stat_value: Optional stat value for the object
        :return: Tuple with verifier name and verifier data
        """
        return ("SHA1", self.get_file_sha1(file_id, path=path,
            stat_value=stat_value))

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        """Return the SHA1 file for a file.

        :note: callers should use get_file_verifier instead
            where possible, as the underlying repository implementation may
            have quicker access to a non-sha1 verifier.

        :param file_id: The handle for this file.
        :param path: The path that this file can be found at.
            These must point to the same object.
        :param stat_value: Optional stat value for the object
        """
        raise NotImplementedError(self.get_file_sha1)

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

    def is_executable(self, file_id, path=None):
        """Check if a file is executable.

        :param file_id: The handle for this file.
        :param path: The path that this file can be found at.
            These must point to the same object.
        """
        raise NotImplementedError(self.is_executable)

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

    def get_symlink_target(self, file_id, path=None):
        """Get the target for a given file_id.

        It is assumed that the caller already knows that file_id is referencing
        a symlink.
        :param file_id: Handle for the symlink entry.
        :param path: The path of the file.
        If both file_id and path are supplied, an implementation may use
        either one.
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
        from bzrlib import versionedfile
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

    def _get_file_revision(self, file_id, vf, tree_revision):
        """Ensure that file_id, tree_revision is in vf to plan the merge."""

        if getattr(self, '_repository', None) is None:
            last_revision = tree_revision
            parent_keys = [(file_id, t.get_file_revision(file_id)) for t in
                self._iter_parent_trees()]
            vf.add_lines((file_id, last_revision), parent_keys,
                         self.get_file_lines(file_id))
            repo = self.branch.repository
            base_vf = repo.texts
        else:
            last_revision = self.get_file_revision(file_id)
            base_vf = self._repository.texts
        if base_vf not in vf.fallback_versionedfiles:
            vf.fallback_versionedfiles.append(base_vf)
        return last_revision

    def _check_retrieved(self, ie, f):
        if not __debug__:
            return
        fp = osutils.fingerprint_file(f)
        f.seek(0)

        if ie.text_size is not None:
            if ie.text_size != fp['size']:
                raise errors.BzrError(
                        "mismatched size for file %r in %r" %
                        (ie.file_id, self._store),
                        ["inventory expects %d bytes" % ie.text_size,
                         "file is actually %d bytes" % fp['size'],
                         "store is probably damaged/corrupt"])

        if ie.text_sha1 != fp['sha1']:
            raise errors.BzrError("wrong SHA-1 for file %r in %r" %
                    (ie.file_id, self._store),
                    ["inventory expects %s" % ie.text_sha1,
                     "file is actually %s" % fp['sha1'],
                     "store is probably damaged/corrupt"])

    def path2id(self, path):
        """Return the id for path in this tree."""
        raise NotImplementedError(self.path2id)

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

    def iter_children(self, file_id):
        """Iterate over the file ids of the children of an entry.

        :param file_id: File id of the entry
        :return: Iterator over child file ids.
        """
        raise NotImplementedError(self.iter_children)

    def lock_read(self):
        """Lock this tree for multiple read only operations.

        :return: A bzrlib.lock.LogicalLockResult.
        """
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
        raise NotImplementedError(self.filter_unversioned_files)

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

    def supports_content_filtering(self):
        return False

    def _content_filter_stack(self, path=None, file_id=None):
        """The stack of content filters for a path if filtering is supported.

        Readers will be applied in first-to-last order.
        Writers will be applied in last-to-first order.
        Either the path or the file-id needs to be provided.

        :param path: path relative to the root of the tree
            or None if unknown
        :param file_id: file_id or None if unknown
        :return: the list of filters - [] if there are none
        """
        filter_pref_names = filters._get_registered_names()
        if len(filter_pref_names) == 0:
            return []
        if path is None:
            path = self.id2path(file_id)
        prefs = self.iter_search_rules([path], filter_pref_names).next()
        stk = filters._get_filter_stack_for(prefs)
        if 'filters' in debug.debug_flags:
            trace.note(gettext("*** {0} content-filter: {1} => {2!r}").format(path,prefs,stk))
        return stk

    def _content_filter_stack_provider(self):
        """A function that returns a stack of ContentFilters.

        The function takes a path (relative to the top of the tree) and a
        file-id as parameters.

        :return: None if content filtering is not supported by this tree.
        """
        if self.supports_content_filtering():
            return lambda path, file_id: \
                    self._content_filter_stack(path, file_id)
        else:
            return None

    def iter_search_rules(self, path_names, pref_names=None,
        _default_searcher=None):
        """Find the preferences for filenames in a tree.

        :param path_names: an iterable of paths to find attributes for.
          Paths are given relative to the root of the tree.
        :param pref_names: the list of preferences to lookup - None for all
        :param _default_searcher: private parameter to assist testing - don't use
        :return: an iterator of tuple sequences, one per path-name.
          See _RulesSearcher.get_items for details on the tuple sequence.
        """
        if _default_searcher is None:
            _default_searcher = rules._per_user_searcher
        searcher = self._get_rules_searcher(_default_searcher)
        if searcher is not None:
            if pref_names is not None:
                for path in path_names:
                    yield searcher.get_selected_items(path, pref_names)
            else:
                for path in path_names:
                    yield searcher.get_items(path)

    def _get_rules_searcher(self, default_searcher):
        """Get the RulesSearcher for this tree given the default one."""
        searcher = default_searcher
        return searcher


class InventoryTree(Tree):
    """A tree that relies on an inventory for its metadata.

    Trees contain an `Inventory` object, and also know how to retrieve
    file texts mentioned in the inventory, either from a working
    directory or from a store.

    It is possible for trees to contain files that are not described
    in their inventory or vice versa; for this use `filenames()`.

    Subclasses should set the _inventory attribute, which is considered
    private to external API users.
    """

    def get_canonical_inventory_paths(self, paths):
        """Like get_canonical_inventory_path() but works on multiple items.

        :param paths: A sequence of paths relative to the root of the tree.
        :return: A list of paths, with each item the corresponding input path
        adjusted to account for existing elements that match case
        insensitively.
        """
        return list(self._yield_canonical_inventory_paths(paths))

    def get_canonical_inventory_path(self, path):
        """Returns the first inventory item that case-insensitively matches path.

        If a path matches exactly, it is returned. If no path matches exactly
        but more than one path matches case-insensitively, it is implementation
        defined which is returned.

        If no path matches case-insensitively, the input path is returned, but
        with as many path entries that do exist changed to their canonical
        form.

        If you need to resolve many names from the same tree, you should
        use get_canonical_inventory_paths() to avoid O(N) behaviour.

        :param path: A paths relative to the root of the tree.
        :return: The input path adjusted to account for existing elements
        that match case insensitively.
        """
        return self._yield_canonical_inventory_paths([path]).next()

    def _yield_canonical_inventory_paths(self, paths):
        for path in paths:
            # First, if the path as specified exists exactly, just use it.
            if self.path2id(path) is not None:
                yield path
                continue
            # go walkin...
            cur_id = self.get_root_id()
            cur_path = ''
            bit_iter = iter(path.split("/"))
            for elt in bit_iter:
                lelt = elt.lower()
                new_path = None
                for child in self.iter_children(cur_id):
                    try:
                        # XXX: it seem like if the child is known to be in the
                        # tree, we shouldn't need to go from its id back to
                        # its path -- mbp 2010-02-11
                        #
                        # XXX: it seems like we could be more efficient
                        # by just directly looking up the original name and
                        # only then searching all children; also by not
                        # chopping paths so much. -- mbp 2010-02-11
                        child_base = os.path.basename(self.id2path(child))
                        if (child_base == elt):
                            # if we found an exact match, we can stop now; if
                            # we found an approximate match we need to keep
                            # searching because there might be an exact match
                            # later.  
                            cur_id = child
                            new_path = osutils.pathjoin(cur_path, child_base)
                            break
                        elif child_base.lower() == lelt:
                            cur_id = child
                            new_path = osutils.pathjoin(cur_path, child_base)
                    except errors.NoSuchId:
                        # before a change is committed we can see this error...
                        continue
                if new_path:
                    cur_path = new_path
                else:
                    # got to the end of this directory and no entries matched.
                    # Return what matched so far, plus the rest as specified.
                    cur_path = osutils.pathjoin(cur_path, elt, *list(bit_iter))
                    break
            yield cur_path
        # all done.

    @deprecated_method(deprecated_in((2, 5, 0)))
    def _get_inventory(self):
        return self._inventory

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def _get_root_inventory(self):
        return self._inventory

    root_inventory = property(_get_root_inventory,
        doc="Root inventory of this tree")

    def _unpack_file_id(self, file_id):
        """Find the inventory and inventory file id for a tree file id.

        :param file_id: The tree file id, as bytestring or tuple
        :return: Inventory and inventory file id
        """
        if isinstance(file_id, tuple):
            if len(file_id) != 1:
                raise ValueError("nested trees not yet supported: %r" % file_id)
            file_id = file_id[0]
        return self.root_inventory, file_id

    @needs_read_lock
    def path2id(self, path):
        """Return the id for path in this tree."""
        return self._path2inv_file_id(path)[1]

    def _path2inv_file_id(self, path):
        """Lookup a inventory and inventory file id by path.

        :param path: Path to look up
        :return: tuple with inventory and inventory file id
        """
        # FIXME: Support nested trees
        return self.root_inventory, self.root_inventory.path2id(path)

    def id2path(self, file_id):
        """Return the path for a file id.

        :raises NoSuchId:
        """
        inventory, file_id = self._unpack_file_id(file_id)
        return inventory.id2path(file_id)

    def has_id(self, file_id):
        inventory, file_id = self._unpack_file_id(file_id)
        return inventory.has_id(file_id)

    def has_or_had_id(self, file_id):
        inventory, file_id = self._unpack_file_id(file_id)
        return inventory.has_id(file_id)

    def all_file_ids(self):
        return set(
            [entry.file_id for path, entry in self.iter_entries_by_dir()])

    @deprecated_method(deprecated_in((2, 4, 0)))
    def __iter__(self):
        return iter(self.all_file_ids())

    def filter_unversioned_files(self, paths):
        """Filter out paths that are versioned.

        :return: set of paths.
        """
        # NB: we specifically *don't* call self.has_filename, because for
        # WorkingTrees that can indicate files that exist on disk but that
        # are not versioned.
        return set((p for p in paths if self.path2id(p) is None))

    @needs_read_lock
    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        """Walk the tree in 'by_dir' order.

        This will yield each entry in the tree as a (path, entry) tuple.
        The order that they are yielded is:

        See Tree.iter_entries_by_dir for details.

        :param yield_parents: If True, yield the parents from the root leading
            down to specific_file_ids that have been requested. This has no
            impact if specific_file_ids is None.
        """
        if specific_file_ids is None:
            inventory_file_ids = None
        else:
            inventory_file_ids = []
            for tree_file_id in specific_file_ids:
                inventory, inv_file_id = self._unpack_file_id(tree_file_id)
                if not inventory is self.root_inventory: # for now
                    raise AssertionError("%r != %r" % (
                        inventory, self.root_inventory))
                inventory_file_ids.append(inv_file_id)
        # FIXME: Handle nested trees
        return self.root_inventory.iter_entries_by_dir(
            specific_file_ids=inventory_file_ids, yield_parents=yield_parents)

    @needs_read_lock
    def iter_child_entries(self, file_id, path=None):
        inv, inv_file_id = self._unpack_file_id(file_id)
        return inv[inv_file_id].children.itervalues()

    @deprecated_method(deprecated_in((2, 5, 0)))
    def get_file_by_path(self, path):
        return self.get_file(self.path2id(path), path)

    def iter_children(self, file_id, path=None):
        """See Tree.iter_children."""
        entry = self.iter_entries_by_dir([file_id]).next()[1]
        for child in getattr(entry, 'children', {}).itervalues():
            yield child.file_id


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
                if not tree.has_or_had_id(file_id):
                    continue
                for child_id in tree.iter_children(file_id):
                    if child_id not in interesting_ids:
                        new_pending.add(child_id)
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

    # Formats that will be used to test this InterTree. If both are
    # None, this InterTree will not be tested (e.g. because a complex
    # setup is required)
    _matching_from_tree_format = None
    _matching_to_tree_format = None

    _optimisers = []

    @classmethod
    def is_compatible(kls, source, target):
        # The default implementation is naive and uses the public API, so
        # it works for all trees.
        return True

    def _changes_from_entries(self, source_entry, target_entry,
        source_path=None, target_path=None):
        """Generate a iter_changes tuple between source_entry and target_entry.

        :param source_entry: An inventory entry from self.source, or None.
        :param target_entry: An inventory entry from self.target, or None.
        :param source_path: The path of source_entry, if known. If not known
            it will be looked up.
        :param target_path: The path of target_entry, if known. If not known
            it will be looked up.
        :return: A tuple, item 0 of which is an iter_changes result tuple, and
            item 1 is True if there are any changes in the result tuple.
        """
        if source_entry is None:
            if target_entry is None:
                return None
            file_id = target_entry.file_id
        else:
            file_id = source_entry.file_id
        if source_entry is not None:
            source_versioned = True
            source_name = source_entry.name
            source_parent = source_entry.parent_id
            if source_path is None:
                source_path = self.source.id2path(file_id)
            source_kind, source_executable, source_stat = \
                self.source._comparison_data(source_entry, source_path)
        else:
            source_versioned = False
            source_name = None
            source_parent = None
            source_kind = None
            source_executable = None
        if target_entry is not None:
            target_versioned = True
            target_name = target_entry.name
            target_parent = target_entry.parent_id
            if target_path is None:
                target_path = self.target.id2path(file_id)
            target_kind, target_executable, target_stat = \
                self.target._comparison_data(target_entry, target_path)
        else:
            target_versioned = False
            target_name = None
            target_parent = None
            target_kind = None
            target_executable = None
        versioned = (source_versioned, target_versioned)
        kind = (source_kind, target_kind)
        changed_content = False
        if source_kind != target_kind:
            changed_content = True
        elif source_kind == 'file':
            if not self.file_content_matches(file_id, file_id, source_path,
                    target_path, source_stat, target_stat):
                changed_content = True
        elif source_kind == 'symlink':
            if (self.source.get_symlink_target(file_id) !=
                self.target.get_symlink_target(file_id)):
                changed_content = True
        elif source_kind == 'tree-reference':
            if (self.source.get_reference_revision(file_id, source_path)
                != self.target.get_reference_revision(file_id, target_path)):
                    changed_content = True
        parent = (source_parent, target_parent)
        name = (source_name, target_name)
        executable = (source_executable, target_executable)
        if (changed_content is not False or versioned[0] != versioned[1]
            or parent[0] != parent[1] or name[0] != name[1] or
            executable[0] != executable[1]):
            changes = True
        else:
            changes = False
        return (file_id, (source_path, target_path), changed_content,
                versioned, parent, name, kind, executable), changes

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
            fake_entry = inventory.InventoryFile('unused', 'unused', 'unused')
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
        :param specific_files: An optional list of file paths to restrict the
            comparison to. When mapping filenames to ids, all matches in all
            trees (including optional extra_trees) are used, and all children
            of matched directories are included. The parents in the target tree
            of the specific files up to and including the root of the tree are
            always evaluated for changes too.
        :param want_unversioned: Should unversioned files be returned in the
            output. An unversioned file is defined as one with (False, False)
            for the versioned pair.
        """
        lookup_trees = [self.source]
        if extra_trees:
             lookup_trees.extend(extra_trees)
        # The ids of items we need to examine to insure delta consistency.
        precise_file_ids = set()
        changed_file_ids = []
        if specific_files == []:
            specific_file_ids = []
        else:
            specific_file_ids = self.target.paths2ids(specific_files,
                lookup_trees, require_versioned=require_versioned)
        if specific_files is not None:
            # reparented or added entries must have their parents included
            # so that valid deltas can be created. The seen_parents set
            # tracks the parents that we need to have.
            # The seen_dirs set tracks directory entries we've yielded.
            # After outputting version object in to_entries we set difference
            # the two seen sets and start checking parents.
            seen_parents = set()
            seen_dirs = set()
        if want_unversioned:
            all_unversioned = sorted([(p.split('/'), p) for p in
                                     self.target.extras()
                if specific_files is None or
                    osutils.is_inside_any(specific_files, p)])
            all_unversioned = collections.deque(all_unversioned)
        else:
            all_unversioned = collections.deque()
        to_paths = {}
        from_entries_by_dir = list(self.source.iter_entries_by_dir(
            specific_file_ids=specific_file_ids))
        from_data = dict((e.file_id, (p, e)) for p, e in from_entries_by_dir)
        to_entries_by_dir = list(self.target.iter_entries_by_dir(
            specific_file_ids=specific_file_ids))
        num_entries = len(from_entries_by_dir) + len(to_entries_by_dir)
        entry_count = 0
        # the unversioned path lookup only occurs on real trees - where there
        # can be extras. So the fake_entry is solely used to look up
        # executable it values when execute is not supported.
        fake_entry = inventory.InventoryFile('unused', 'unused', 'unused')
        for target_path, target_entry in to_entries_by_dir:
            while (all_unversioned and
                all_unversioned[0][0] < target_path.split('/')):
                unversioned_path = all_unversioned.popleft()
                target_kind, target_executable, target_stat = \
                    self.target._comparison_data(fake_entry, unversioned_path[1])
                yield (None, (None, unversioned_path[1]), True, (False, False),
                    (None, None),
                    (None, unversioned_path[0][-1]),
                    (None, target_kind),
                    (None, target_executable))
            source_path, source_entry = from_data.get(target_entry.file_id,
                (None, None))
            result, changes = self._changes_from_entries(source_entry,
                target_entry, source_path=source_path, target_path=target_path)
            to_paths[result[0]] = result[1][1]
            entry_count += 1
            if result[3][0]:
                entry_count += 1
            if pb is not None:
                pb.update('comparing files', entry_count, num_entries)
            if changes or include_unchanged:
                if specific_file_ids is not None:
                    new_parent_id = result[4][1]
                    precise_file_ids.add(new_parent_id)
                    changed_file_ids.append(result[0])
                yield result
            # Ensure correct behaviour for reparented/added specific files.
            if specific_files is not None:
                # Record output dirs
                if result[6][1] == 'directory':
                    seen_dirs.add(result[0])
                # Record parents of reparented/added entries.
                versioned = result[3]
                parents = result[4]
                if not versioned[0] or parents[0] != parents[1]:
                    seen_parents.add(parents[1])
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
        # Yield all remaining source paths
        for path, from_entry in from_entries_by_dir:
            file_id = from_entry.file_id
            if file_id in to_paths:
                # already returned
                continue
            if not self.target.has_id(file_id):
                # common case - paths we have not emitted are not present in
                # target.
                to_path = None
            else:
                to_path = self.target.id2path(file_id)
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
            changed_content = from_kind is not None
            # the parent's path is necessarily known at this point.
            changed_file_ids.append(file_id)
            yield(file_id, (path, to_path), changed_content, versioned, parent,
                  name, kind, executable)
        changed_file_ids = set(changed_file_ids)
        if specific_file_ids is not None:
            for result in self._handle_precise_ids(precise_file_ids,
                changed_file_ids):
                yield result

    def _get_entry(self, tree, file_id):
        """Get an inventory entry from a tree, with missing entries as None.

        If the tree raises NotImplementedError on accessing .inventory, then
        this is worked around using iter_entries_by_dir on just the file id
        desired.

        :param tree: The tree to lookup the entry in.
        :param file_id: The file_id to lookup.
        """
        try:
            inventory = tree.root_inventory
        except NotImplementedError:
            # No inventory available.
            try:
                iterator = tree.iter_entries_by_dir(specific_file_ids=[file_id])
                return iterator.next()[1]
            except StopIteration:
                return None
        else:
            try:
                return inventory[file_id]
            except errors.NoSuchId:
                return None

    def _handle_precise_ids(self, precise_file_ids, changed_file_ids,
        discarded_changes=None):
        """Fill out a partial iter_changes to be consistent.

        :param precise_file_ids: The file ids of parents that were seen during
            the iter_changes.
        :param changed_file_ids: The file ids of already emitted items.
        :param discarded_changes: An optional dict of precalculated
            iter_changes items which the partial iter_changes had not output
            but had calculated.
        :return: A generator of iter_changes items to output.
        """
        # process parents of things that had changed under the users
        # requested paths to prevent incorrect paths or parent ids which
        # aren't in the tree.
        while precise_file_ids:
            precise_file_ids.discard(None)
            # Don't emit file_ids twice
            precise_file_ids.difference_update(changed_file_ids)
            if not precise_file_ids:
                break
            # If the there was something at a given output path in source, we
            # have to include the entry from source in the delta, or we would
            # be putting this entry into a used path.
            paths = []
            for parent_id in precise_file_ids:
                try:
                    paths.append(self.target.id2path(parent_id))
                except errors.NoSuchId:
                    # This id has been dragged in from the source by delta
                    # expansion and isn't present in target at all: we don't
                    # need to check for path collisions on it.
                    pass
            for path in paths:
                old_id = self.source.path2id(path)
                precise_file_ids.add(old_id)
            precise_file_ids.discard(None)
            current_ids = precise_file_ids
            precise_file_ids = set()
            # We have to emit all of precise_file_ids that have been altered.
            # We may have to output the children of some of those ids if any
            # directories have stopped being directories.
            for file_id in current_ids:
                # Examine file_id
                if discarded_changes:
                    result = discarded_changes.get(file_id)
                    old_entry = None
                else:
                    result = None
                if result is None:
                    old_entry = self._get_entry(self.source, file_id)
                    new_entry = self._get_entry(self.target, file_id)
                    result, changes = self._changes_from_entries(
                        old_entry, new_entry)
                else:
                    changes = True
                # Get this parents parent to examine.
                new_parent_id = result[4][1]
                precise_file_ids.add(new_parent_id)
                if changes:
                    if (result[6][0] == 'directory' and
                        result[6][1] != 'directory'):
                        # This stopped being a directory, the old children have
                        # to be included.
                        if old_entry is None:
                            # Reusing a discarded change.
                            old_entry = self._get_entry(self.source, file_id)
                        precise_file_ids.update(
                                self.source.iter_children(file_id))
                    changed_file_ids.add(result[0])
                    yield result

    @needs_read_lock
    def file_content_matches(self, source_file_id, target_file_id,
            source_path=None, target_path=None, source_stat=None, target_stat=None):
        """Check if two files are the same in the source and target trees.

        This only checks that the contents of the files are the same,
        it does not touch anything else.

        :param source_file_id: File id of the file in the source tree
        :param target_file_id: File id of the file in the target tree
        :param source_path: Path of the file in the source tree
        :param target_path: Path of the file in the target tree
        :param source_stat: Optional stat value of the file in the source tree
        :param target_stat: Optional stat value of the file in the target tree
        :return: Boolean indicating whether the files have the same contents
        """
        source_verifier_kind, source_verifier_data = self.source.get_file_verifier(
            source_file_id, source_path, source_stat)
        target_verifier_kind, target_verifier_data = self.target.get_file_verifier(
            target_file_id, target_path, target_stat)
        if source_verifier_kind == target_verifier_kind:
            return (source_verifier_data == target_verifier_data)
        # Fall back to SHA1 for now
        if source_verifier_kind != "SHA1":
            source_sha1 = self.source.get_file_sha1(source_file_id,
                    source_path, source_stat)
        else:
            source_sha1 = source_verifier_data
        if target_verifier_kind != "SHA1":
            target_sha1 = self.target.get_file_sha1(target_file_id,
                    target_path, target_stat)
        else:
            target_sha1 = target_verifier_data
        return (source_sha1 == target_sha1)

InterTree.register_optimiser(InterTree)


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
            cur_ie = other_tree.root_inventory[file_id]
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
