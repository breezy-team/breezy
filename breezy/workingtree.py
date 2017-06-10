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

"""WorkingTree object and friends.

A WorkingTree represents the editable working copy of a branch.
Operations which represent the WorkingTree are also done here,
such as renaming or adding files.

At the moment every WorkingTree has its own branch.  Remote
WorkingTrees aren't supported.

To get a WorkingTree, call bzrdir.open_workingtree() or
WorkingTree.open(dir).
"""

from __future__ import absolute_import

import errno
import os
import re
import sys

import breezy

from .lazy_import import lazy_import
lazy_import(globals(), """
from bisect import bisect_left
import itertools
import operator
import stat

from breezy import (
    branch,
    conflicts as _mod_conflicts,
    controldir,
    errors,
    filters as _mod_filters,
    generate_ids,
    globbing,
    ignores,
    merge,
    revision as _mod_revision,
    shelf,
    transform,
    transport,
    ui,
    views,
    )
""")

from . import (
    osutils,
    )
from .decorators import needs_read_lock, needs_write_lock
from .i18n import gettext
from . import mutabletree
from .mutabletree import needs_tree_write_lock
from .trace import mutter, note


ERROR_PATH_NOT_FOUND = 3    # WindowsError errno code, equivalent to ENOENT


class TreeEntry(object):
    """An entry that implements the minimum interface used by commands.

    This needs further inspection, it may be better to have
    InventoryEntries without ids - though that seems wrong. For now,
    this is a parallel hierarchy to InventoryEntry, and needs to become
    one of several things: decorates to that hierarchy, children of, or
    parents of it.
    Another note is that these objects are currently only used when there is
    no InventoryEntry available - i.e. for unversioned objects.
    Perhaps they should be UnversionedEntry et al. ? - RBC 20051003
    """

    def __eq__(self, other):
        # yes, this us ugly, TODO: best practice __eq__ style.
        return (isinstance(other, TreeEntry)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return "???"


class TreeDirectory(TreeEntry):
    """See TreeEntry. This is a directory in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeDirectory)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return "/"


class TreeFile(TreeEntry):
    """See TreeEntry. This is a regular file in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeFile)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class TreeLink(TreeEntry):
    """See TreeEntry. This is a symlink in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeLink)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class WorkingTree(mutabletree.MutableTree,
    controldir.ControlComponent):
    """Working copy tree.

    :ivar basedir: The root of the tree on disk. This is a unicode path object
        (as opposed to a URL).
    """

    # override this to set the strategy for storing views
    def _make_views(self):
        return views.DisabledViews(self)

    def __init__(self, basedir='.',
                 branch=None,
                 _internal=False,
                 _transport=None,
                 _format=None,
                 _bzrdir=None):
        """Construct a WorkingTree instance. This is not a public API.

        :param branch: A branch to override probing for the branch.
        """
        self._format = _format
        self.bzrdir = _bzrdir
        if not _internal:
            raise errors.BzrError("Please use bzrdir.open_workingtree or "
                "WorkingTree.open() to obtain a WorkingTree.")
        basedir = osutils.safe_unicode(basedir)
        mutter("opening working tree %r", basedir)
        if branch is not None:
            self._branch = branch
        else:
            self._branch = self.bzrdir.open_branch()
        self.basedir = osutils.realpath(basedir)
        self._transport = _transport
        self._rules_searcher = None
        self.views = self._make_views()

    @property
    def user_transport(self):
        return self.bzrdir.user_transport

    @property
    def control_transport(self):
        return self._transport

    def is_control_filename(self, filename):
        """True if filename is the name of a control file in this tree.

        :param filename: A filename within the tree. This is a relative path
            from the root of this tree.

        This is true IF and ONLY IF the filename is part of the meta data
        that bzr controls in this tree. I.E. a random .bzr directory placed
        on disk will not be a control file for this tree.
        """
        return self.bzrdir.is_control_filename(filename)

    branch = property(
        fget=lambda self: self._branch,
        doc="""The branch this WorkingTree is connected to.

            This cannot be set - it is reflective of the actual disk structure
            the working tree has been constructed from.
            """)

    def has_versioned_directories(self):
        """See `Tree.has_versioned_directories`."""
        return self._format.supports_versioned_directories

    def _supports_executable(self):
        if sys.platform == 'win32':
            return False
        # FIXME: Ideally this should check the file system
        return True

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        raise NotImplementedError(self.break_lock)

    def requires_rich_root(self):
        return self._format.requires_rich_root

    def supports_tree_reference(self):
        return False

    def supports_content_filtering(self):
        return self._format.supports_content_filtering()

    def supports_views(self):
        return self.views.supports_views()

    def get_config_stack(self):
        """Retrieve the config stack for this tree.

        :return: A ``breezy.config.Stack``
        """
        # For the moment, just provide the branch config stack.
        return self.branch.get_config_stack()

    @staticmethod
    def open(path=None, _unsupported=False):
        """Open an existing working tree at path.

        """
        if path is None:
            path = osutils.getcwd()
        control = controldir.ControlDir.open(path, _unsupported=_unsupported)
        return control.open_workingtree(unsupported=_unsupported)

    @staticmethod
    def open_containing(path=None):
        """Open an existing working tree which has its root about path.

        This probes for a working tree at path and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into /.  If there isn't one, raises NotBranchError.
        TODO: give this a new exception.
        If there is one, it is returned, along with the unused portion of path.

        :return: The WorkingTree that contains 'path', and the rest of path
        """
        if path is None:
            path = osutils.getcwd()
        control, relpath = controldir.ControlDir.open_containing(path)
        return control.open_workingtree(), relpath

    @staticmethod
    def open_containing_paths(file_list, default_directory=None,
                              canonicalize=True, apply_view=True):
        """Open the WorkingTree that contains a set of paths.

        Fail if the paths given are not all in a single tree.

        This is used for the many command-line interfaces that take a list of
        any number of files and that require they all be in the same tree.
        """
        if default_directory is None:
            default_directory = u'.'
        # recommended replacement for builtins.internal_tree_files
        if file_list is None or len(file_list) == 0:
            tree = WorkingTree.open_containing(default_directory)[0]
            # XXX: doesn't really belong here, and seems to have the strange
            # side effect of making it return a bunch of files, not the whole
            # tree -- mbp 20100716
            if tree.supports_views() and apply_view:
                view_files = tree.views.lookup_view()
                if view_files:
                    file_list = view_files
                    view_str = views.view_display_str(view_files)
                    note(gettext("Ignoring files outside view. View is %s") % view_str)
            return tree, file_list
        if default_directory == u'.':
            seed = file_list[0]
        else:
            seed = default_directory
            file_list = [osutils.pathjoin(default_directory, f)
                         for f in file_list]
        tree = WorkingTree.open_containing(seed)[0]
        return tree, tree.safe_relpath_files(file_list, canonicalize,
                                             apply_view=apply_view)

    def safe_relpath_files(self, file_list, canonicalize=True, apply_view=True):
        """Convert file_list into a list of relpaths in tree.

        :param self: A tree to operate on.
        :param file_list: A list of user provided paths or None.
        :param apply_view: if True and a view is set, apply it or check that
            specified files are within it
        :return: A list of relative paths.
        :raises errors.PathNotChild: When a provided path is in a different self
            than self.
        """
        if file_list is None:
            return None
        if self.supports_views() and apply_view:
            view_files = self.views.lookup_view()
        else:
            view_files = []
        new_list = []
        # self.relpath exists as a "thunk" to osutils, but canonical_relpath
        # doesn't - fix that up here before we enter the loop.
        if canonicalize:
            fixer = lambda p: osutils.canonical_relpath(self.basedir, p)
        else:
            fixer = self.relpath
        for filename in file_list:
            relpath = fixer(osutils.dereference_path(filename))
            if view_files and not osutils.is_inside_any(view_files, relpath):
                raise errors.FileOutsideView(filename, view_files)
            new_list.append(relpath)
        return new_list

    @staticmethod
    def open_downlevel(path=None):
        """Open an unsupported working tree.

        Only intended for advanced situations like upgrading part of a bzrdir.
        """
        return WorkingTree.open(path, _unsupported=True)

    @staticmethod
    def find_trees(location):
        def list_current(transport):
            return [d for d in transport.list_dir('') if d != '.bzr']
        def evaluate(bzrdir):
            try:
                tree = bzrdir.open_workingtree()
            except errors.NoWorkingTree:
                return True, None
            else:
                return True, tree
        t = transport.get_transport(location)
        iterator = controldir.ControlDir.find_bzrdirs(t, evaluate=evaluate,
                                              list_current=list_current)
        return [tr for tr in iterator if tr is not None]

    def __repr__(self):
        return "<%s of %s>" % (self.__class__.__name__,
                               getattr(self, 'basedir', None))

    def abspath(self, filename):
        return osutils.pathjoin(self.basedir, filename)

    def basis_tree(self):
        """Return RevisionTree for the current last revision.

        If the left most parent is a ghost then the returned tree will be an
        empty tree - one obtained by calling
        repository.revision_tree(NULL_REVISION).
        """
        try:
            revision_id = self.get_parent_ids()[0]
        except IndexError:
            # no parents, return an empty revision tree.
            # in the future this should return the tree for
            # 'empty:' - the implicit root empty tree.
            return self.branch.repository.revision_tree(
                       _mod_revision.NULL_REVISION)
        try:
            return self.revision_tree(revision_id)
        except errors.NoSuchRevision:
            pass
        # No cached copy available, retrieve from the repository.
        # FIXME? RBC 20060403 should we cache the inventory locally
        # at this point ?
        try:
            return self.branch.repository.revision_tree(revision_id)
        except (errors.RevisionNotPresent, errors.NoSuchRevision):
            # the basis tree *may* be a ghost or a low level error may have
            # occurred. If the revision is present, its a problem, if its not
            # its a ghost.
            if self.branch.repository.has_revision(revision_id):
                raise
            # the basis tree is a ghost so return an empty tree.
            return self.branch.repository.revision_tree(
                       _mod_revision.NULL_REVISION)

    def _cleanup(self):
        self._flush_ignore_list_cache()

    def relpath(self, path):
        """Return the local path portion from a given path.

        The path may be absolute or relative. If its a relative path it is
        interpreted relative to the python current working directory.
        """
        return osutils.relpath(self.basedir, path)

    def has_filename(self, filename):
        return osutils.lexists(self.abspath(filename))

    def get_file(self, file_id, path=None, filtered=True):
        return self.get_file_with_stat(file_id, path, filtered=filtered)[0]

    def get_file_with_stat(self, file_id, path=None, filtered=True,
                           _fstat=osutils.fstat):
        """See Tree.get_file_with_stat."""
        if path is None:
            path = self.id2path(file_id)
        file_obj = self.get_file_byname(path, filtered=False)
        stat_value = _fstat(file_obj.fileno())
        if filtered and self.supports_content_filtering():
            filters = self._content_filter_stack(path)
            file_obj = _mod_filters.filtered_input_file(file_obj, filters)
        return (file_obj, stat_value)

    def get_file_text(self, file_id, path=None, filtered=True):
        my_file = self.get_file(file_id, path=path, filtered=filtered)
        try:
            return my_file.read()
        finally:
            my_file.close()

    def get_file_byname(self, filename, filtered=True):
        path = self.abspath(filename)
        f = file(path, 'rb')
        if filtered and self.supports_content_filtering():
            filters = self._content_filter_stack(filename)
            return _mod_filters.filtered_input_file(f, filters)
        else:
            return f

    def get_file_lines(self, file_id, path=None, filtered=True):
        """See Tree.get_file_lines()"""
        file = self.get_file(file_id, path, filtered=filtered)
        try:
            return file.readlines()
        finally:
            file.close()

    def get_parent_ids(self):
        """See Tree.get_parent_ids.

        This implementation reads the pending merges list and last_revision
        value and uses that to decide what the parents list should be.
        """
        last_rev = _mod_revision.ensure_null(self._last_revision())
        if _mod_revision.NULL_REVISION == last_rev:
            parents = []
        else:
            parents = [last_rev]
        try:
            merges_bytes = self._transport.get_bytes('pending-merges')
        except errors.NoSuchFile:
            pass
        else:
            for l in osutils.split_lines(merges_bytes):
                revision_id = l.rstrip('\n')
                parents.append(revision_id)
        return parents

    def get_root_id(self):
        """Return the id of this trees root"""
        raise NotImplementedError(self.get_root_id)

    @needs_read_lock
    def clone(self, to_controldir, revision_id=None):
        """Duplicate this working tree into to_bzr, including all state.

        Specifically modified files are kept as modified, but
        ignored and unknown files are discarded.

        If you want to make a new line of development, see ControlDir.sprout()

        revision
            If not None, the cloned tree will have its last revision set to
            revision, and difference between the source trees last revision
            and this one merged in.
        """
        # assumes the target bzr dir format is compatible.
        result = to_controldir.create_workingtree()
        self.copy_content_into(result, revision_id)
        return result

    @needs_read_lock
    def copy_content_into(self, tree, revision_id=None):
        """Copy the current content and user files of this tree into tree."""
        tree.set_root_id(self.get_root_id())
        if revision_id is None:
            merge.transform_tree(tree, self)
        else:
            # TODO now merge from tree.last_revision to revision (to preserve
            # user local changes)
            try:
                other_tree = self.revision_tree(revision_id)
            except errors.NoSuchRevision:
                other_tree = self.branch.repository.revision_tree(revision_id)

            merge.transform_tree(tree, other_tree)
            if revision_id == _mod_revision.NULL_REVISION:
                new_parents = []
            else:
                new_parents = [revision_id]
            tree.set_parent_ids(new_parents)

    def id2abspath(self, file_id):
        return self.abspath(self.id2path(file_id))

    def get_file_size(self, file_id):
        """See Tree.get_file_size"""
        # XXX: this returns the on-disk size; it should probably return the
        # canonical size
        try:
            return os.path.getsize(self.id2abspath(file_id))
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            else:
                return None

    @needs_tree_write_lock
    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds."""
        for pos, f in enumerate(files):
            if kinds[pos] is None:
                fullpath = osutils.normpath(self.abspath(f))
                try:
                    kinds[pos] = osutils.file_kind(fullpath)
                except OSError as e:
                    if e.errno == errno.ENOENT:
                        raise errors.NoSuchFile(fullpath)

    @needs_write_lock
    def add_parent_tree_id(self, revision_id, allow_leftmost_as_ghost=False):
        """Add revision_id as a parent.

        This is equivalent to retrieving the current list of parent ids
        and setting the list to its value plus revision_id.

        :param revision_id: The revision id to add to the parent list. It may
            be a ghost revision as long as its not the first parent to be
            added, or the allow_leftmost_as_ghost parameter is set True.
        :param allow_leftmost_as_ghost: Allow the first parent to be a ghost.
        """
        parents = self.get_parent_ids() + [revision_id]
        self.set_parent_ids(parents, allow_leftmost_as_ghost=len(parents) > 1
            or allow_leftmost_as_ghost)

    @needs_tree_write_lock
    def add_parent_tree(self, parent_tuple, allow_leftmost_as_ghost=False):
        """Add revision_id, tree tuple as a parent.

        This is equivalent to retrieving the current list of parent trees
        and setting the list to its value plus parent_tuple. See also
        add_parent_tree_id - if you only have a parent id available it will be
        simpler to use that api. If you have the parent already available, using
        this api is preferred.

        :param parent_tuple: The (revision id, tree) to add to the parent list.
            If the revision_id is a ghost, pass None for the tree.
        :param allow_leftmost_as_ghost: Allow the first parent to be a ghost.
        """
        parent_ids = self.get_parent_ids() + [parent_tuple[0]]
        if len(parent_ids) > 1:
            # the leftmost may have already been a ghost, preserve that if it
            # was.
            allow_leftmost_as_ghost = True
        self.set_parent_ids(parent_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)

    @needs_tree_write_lock
    def add_pending_merge(self, *revision_ids):
        # TODO: Perhaps should check at this point that the
        # history of the revision is actually present?
        parents = self.get_parent_ids()
        updated = False
        for rev_id in revision_ids:
            if rev_id in parents:
                continue
            parents.append(rev_id)
            updated = True
        if updated:
            self.set_parent_ids(parents, allow_leftmost_as_ghost=True)

    def path_content_summary(self, path, _lstat=os.lstat,
        _mapper=osutils.file_kind_from_stat_mode):
        """See Tree.path_content_summary."""
        abspath = self.abspath(path)
        try:
            stat_result = _lstat(abspath)
        except OSError as e:
            if getattr(e, 'errno', None) == errno.ENOENT:
                # no file.
                return ('missing', None, None, None)
            # propagate other errors
            raise
        kind = _mapper(stat_result.st_mode)
        if kind == 'file':
            return self._file_content_summary(path, stat_result)
        elif kind == 'directory':
            # perhaps it looks like a plain directory, but it's really a
            # reference.
            if self._directory_is_tree_reference(path):
                kind = 'tree-reference'
            return kind, None, None, None
        elif kind == 'symlink':
            target = osutils.readlink(abspath)
            return ('symlink', None, None, target)
        else:
            return (kind, None, None, None)

    def _file_content_summary(self, path, stat_result):
        size = stat_result.st_size
        executable = self._is_executable_from_path_and_stat(path, stat_result)
        # try for a stat cache lookup
        return ('file', size, executable, self._sha_from_stat(
            path, stat_result))

    def _check_parents_for_ghosts(self, revision_ids, allow_leftmost_as_ghost):
        """Common ghost checking functionality from set_parent_*.

        This checks that the left hand-parent exists if there are any
        revisions present.
        """
        if len(revision_ids) > 0:
            leftmost_id = revision_ids[0]
            if (not allow_leftmost_as_ghost and not
                self.branch.repository.has_revision(leftmost_id)):
                raise errors.GhostRevisionUnusableHere(leftmost_id)

    def _set_merges_from_parent_ids(self, parent_ids):
        merges = parent_ids[1:]
        self._transport.put_bytes('pending-merges', '\n'.join(merges),
            mode=self.bzrdir._get_file_mode())

    def _filter_parent_ids_by_ancestry(self, revision_ids):
        """Check that all merged revisions are proper 'heads'.

        This will always return the first revision_id, and any merged revisions
        which are
        """
        if len(revision_ids) == 0:
            return revision_ids
        graph = self.branch.repository.get_graph()
        heads = graph.heads(revision_ids)
        new_revision_ids = revision_ids[:1]
        for revision_id in revision_ids[1:]:
            if revision_id in heads and revision_id not in new_revision_ids:
                new_revision_ids.append(revision_id)
        if new_revision_ids != revision_ids:
            mutter('requested to set revision_ids = %s,'
                         ' but filtered to %s', revision_ids, new_revision_ids)
        return new_revision_ids

    @needs_tree_write_lock
    def set_parent_ids(self, revision_ids, allow_leftmost_as_ghost=False):
        """Set the parent ids to revision_ids.

        See also set_parent_trees. This api will try to retrieve the tree data
        for each element of revision_ids from the trees repository. If you have
        tree data already available, it is more efficient to use
        set_parent_trees rather than set_parent_ids. set_parent_ids is however
        an easier API to use.

        :param revision_ids: The revision_ids to set as the parent ids of this
            working tree. Any of these may be ghosts.
        """
        self._check_parents_for_ghosts(revision_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)
        for revision_id in revision_ids:
            _mod_revision.check_not_reserved_id(revision_id)

        revision_ids = self._filter_parent_ids_by_ancestry(revision_ids)

        if len(revision_ids) > 0:
            self.set_last_revision(revision_ids[0])
        else:
            self.set_last_revision(_mod_revision.NULL_REVISION)

        self._set_merges_from_parent_ids(revision_ids)

    @needs_tree_write_lock
    def set_pending_merges(self, rev_list):
        parents = self.get_parent_ids()
        leftmost = parents[:1]
        new_parents = leftmost + rev_list
        self.set_parent_ids(new_parents)

    @needs_tree_write_lock
    def set_merge_modified(self, modified_hashes):
        """Set the merge modified hashes."""
        raise NotImplementedError(self.set_merge_modified)

    def _sha_from_stat(self, path, stat_result):
        """Get a sha digest from the tree's stat cache.

        The default implementation assumes no stat cache is present.

        :param path: The path.
        :param stat_result: The stat result being looked up.
        """
        return None

    @needs_write_lock # because merge pulls data into the branch.
    def merge_from_branch(self, branch, to_revision=None, from_revision=None,
                          merge_type=None, force=False):
        """Merge from a branch into this working tree.

        :param branch: The branch to merge from.
        :param to_revision: If non-None, the merge will merge to to_revision,
            but not beyond it. to_revision does not need to be in the history
            of the branch when it is supplied. If None, to_revision defaults to
            branch.last_revision().
        """
        from .merge import Merger, Merge3Merger
        merger = Merger(self.branch, this_tree=self)
        # check that there are no local alterations
        if not force and self.has_changes():
            raise errors.UncommittedChanges(self)
        if to_revision is None:
            to_revision = _mod_revision.ensure_null(branch.last_revision())
        merger.other_rev_id = to_revision
        if _mod_revision.is_null(merger.other_rev_id):
            raise errors.NoCommits(branch)
        self.branch.fetch(branch, last_revision=merger.other_rev_id)
        merger.other_basis = merger.other_rev_id
        merger.other_tree = self.branch.repository.revision_tree(
            merger.other_rev_id)
        merger.other_branch = branch
        if from_revision is None:
            merger.find_base()
        else:
            merger.set_base_revision(from_revision, branch)
        if merger.base_rev_id == merger.other_rev_id:
            raise errors.PointlessMerge
        merger.backup_files = False
        if merge_type is None:
            merger.merge_type = Merge3Merger
        else:
            merger.merge_type = merge_type
        merger.set_interesting_files(None)
        merger.show_base = False
        merger.reprocess = False
        conflicts = merger.do_merge()
        merger.set_pending()
        return conflicts

    def merge_modified(self):
        """Return a dictionary of files modified by a merge.

        The list is initialized by WorkingTree.set_merge_modified, which is
        typically called after we make some automatic updates to the tree
        because of a merge.

        This returns a map of file_id->sha1, containing only files which are
        still in the working inventory and have that text hash.
        """
        raise NotImplementedError(self.merge_modified)

    @needs_write_lock
    def mkdir(self, path, file_id=None):
        """See MutableTree.mkdir()."""
        if file_id is None:
            file_id = generate_ids.gen_file_id(os.path.basename(path))
        os.mkdir(self.abspath(path))
        self.add(path, file_id, 'directory')
        return file_id

    def get_symlink_target(self, file_id, path=None):
        if path is not None:
            abspath = self.abspath(path)
        else:
            abspath = self.id2abspath(file_id)
        target = osutils.readlink(abspath)
        return target

    def subsume(self, other_tree):
        raise NotImplementedError(self.subsume)

    def _setup_directory_is_tree_reference(self):
        if self._branch.repository._format.supports_tree_reference:
            self._directory_is_tree_reference = \
                self._directory_may_be_tree_reference
        else:
            self._directory_is_tree_reference = \
                self._directory_is_never_tree_reference

    def _directory_is_never_tree_reference(self, relpath):
        return False

    def _directory_may_be_tree_reference(self, relpath):
        # as a special case, if a directory contains control files then
        # it's a tree reference, except that the root of the tree is not
        return relpath and osutils.isdir(self.abspath(relpath) + u"/.bzr")
        # TODO: We could ask all the control formats whether they
        # recognize this directory, but at the moment there's no cheap api
        # to do that.  Since we probably can only nest bzr checkouts and
        # they always use this name it's ok for now.  -- mbp 20060306
        #
        # FIXME: There is an unhandled case here of a subdirectory
        # containing .bzr but not a branch; that will probably blow up
        # when you try to commit it.  It might happen if there is a
        # checkout in a subdirectory.  This can be avoided by not adding
        # it.  mbp 20070306

    def extract(self, file_id, format=None):
        """Extract a subtree from this tree.

        A new branch will be created, relative to the path for this tree.
        """
        raise NotImplementedError(self.extract)

    def flush(self):
        """Write the in memory meta data to disk."""
        raise NotImplementedError(self.flush)

    def _kind(self, relpath):
        return osutils.file_kind(self.abspath(relpath))

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        """List all files as (path, class, kind, id, entry).

        Lists, but does not descend into unversioned directories.
        This does not include files that have been deleted in this
        tree. Skips the control directory.

        :param include_root: if True, return an entry for the root
        :param from_dir: start from this directory or None for the root
        :param recursive: whether to recurse into subdirectories or not
        """
        raise NotImplementedError(self.list_files)

    def move(self, from_paths, to_dir=None, after=False):
        """Rename files.

        to_dir must be known to the working tree.

        If to_dir exists and is a directory, the files are moved into
        it, keeping their old names.

        Note that to_dir is only the last component of the new name;
        this doesn't change the directory.

        For each entry in from_paths the move mode will be determined
        independently.

        The first mode moves the file in the filesystem and updates the
        working tree metadata. The second mode only updates the working tree
        metadata without touching the file on the filesystem.

        move uses the second mode if 'after == True' and the target is not
        versioned but present in the working tree.

        move uses the second mode if 'after == False' and the source is
        versioned but no longer in the working tree, and the target is not
        versioned but present in the working tree.

        move uses the first mode if 'after == False' and the source is
        versioned and present in the working tree, and the target is not
        versioned and not present in the working tree.

        Everything else results in an error.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        raise NotImplementedError(self.move)

    @needs_tree_write_lock
    def rename_one(self, from_rel, to_rel, after=False):
        """Rename one file.

        This can change the directory or the filename or both.

        rename_one has several 'modes' to work. First, it can rename a physical
        file and change the file_id. That is the normal mode. Second, it can
        only change the file_id without touching any physical file.

        rename_one uses the second mode if 'after == True' and 'to_rel' is
        either not versioned or newly added, and present in the working tree.

        rename_one uses the second mode if 'after == False' and 'from_rel' is
        versioned but no longer in the working tree, and 'to_rel' is not
        versioned but present in the working tree.

        rename_one uses the first mode if 'after == False' and 'from_rel' is
        versioned and present in the working tree, and 'to_rel' is not
        versioned and not present in the working tree.

        Everything else results in an error.
        """
        raise NotImplementedError(self.rename_one)

    @needs_read_lock
    def unknowns(self):
        """Return all unknown files.

        These are files in the working directory that are not versioned or
        control files or ignored.
        """
        # force the extras method to be fully executed before returning, to
        # prevent race conditions with the lock
        return iter(
            [subp for subp in self.extras() if not self.is_ignored(subp)])

    def unversion(self, file_ids):
        """Remove the file ids in file_ids from the current versioned set.

        When a file_id is unversioned, all of its children are automatically
        unversioned.

        :param file_ids: The file ids to stop versioning.
        :raises: NoSuchId if any fileid is not currently versioned.
        """
        raise NotImplementedError(self.unversion)

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
             change_reporter=None, possible_transports=None, local=False,
             show_base=False):
        source.lock_read()
        try:
            old_revision_info = self.branch.last_revision_info()
            basis_tree = self.basis_tree()
            count = self.branch.pull(source, overwrite, stop_revision,
                                     possible_transports=possible_transports,
                                     local=local)
            new_revision_info = self.branch.last_revision_info()
            if new_revision_info != old_revision_info:
                repository = self.branch.repository
                if repository._format.fast_deltas:
                    parent_ids = self.get_parent_ids()
                    if parent_ids:
                        basis_id = parent_ids[0]
                        basis_tree = repository.revision_tree(basis_id)
                basis_tree.lock_read()
                try:
                    new_basis_tree = self.branch.basis_tree()
                    merge.merge_inner(
                                self.branch,
                                new_basis_tree,
                                basis_tree,
                                this_tree=self,
                                pb=None,
                                change_reporter=change_reporter,
                                show_base=show_base)
                    basis_root_id = basis_tree.get_root_id()
                    new_root_id = new_basis_tree.get_root_id()
                    if new_root_id is not None and basis_root_id != new_root_id:
                        self.set_root_id(new_root_id)
                finally:
                    basis_tree.unlock()
                # TODO - dedup parents list with things merged by pull ?
                # reuse the revisiontree we merged against to set the new
                # tree data.
                parent_trees = []
                if self.branch.last_revision() != _mod_revision.NULL_REVISION:
                    parent_trees.append(
                        (self.branch.last_revision(), new_basis_tree))
                # we have to pull the merge trees out again, because
                # merge_inner has set the ids. - this corner is not yet
                # layered well enough to prevent double handling.
                # XXX TODO: Fix the double handling: telling the tree about
                # the already known parent data is wasteful.
                merges = self.get_parent_ids()[1:]
                parent_trees.extend([
                    (parent, repository.revision_tree(parent)) for
                     parent in merges])
                self.set_parent_trees(parent_trees)
            return count
        finally:
            source.unlock()

    @needs_write_lock
    def put_file_bytes_non_atomic(self, file_id, bytes):
        """See MutableTree.put_file_bytes_non_atomic."""
        stream = file(self.id2abspath(file_id), 'wb')
        try:
            stream.write(bytes)
        finally:
            stream.close()

    def extras(self):
        """Yield all unversioned files in this WorkingTree.

        If there are any unversioned directories then only the directory is
        returned, not all its children.  But if there are unversioned files
        under a versioned subdirectory, they are returned.

        Currently returned depth-first, sorted by name within directories.
        This is the same order used by 'osutils.walkdirs'.
        """
        raise NotImplementedError(self.extras)

    def ignored_files(self):
        """Yield list of PATH, IGNORE_PATTERN"""
        for subp in self.extras():
            pat = self.is_ignored(subp)
            if pat is not None:
                yield subp, pat

    def get_ignore_list(self):
        """Return list of ignore patterns.

        Cached in the Tree object after the first call.
        """
        ignoreset = getattr(self, '_ignoreset', None)
        if ignoreset is not None:
            return ignoreset

        ignore_globs = set()
        ignore_globs.update(ignores.get_runtime_ignores())
        ignore_globs.update(ignores.get_user_ignores())
        if self.has_filename(breezy.IGNORE_FILENAME):
            f = self.get_file_byname(breezy.IGNORE_FILENAME)
            try:
                ignore_globs.update(ignores.parse_ignore_file(f))
            finally:
                f.close()
        self._ignoreset = ignore_globs
        return ignore_globs

    def _flush_ignore_list_cache(self):
        """Resets the cached ignore list to force a cache rebuild."""
        self._ignoreset = None
        self._ignoreglobster = None

    def is_ignored(self, filename):
        r"""Check whether the filename matches an ignore pattern.

        Patterns containing '/' or '\' need to match the whole path;
        others match against only the last component.  Patterns starting
        with '!' are ignore exceptions.  Exceptions take precedence
        over regular patterns and cause the filename to not be ignored.

        If the file is ignored, returns the pattern which caused it to
        be ignored, otherwise None.  So this can simply be used as a
        boolean if desired."""
        if getattr(self, '_ignoreglobster', None) is None:
            self._ignoreglobster = globbing.ExceptionGlobster(self.get_ignore_list())
        return self._ignoreglobster.match(filename)

    def kind(self, file_id):
        return osutils.file_kind(self.id2abspath(file_id))

    def stored_kind(self, file_id):
        """See Tree.stored_kind"""
        raise NotImplementedError(self.stored_kind)

    def _comparison_data(self, entry, path):
        abspath = self.abspath(path)
        try:
            stat_value = os.lstat(abspath)
        except OSError as e:
            if getattr(e, 'errno', None) == errno.ENOENT:
                stat_value = None
                kind = None
                executable = False
            else:
                raise
        else:
            mode = stat_value.st_mode
            kind = osutils.file_kind_from_stat_mode(mode)
            if not self._supports_executable():
                executable = entry is not None and entry.executable
            else:
                executable = bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)
        return kind, executable, stat_value

    def _file_size(self, entry, stat_value):
        return stat_value.st_size

    def last_revision(self):
        """Return the last revision of the branch for this tree.

        This format tree does not support a separate marker for last-revision
        compared to the branch.

        See MutableTree.last_revision
        """
        return self._last_revision()

    @needs_read_lock
    def _last_revision(self):
        """helper for get_parent_ids."""
        return _mod_revision.ensure_null(self.branch.last_revision())

    def is_locked(self):
        """Check if this tree is locked."""
        raise NotImplementedError(self.is_locked)

    def lock_read(self):
        """Lock the tree for reading.

        This also locks the branch, and can be unlocked via self.unlock().

        :return: A breezy.lock.LogicalLockResult.
        """
        raise NotImplementedError(self.lock_read)

    def lock_tree_write(self):
        """See MutableTree.lock_tree_write, and WorkingTree.unlock.

        :return: A breezy.lock.LogicalLockResult.
        """
        raise NotImplementedError(self.lock_tree_write)

    def lock_write(self):
        """See MutableTree.lock_write, and WorkingTree.unlock.

        :return: A breezy.lock.LogicalLockResult.
        """
        raise NotImplementedError(self.lock_write)

    def get_physical_lock_status(self):
        raise NotImplementedError(self.get_physical_lock_status)

    def set_last_revision(self, new_revision):
        """Change the last revision in the working tree."""
        raise NotImplementedError(self.set_last_revision)

    def _change_last_revision(self, new_revision):
        """Template method part of set_last_revision to perform the change.

        This is used to allow WorkingTree3 instances to not affect branch
        when their last revision is set.
        """
        if _mod_revision.is_null(new_revision):
            self.branch.set_last_revision_info(0, new_revision)
            return False
        _mod_revision.check_not_reserved_id(new_revision)
        try:
            self.branch.generate_revision_history(new_revision)
        except errors.NoSuchRevision:
            # not present in the repo - dont try to set it deeper than the tip
            self.branch._set_revision_history([new_revision])
        return True

    @needs_tree_write_lock
    def remove(self, files, verbose=False, to_file=None, keep_files=True,
        force=False):
        """Remove nominated files from the working tree metadata.

        :files: File paths relative to the basedir.
        :keep_files: If true, the files will also be kept.
        :force: Delete files and directories, even if they are changed and
            even if the directories are not empty.
        """
        if isinstance(files, basestring):
            files = [files]

        inv_delta = []

        all_files = set() # specified and nested files 
        unknown_nested_files=set()
        if to_file is None:
            to_file = sys.stdout

        files_to_backup = []

        def recurse_directory_to_add_files(directory):
            # Recurse directory and add all files
            # so we can check if they have changed.
            for parent_info, file_infos in self.walkdirs(directory):
                for relpath, basename, kind, lstat, fileid, kind in file_infos:
                    # Is it versioned or ignored?
                    if self.path2id(relpath):
                        # Add nested content for deletion.
                        all_files.add(relpath)
                    else:
                        # Files which are not versioned
                        # should be treated as unknown.
                        files_to_backup.append(relpath)

        for filename in files:
            # Get file name into canonical form.
            abspath = self.abspath(filename)
            filename = self.relpath(abspath)
            if len(filename) > 0:
                all_files.add(filename)
                recurse_directory_to_add_files(filename)

        files = list(all_files)

        if len(files) == 0:
            return # nothing to do

        # Sort needed to first handle directory content before the directory
        files.sort(reverse=True)

        # Bail out if we are going to delete files we shouldn't
        if not keep_files and not force:
            for (file_id, path, content_change, versioned, parent_id, name,
                 kind, executable) in self.iter_changes(self.basis_tree(),
                     include_unchanged=True, require_versioned=False,
                     want_unversioned=True, specific_files=files):
                if versioned[0] == False:
                    # The record is unknown or newly added
                    files_to_backup.append(path[1])
                elif (content_change and (kind[1] is not None) and
                        osutils.is_inside_any(files, path[1])):
                    # Versioned and changed, but not deleted, and still
                    # in one of the dirs to be deleted.
                    files_to_backup.append(path[1])

        def backup(file_to_backup):
            backup_name = self.bzrdir._available_backup_name(file_to_backup)
            osutils.rename(abs_path, self.abspath(backup_name))
            return "removed %s (but kept a copy: %s)" % (file_to_backup,
                                                         backup_name)

        # Build inv_delta and delete files where applicable,
        # do this before any modifications to meta data.
        for f in files:
            fid = self.path2id(f)
            message = None
            if not fid:
                message = "%s is not versioned." % (f,)
            else:
                if verbose:
                    # having removed it, it must be either ignored or unknown
                    if self.is_ignored(f):
                        new_status = 'I'
                    else:
                        new_status = '?'
                    # XXX: Really should be a more abstract reporter interface
                    kind_ch = osutils.kind_marker(self.kind(fid))
                    to_file.write(new_status + '       ' + f + kind_ch + '\n')
                # Unversion file
                inv_delta.append((f, None, fid, None))
                message = "removed %s" % (f,)

            if not keep_files:
                abs_path = self.abspath(f)
                if osutils.lexists(abs_path):
                    if (osutils.isdir(abs_path) and
                        len(os.listdir(abs_path)) > 0):
                        if force:
                            osutils.rmtree(abs_path)
                            message = "deleted %s" % (f,)
                        else:
                            message = backup(f)
                    else:
                        if f in files_to_backup:
                            message = backup(f)
                        else:
                            osutils.delete_any(abs_path)
                            message = "deleted %s" % (f,)
                elif message is not None:
                    # Only care if we haven't done anything yet.
                    message = "%s does not exist." % (f,)

            # Print only one message (if any) per file.
            if message is not None:
                note(message)
        self.apply_inventory_delta(inv_delta)

    @needs_tree_write_lock
    def revert(self, filenames=None, old_tree=None, backups=True,
               pb=None, report_changes=False):
        from .conflicts import resolve
        if old_tree is None:
            basis_tree = self.basis_tree()
            basis_tree.lock_read()
            old_tree = basis_tree
        else:
            basis_tree = None
        try:
            conflicts = transform.revert(self, old_tree, filenames, backups, pb,
                                         report_changes)
            if filenames is None and len(self.get_parent_ids()) > 1:
                parent_trees = []
                last_revision = self.last_revision()
                if last_revision != _mod_revision.NULL_REVISION:
                    if basis_tree is None:
                        basis_tree = self.basis_tree()
                        basis_tree.lock_read()
                    parent_trees.append((last_revision, basis_tree))
                self.set_parent_trees(parent_trees)
                resolve(self)
            else:
                resolve(self, filenames, ignore_misses=True, recursive=True)
        finally:
            if basis_tree is not None:
                basis_tree.unlock()
        return conflicts

    @needs_write_lock
    def store_uncommitted(self):
        """Store uncommitted changes from the tree in the branch."""
        target_tree = self.basis_tree()
        shelf_creator = shelf.ShelfCreator(self, target_tree)
        try:
            if not shelf_creator.shelve_all():
                return
            self.branch.store_uncommitted(shelf_creator)
            shelf_creator.transform()
        finally:
            shelf_creator.finalize()
        note('Uncommitted changes stored in branch "%s".', self.branch.nick)

    @needs_write_lock
    def restore_uncommitted(self):
        """Restore uncommitted changes from the branch into the tree."""
        unshelver = self.branch.get_unshelver(self)
        if unshelver is None:
            return
        try:
            merger = unshelver.make_merger()
            merger.ignore_zero = True
            merger.do_merge()
            self.branch.store_uncommitted(None)
        finally:
            unshelver.finalize()

    def revision_tree(self, revision_id):
        """See Tree.revision_tree.

        WorkingTree can supply revision_trees for the basis revision only
        because there is only one cached inventory in the bzr directory.
        """
        raise NotImplementedError(self.revision_tree)

    @needs_tree_write_lock
    def set_root_id(self, file_id):
        """Set the root id for this tree."""
        # for compatability
        if file_id is None:
            raise ValueError(
                'WorkingTree.set_root_id with fileid=None')
        file_id = osutils.safe_file_id(file_id)
        self._set_root_id(file_id)

    def _set_root_id(self, file_id):
        """Set the root id for this tree, in a format specific manner.

        :param file_id: The file id to assign to the root. It must not be
            present in the current inventory or an error will occur. It must
            not be None, but rather a valid file id.
        """
        raise NotImplementedError(self._set_root_id)

    def unlock(self):
        """See Branch.unlock.

        WorkingTree locking just uses the Branch locking facilities.
        This is current because all working trees have an embedded branch
        within them. IF in the future, we were to make branch data shareable
        between multiple working trees, i.e. via shared storage, then we
        would probably want to lock both the local tree, and the branch.
        """
        raise NotImplementedError(self.unlock)

    _marker = object()

    def update(self, change_reporter=None, possible_transports=None,
               revision=None, old_tip=_marker, show_base=False):
        """Update a working tree along its branch.

        This will update the branch if its bound too, which means we have
        multiple trees involved:

        - The new basis tree of the master.
        - The old basis tree of the branch.
        - The old basis tree of the working tree.
        - The current working tree state.

        Pathologically, all three may be different, and non-ancestors of each
        other.  Conceptually we want to:

        - Preserve the wt.basis->wt.state changes
        - Transform the wt.basis to the new master basis.
        - Apply a merge of the old branch basis to get any 'local' changes from
          it into the tree.
        - Restore the wt.basis->wt.state changes.

        There isn't a single operation at the moment to do that, so we:

        - Merge current state -> basis tree of the master w.r.t. the old tree
          basis.
        - Do a 'normal' merge of the old branch basis if it is relevant.

        :param revision: The target revision to update to. Must be in the
            revision history.
        :param old_tip: If branch.update() has already been run, the value it
            returned (old tip of the branch or None). _marker is used
            otherwise.
        """
        if self.branch.get_bound_location() is not None:
            self.lock_write()
            update_branch = (old_tip is self._marker)
        else:
            self.lock_tree_write()
            update_branch = False
        try:
            if update_branch:
                old_tip = self.branch.update(possible_transports)
            else:
                if old_tip is self._marker:
                    old_tip = None
            return self._update_tree(old_tip, change_reporter, revision, show_base)
        finally:
            self.unlock()

    @needs_tree_write_lock
    def _update_tree(self, old_tip=None, change_reporter=None, revision=None,
                     show_base=False):
        """Update a tree to the master branch.

        :param old_tip: if supplied, the previous tip revision the branch,
            before it was changed to the master branch's tip.
        """
        # here if old_tip is not None, it is the old tip of the branch before
        # it was updated from the master branch. This should become a pending
        # merge in the working tree to preserve the user existing work.  we
        # cant set that until we update the working trees last revision to be
        # one from the new branch, because it will just get absorbed by the
        # parent de-duplication logic.
        #
        # We MUST save it even if an error occurs, because otherwise the users
        # local work is unreferenced and will appear to have been lost.
        #
        nb_conflicts = 0
        try:
            last_rev = self.get_parent_ids()[0]
        except IndexError:
            last_rev = _mod_revision.NULL_REVISION
        if revision is None:
            revision = self.branch.last_revision()

        old_tip = old_tip or _mod_revision.NULL_REVISION

        if not _mod_revision.is_null(old_tip) and old_tip != last_rev:
            # the branch we are bound to was updated
            # merge those changes in first
            base_tree  = self.basis_tree()
            other_tree = self.branch.repository.revision_tree(old_tip)
            nb_conflicts = merge.merge_inner(self.branch, other_tree,
                                             base_tree, this_tree=self,
                                             change_reporter=change_reporter,
                                             show_base=show_base)
            if nb_conflicts:
                self.add_parent_tree((old_tip, other_tree))
                note(gettext('Rerun update after fixing the conflicts.'))
                return nb_conflicts

        if last_rev != _mod_revision.ensure_null(revision):
            # the working tree is up to date with the branch
            # we can merge the specified revision from master
            to_tree = self.branch.repository.revision_tree(revision)
            to_root_id = to_tree.get_root_id()

            basis = self.basis_tree()
            basis.lock_read()
            try:
                if (basis.get_root_id() is None or basis.get_root_id() != to_root_id):
                    self.set_root_id(to_root_id)
                    self.flush()
            finally:
                basis.unlock()

            # determine the branch point
            graph = self.branch.repository.get_graph()
            base_rev_id = graph.find_unique_lca(self.branch.last_revision(),
                                                last_rev)
            base_tree = self.branch.repository.revision_tree(base_rev_id)

            nb_conflicts = merge.merge_inner(self.branch, to_tree, base_tree,
                                             this_tree=self,
                                             change_reporter=change_reporter,
                                             show_base=show_base)
            self.set_last_revision(revision)
            # TODO - dedup parents list with things merged by pull ?
            # reuse the tree we've updated to to set the basis:
            parent_trees = [(revision, to_tree)]
            merges = self.get_parent_ids()[1:]
            # Ideally we ask the tree for the trees here, that way the working
            # tree can decide whether to give us the entire tree or give us a
            # lazy initialised tree. dirstate for instance will have the trees
            # in ram already, whereas a last-revision + basis-inventory tree
            # will not, but also does not need them when setting parents.
            for parent in merges:
                parent_trees.append(
                    (parent, self.branch.repository.revision_tree(parent)))
            if not _mod_revision.is_null(old_tip):
                parent_trees.append(
                    (old_tip, self.branch.repository.revision_tree(old_tip)))
            self.set_parent_trees(parent_trees)
            last_rev = parent_trees[0][0]
        return nb_conflicts

    def set_conflicts(self, arg):
        raise errors.UnsupportedOperation(self.set_conflicts, self)

    def add_conflicts(self, arg):
        raise errors.UnsupportedOperation(self.add_conflicts, self)

    def conflicts(self):
        raise NotImplementedError(self.conflicts)

    def walkdirs(self, prefix=""):
        """Walk the directories of this tree.

        returns a generator which yields items in the form:
                ((curren_directory_path, fileid),
                 [(file1_path, file1_name, file1_kind, (lstat), file1_id,
                   file1_kind), ... ])

        This API returns a generator, which is only valid during the current
        tree transaction - within a single lock_read or lock_write duration.

        If the tree is not locked, it may cause an error to be raised,
        depending on the tree implementation.
        """
        disk_top = self.abspath(prefix)
        if disk_top.endswith('/'):
            disk_top = disk_top[:-1]
        top_strip_len = len(disk_top) + 1
        inventory_iterator = self._walkdirs(prefix)
        disk_iterator = osutils.walkdirs(disk_top, prefix)
        try:
            current_disk = next(disk_iterator)
            disk_finished = False
        except OSError as e:
            if not (e.errno == errno.ENOENT or
                (sys.platform == 'win32' and e.errno == ERROR_PATH_NOT_FOUND)):
                raise
            current_disk = None
            disk_finished = True
        try:
            current_inv = next(inventory_iterator)
            inv_finished = False
        except StopIteration:
            current_inv = None
            inv_finished = True
        while not inv_finished or not disk_finished:
            if current_disk:
                ((cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content) = current_disk
            else:
                ((cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content) = ((None, None), None)
            if not disk_finished:
                # strip out .bzr dirs
                if (cur_disk_dir_path_from_top[top_strip_len:] == '' and
                    len(cur_disk_dir_content) > 0):
                    # osutils.walkdirs can be made nicer -
                    # yield the path-from-prefix rather than the pathjoined
                    # value.
                    bzrdir_loc = bisect_left(cur_disk_dir_content,
                        ('.bzr', '.bzr'))
                    if (bzrdir_loc < len(cur_disk_dir_content)
                        and self.bzrdir.is_control_filename(
                            cur_disk_dir_content[bzrdir_loc][0])):
                        # we dont yield the contents of, or, .bzr itself.
                        del cur_disk_dir_content[bzrdir_loc]
            if inv_finished:
                # everything is unknown
                direction = 1
            elif disk_finished:
                # everything is missing
                direction = -1
            else:
                direction = cmp(current_inv[0][0], cur_disk_dir_relpath)
            if direction > 0:
                # disk is before inventory - unknown
                dirblock = [(relpath, basename, kind, stat, None, None) for
                    relpath, basename, kind, stat, top_path in
                    cur_disk_dir_content]
                yield (cur_disk_dir_relpath, None), dirblock
                try:
                    current_disk = next(disk_iterator)
                except StopIteration:
                    disk_finished = True
            elif direction < 0:
                # inventory is before disk - missing.
                dirblock = [(relpath, basename, 'unknown', None, fileid, kind)
                    for relpath, basename, dkind, stat, fileid, kind in
                    current_inv[1]]
                yield (current_inv[0][0], current_inv[0][1]), dirblock
                try:
                    current_inv = next(inventory_iterator)
                except StopIteration:
                    inv_finished = True
            else:
                # versioned present directory
                # merge the inventory and disk data together
                dirblock = []
                for relpath, subiterator in itertools.groupby(sorted(
                    current_inv[1] + cur_disk_dir_content,
                    key=operator.itemgetter(0)), operator.itemgetter(1)):
                    path_elements = list(subiterator)
                    if len(path_elements) == 2:
                        inv_row, disk_row = path_elements
                        # versioned, present file
                        dirblock.append((inv_row[0],
                            inv_row[1], disk_row[2],
                            disk_row[3], inv_row[4],
                            inv_row[5]))
                    elif len(path_elements[0]) == 5:
                        # unknown disk file
                        dirblock.append((path_elements[0][0],
                            path_elements[0][1], path_elements[0][2],
                            path_elements[0][3], None, None))
                    elif len(path_elements[0]) == 6:
                        # versioned, absent file.
                        dirblock.append((path_elements[0][0],
                            path_elements[0][1], 'unknown', None,
                            path_elements[0][4], path_elements[0][5]))
                    else:
                        raise NotImplementedError('unreachable code')
                yield current_inv[0], dirblock
                try:
                    current_inv = next(inventory_iterator)
                except StopIteration:
                    inv_finished = True
                try:
                    current_disk = next(disk_iterator)
                except StopIteration:
                    disk_finished = True

    def _walkdirs(self, prefix=""):
        """Walk the directories of this tree.

        :param prefix: is used as the directrory to start with.
        :returns: a generator which yields items in the form::

            ((curren_directory_path, fileid),
             [(file1_path, file1_name, file1_kind, None, file1_id,
               file1_kind), ... ])
        """
        raise NotImplementedError(self._walkdirs)

    @needs_tree_write_lock
    def auto_resolve(self):
        """Automatically resolve text conflicts according to contents.

        Only text conflicts are auto_resolvable. Files with no conflict markers
        are considered 'resolved', because bzr always puts conflict markers
        into files that have text conflicts.  The corresponding .THIS .BASE and
        .OTHER files are deleted, as per 'resolve'.

        :return: a tuple of ConflictLists: (un_resolved, resolved).
        """
        un_resolved = _mod_conflicts.ConflictList()
        resolved = _mod_conflicts.ConflictList()
        conflict_re = re.compile('^(<{7}|={7}|>{7})')
        for conflict in self.conflicts():
            if (conflict.typestring != 'text conflict' or
                self.kind(conflict.file_id) != 'file'):
                un_resolved.append(conflict)
                continue
            my_file = open(self.id2abspath(conflict.file_id), 'rb')
            try:
                for line in my_file:
                    if conflict_re.search(line):
                        un_resolved.append(conflict)
                        break
                else:
                    resolved.append(conflict)
            finally:
                my_file.close()
        resolved.remove_files(self)
        self.set_conflicts(un_resolved)
        return un_resolved, resolved

    def _validate(self):
        """Validate internal structures.

        This is meant mostly for the test suite. To give it a chance to detect
        corruption after actions have occurred. The default implementation is a
        just a no-op.

        :return: None. An exception should be raised if there is an error.
        """
        return

    def check_state(self):
        """Check that the working state is/isn't valid."""
        raise NotImplementedError(self.check_state)

    def reset_state(self, revision_ids=None):
        """Reset the state of the working tree.

        This does a hard-reset to a last-known-good state. This is a way to
        fix if something got corrupted (like the .bzr/checkout/dirstate file)
        """
        raise NotImplementedError(self.reset_state)

    def _get_rules_searcher(self, default_searcher):
        """See Tree._get_rules_searcher."""
        if self._rules_searcher is None:
            self._rules_searcher = super(WorkingTree,
                self)._get_rules_searcher(default_searcher)
        return self._rules_searcher

    def get_shelf_manager(self):
        """Return the ShelfManager for this WorkingTree."""
        from .shelf import ShelfManager
        return ShelfManager(self, self._transport)


