# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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


"""Git Trees."""

from __future__ import absolute_import

from collections import deque
import errno
from io import BytesIO
import os

from dulwich.config import (
    parse_submodules,
    ConfigFile as GitConfigFile,
    )
from dulwich.diff_tree import tree_changes
from dulwich.errors import NotTreeError
from dulwich.index import (
    blob_from_path_and_stat,
    cleanup_mode,
    commit_tree,
    index_entry_from_stat,
    Index,
    )
from dulwich.object_store import (
    tree_lookup_path,
    OverlayObjectStore,
    )
from dulwich.objects import (
    Blob,
    Tree,
    ZERO_SHA,
    S_IFGITLINK,
    S_ISGITLINK,
    )
import stat
import posixpath

from .. import (
    controldir as _mod_controldir,
    delta,
    errors,
    mutabletree,
    osutils,
    revisiontree,
    trace,
    tree as _mod_tree,
    workingtree,
    )
from ..revision import (
    CURRENT_REVISION,
    NULL_REVISION,
    )
from ..sixish import (
    text_type,
    viewitems,
    )

from .mapping import (
    mode_is_executable,
    mode_kind,
    default_mapping,
    )
from .transportgit import (
    TransportObjectStore,
    TransportRepo,
    )


class GitTreeDirectory(_mod_tree.TreeDirectory):

    __slots__ = ['file_id', 'name', 'parent_id', 'children']

    def __init__(self, file_id, name, parent_id):
        self.file_id = file_id
        self.name = name
        self.parent_id = parent_id
        # TODO(jelmer)
        self.children = {}

    @property
    def kind(self):
        return 'directory'

    @property
    def executable(self):
        return False

    def copy(self):
        return self.__class__(
            self.file_id, self.name, self.parent_id)

    def __repr__(self):
        return "%s(file_id=%r, name=%r, parent_id=%r)" % (
            self.__class__.__name__, self.file_id, self.name,
            self.parent_id)

    def __eq__(self, other):
        return (self.kind == other.kind and
                self.file_id == other.file_id and
                self.name == other.name and
                self.parent_id == other.parent_id)


class GitTreeFile(_mod_tree.TreeFile):

    __slots__ = ['file_id', 'name', 'parent_id', 'text_size', 'text_sha1',
                 'executable']

    def __init__(self, file_id, name, parent_id, text_size=None,
                 text_sha1=None, executable=None):
        self.file_id = file_id
        self.name = name
        self.parent_id = parent_id
        self.text_size = text_size
        self.text_sha1 = text_sha1
        self.executable = executable

    @property
    def kind(self):
        return 'file'

    def __eq__(self, other):
        return (self.kind == other.kind and
                self.file_id == other.file_id and
                self.name == other.name and
                self.parent_id == other.parent_id and
                self.text_sha1 == other.text_sha1 and
                self.text_size == other.text_size and
                self.executable == other.executable)

    def __repr__(self):
        return ("%s(file_id=%r, name=%r, parent_id=%r, text_size=%r, "
                "text_sha1=%r, executable=%r)") % (
            type(self).__name__, self.file_id, self.name, self.parent_id,
            self.text_size, self.text_sha1, self.executable)

    def copy(self):
        ret = self.__class__(
            self.file_id, self.name, self.parent_id)
        ret.text_sha1 = self.text_sha1
        ret.text_size = self.text_size
        ret.executable = self.executable
        return ret


class GitTreeSymlink(_mod_tree.TreeLink):

    __slots__ = ['file_id', 'name', 'parent_id', 'symlink_target']

    def __init__(self, file_id, name, parent_id,
                 symlink_target=None):
        self.file_id = file_id
        self.name = name
        self.parent_id = parent_id
        self.symlink_target = symlink_target

    @property
    def kind(self):
        return 'symlink'

    @property
    def executable(self):
        return False

    @property
    def text_size(self):
        return None

    def __repr__(self):
        return "%s(file_id=%r, name=%r, parent_id=%r, symlink_target=%r)" % (
            type(self).__name__, self.file_id, self.name, self.parent_id,
            self.symlink_target)

    def __eq__(self, other):
        return (self.kind == other.kind and
                self.file_id == other.file_id and
                self.name == other.name and
                self.parent_id == other.parent_id and
                self.symlink_target == other.symlink_target)

    def copy(self):
        return self.__class__(
            self.file_id, self.name, self.parent_id,
            self.symlink_target)


class GitTreeSubmodule(_mod_tree.TreeReference):

    __slots__ = ['file_id', 'name', 'parent_id', 'reference_revision']

    def __init__(self, file_id, name, parent_id, reference_revision=None):
        self.file_id = file_id
        self.name = name
        self.parent_id = parent_id
        self.reference_revision = reference_revision

    @property
    def executable(self):
        return False

    @property
    def kind(self):
        return 'tree-reference'

    def __repr__(self):
        return ("%s(file_id=%r, name=%r, parent_id=%r, "
                "reference_revision=%r)") % (
            type(self).__name__, self.file_id, self.name, self.parent_id,
            self.reference_revision)

    def __eq__(self, other):
        return (self.kind == other.kind and
                self.file_id == other.file_id and
                self.name == other.name and
                self.parent_id == other.parent_id and
                self.reference_revision == other.reference_revision)

    def copy(self):
        return self.__class__(
            self.file_id, self.name, self.parent_id,
            self.reference_revision)


entry_factory = {
    'directory': GitTreeDirectory,
    'file': GitTreeFile,
    'symlink': GitTreeSymlink,
    'tree-reference': GitTreeSubmodule,
    }


def ensure_normalized_path(path):
    """Check whether path is normalized.

    :raises InvalidNormalization: When path is not normalized, and cannot be
        accessed on this platform by the normalized path.
    :return: The NFC normalised version of path.
    """
    norm_path, can_access = osutils.normalized_filename(path)
    if norm_path != path:
        if can_access:
            return norm_path
        else:
            raise errors.InvalidNormalization(path)
    return path


