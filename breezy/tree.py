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

try:
    from collections.abc import deque
except ImportError:  # python < 3.7
    from collections import deque

from .lazy_import import lazy_import
lazy_import(globals(), """

from breezy import (
    conflicts as _mod_conflicts,
    debug,
    delta,
    filters,
    revision as _mod_revision,
    rules,
    trace,
    )
from breezy.i18n import gettext
""")

from . import (
    errors,
    lock,
    osutils,
    )
from .inter import InterObject
from .sixish import (
    text_type,
    viewvalues,
    )


class FileTimestampUnavailable(errors.BzrError):

    _fmt = "The filestamp for %(path)s is not available."

    internal_error = True

    def __init__(self, path):
        self.path = path


class MissingNestedTree(errors.BzrError):

    _fmt = "The nested tree for %(path)s can not be resolved."""

    def __init__(self, path):
        self.path = path


class TreeEntry(object):
    """An entry that implements the minimum interface used by commands.
    """

    __slots__ = []

    def __eq__(self, other):
        # yes, this is ugly, TODO: best practice __eq__ style.
        return (isinstance(other, TreeEntry)
                and other.__class__ == self.__class__)

    kind = None

    def kind_character(self):
        return "???"

    def is_unmodified(self, other):
        """Does this entry reference the same entry?

        This is mostly the same as __eq__, but returns False
        for entries without enough information (i.e. revision is None)
        """
        return False


class TreeDirectory(TreeEntry):
    """See TreeEntry. This is a directory in a working tree."""

    __slots__ = []

    kind = 'directory'

    def kind_character(self):
        return "/"


class TreeFile(TreeEntry):
    """See TreeEntry. This is a regular file in a working tree."""

    __slots__ = []

    kind = 'file'

    def kind_character(self):
        return ''


class TreeLink(TreeEntry):
    """See TreeEntry. This is a symlink in a working tree."""

    __slots__ = []

    kind = 'symlink'

    def kind_character(self):
        return ''


class TreeReference(TreeEntry):
    """See TreeEntry. This is a reference to a nested tree in a working tree."""

    __slots__ = []

    kind = 'tree-reference'

    def kind_character(self):
        return '+'


class TreeChange(object):
    """Describes the changes between the same item in two different trees."""

    __slots__ = ['file_id', 'path', 'changed_content', 'versioned', 'parent_id',
                 'name', 'kind', 'executable', 'copied']

    def __init__(self, file_id, path, changed_content, versioned, parent_id,
                 name, kind, executable, copied=False):
        self.file_id = file_id
        self.path = path
        self.changed_content = changed_content
        self.versioned = versioned
        self.parent_id = parent_id
        self.name = name
        self.kind = kind
        self.executable = executable
        self.copied = copied

    def __repr__(self):
        return "%s%r" % (self.__class__.__name__, self._as_tuple())

    def __len__(self):
        return len(self.__slots__)

    def _as_tuple(self):
        return (self.file_id, self.path, self.changed_content, self.versioned,
                self.parent_id, self.name, self.kind, self.executable, self.copied)

    def __eq__(self, other):
        if isinstance(other, TreeChange):
            return self._as_tuple() == other._as_tuple()
        if isinstance(other, tuple):
            return self._as_tuple() == other
        return False

    def __lt__(self, other):
        return self._as_tuple() < other._as_tuple()

    def meta_modified(self):
        if self.versioned == (True, True):
            return (self.executable[0] != self.executable[1])
        return False

    def is_reparented(self):
        return self.parent_id[0] != self.parent_id[1]

    def discard_new(self):
        return self.__class__(
            self.file_id, (self.path[0], None), self.changed_content,
            (self.versioned[0], None), (self.parent_id[0], None),
            (self.name[0], None), (self.kind[0], None),
            (self.executable[0], None),
            copied=False)