class WorkingTreeFormatRegistry(controldir.ControlComponentFormatRegistry):
    """Registry for working tree formats."""

    def __init__(self, other_registry=None):
        super(WorkingTreeFormatRegistry, self).__init__(other_registry)
        self._default_format = None
        self._default_format_key = None

    def get_default(self):
        """Return the current default format."""
        if (self._default_format_key is not None and
            self._default_format is None):
            self._default_format = self.get(self._default_format_key)
        return self._default_format

    def set_default(self, format):
        """Set the default format."""
        self._default_format = format
        self._default_format_key = None

    def set_default_key(self, format_string):
        """Set the default format by its format string."""
        self._default_format_key = format_string
        self._default_format = None


format_registry = WorkingTreeFormatRegistry()


class WorkingTreeFormat(controldir.ControlComponentFormat):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference
    during workingtree opening. Its not required that these be instances, they
    can be classes themselves with class methods - it simply depends on
    whether state is needed for a given format or not.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object will be created every time regardless.
    """

    requires_rich_root = False

    upgrade_recommended = False

    requires_normalized_unicode_filenames = False

    case_sensitive_filename = "FoRMaT"

    missing_parent_conflicts = False
    """If this format supports missing parent conflicts."""

    supports_versioned_directories = None

    def initialize(self, controldir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """Initialize a new working tree in controldir.

        :param controldir: ControlDir to initialize the working tree in.
        :param revision_id: allows creating a working tree at a different
            revision than the branch is at.
        :param from_branch: Branch to checkout
        :param accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        :param hardlink: If true, hard-link files from accelerator_tree,
            where possible.
        """
        raise NotImplementedError(self.initialize)

    def __eq__(self, other):
        return self.__class__ is other.__class__

    def __ne__(self, other):
        return not (self == other)

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def supports_content_filtering(self):
        """True if this format supports content filtering."""
        return False

    def supports_views(self):
        """True if this format supports stored views."""
        return False

    def get_controldir_for_branch(self):
        """Get the control directory format for creating branches.

        This is to support testing of working tree formats that can not exist
        in the same control directory as a branch.
        """
        return self._matchingbzrdir


format_registry.register_lazy("Bazaar Working Tree Format 4 (bzr 0.15)\n",
    "breezy.workingtree_4", "WorkingTreeFormat4")
format_registry.register_lazy("Bazaar Working Tree Format 5 (bzr 1.11)\n",
    "breezy.workingtree_4", "WorkingTreeFormat5")
format_registry.register_lazy("Bazaar Working Tree Format 6 (bzr 1.14)\n",
    "breezy.workingtree_4", "WorkingTreeFormat6")
format_registry.register_lazy("Bazaar-NG Working Tree format 3",
    "breezy.workingtree_3", "WorkingTreeFormat3")
format_registry.set_default_key("Bazaar Working Tree Format 6 (bzr 1.14)\n")