class GitRevisionTree(revisiontree.RevisionTree):
    """Revision tree implementation based on Git objects."""

    def __init__(self, repository, revision_id):
        self._revision_id = revision_id
        self._repository = repository
        self._submodules = None
        self.store = repository._git.object_store
        if not isinstance(revision_id, bytes):
            raise TypeError(revision_id)
        self.commit_id, self.mapping = repository.lookup_bzr_revision_id(
            revision_id)
        if revision_id == NULL_REVISION:
            self.tree = None
            self.mapping = default_mapping
        else:
            try:
                commit = self.store[self.commit_id]
            except KeyError:
                raise errors.NoSuchRevision(repository, revision_id)
            self.tree = commit.tree

    def _submodule_info(self):
        if self._submodules is None:
            try:
                with self.get_file('.gitmodules') as f:
                    config = GitConfigFile.from_file(f)
                    self._submodules = {
                        path: (url, section)
                        for path, url, section in parse_submodules(config)}
            except errors.NoSuchFile:
                self._submodules = {}
        return self._submodules

    def _get_submodule_repository(self, relpath):
        if not isinstance(relpath, bytes):
            raise TypeError(relpath)
        try:
            info = self._submodule_info()[relpath]
        except KeyError:
            nested_repo_transport = self._repository.controldir.user_transport.clone(
                relpath.decode('utf-8'))
        else:
            nested_repo_transport = self._repository.controldir.control_transport.clone(
                posixpath.join('modules', info[1].decode('utf-8')))
        nested_controldir = _mod_controldir.ControlDir.open_from_transport(
            nested_repo_transport)
        return nested_controldir.find_repository()

    def _get_submodule_store(self, relpath):
        return self._get_submodule_repository(relpath)._git.object_store

    def get_nested_tree(self, path):
        encoded_path = path.encode('utf-8')
        nested_repo = self._get_submodule_repository(encoded_path)
        ref_rev = self.get_reference_revision(path)
        return nested_repo.revision_tree(ref_rev)

    def supports_rename_tracking(self):
        return False

    def get_file_revision(self, path):
        change_scanner = self._repository._file_change_scanner
        if self.commit_id == ZERO_SHA:
            return NULL_REVISION
        (unused_path, commit_id) = change_scanner.find_last_change_revision(
            path.encode('utf-8'), self.commit_id)
        return self._repository.lookup_foreign_revision_id(
            commit_id, self.mapping)

    def get_file_mtime(self, path):
        try:
            revid = self.get_file_revision(path)
        except KeyError:
            raise errors.NoSuchFile(path)
        try:
            rev = self._repository.get_revision(revid)
        except errors.NoSuchRevision:
            raise _mod_tree.FileTimestampUnavailable(path)
        return rev.timestamp

    def id2path(self, file_id, recurse='down'):
        try:
            path = self.mapping.parse_file_id(file_id)
        except ValueError:
            raise errors.NoSuchId(self, file_id)
        if self.is_versioned(path):
            return path
        raise errors.NoSuchId(self, file_id)

    def is_versioned(self, path):
        return self.has_filename(path)

    def path2id(self, path):
        if self.mapping.is_special_file(path):
            return None
        if not self.is_versioned(path):
            return None
        return self.mapping.generate_file_id(osutils.safe_unicode(path))

    def all_file_ids(self):
        raise errors.UnsupportedOperation(self.all_file_ids, self)

    def all_versioned_paths(self):
        ret = {u''}
        todo = [(self.store, b'', self.tree)]
        while todo:
            (store, path, tree_id) = todo.pop()
            if tree_id is None:
                continue
            tree = store[tree_id]
            for name, mode, hexsha in tree.items():
                subpath = posixpath.join(path, name)
                ret.add(subpath.decode('utf-8'))
                if stat.S_ISDIR(mode):
                    todo.append((store, subpath, hexsha))
        return ret

    def _lookup_path(self, path):
        if self.tree is None:
            raise errors.NoSuchFile(path)

        encoded_path = path.encode('utf-8')
        parts = encoded_path.split(b'/')
        hexsha = self.tree
        store = self.store
        mode = None
        for i, p in enumerate(parts):
            if not p:
                continue
            obj = store[hexsha]
            if not isinstance(obj, Tree):
                raise NotTreeError(hexsha)
            try:
                mode, hexsha = obj[p]
            except KeyError:
                raise errors.NoSuchFile(path)
            if S_ISGITLINK(mode) and i != len(parts) - 1:
                store = self._get_submodule_store(b'/'.join(parts[:i + 1]))
                hexsha = store[hexsha].tree
        return (store, mode, hexsha)

    def is_executable(self, path):
        (store, mode, hexsha) = self._lookup_path(path)
        if mode is None:
            # the tree root is a directory
            return False
        return mode_is_executable(mode)

    def kind(self, path):
        (store, mode, hexsha) = self._lookup_path(path)
        if mode is None:
            # the tree root is a directory
            return "directory"
        return mode_kind(mode)

    def has_filename(self, path):
        try:
            self._lookup_path(path)
        except errors.NoSuchFile:
            return False
        else:
            return True

    def _submodule_info(self):
        if self._submodules is None:
            try:
                with self.get_file('.gitmodules') as f:
                    config = GitConfigFile.from_file(f)
                    self._submodules = {
                        path: (url, section)
                        for path, url, section in parse_submodules(config)}
            except errors.NoSuchFile:
                self._submodules = {}
        return self._submodules

    def list_files(self, include_root=False, from_dir=None, recursive=True,
                   recurse_nested=False):
        if self.tree is None:
            return
        if from_dir is None or from_dir == '.':
            from_dir = u""
        (store, mode, hexsha) = self._lookup_path(from_dir)
        if mode is None:  # Root
            root_ie = self._get_dir_ie(b"", None)
        else:
            parent_path = posixpath.dirname(from_dir)
            parent_id = self.mapping.generate_file_id(parent_path)
            if mode_kind(mode) == 'directory':
                root_ie = self._get_dir_ie(from_dir.encode("utf-8"), parent_id)
            else:
                root_ie = self._get_file_ie(
                    store, from_dir.encode("utf-8"),
                    posixpath.basename(from_dir), mode, hexsha)
        if include_root:
            yield (from_dir, "V", root_ie.kind, root_ie)
        todo = []
        if root_ie.kind == 'directory':
            todo.append((store, from_dir.encode("utf-8"),
                         b"", hexsha, root_ie.file_id))
        while todo:
            (store, path, relpath, hexsha, parent_id) = todo.pop()
            tree = store[hexsha]
            for name, mode, hexsha in tree.iteritems():
                if self.mapping.is_special_file(name):
                    continue
                child_path = posixpath.join(path, name)
                child_relpath = posixpath.join(relpath, name)
                if S_ISGITLINK(mode) and recurse_nested:
                    mode = stat.S_IFDIR
                    store = self._get_submodule_store(child_relpath)
                    hexsha = store[hexsha].tree
                if stat.S_ISDIR(mode):
                    ie = self._get_dir_ie(child_path, parent_id)
                    if recursive:
                        todo.append(
                            (store, child_path, child_relpath, hexsha,
                             ie.file_id))
                else:
                    ie = self._get_file_ie(
                        store, child_path, name, mode, hexsha, parent_id)
                yield (child_relpath.decode('utf-8'), "V", ie.kind, ie)

    def _get_file_ie(self, store, path, name, mode, hexsha, parent_id):
        if not isinstance(path, bytes):
            raise TypeError(path)
        if not isinstance(name, bytes):
            raise TypeError(name)
        kind = mode_kind(mode)
        path = path.decode('utf-8')
        name = name.decode("utf-8")
        file_id = self.mapping.generate_file_id(path)
        ie = entry_factory[kind](file_id, name, parent_id)
        if kind == 'symlink':
            ie.symlink_target = store[hexsha].data.decode('utf-8')
        elif kind == 'tree-reference':
            ie.reference_revision = self.mapping.revision_id_foreign_to_bzr(
                hexsha)
        else:
            data = store[hexsha].data
            ie.text_sha1 = osutils.sha_string(data)
            ie.text_size = len(data)
            ie.executable = mode_is_executable(mode)
        return ie

    def _get_dir_ie(self, path, parent_id):
        path = path.decode('utf-8')
        file_id = self.mapping.generate_file_id(path)
        return GitTreeDirectory(file_id, posixpath.basename(path), parent_id)

    def iter_child_entries(self, path):
        (store, mode, tree_sha) = self._lookup_path(path)

        if mode is not None and not stat.S_ISDIR(mode):
            return

        encoded_path = path.encode('utf-8')
        file_id = self.path2id(path)
        tree = store[tree_sha]
        for name, mode, hexsha in tree.iteritems():
            if self.mapping.is_special_file(name):
                continue
            child_path = posixpath.join(encoded_path, name)
            if stat.S_ISDIR(mode):
                yield self._get_dir_ie(child_path, file_id)
            else:
                yield self._get_file_ie(store, child_path, name, mode, hexsha,
                                        file_id)

    def iter_entries_by_dir(self, specific_files=None,
                            recurse_nested=False):
        if self.tree is None:
            return
        if specific_files is not None:
            if specific_files in ([""], []):
                specific_files = None
            else:
                specific_files = set([p.encode('utf-8')
                                      for p in specific_files])
        todo = deque([(self.store, b"", self.tree, self.path2id(''))])
        if specific_files is None or u"" in specific_files:
            yield u"", self._get_dir_ie(b"", None)
        while todo:
            store, path, tree_sha, parent_id = todo.popleft()
            tree = store[tree_sha]
            extradirs = []
            for name, mode, hexsha in tree.iteritems():
                if self.mapping.is_special_file(name):
                    continue
                child_path = posixpath.join(path, name)
                child_path_decoded = child_path.decode('utf-8')
                if recurse_nested and S_ISGITLINK(mode):
                    mode = stat.S_IFDIR
                    store = self._get_submodule_store(child_path)
                    hexsha = store[hexsha].tree
                if stat.S_ISDIR(mode):
                    if (specific_files is None or
                            any([p for p in specific_files if p.startswith(
                                child_path)])):
                        extradirs.append(
                            (store, child_path, hexsha,
                             self.path2id(child_path_decoded)))
                if specific_files is None or child_path in specific_files:
                    if stat.S_ISDIR(mode):
                        yield (child_path_decoded,
                               self._get_dir_ie(child_path, parent_id))
                    else:
                        yield (child_path_decoded,
                               self._get_file_ie(store, child_path, name, mode,
                                                 hexsha, parent_id))
            todo.extendleft(reversed(extradirs))

    def iter_references(self):
        if self.supports_tree_reference():
            for path, entry in self.iter_entries_by_dir():
                if entry.kind == 'tree-reference':
                    yield path

    def get_revision_id(self):
        """See RevisionTree.get_revision_id."""
        return self._revision_id

    def get_file_sha1(self, path, stat_value=None):
        if self.tree is None:
            raise errors.NoSuchFile(path)
        return osutils.sha_string(self.get_file_text(path))

    def get_file_verifier(self, path, stat_value=None):
        (store, mode, hexsha) = self._lookup_path(path)
        return ("GIT", hexsha)

    def get_file_size(self, path):
        (store, mode, hexsha) = self._lookup_path(path)
        if stat.S_ISREG(mode):
            return len(store[hexsha].data)
        return None

    def get_file_text(self, path):
        """See RevisionTree.get_file_text."""
        (store, mode, hexsha) = self._lookup_path(path)
        if stat.S_ISREG(mode):
            return store[hexsha].data
        else:
            return b""

    def get_symlink_target(self, path):
        """See RevisionTree.get_symlink_target."""
        (store, mode, hexsha) = self._lookup_path(path)
        if stat.S_ISLNK(mode):
            return store[hexsha].data.decode('utf-8')
        else:
            return None

    def get_reference_revision(self, path):
        """See RevisionTree.get_symlink_target."""
        (store, mode, hexsha) = self._lookup_path(path)
        if S_ISGITLINK(mode):
            try:
                nested_repo = self._get_submodule_repository(path.encode('utf-8'))
            except errors.NotBranchError:
                return self.mapping.revision_id_foreign_to_bzr(hexsha)
            else:
                return nested_repo.lookup_foreign_revision_id(hexsha)
        else:
            return None

    def _comparison_data(self, entry, path):
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def path_content_summary(self, path):
        """See Tree.path_content_summary."""
        try:
            (store, mode, hexsha) = self._lookup_path(path)
        except errors.NoSuchFile:
            return ('missing', None, None, None)
        kind = mode_kind(mode)
        if kind == 'file':
            executable = mode_is_executable(mode)
            contents = store[hexsha].data
            return (kind, len(contents), executable,
                    osutils.sha_string(contents))
        elif kind == 'symlink':
            return (kind, None, None, store[hexsha].data.decode('utf-8'))
        elif kind == 'tree-reference':
            nested_repo = self._get_submodule_repository(path.encode('utf-8'))
            return (kind, None, None,
                    nested_repo.lookup_foreign_revision_id(hexsha))
        else:
            return (kind, None, None, None)

    def find_related_paths_across_trees(self, paths, trees=[],
                                        require_versioned=True):
        if paths is None:
            return None
        if require_versioned:
            trees = [self] + (trees if trees is not None else [])
            unversioned = set()
            for p in paths:
                for t in trees:
                    if t.is_versioned(p):
                        break
                else:
                    unversioned.add(p)
            if unversioned:
                raise errors.PathsNotVersionedError(unversioned)
        return filter(self.is_versioned, paths)

    def _iter_tree_contents(self, include_trees=False):
        if self.tree is None:
            return iter([])
        return self.store.iter_tree_contents(
            self.tree, include_trees=include_trees)

    def annotate_iter(self, path, default_revision=CURRENT_REVISION):
        """Return an iterator of revision_id, line tuples.

        For working trees (and mutable trees in general), the special
        revision_id 'current:' will be used for lines that are new in this
        tree, e.g. uncommitted changes.
        :param default_revision: For lines that don't match a basis, mark them
            with this revision id. Not all implementations will make use of
            this value.
        """
        with self.lock_read():
            # Now we have the parents of this content
            from breezy.annotate import Annotator
            from .annotate import AnnotateProvider
            annotator = Annotator(AnnotateProvider(
                self._repository._file_change_scanner))
            this_key = (path, self.get_file_revision(path))
            annotations = [(key[-1], line)
                           for key, line in annotator.annotate_flat(this_key)]
            return annotations

    def _get_rules_searcher(self, default_searcher):
        return default_searcher

    def walkdirs(self, prefix=u""):
        (store, mode, hexsha) = self._lookup_path(prefix)
        todo = deque(
            [(store, prefix.encode('utf-8'), hexsha, self.path2id(prefix))])
        while todo:
            store, path, tree_sha, parent_id = todo.popleft()
            path_decoded = path.decode('utf-8')
            tree = store[tree_sha]
            children = []
            for name, mode, hexsha in tree.iteritems():
                if self.mapping.is_special_file(name):
                    continue
                child_path = posixpath.join(path, name)
                file_id = self.path2id(child_path.decode('utf-8'))
                if stat.S_ISDIR(mode):
                    todo.append((store, child_path, hexsha, file_id))
                children.append(
                    (child_path.decode('utf-8'), name.decode('utf-8'),
                        mode_kind(mode), None,
                        file_id, mode_kind(mode)))
            yield (path_decoded, parent_id), children