class Tree(object):
    """Abstract file tree.

    There are several subclasses:

    * `WorkingTree` exists as files on disk editable by the user.

    * `RevisionTree` is a tree as recorded at some point in the past.

    Trees can be compared, etc, regardless of whether they are working
    trees or versioned trees.
    """

    def supports_rename_tracking(self):
        """Whether this tree supports rename tracking.

        This defaults to True, but some implementations may want to override
        it.
        """
        return True

    def has_versioned_directories(self):
        """Whether this tree can contain explicitly versioned directories.

        This defaults to True, but some implementations may want to override
        it.
        """
        return True

    def supports_symlinks(self):
        """Does this tree support symbolic links?
        """
        return osutils.has_symlinks()

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
            mapping the contents of specific_files (paths) to their identities.
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
                                      extra_trees, require_versioned,
                                      want_unversioned=want_unversioned)

    def conflicts(self):
        """Get a list of the conflicts in the tree.

        Each conflict is an instance of breezy.conflicts.Conflict.
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

    def is_ignored(self, filename):
        """Check whether the filename is ignored by this tree.

        :param filename: The relative filename within the tree.
        :return: True if the filename is ignored.
        """
        return False

    def all_file_ids(self):
        """Iterate through all file ids, including ids for missing files."""
        raise NotImplementedError(self.all_file_ids)

    def all_versioned_paths(self):
        """Iterate through all paths, including paths for missing files."""
        raise NotImplementedError(self.all_versioned_paths)

    def id2path(self, file_id, recurse='down'):
        """Return the path for a file id.

        :raises NoSuchId:
        """
        raise NotImplementedError(self.id2path)

    def iter_entries_by_dir(self, specific_files=None, recurse_nested=False):
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

        If recurse_nested is enabled then nested trees are included as if
        they were a part of the tree. If is disabled then TreeReference
        objects (without any children) are yielded.
        """
        raise NotImplementedError(self.iter_entries_by_dir)

    def iter_child_entries(self, path):
        """Iterate over the children of a directory or tree reference.

        :param path: Path of the directory
        :raise NoSuchFile: When the path does not exist
        :return: Iterator over entries in the directory
        """
        raise NotImplementedError(self.iter_child_entries)

    def list_files(self, include_root=False, from_dir=None, recursive=True,
                   recurse_nested=False):
        """List all files in this tree.

        :param include_root: Whether to include the entry for the tree root
        :param from_dir: Directory under which to list files
        :param recursive: Whether to list files recursively
        :param recurse_nested: enter nested trees
        :return: iterator over tuples of
            (path, versioned, kind, inventory entry)
        """
        raise NotImplementedError(self.list_files)

    def iter_references(self):
        if self.supports_tree_reference():
            for path, entry in self.iter_entries_by_dir():
                if entry.kind == 'tree-reference':
                    yield path

    def get_containing_nested_tree(self, path):
        """Find the nested tree that contains a path.

        :return: tuple with (nested tree and path inside the nested tree)
        """
        for nested_path in self.iter_references():
            nested_path += '/'
            if path.startswith(nested_path):
                nested_tree = self.get_nested_tree(nested_path)
                return nested_tree, path[len(nested_path):]
        else:
            return None, None

    def get_nested_tree(self, path):
        """Open the nested tree at the specified path.

        :param path: Path from which to resolve tree reference.
        :return: A Tree object for the nested tree
        :raise MissingNestedTree: If the nested tree can not be resolved
        """
        raise NotImplementedError(self.get_nested_tree)

    def kind(self, path):
        raise NotImplementedError("Tree subclass %s must implement kind"
                                  % self.__class__.__name__)

    def stored_kind(self, path):
        """File kind stored for this path.

        May not match kind on disk for working trees.  Always available
        for versioned files, even when the file itself is missing.
        """
        return self.kind(path)

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

    def get_reference_revision(self, path, branch=None):
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

    def get_file(self, path):
        """Return a file object for the file path in the tree.
        """
        raise NotImplementedError(self.get_file)

    def get_file_with_stat(self, path):
        """Get a file handle and stat object for path.

        The default implementation returns (self.get_file, None) for backwards
        compatibility.

        :param path: The path of the file.
        :return: A tuple (file_handle, stat_value_or_None). If the tree has
            no stat facility, or need for a stat cache feedback during commit,
            it may return None for the second element of the tuple.
        """
        return (self.get_file(path), None)

    def get_file_text(self, path):
        """Return the byte content of a file.

        :param path: The path of the file.

        :returns: A single byte string for the whole file.
        """
        with self.get_file(path) as my_file:
            return my_file.read()

    def get_file_lines(self, path):
        """Return the content of a file, as lines.

        :param path: The path of the file.
        """
        return osutils.split_lines(self.get_file_text(path))

    def get_file_verifier(self, path, stat_value=None):
        """Return a verifier for a file.

        The default implementation returns a sha1.

        :param path: The path that this file can be found at.
            These must point to the same object.
        :param stat_value: Optional stat value for the object
        :return: Tuple with verifier name and verifier data
        """
        return ("SHA1", self.get_file_sha1(path, stat_value=stat_value))

    def get_file_sha1(self, path, stat_value=None):
        """Return the SHA1 file for a file.

        :note: callers should use get_file_verifier instead
            where possible, as the underlying repository implementation may
            have quicker access to a non-sha1 verifier.

        :param path: The path that this file can be found at.
        :param stat_value: Optional stat value for the object
        """
        raise NotImplementedError(self.get_file_sha1)

    def get_file_mtime(self, path):
        """Return the modification time for a file.

        :param path: The path that this file can be found at.
        """
        raise NotImplementedError(self.get_file_mtime)

    def get_file_size(self, path):
        """Return the size of a file in bytes.

        This applies only to regular files.  If invoked on directories or
        symlinks, it will return None.
        """
        raise NotImplementedError(self.get_file_size)

    def is_executable(self, path):
        """Check if a file is executable.

        :param path: The path that this file can be found at.
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

        :param desired_files: a list of (path, identifier) pairs
        """
        for path, identifier in desired_files:
            # We wrap the string in a tuple so that we can return an iterable
            # of bytestrings.  (Technically, a bytestring is also an iterable
            # of bytestrings, but iterating through each character is not
            # performant.)
            cur_file = (self.get_file_text(path),)
            yield identifier, cur_file

    def get_symlink_target(self, path):
        """Get the target for a given path.

        It is assumed that the caller already knows that path is referencing
        a symlink.
        :param path: The path of the file.
        :return: The path the symlink points to.
        """
        raise NotImplementedError(self.get_symlink_target)

    def annotate_iter(self, path,
                      default_revision=_mod_revision.CURRENT_REVISION):
        """Return an iterator of revision_id, line tuples.

        For working trees (and mutable trees in general), the special
        revision_id 'current:' will be used for lines that are new in this
        tree, e.g. uncommitted changes.
        :param path: The file to produce an annotated version from
        :param default_revision: For lines that don't match a basis, mark them
            with this revision id. Not all implementations will make use of
            this value.
        """
        raise NotImplementedError(self.annotate_iter)

    def path2id(self, path):
        """Return the id for path in this tree."""
        raise NotImplementedError(self.path2id)

    def is_versioned(self, path):
        """Check whether path is versioned.

        :param path: Path to check
        :return: boolean
        """
        return self.path2id(path) is not None

    def find_related_paths_across_trees(self, paths, trees=[],
                                        require_versioned=True):
        """Find related paths in tree corresponding to specified filenames in any
        of `lookup_trees`.

        All matches in all trees will be used, and all children of matched
        directories will be used.

        :param paths: The filenames to find related paths for (if None, returns
            None)
        :param trees: The trees to find file_ids within
        :param require_versioned: if true, all specified filenames must occur in
            at least one tree.
        :return: a set of paths for the specified filenames and their children
            in `tree`
        """
        raise NotImplementedError(self.find_related_paths_across_trees)

    def lock_read(self):
        """Lock this tree for multiple read only operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        return lock.LogicalLockResult(self.unlock)

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
        return set(p for p in paths if not self.is_versioned(p))

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

    def _content_filter_stack(self, path=None):
        """The stack of content filters for a path if filtering is supported.

        Readers will be applied in first-to-last order.
        Writers will be applied in last-to-first order.
        Either the path or the file-id needs to be provided.

        :param path: path relative to the root of the tree
            or None if unknown
        :return: the list of filters - [] if there are none
        """
        filter_pref_names = filters._get_registered_names()
        if len(filter_pref_names) == 0:
            return []
        prefs = next(self.iter_search_rules([path], filter_pref_names))
        stk = filters._get_filter_stack_for(prefs)
        if 'filters' in debug.debug_flags:
            trace.note(
                gettext("*** {0} content-filter: {1} => {2!r}").format(path, prefs, stk))
        return stk

    def _content_filter_stack_provider(self):
        """A function that returns a stack of ContentFilters.

        The function takes a path (relative to the top of the tree) and a
        file-id as parameters.

        :return: None if content filtering is not supported by this tree.
        """
        if self.supports_content_filtering():
            return self._content_filter_stack
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

    def archive(self, format, name, root='', subdir=None,
                force_mtime=None):
        """Create an archive of this tree.

        :param format: Format name (e.g. 'tar')
        :param name: target file name
        :param root: Root directory name (or None)
        :param subdir: Subdirectory to export (or None)
        :return: Iterator over archive chunks
        """
        from .archive import create_archive
        with self.lock_read():
            return create_archive(format, self, name, root,
                                  subdir, force_mtime=force_mtime)

    @classmethod
    def versionable_kind(cls, kind):
        """Check if this tree support versioning a specific file kind."""
        return (kind in ('file', 'directory', 'symlink', 'tree-reference'))


class InterTree(InterObject):
    """This class represents operations taking place between two Trees.

    Its instances have methods like 'compare' and contain references to the
    source and target trees these operations are to be carried out on.

    Clients of breezy should not need to use InterTree directly, rather they
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

    def _changes_from_entries(self, source_entry, target_entry, source_path,
                              target_path):
        """Generate a iter_changes tuple between source_entry and target_entry.

        :param source_entry: An inventory entry from self.source, or None.
        :param target_entry: An inventory entry from self.target, or None.
        :param source_path: The path of source_entry.
        :param target_path: The path of target_entry.
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
            if not self.file_content_matches(
                    source_path, target_path,
                    source_stat, target_stat):
                changed_content = True
        elif source_kind == 'symlink':
            if (self.source.get_symlink_target(source_path) !=
                    self.target.get_symlink_target(target_path)):
                changed_content = True
        elif source_kind == 'tree-reference':
            if (self.source.get_reference_revision(source_path)
                    != self.target.get_reference_revision(target_path)):
                changed_content = True
        parent = (source_parent, target_parent)
        name = (source_name, target_name)
        executable = (source_executable, target_executable)
        if (changed_content is not False or versioned[0] != versioned[1] or
            parent[0] != parent[1] or name[0] != name[1] or
                executable[0] != executable[1]):
            changes = True
        else:
            changes = False
        return TreeChange(
            file_id, (source_path, target_path), changed_content,
            versioned, parent, name, kind, executable), changes

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
        with self.lock_read():
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
        if not extra_trees:
            extra_trees = []
        else:
            extra_trees = list(extra_trees)
        # The ids of items we need to examine to insure delta consistency.
        precise_file_ids = set()
        changed_file_ids = []
        if specific_files == []:
            target_specific_files = []
            source_specific_files = []
        else:
            target_specific_files = self.target.find_related_paths_across_trees(
                specific_files, [self.source] + extra_trees,
                require_versioned=require_versioned)
            source_specific_files = self.source.find_related_paths_across_trees(
                specific_files, [self.target] + extra_trees,
                require_versioned=require_versioned)
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
            all_unversioned = deque(all_unversioned)
        else:
            all_unversioned = deque()
        to_paths = {}
        from_entries_by_dir = list(self.source.iter_entries_by_dir(
            specific_files=source_specific_files))
        from_data = dict(from_entries_by_dir)
        to_entries_by_dir = list(self.target.iter_entries_by_dir(
            specific_files=target_specific_files))
        path_equivs = self.find_source_paths([p for p, e in to_entries_by_dir])
        num_entries = len(from_entries_by_dir) + len(to_entries_by_dir)
        entry_count = 0
        # the unversioned path lookup only occurs on real trees - where there
        # can be extras. So the fake_entry is solely used to look up
        # executable it values when execute is not supported.
        fake_entry = TreeFile()
        for target_path, target_entry in to_entries_by_dir:
            while (all_unversioned and
                   all_unversioned[0][0] < target_path.split('/')):
                unversioned_path = all_unversioned.popleft()
                target_kind, target_executable, target_stat = \
                    self.target._comparison_data(
                        fake_entry, unversioned_path[1])
                yield TreeChange(
                    None, (None, unversioned_path[1]), True, (False, False),
                    (None, None),
                    (None, unversioned_path[0][-1]),
                    (None, target_kind),
                    (None, target_executable))
            source_path = path_equivs[target_path]
            if source_path is not None:
                source_entry = from_data.get(source_path)
            else:
                source_entry = None
            result, changes = self._changes_from_entries(
                source_entry, target_entry, source_path=source_path, target_path=target_path)
            to_paths[result.file_id] = result.path[1]
            entry_count += 1
            if result.versioned[0]:
                entry_count += 1
            if pb is not None:
                pb.update('comparing files', entry_count, num_entries)
            if changes or include_unchanged:
                if specific_files is not None:
                    precise_file_ids.add(result.parent_id[1])
                    changed_file_ids.append(result.file_id)
                yield result
            # Ensure correct behaviour for reparented/added specific files.
            if specific_files is not None:
                # Record output dirs
                if result.kind[1] == 'directory':
                    seen_dirs.add(result.file_id)
                # Record parents of reparented/added entries.
                if not result.versioned[0] or result.is_reparented():
                    seen_parents.add(result.parent_id[1])
        while all_unversioned:
            # yield any trailing unversioned paths
            unversioned_path = all_unversioned.popleft()
            to_kind, to_executable, to_stat = \
                self.target._comparison_data(fake_entry, unversioned_path[1])
            yield TreeChange(
                None, (None, unversioned_path[1]), True, (False, False),
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
            to_path = self.find_target_path(path)
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
            yield TreeChange(
                file_id, (path, to_path), changed_content, versioned, parent,
                name, kind, executable)
        changed_file_ids = set(changed_file_ids)
        if specific_files is not None:
            for result in self._handle_precise_ids(precise_file_ids,
                                                   changed_file_ids):
                yield result

    @staticmethod
    def _get_entry(tree, path):
        """Get an inventory entry from a tree, with missing entries as None.

        If the tree raises NotImplementedError on accessing .inventory, then
        this is worked around using iter_entries_by_dir on just the file id
        desired.

        :param tree: The tree to lookup the entry in.
        :param path: The path to look up
        """
        # No inventory available.
        try:
            iterator = tree.iter_entries_by_dir(specific_files=[path])
            return next(iterator)[1]
        except StopIteration:
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
                    source_entry = None
                else:
                    result = None
                if result is None:
                    try:
                        source_path = self.source.id2path(file_id)
                    except errors.NoSuchId:
                        source_path = None
                        source_entry = None
                    else:
                        source_entry = self._get_entry(
                            self.source, source_path)
                    try:
                        target_path = self.target.id2path(file_id)
                    except errors.NoSuchId:
                        target_path = None
                        target_entry = None
                    else:
                        target_entry = self._get_entry(
                            self.target, target_path)
                    result, changes = self._changes_from_entries(
                        source_entry, target_entry, source_path, target_path)
                else:
                    changes = True
                # Get this parents parent to examine.
                new_parent_id = result.parent_id[1]
                precise_file_ids.add(new_parent_id)
                if changes:
                    if (result.kind[0] == 'directory' and
                            result.kind[1] != 'directory'):
                        # This stopped being a directory, the old children have
                        # to be included.
                        if source_entry is None:
                            # Reusing a discarded change.
                            source_entry = self._get_entry(
                                self.source, result.path[0])
                        precise_file_ids.update(
                            child.file_id
                            for child in self.source.iter_child_entries(result.path[0]))
                    changed_file_ids.add(result.file_id)
                    yield result

    def file_content_matches(
            self, source_path, target_path,
            source_stat=None, target_stat=None):
        """Check if two files are the same in the source and target trees.

        This only checks that the contents of the files are the same,
        it does not touch anything else.

        :param source_path: Path of the file in the source tree
        :param target_path: Path of the file in the target tree
        :param source_stat: Optional stat value of the file in the source tree
        :param target_stat: Optional stat value of the file in the target tree
        :return: Boolean indicating whether the files have the same contents
        """
        with self.lock_read():
            source_verifier_kind, source_verifier_data = (
                self.source.get_file_verifier(source_path, source_stat))
            target_verifier_kind, target_verifier_data = (
                self.target.get_file_verifier(
                    target_path, target_stat))
            if source_verifier_kind == target_verifier_kind:
                return (source_verifier_data == target_verifier_data)
            # Fall back to SHA1 for now
            if source_verifier_kind != "SHA1":
                source_sha1 = self.source.get_file_sha1(
                    source_path, source_stat)
            else:
                source_sha1 = source_verifier_data
            if target_verifier_kind != "SHA1":
                target_sha1 = self.target.get_file_sha1(
                    target_path, target_stat)
            else:
                target_sha1 = target_verifier_data
            return (source_sha1 == target_sha1)

    def find_target_path(self, path, recurse='none'):
        """Find target tree path.

        :param path: Path to search for (exists in source)
        :return: path in target, or None if there is no equivalent path.
        :raise NoSuchFile: If the path doesn't exist in source
        """
        file_id = self.source.path2id(path)
        if file_id is None:
            raise errors.NoSuchFile(path)
        try:
            return self.target.id2path(file_id, recurse=recurse)
        except errors.NoSuchId:
            return None

    def find_source_path(self, path, recurse='none'):
        """Find the source tree path.

        :param path: Path to search for (exists in target)
        :return: path in source, or None if there is no equivalent path.
        :raise NoSuchFile: if the path doesn't exist in target
        """
        file_id = self.target.path2id(path)
        if file_id is None:
            raise errors.NoSuchFile(path)
        try:
            return self.source.id2path(file_id, recurse=recurse)
        except errors.NoSuchId:
            return None

    def find_target_paths(self, paths, recurse='none'):
        """Find target tree paths.

        :param paths: Iterable over paths in target to search for
        :return: Dictionary mapping from source paths to paths in target , or
            None if there is no equivalent path.
        """
        ret = {}
        for path in paths:
            ret[path] = self.find_target_path(path, recurse=recurse)
        return ret

    def find_source_paths(self, paths, recurse='none'):
        """Find source tree paths.

        :param paths: Iterable over paths in target to search for
        :return: Dictionary mapping from target paths to paths in source, or
            None if there is no equivalent path.
        """
        ret = {}
        for path in paths:
            ret[path] = self.find_source_path(path, recurse=recurse)
        return ret


InterTree.register_optimiser(InterTree)


def find_previous_paths(from_tree, to_tree, paths, recurse='none'):
    """Find previous tree paths.

    :param from_tree: From tree
    :param to_tree: To tree
    :param paths: Iterable over paths in from_tree to search for
    :return: Dictionary mapping from from_tree paths to paths in to_tree, or
        None if there is no equivalent path.
    """
    return InterTree.get(to_tree, from_tree).find_source_paths(paths, recurse=recurse)


def find_previous_path(from_tree, to_tree, path, recurse='none'):
    """Find previous tree path.

    :param from_tree: From tree
    :param to_tree: To tree
    :param path: Path to search for (exists in from_tree)
    :return: path in to_tree, or None if there is no equivalent path.
    :raise NoSuchFile: If the path doesn't exist in from_tree
    """
    return InterTree.get(to_tree, from_tree).find_source_path(
        path, recurse=recurse)


def get_canonical_path(tree, path, normalize):
    """Find the canonical path of an item, ignoring case.

    :param tree: Tree to traverse
    :param path: Case-insensitive path to look up
    :param normalize: Function to normalize a filename for comparison
    :return: The canonical path
    """
    # go walkin...
    cur_path = ''
    bit_iter = iter(path.split("/"))
    for elt in bit_iter:
        lelt = normalize(elt)
        new_path = None
        try:
            for child in tree.iter_child_entries(cur_path):
                try:
                    if child.name == elt:
                        # if we found an exact match, we can stop now; if
                        # we found an approximate match we need to keep
                        # searching because there might be an exact match
                        # later.
                        new_path = osutils.pathjoin(cur_path, child.name)
                        break
                    elif normalize(child.name) == lelt:
                        new_path = osutils.pathjoin(cur_path, child.name)
                except errors.NoSuchId:
                    # before a change is committed we can see this error...
                    continue
        except errors.NotADirectory:
            pass
        if new_path:
            cur_path = new_path
        else:
            # got to the end of this directory and no entries matched.
            # Return what matched so far, plus the rest as specified.
            cur_path = osutils.pathjoin(cur_path, elt, *list(bit_iter))
            break
    return cur_path
