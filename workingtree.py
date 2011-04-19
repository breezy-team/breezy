# Copyright (C) 2008-2011 Jelmer Vernooij <jelmer@samba.org>
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


"""An adapter between a Git index and a Bazaar Working Tree"""


from cStringIO import (
    StringIO,
    )
import errno
from dulwich.index import (
    Index,
    )
from dulwich.objects import (
    Blob,
    ZERO_SHA,
    )
import os
import posixpath
import stat

from bzrlib import (
    errors,
    conflicts as _mod_conflicts,
    ignores,
    inventory,
    lockable_files,
    lockdir,
    osutils,
    transport,
    tree,
    workingtree,
    )
from bzrlib.decorators import (
    needs_read_lock,
    )


from bzrlib.plugins.git.dir import (
    LocalGitDir,
    )
from bzrlib.plugins.git.tree import (
    changes_from_git_changes,
    tree_delta_from_git_changes,
    )
from bzrlib.plugins.git.mapping import (
    GitFileIdMap,
    mode_kind,
    )

IGNORE_FILENAME = ".gitignore"


class GitWorkingTree(workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, bzrdir, repo, branch, index):
        self.basedir = bzrdir.root_transport.local_abspath('.')
        self.bzrdir = bzrdir
        self.repository = repo
        self.mapping = self.repository.get_mapping()
        self._branch = branch
        self._transport = bzrdir.transport

        self.controldir = self.bzrdir.transport.local_abspath('bzr')

        try:
            os.makedirs(self.controldir)
            os.makedirs(os.path.join(self.controldir, 'lock'))
        except OSError:
            pass

        self._control_files = lockable_files.LockableFiles(
            transport.get_transport(self.controldir), 'lock', lockdir.LockDir)
        self._format = GitWorkingTreeFormat()
        self.index = index
        self.views = self._make_views()
        self._rules_searcher = None
        self._detect_case_handling()

    def _index_add_entry(self, path, file_id, kind):
        if kind == "directory":
            # Git indexes don't contain directories
            return
        if kind == "file":
            blob = Blob()
            try:
                file, stat_val = self.get_file_with_stat(file_id, path)
            except (errors.NoSuchFile, IOError):
                # TODO: Rather than come up with something here, use the old index
                file = StringIO()
                from posix import stat_result
                stat_val = stat_result((stat.S_IFREG | 0644, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            blob.set_raw_string(file.read())
        elif kind == "symlink":
            blob = Blob()
            try:
                stat_val = os.lstat(self.abspath(path))
            except (errors.NoSuchFile, OSError):
                # TODO: Rather than come up with something here, use the 
                # old index
                from posix import stat_result
                stat_val = stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            blob.set_raw_string(self.get_symlink_target(file_id).encode("utf-8"))
        else:
            raise AssertionError("unknown kind '%s'" % kind)
        # Add object to the repository if it didn't exist yet
        if not blob.id in self.repository._git.object_store:
            self.repository._git.object_store.add_object(blob)
        # Add an entry to the index or update the existing entry
        flags = 0 # FIXME
        self.index[path.encode("utf-8")] = (stat_val.st_ctime,
                stat_val.st_mtime, stat_val.st_dev, stat_val.st_ino,
                stat_val.st_mode, stat_val.st_uid, stat_val.st_gid,
                stat_val.st_size, blob.id, flags)

    def _add(self, files, ids, kinds):
        for (path, file_id, kind) in zip(files, ids, kinds):
            self._index_add_entry(path, file_id, kind)

    def get_root_id(self):
        return self.mapping.generate_file_id("")

    def extras(self):
        """Yield all unversioned files in this WorkingTree.
        """
        for (dirpath, dirnames, filenames) in os.walk(self.basedir):
            if self.bzrdir.is_control_filename(dirpath[len(self.basedir):].strip("/")):
                continue
            for filename in filenames:
                relpath = os.path.join(dirpath[len(self.basedir):].strip("/"), filename)
                if not relpath in self.index:
                    yield relpath

    def unlock(self):
        # non-implementation specific cleanup
        self._cleanup()

        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()

    def _rewrite_index(self):
        self.index.clear()
        for path, entry in self._inventory.iter_entries():
            self._index_add_entry(path, entry.file_id, entry.kind)

    def flush(self):
        # TODO: Maybe this should only write on dirty ?
        if self._control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        self._rewrite_index()
        self.index.write()

    def __iter__(self):
        for path in self.index:
            yield self._fileid_map.lookup_file_id(path)

    def id2path(self, file_id):
        if type(file_id) != str:
            raise AssertionError
        path = self._fileid_map.lookup_path(file_id)
        if path in self.index:
            return path
        raise errors.NoSuchId(None, file_id)

    def get_ignore_list(self):
        ignoreset = getattr(self, '_ignoreset', None)
        if ignoreset is not None:
            return ignoreset

        ignore_globs = set()
        ignore_globs.update(ignores.get_runtime_ignores())
        ignore_globs.update(ignores.get_user_ignores())
        if self.has_filename(IGNORE_FILENAME):
            f = self.get_file_byname(IGNORE_FILENAME)
            try:
                ignore_globs.update(ignores.parse_ignore_file(f))
            finally:
                f.close()
        self._ignoreset = ignore_globs
        return ignore_globs

    def set_last_revision(self, revid):
        self._change_last_revision(revid)

    def _reset_data(self):
        try:
            head = self.repository._git.head()
        except KeyError, name:
            raise errors.NotBranchError("branch %s at %s" % (name, self.repository.base))
        store = self.repository._git.object_store
        if head == ZERO_SHA:
            self._fileid_map = GitFileIdMap({}, self.mapping)
        else:
            self._fileid_map = self.mapping.get_fileid_map(store.__getitem__,
                store[head].tree)

    @needs_read_lock
    def get_file_sha1(self, file_id, path=None, stat_value=None):
        if not path:
            path = self.id2path(file_id)
        try:
            return osutils.sha_file_by_name(self.abspath(path).encode(osutils._fs_enc))
        except OSError, (num, msg):
            if num in (errno.EISDIR, errno.ENOENT):
                return None
            raise

    def revision_tree(self, revid):
        return self.repository.revision_tree(revid)

    def _get_dir_ie(self, path, parent_id):
        file_id = self._fileid_map.lookup_file_id(path)
        return inventory.InventoryDirectory(file_id,
            posixpath.dirname(path).strip("/"), parent_id)

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

    def _get_file_ie(self, path, value, parent_id):
        assert isinstance(path, str)
        assert isinstance(value, tuple) and len(value) == 10
        (ctime, mtime, dev, ino, mode, uid, gid, size, sha, flags) = value
        file_id = self._fileid_map.lookup_file_id(path)
        if type(file_id) != str:
            raise AssertionError
        kind = mode_kind(mode)
        ie = inventory.entry_factory[kind](file_id,
            posixpath.basename(path.decode("utf-8")), parent_id)
        if kind == 'symlink':
            ie.symlink_target = self.get_symlink_target(file_id, path)
        else:
            data = self.get_file_text(file_id, path)
            ie.text_sha1 = osutils.sha_string(data)
            ie.text_size = len(data)
            ie.executable = self.is_executable(file_id, path)
        ie.revision = None
        return ie

    def _is_executable_from_path_and_stat_from_stat(self, path, stat_result):
        mode = stat_result.st_mode
        return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    if not osutils.supports_executable():
        def is_executable(self, file_id, path=None):
            basis_tree = self.basis_tree()
            if file_id in basis_tree:
                return basis_tree.is_executable(file_id)
            # Default to not executable
            return False
    else:
        def is_executable(self, file_id, path=None):
            if not path:
                path = self.id2path(file_id)
            mode = os.lstat(self.abspath(path)).st_mode
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

        _is_executable_from_path_and_stat = \
            _is_executable_from_path_and_stat_from_stat

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        # FIXME: Yield non-versioned files
        # FIXME: support from_dir
        # FIXME: Support recursive
        dir_ids = {}
        root_ie = self._get_dir_ie("", None)
        if include_root and not from_dir:
            yield "", "V", root_ie.kind, root_ie.file_id, root_ie
        dir_ids[""] = root_ie.file_id
        for path, value in self.index.iteritems():
            parent = posixpath.dirname(path).strip("/")
            for dir_path, dir_ie in self._add_missing_parent_ids(parent, dir_ids):
                yield dir_path, "V", dir_ie.kind, dir_ie.file_id, dir_ie
            ie = self._get_file_ie(path, value, dir_ids[parent])
            yield path, "V", ie.kind, ie.file_id, ie

    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        # FIXME: Support specific_file_ids
        # FIXME: Is return order correct?
        if specific_file_ids is not None:
            raise NotImplementedError(self.iter_entries_by_dir)
        root_ie = self._get_dir_ie("", None)
        yield "", root_ie
        dir_ids = {"": root_ie.file_id}
        for path, value in self.index.iteritems():
            parent = posixpath.dirname(path).strip("/")
            for (dir_path, dir_ie) in self._add_missing_parent_ids(parent, dir_ids):
                yield dir_path, dir_ie
            parent_id = self.fileid_map.lookup_file_id(parent)
            yield path, self._get_file_ie(path, value, parent_id)

    @needs_read_lock
    def conflicts(self):
        # FIXME:
        return _mod_conflicts.ConflictList()


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    @property
    def _matchingbzrdir(self):
        from bzrlib.plugins.git.dir import LocalGitControlDirFormat
        return LocalGitControlDirFormat()

    def get_format_description(self):
        return "Git Working Tree"

    def initialize(self, a_bzrdir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """See WorkingTreeFormat.initialize()."""
        if not isinstance(a_bzrdir, LocalGitDir):
            raise errors.IncompatibleFormat(self, a_bzrdir)
        index = Index(a_bzrdir.root_transport.local_abspath(".git/index"))
        index.write()
        return GitWorkingTree(a_bzrdir, a_bzrdir.open_repository(),
            a_bzrdir.open_branch(), index)


class InterIndexGitTree(tree.InterTree):
    """InterTree that works between a Git revision tree and an index."""

    def __init__(self, source, target):
        super(InterIndexGitTree, self).__init__(source, target)
        self._index = target.index

    @classmethod
    def is_compatible(cls, source, target):
        from bzrlib.plugins.git.repository import GitRevisionTree
        return (isinstance(source, GitRevisionTree) and 
                isinstance(target, GitWorkingTree))

    def compare(self, want_unchanged=False, specific_files=None,
                extra_trees=None, require_versioned=False, include_root=False,
                want_unversioned=False):
        changes = self._index.changes_from_tree(
            self.source._repository._git.object_store, self.source.tree, 
            want_unchanged=want_unchanged)
        source_fileid_map = self.source.mapping.get_fileid_map(
            self.source._repository._git.object_store.__getitem__,
            self.source.tree)
        if self.target.mapping.BZR_FILE_IDS_FILE is not None:
            file_id = self.target.path2id(
                self.target.mapping.BZR_FILE_IDS_FILE)
            if file_id is None:
                target_fileid_map = {}
            else:
                target_fileid_map = self.target.mapping.import_fileid_map(Blob.from_string(self.target.get_file_text(file_id)))
        else:
            target_fileid_map = {}
        target_fileid_map = GitFileIdMap(target_fileid_map, self.target.mapping)
        ret = tree_delta_from_git_changes(changes, self.target.mapping,
            (source_fileid_map, target_fileid_map),
            specific_file=specific_files, require_versioned=require_versioned)
        if want_unversioned:
            for e in self.target.extras():
                ret.unversioned.append((e, None, osutils.file_kind(self.target.abspath(e))))
        return ret

    def iter_changes(self, include_unchanged=False, specific_files=None,
        pb=None, extra_trees=[], require_versioned=True, want_unversioned=False):
        changes = self._index.changes_from_tree(
            self.source._repository._git.object_store, self.source.tree,
            want_unchanged=include_unchanged)
        # FIXME: Handle want_unversioned
        return changes_from_git_changes(changes, self.target.mapping,
            specific_file=specific_files)


tree.InterTree.register_optimiser(InterIndexGitTree)