def tree_delta_from_git_changes(changes, mappings,
                                specific_files=None,
                                require_versioned=False, include_root=False,
                                target_extras=None):
    """Create a TreeDelta from two git trees.

    source and target are iterators over tuples with:
        (filename, sha, mode)
    """
    (old_mapping, new_mapping) = mappings
    if target_extras is None:
        target_extras = set()
    ret = delta.TreeDelta()
    added = []
    for (oldpath, newpath), (oldmode, newmode), (oldsha, newsha) in changes:
        if newpath == b'' and not include_root:
            continue
        if oldpath is not None:
            oldpath_decoded = oldpath.decode('utf-8')
        else:
            oldpath_decoded = None
        if newpath is not None:
            newpath_decoded = newpath.decode('utf-8')
        else:
            newpath_decoded = None
        if not (specific_files is None or
                (oldpath is not None and
                    osutils.is_inside_or_parent_of_any(
                        specific_files, oldpath_decoded)) or
                (newpath is not None and
                    osutils.is_inside_or_parent_of_any(
                        specific_files, newpath_decoded))):
            continue

        if oldpath_decoded is None:
            fileid = new_mapping.generate_file_id(newpath_decoded)
            oldexe = None
            oldkind = None
            oldname = None
            oldparent = None
            oldversioned = False
        else:
            oldversioned = True
            if oldmode:
                oldexe = mode_is_executable(oldmode)
                oldkind = mode_kind(oldmode)
            else:
                oldexe = False
                oldkind = None
            if oldpath_decoded == u'':
                oldparent = None
                oldname = u''
            else:
                (oldparentpath, oldname) = osutils.split(oldpath_decoded)
                oldparent = old_mapping.generate_file_id(oldparentpath)
            fileid = old_mapping.generate_file_id(oldpath_decoded)
        if newpath_decoded is None:
            newexe = None
            newkind = None
            newname = None
            newparent = None
            newversioned = False
        else:
            newversioned = (newpath_decoded not in target_extras)
            if newmode:
                newexe = mode_is_executable(newmode)
                newkind = mode_kind(newmode)
            else:
                newexe = False
                newkind = None
            if newpath_decoded == u'':
                newparent = None
                newname = u''
            else:
                newparentpath, newname = osutils.split(newpath_decoded)
                newparent = new_mapping.generate_file_id(newparentpath)
        if old_mapping.is_special_file(oldpath):
            oldpath = None
        if new_mapping.is_special_file(newpath):
            newpath = None
        if oldpath is None and newpath is None:
            continue
        change = _mod_tree.TreeChange(
            fileid, (oldpath_decoded, newpath_decoded), (oldsha != newsha),
            (oldversioned, newversioned),
            (oldparent, newparent), (oldname, newname),
            (oldkind, newkind), (oldexe, newexe))
        if oldpath is None:
            added.append((newpath, newkind))
        elif newpath is None or newmode == 0:
            ret.removed.append(change)
        elif oldpath != newpath:
            ret.renamed.append(change)
        elif mode_kind(oldmode) != mode_kind(newmode):
            ret.kind_changed.append(change)
        elif oldsha != newsha or oldmode != newmode:
            if stat.S_ISDIR(oldmode) and stat.S_ISDIR(newmode):
                continue
            ret.modified.append(change)
        else:
            ret.unchanged.append(change)

    implicit_dirs = {b''}
    for path, kind in added:
        if kind == 'directory' or path in target_extras:
            continue
        implicit_dirs.update(osutils.parent_directories(path))

    for path, kind in added:
        if kind == 'directory' and path not in implicit_dirs:
            continue
        path_decoded = osutils.normalized_filename(path)[0]
        parent_path, basename = osutils.split(path_decoded)
        parent_id = new_mapping.generate_file_id(parent_path)
        if path in target_extras:
            ret.unversioned.append(_mod_tree.TreeChange(
                None, (None, path_decoded),
                True, (False, False), (None, parent_id),
                (None, basename), (None, kind), (None, False)))
        else:
            file_id = new_mapping.generate_file_id(path_decoded)
            ret.added.append(
                _mod_tree.TreeChange(
                    file_id, (None, path_decoded), True,
                    (False, True),
                    (None, parent_id),
                    (None, basename), (None, kind), (None, False)))

    return ret


def changes_from_git_changes(changes, mapping, specific_files=None,
                             include_unchanged=False, target_extras=None):
    """Create a iter_changes-like generator from a git stream.

    source and target are iterators over tuples with:
        (filename, sha, mode)
    """
    if target_extras is None:
        target_extras = set()
    for (oldpath, newpath), (oldmode, newmode), (oldsha, newsha) in changes:
        if oldpath is not None:
            oldpath_decoded = oldpath.decode('utf-8')
        else:
            oldpath_decoded = None
        if newpath is not None:
            newpath_decoded = newpath.decode('utf-8')
        else:
            newpath_decoded = None
        if not (specific_files is None or
                (oldpath_decoded is not None and
                    osutils.is_inside_or_parent_of_any(
                        specific_files, oldpath_decoded)) or
                (newpath_decoded is not None and
                    osutils.is_inside_or_parent_of_any(
                        specific_files, newpath_decoded))):
            continue
        if oldpath is not None and mapping.is_special_file(oldpath):
            continue
        if newpath is not None and mapping.is_special_file(newpath):
            continue
        if oldpath_decoded is None:
            fileid = mapping.generate_file_id(newpath_decoded)
            oldexe = None
            oldkind = None
            oldname = None
            oldparent = None
            oldversioned = False
        else:
            oldversioned = True
            if oldmode:
                oldexe = mode_is_executable(oldmode)
                oldkind = mode_kind(oldmode)
            else:
                oldexe = False
                oldkind = None
            if oldpath_decoded == u'':
                oldparent = None
                oldname = u''
            else:
                (oldparentpath, oldname) = osutils.split(oldpath_decoded)
                oldparent = mapping.generate_file_id(oldparentpath)
            fileid = mapping.generate_file_id(oldpath_decoded)
        if newpath_decoded is None:
            newexe = None
            newkind = None
            newname = None
            newparent = None
            newversioned = False
        else:
            newversioned = (newpath_decoded not in target_extras)
            if newmode:
                newexe = mode_is_executable(newmode)
                newkind = mode_kind(newmode)
            else:
                newexe = False
                newkind = None
            if newpath_decoded == u'':
                newparent = None
                newname = u''
            else:
                newparentpath, newname = osutils.split(newpath_decoded)
                newparent = mapping.generate_file_id(newparentpath)
        if (not include_unchanged and
            oldkind == 'directory' and newkind == 'directory' and
                oldpath_decoded == newpath_decoded):
            continue
        yield _mod_tree.TreeChange(
            fileid, (oldpath_decoded, newpath_decoded), (oldsha != newsha),
            (oldversioned, newversioned),
            (oldparent, newparent), (oldname, newname),
            (oldkind, newkind), (oldexe, newexe))


class InterGitTrees(_mod_tree.InterTree):
    """InterTree that works between two git trees."""

    _matching_from_tree_format = None
    _matching_to_tree_format = None
    _test_mutable_trees_to_test_trees = None

    @classmethod
    def is_compatible(cls, source, target):
        return (isinstance(source, GitRevisionTree) and
                isinstance(target, GitRevisionTree))

    def compare(self, want_unchanged=False, specific_files=None,
                extra_trees=None, require_versioned=False, include_root=False,
                want_unversioned=False):
        with self.lock_read():
            changes, target_extras = self._iter_git_changes(
                want_unchanged=want_unchanged,
                require_versioned=require_versioned,
                specific_files=specific_files,
                extra_trees=extra_trees,
                want_unversioned=want_unversioned)
            return tree_delta_from_git_changes(
                changes, (self.source.mapping, self.target.mapping),
                specific_files=specific_files,
                include_root=include_root, target_extras=target_extras)

    def iter_changes(self, include_unchanged=False, specific_files=None,
                     pb=None, extra_trees=[], require_versioned=True,
                     want_unversioned=False):
        with self.lock_read():
            changes, target_extras = self._iter_git_changes(
                want_unchanged=include_unchanged,
                require_versioned=require_versioned,
                specific_files=specific_files,
                extra_trees=extra_trees,
                want_unversioned=want_unversioned)
            return changes_from_git_changes(
                changes, self.target.mapping,
                specific_files=specific_files,
                include_unchanged=include_unchanged,
                target_extras=target_extras)

    def _iter_git_changes(self, want_unchanged=False, specific_files=None,
                          require_versioned=False, extra_trees=None,
                          want_unversioned=False):
        raise NotImplementedError(self._iter_git_changes)

    def find_target_path(self, path, recurse='none'):
        ret = self.find_target_paths([path], recurse=recurse)
        return ret[path]

    def find_source_path(self, path, recurse='none'):
        ret = self.find_source_paths([path], recurse=recurse)
        return ret[path]

    def find_target_paths(self, paths, recurse='none'):
        paths = set(paths)
        ret = {}
        changes = self._iter_git_changes(specific_files=paths)[0]
        for (oldpath, newpath), (oldmode, newmode), (oldsha, newsha) in changes:
            if oldpath in paths:
                ret[oldpath] = newpath
        for path in paths:
            if path not in ret:
                if self.source.has_filename(path):
                    if self.target.has_filename(path):
                        ret[path] = path
                    else:
                        ret[path] = None
                else:
                    raise errors.NoSuchFile(path)
        return ret

    def find_source_paths(self, paths, recurse='none'):
        paths = set(paths)
        ret = {}
        changes = self._iter_git_changes(specific_files=paths)[0]
        for (oldpath, newpath), (oldmode, newmode), (oldsha, newsha) in changes:
            if newpath in paths:
                ret[newpath] = oldpath
        for path in paths:
            if path not in ret:
                if self.target.has_filename(path):
                    if self.source.has_filename(path):
                        ret[path] = path
                    else:
                        ret[path] = None
                else:
                    raise errors.NoSuchFile(path)
        return ret


class InterGitRevisionTrees(InterGitTrees):
    """InterTree that works between two git revision trees."""

    _matching_from_tree_format = None
    _matching_to_tree_format = None
    _test_mutable_trees_to_test_trees = None

    @classmethod
    def is_compatible(cls, source, target):
        return (isinstance(source, GitRevisionTree) and
                isinstance(target, GitRevisionTree))

    def _iter_git_changes(self, want_unchanged=False, specific_files=None,
                          require_versioned=True, extra_trees=None,
                          want_unversioned=False):
        trees = [self.source]
        if extra_trees is not None:
            trees.extend(extra_trees)
        if specific_files is not None:
            specific_files = self.target.find_related_paths_across_trees(
                specific_files, trees,
                require_versioned=require_versioned)

        if (self.source._repository._git.object_store !=
                self.target._repository._git.object_store):
            store = OverlayObjectStore(
                [self.source._repository._git.object_store,
                    self.target._repository._git.object_store])
        else:
            store = self.source._repository._git.object_store
        return store.tree_changes(
            self.source.tree, self.target.tree, want_unchanged=want_unchanged,
            include_trees=True, change_type_same=True), set()


_mod_tree.InterTree.register_optimiser(InterGitRevisionTrees)


class MutableGitIndexTree(mutabletree.MutableTree):

    def __init__(self):
        self._lock_mode = None
        self._lock_count = 0
        self._versioned_dirs = None
        self._index_dirty = False
        self._submodules = None

    def is_versioned(self, path):
        with self.lock_read():
            path = path.rstrip('/').encode('utf-8')
            (index, subpath) = self._lookup_index(path)
            return (subpath in index or self._has_dir(path))

    def _has_dir(self, path):
        if not isinstance(path, bytes):
            raise TypeError(path)
        if path == b"":
            return True
        if self._versioned_dirs is None:
            self._load_dirs()
        return path in self._versioned_dirs

    def _load_dirs(self):
        if self._lock_mode is None:
            raise errors.ObjectNotLocked(self)
        self._versioned_dirs = set()
        for p, i in self._recurse_index_entries():
            self._ensure_versioned_dir(posixpath.dirname(p))

    def _ensure_versioned_dir(self, dirname):
        if not isinstance(dirname, bytes):
            raise TypeError(dirname)
        if dirname in self._versioned_dirs:
            return
        if dirname != b"":
            self._ensure_versioned_dir(posixpath.dirname(dirname))
        self._versioned_dirs.add(dirname)

    def path2id(self, path):
        with self.lock_read():
            path = path.rstrip('/')
            if self.is_versioned(path.rstrip('/')):
                return self.mapping.generate_file_id(
                    osutils.safe_unicode(path))
            return None

    def id2path(self, file_id, recurse='down'):
        if file_id is None:
            return ''
        if type(file_id) is not bytes:
            raise TypeError(file_id)
        with self.lock_read():
            try:
                path = self.mapping.parse_file_id(file_id)
            except ValueError:
                raise errors.NoSuchId(self, file_id)
            if self.is_versioned(path):
                return path
            raise errors.NoSuchId(self, file_id)

    def _set_root_id(self, file_id):
        raise errors.UnsupportedOperation(self._set_root_id, self)

    def _add(self, files, ids, kinds):
        for (path, file_id, kind) in zip(files, ids, kinds):
            if file_id is not None:
                raise workingtree.SettingFileIdUnsupported()
            path, can_access = osutils.normalized_filename(path)
            if not can_access:
                raise errors.InvalidNormalization(path)
            self._index_add_entry(path, kind)

    def _read_submodule_head(self, path):
        raise NotImplementedError(self._read_submodule_head)

    def _submodule_info(self):
        if self._submodules is None:
            try:
                with self.get_file('.gitmodules') as f:
                    config = GitConfigFile.from_file(f)
                    self._submodules = {
                        path: (url, section)
                        for path, url, section in parse_submodules(config)}
            except errors.NoSuchFile:
                self._submodules = {}
        return self._submodules

    def _lookup_index(self, encoded_path):
        if not isinstance(encoded_path, bytes):
            raise TypeError(encoded_path)
        # Common case:
        if encoded_path in self.index:
            return self.index, encoded_path
        # TODO(jelmer): Perhaps have a cache with paths under which some
        # submodules exist?
        index = self.index
        remaining_path = encoded_path
        while True:
            parts = remaining_path.split(b'/')
            for i in range(1, len(parts)):
                basepath = b'/'.join(parts[:i])
                try:
                    (ctime, mtime, dev, ino, mode, uid, gid, size, sha,
                     flags) = index[basepath]
                except KeyError:
                    continue
                else:
                    if S_ISGITLINK(mode):
                        index = self._get_submodule_index(basepath)
                        remaining_path = b'/'.join(parts[i:])
                        break
                    else:
                        return index, remaining_path
            else:
                return index, remaining_path
        return index, remaining_path

    def _index_del_entry(self, index, path):
        del index[path]
        # TODO(jelmer): Keep track of dirty per index
        self._index_dirty = True

    def _index_add_entry(self, path, kind, flags=0, reference_revision=None):
        if kind == "directory":
            # Git indexes don't contain directories
            return
        if kind == "file":
            blob = Blob()
            try:
                file, stat_val = self.get_file_with_stat(path)
            except (errors.NoSuchFile, IOError):
                # TODO: Rather than come up with something here, use the old
                # index
                file = BytesIO()
                stat_val = os.stat_result(
                    (stat.S_IFREG | 0o644, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            with file:
                blob.set_raw_string(file.read())
            # Add object to the repository if it didn't exist yet
            if blob.id not in self.store:
                self.store.add_object(blob)
            hexsha = blob.id
        elif kind == "symlink":
            blob = Blob()
            try:
                stat_val = self._lstat(path)
            except EnvironmentError:
                # TODO: Rather than come up with something here, use the
                # old index
                stat_val = os.stat_result(
                    (stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            blob.set_raw_string(
                self.get_symlink_target(path).encode("utf-8"))
            # Add object to the repository if it didn't exist yet
            if blob.id not in self.store:
                self.store.add_object(blob)
            hexsha = blob.id
        elif kind == "tree-reference":
            if reference_revision is not None:
                hexsha = self.branch.lookup_bzr_revision_id(
                    reference_revision)[0]
            else:
                hexsha = self._read_submodule_head(path)
                if hexsha is None:
                    raise errors.NoCommits(path)
            try:
                stat_val = self._lstat(path)
            except EnvironmentError:
                stat_val = os.stat_result(
                    (S_IFGITLINK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            stat_val = os.stat_result((S_IFGITLINK, ) + stat_val[1:])
        else:
            raise AssertionError("unknown kind '%s'" % kind)
        # Add an entry to the index or update the existing entry
        ensure_normalized_path(path)
        encoded_path = path.encode("utf-8")
        if b'\r' in encoded_path or b'\n' in encoded_path:
            # TODO(jelmer): Why do we need to do this?
            trace.mutter('ignoring path with invalid newline in it: %r', path)
            return
        (index, index_path) = self._lookup_index(encoded_path)
        index[index_path] = index_entry_from_stat(stat_val, hexsha, flags)
        self._index_dirty = True
        if self._versioned_dirs is not None:
            self._ensure_versioned_dir(index_path)

    def _recurse_index_entries(self, index=None, basepath=b"",
                               recurse_nested=False):
        # Iterate over all index entries
        with self.lock_read():
            if index is None:
                index = self.index
            for path, value in index.items():
                (ctime, mtime, dev, ino, mode, uid, gid, size, sha,
                 flags) = value
                if S_ISGITLINK(mode) and recurse_nested:
                    subindex = self._get_submodule_index(path)
                    for entry in self._recurse_index_entries(
                            index=subindex, basepath=path,
                            recurse_nested=recurse_nested):
                        yield entry
                else:
                    yield (posixpath.join(basepath, path), value)

    def iter_entries_by_dir(self, specific_files=None,
                            recurse_nested=False):
        with self.lock_read():
            if specific_files is not None:
                specific_files = set(specific_files)
            else:
                specific_files = None
            root_ie = self._get_dir_ie(u"", None)
            ret = {}
            if specific_files is None or u"" in specific_files:
                ret[(u"", u"")] = root_ie
            dir_ids = {u"": root_ie.file_id}
            for path, value in self._recurse_index_entries(
                    recurse_nested=recurse_nested):
                if self.mapping.is_special_file(path):
                    continue
                path = path.decode("utf-8")
                if specific_files is not None and path not in specific_files:
                    continue
                (parent, name) = posixpath.split(path)
                try:
                    file_ie = self._get_file_ie(name, path, value, None)
                except errors.NoSuchFile:
                    continue
                if specific_files is None:
                    for (dir_path, dir_ie) in self._add_missing_parent_ids(
                            parent, dir_ids):
                        ret[(posixpath.dirname(dir_path), dir_path)] = dir_ie
                file_ie.parent_id = self.path2id(parent)
                ret[(posixpath.dirname(path), path)] = file_ie
            # Special casing for directories
            if specific_files:
                for path in specific_files:
                    key = (posixpath.dirname(path), path)
                    if key not in ret and self.is_versioned(path):
                        ret[key] = self._get_dir_ie(path, self.path2id(key[0]))
            return ((path, ie) for ((_, path), ie) in sorted(viewitems(ret)))

    def iter_references(self):
        if self.supports_tree_reference():
            # TODO(jelmer): Implement a more efficient version of this
            for path, entry in self.iter_entries_by_dir():
                if entry.kind == 'tree-reference':
                    yield path

    def _get_dir_ie(self, path, parent_id):
        file_id = self.path2id(path)
        return GitTreeDirectory(file_id,
                                posixpath.basename(path).strip("/"), parent_id)

    def _get_file_ie(self, name, path, value, parent_id):
        if not isinstance(name, text_type):
            raise TypeError(name)
        if not isinstance(path, text_type):
            raise TypeError(path)
        if not isinstance(value, tuple) or len(value) != 10:
            raise TypeError(value)
        (ctime, mtime, dev, ino, mode, uid, gid, size, sha, flags) = value
        file_id = self.path2id(path)
        if not isinstance(file_id, bytes):
            raise TypeError(file_id)
        kind = mode_kind(mode)
        ie = entry_factory[kind](file_id, name, parent_id)
        if kind == 'symlink':
            ie.symlink_target = self.get_symlink_target(path)
        elif kind == 'tree-reference':
            ie.reference_revision = self.get_reference_revision(path)
        else:
            try:
                data = self.get_file_text(path)
            except errors.NoSuchFile:
                data = None
            except IOError as e:
                if e.errno != errno.ENOENT:
                    raise
                data = None
            if data is None:
                data = self.branch.repository._git.object_store[sha].data
            ie.text_sha1 = osutils.sha_string(data)
            ie.text_size = len(data)
            ie.executable = bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)
        return ie

    def _add_missing_parent_ids(self, path, dir_ids):
        if path in dir_ids:
            return []
        parent = posixpath.dirname(path).strip("/")
        ret = self._add_missing_parent_ids(parent, dir_ids)
        parent_id = dir_ids[parent]
        ie = self._get_dir_ie(path, parent_id)
        dir_ids[path] = ie.file_id
        ret.append((path, ie))
        return ret

    def _comparison_data(self, entry, path):
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def _unversion_path(self, path):
        if self._lock_mode is None:
            raise errors.ObjectNotLocked(self)
        encoded_path = path.encode("utf-8")
        count = 0
        (index, subpath) = self._lookup_index(encoded_path)
        try:
            self._index_del_entry(index, encoded_path)
        except KeyError:
            # A directory, perhaps?
            # TODO(jelmer): Deletes that involve submodules?
            for p in list(index):
                if p.startswith(subpath + b"/"):
                    count += 1
                    self._index_del_entry(index, p)
        else:
            count = 1
        self._versioned_dirs = None
        return count

    def unversion(self, paths):
        with self.lock_tree_write():
            for path in paths:
                if self._unversion_path(path) == 0:
                    raise errors.NoSuchFile(path)
            self._versioned_dirs = None
            self.flush()

    def flush(self):
        pass

    def update_basis_by_delta(self, revid, delta):
        # TODO(jelmer): This shouldn't be called, it's inventory specific.
        for (old_path, new_path, file_id, ie) in delta:
            if old_path is not None:
                (index, old_subpath) = self._lookup_index(
                    old_path.encode('utf-8'))
                if old_subpath in index:
                    self._index_del_entry(index, old_subpath)
                    self._versioned_dirs = None
            if new_path is not None and ie.kind != 'directory':
                self._index_add_entry(new_path, ie.kind)
        self.flush()
        self._set_merges_from_parent_ids([])

    def move(self, from_paths, to_dir=None, after=None):
        rename_tuples = []
        with self.lock_tree_write():
            to_abs = self.abspath(to_dir)
            if not os.path.isdir(to_abs):
                raise errors.BzrMoveFailedError('', to_dir,
                                                errors.NotADirectory(to_abs))

            for from_rel in from_paths:
                from_tail = os.path.split(from_rel)[-1]
                to_rel = os.path.join(to_dir, from_tail)
                self.rename_one(from_rel, to_rel, after=after)
                rename_tuples.append((from_rel, to_rel))
            self.flush()
            return rename_tuples

    def rename_one(self, from_rel, to_rel, after=None):
        from_path = from_rel.encode("utf-8")
        to_rel, can_access = osutils.normalized_filename(to_rel)
        if not can_access:
            raise errors.InvalidNormalization(to_rel)
        to_path = to_rel.encode("utf-8")
        with self.lock_tree_write():
            if not after:
                # Perhaps it's already moved?
                after = (
                    not self.has_filename(from_rel) and
                    self.has_filename(to_rel) and
                    not self.is_versioned(to_rel))
            if after:
                if not self.has_filename(to_rel):
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel, errors.NoSuchFile(to_rel))
                if self.basis_tree().is_versioned(to_rel):
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel, errors.AlreadyVersionedError(to_rel))

                kind = self.kind(to_rel)
            else:
                try:
                    to_kind = self.kind(to_rel)
                except errors.NoSuchFile:
                    exc_type = errors.BzrRenameFailedError
                    to_kind = None
                else:
                    exc_type = errors.BzrMoveFailedError
                if self.is_versioned(to_rel):
                    raise exc_type(from_rel, to_rel,
                                   errors.AlreadyVersionedError(to_rel))
                if not self.has_filename(from_rel):
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel, errors.NoSuchFile(from_rel))
                kind = self.kind(from_rel)
                if not self.is_versioned(from_rel) and kind != 'directory':
                    raise exc_type(from_rel, to_rel,
                                   errors.NotVersionedError(from_rel))
                if self.has_filename(to_rel):
                    raise errors.RenameFailedFilesExist(
                        from_rel, to_rel, errors.FileExists(to_rel))

                kind = self.kind(from_rel)

            if not after and kind != 'directory':
                (index, from_subpath) = self._lookup_index(from_path)
                if from_subpath not in index:
                    # It's not a file
                    raise errors.BzrMoveFailedError(
                        from_rel, to_rel,
                        errors.NotVersionedError(path=from_rel))

            if not after:
                try:
                    self._rename_one(from_rel, to_rel)
                except OSError as e:
                    if e.errno == errno.ENOENT:
                        raise errors.BzrMoveFailedError(
                            from_rel, to_rel, errors.NoSuchFile(to_rel))
                    raise
            if kind != 'directory':
                (index, from_index_path) = self._lookup_index(from_path)
                try:
                    self._index_del_entry(index, from_path)
                except KeyError:
                    pass
                self._index_add_entry(to_rel, kind)
            else:
                todo = [(p, i) for (p, i) in self._recurse_index_entries()
                        if p.startswith(from_path + b'/')]
                for child_path, child_value in todo:
                    (child_to_index, child_to_index_path) = self._lookup_index(
                        posixpath.join(to_path, posixpath.relpath(child_path, from_path)))
                    child_to_index[child_to_index_path] = child_value
                    # TODO(jelmer): Mark individual index as dirty
                    self._index_dirty = True
                    (child_from_index, child_from_index_path) = self._lookup_index(
                        child_path)
                    self._index_del_entry(
                        child_from_index, child_from_index_path)

            self._versioned_dirs = None
            self.flush()

    def find_related_paths_across_trees(self, paths, trees=[],
                                        require_versioned=True):
        if paths is None:
            return None

        if require_versioned:
            trees = [self] + (trees if trees is not None else [])
            unversioned = set()
            for p in paths:
                for t in trees:
                    if t.is_versioned(p):
                        break
                else:
                    unversioned.add(p)
            if unversioned:
                raise errors.PathsNotVersionedError(unversioned)

        return filter(self.is_versioned, paths)

    def path_content_summary(self, path):
        """See Tree.path_content_summary."""
        try:
            stat_result = self._lstat(path)
        except OSError as e:
            if getattr(e, 'errno', None) == errno.ENOENT:
                # no file.
                return ('missing', None, None, None)
            # propagate other errors
            raise
        kind = mode_kind(stat_result.st_mode)
        if kind == 'file':
            return self._file_content_summary(path, stat_result)
        elif kind == 'directory':
            # perhaps it looks like a plain directory, but it's really a
            # reference.
            if self._directory_is_tree_reference(path):
                kind = 'tree-reference'
            return kind, None, None, None
        elif kind == 'symlink':
            target = osutils.readlink(self.abspath(path))
            return ('symlink', None, None, target)
        else:
            return (kind, None, None, None)

    def stored_kind(self, relpath):
        (index, index_path) = self._lookup_index(relpath.encode('utf-8'))
        if index is None:
            return kind
        try:
            mode = index[index_path].mode
        except KeyError:
            return kind
        else:
            if S_ISGITLINK(mode):
                return 'tree-reference'
            return 'directory'

    def kind(self, relpath):
        kind = osutils.file_kind(self.abspath(relpath))
        if kind == 'directory':
            if self._directory_is_tree_reference(relpath):
                return 'tree-reference'
            return 'directory'
        else:
            return kind

    def _live_entry(self, relpath):
        raise NotImplementedError(self._live_entry)

    def get_transform(self, pb=None):
        from ..transform import TreeTransform
        return TreeTransform(self, pb=pb)



class InterIndexGitTree(InterGitTrees):
    """InterTree that works between a Git revision tree and an index."""

    def __init__(self, source, target):
        super(InterIndexGitTree, self).__init__(source, target)
        self._index = target.index

    @classmethod
    def is_compatible(cls, source, target):
        return (isinstance(source, GitRevisionTree) and
                isinstance(target, MutableGitIndexTree))

    def _iter_git_changes(self, want_unchanged=False, specific_files=None,
                          require_versioned=False, extra_trees=None,
                          want_unversioned=False):
        trees = [self.source]
        if extra_trees is not None:
            trees.extend(extra_trees)
        if specific_files is not None:
            specific_files = self.target.find_related_paths_across_trees(
                specific_files, trees,
                require_versioned=require_versioned)
        # TODO(jelmer): Restrict to specific_files, for performance reasons.
        with self.lock_read():
            return changes_between_git_tree_and_working_copy(
                self.source.store, self.source.tree,
                self.target, want_unchanged=want_unchanged,
                want_unversioned=want_unversioned)


_mod_tree.InterTree.register_optimiser(InterIndexGitTree)


def changes_between_git_tree_and_working_copy(store, from_tree_sha, target,
                                              want_unchanged=False,
                                              want_unversioned=False):
    """Determine the changes between a git tree and a working tree with index.

    """
    extras = set()
    blobs = {}
    # Report dirified directories to commit_tree first, so that they can be
    # replaced with non-empty directories if they have contents.
    dirified = []
    trust_executable = target._supports_executable()
    for path, index_entry in target._recurse_index_entries():
        try:
            live_entry = target._live_entry(path)
        except EnvironmentError as e:
            if e.errno == errno.ENOENT:
                # Entry was removed; keep it listed, but mark it as gone.
                blobs[path] = (ZERO_SHA, 0)
            else:
                raise
        else:
            if live_entry is None:
                # Entry was turned into a directory.
                # Maybe it's just a submodule that's not checked out?
                if S_ISGITLINK(index_entry.mode):
                    blobs[path] = (index_entry.sha, index_entry.mode)
                else:
                    dirified.append((path, Tree().id, stat.S_IFDIR))
                    store.add_object(Tree())
            else:
                mode = live_entry.mode
                if not trust_executable:
                    if mode_is_executable(index_entry.mode):
                        mode |= 0o111
                    else:
                        mode &= ~0o111
                blobs[path] = (live_entry.sha, cleanup_mode(live_entry.mode))
    if want_unversioned:
        for e in target.extras():
            st = target._lstat(e)
            try:
                np, accessible = osutils.normalized_filename(e)
            except UnicodeDecodeError:
                raise errors.BadFilenameEncoding(
                    e, osutils._fs_enc)
            if stat.S_ISDIR(st.st_mode):
                blob = Tree()
            elif stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                blob = blob_from_path_and_stat(
                    target.abspath(e).encode(osutils._fs_enc), st)
            else:
                continue
            store.add_object(blob)
            np = np.encode('utf-8')
            blobs[np] = (blob.id, cleanup_mode(st.st_mode))
            extras.add(np)
    to_tree_sha = commit_tree(
        store, dirified + [(p, s, m) for (p, (s, m)) in blobs.items()])
    return store.tree_changes(
        from_tree_sha, to_tree_sha, include_trees=True,
        want_unchanged=want_unchanged, change_type_same=True), extras
