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

from __future__ import absolute_import

from cStringIO import (
    StringIO,
    )
from collections import defaultdict
import errno
from dulwich.errors import NotGitRepository
from dulwich.ignore import (
    IgnoreFilterManager,
    )
from dulwich.index import (
    Index,
    changes_from_tree,
    cleanup_mode,
    index_entry_from_stat,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )
from dulwich.objects import (
    Blob,
    S_IFGITLINK,
    ZERO_SHA,
    )
from dulwich.repo import Repo
import os
import posixpath
import re
import stat
import sys

from ... import (
    errors,
    conflicts as _mod_conflicts,
    globbing,
    ignores,
    lock,
    osutils,
    trace,
    tree,
    workingtree,
    )
from ...bzr import (
    inventory,
    )


from .dir import (
    LocalGitDir,
    )
from .tree import (
    changes_from_git_changes,
    tree_delta_from_git_changes,
    )
from .mapping import (
    GitFileIdMap,
    mode_kind,
    )

IGNORE_FILENAME = ".gitignore"


class GitWorkingTree(workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, controldir, repo, branch, index):
        self.basedir = controldir.root_transport.local_abspath('.').encode(osutils._fs_enc)
        self.controldir = controldir
        self.repository = repo
        self.store = self.repository._git.object_store
        self.mapping = self.repository.get_mapping()
        self._branch = branch
        self._transport = controldir.transport
        self._format = GitWorkingTreeFormat()
        self.index = index
        self._versioned_dirs = None
        self.views = self._make_views()
        self._rules_searcher = None
        self._detect_case_handling()
        self._reset_data()
        self._fileid_map = self._basis_fileid_map.copy()
        self._lock_mode = None
        self._lock_count = 0

    def supports_tree_reference(self):
        return False

    def lock_read(self):
        """Lock the repository for read operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self._lock_mode:
            self._lock_mode = 'r'
            self._lock_count = 1
            self.index.read()
        else:
            self._lock_count += 1
        self.branch.lock_read()
        return lock.LogicalLockResult(self.unlock)

    def lock_tree_write(self):
        if not self._lock_mode:
            self._lock_mode = 'w'
            self._lock_count = 1
            self.index.read()
        elif self._lock_mode == 'r':
            raise errors.ReadOnlyError(self)
        else:
            self._lock_count +=1
        self.branch.lock_read()
        return lock.LogicalLockResult(self.unlock)

    def lock_write(self, token=None):
        if not self._lock_mode:
            self._lock_mode = 'w'
            self._lock_count = 1
            self.index.read()
        elif self._lock_mode == 'r':
            raise errors.ReadOnlyError(self)
        else:
            self._lock_count +=1
        self.branch.lock_write()
        return lock.LogicalLockResult(self.unlock)

    def is_locked(self):
        return self._lock_count >= 1

    def get_physical_lock_status(self):
        return False

    def unlock(self):
        if not self._lock_count:
            return lock.cant_unlock_not_held(self)
        self.branch.unlock()
        self._cleanup()
        self._lock_count -= 1
        if self._lock_count > 0:
            return
        self._lock_mode = None

    def _cleanup(self):
        pass

    def _detect_case_handling(self):
        try:
            self._transport.stat(".git/cOnFiG")
        except errors.NoSuchFile:
            self.case_sensitive = True
        else:
            self.case_sensitive = False

    def merge_modified(self):
        return {}

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        self.set_parent_ids([p for p, t in parents_list])

    def iter_children(self, file_id):
        dpath = self.id2path(file_id) + "/"
        if dpath in self.index:
            return
        for path in self.index:
            if not path.startswith(dpath):
                continue
            if "/" in path[len(dpath):]:
                # Not a direct child but something further down
                continue
            yield self.path2id(path)

    def _index_add_entry(self, path, kind):
        assert self._lock_mode is not None
        assert isinstance(path, basestring)
        if kind == "directory":
            # Git indexes don't contain directories
            return
        if kind == "file":
            blob = Blob()
            try:
                file, stat_val = self.get_file_with_stat(None, path)
            except (errors.NoSuchFile, IOError):
                # TODO: Rather than come up with something here, use the old index
                file = StringIO()
                stat_val = os.stat_result(
                    (stat.S_IFREG | 0644, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            blob.set_raw_string(file.read())
        elif kind == "symlink":
            blob = Blob()
            try:
                stat_val = os.lstat(self.abspath(path))
            except (errors.NoSuchFile, OSError):
                # TODO: Rather than come up with something here, use the
                # old index
                stat_val = os.stat_result(
                    (stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            blob.set_raw_string(
                self.get_symlink_target(None, path).encode("utf-8"))
        else:
            raise AssertionError("unknown kind '%s'" % kind)
        # Add object to the repository if it didn't exist yet
        if not blob.id in self.store:
            self.store.add_object(blob)
        # Add an entry to the index or update the existing entry
        flags = 0 # FIXME
        encoded_path = path.encode("utf-8")
        self.index[encoded_path] = index_entry_from_stat(
            stat_val, blob.id, flags)
        if self._versioned_dirs is not None:
            self._ensure_versioned_dir(encoded_path)

    def _ensure_versioned_dir(self, dirname):
        if dirname in self._versioned_dirs:
            return
        if dirname != "":
            self._ensure_versioned_dir(posixpath.dirname(dirname))
        self._versioned_dirs.add(dirname)

    def _load_dirs(self):
        assert self._lock_mode is not None
        self._versioned_dirs = set()
        for p in self.index:
            self._ensure_versioned_dir(posixpath.dirname(p))

    def _unversion_path(self, path):
        assert self._lock_mode is not None
        encoded_path = path.encode("utf-8")
        try:
            del self.index[encoded_path]
        except KeyError:
            # A directory, perhaps?
            for p in list(self.index):
                if p.startswith(encoded_path+"/"):
                    del self.index[p]
        # FIXME: remove empty directories

    def unversion(self, file_ids):
        with self.lock_tree_write():
            for file_id in file_ids:
                path = self.id2path(file_id)
                self._unversion_path(path)
            self.flush()

    def check_state(self):
        """Check that the working state is/isn't valid."""
        pass

    def remove(self, files, verbose=False, to_file=None, keep_files=True,
        force=False):
        """Remove nominated files from the working tree metadata.

        :param files: File paths relative to the basedir.
        :param keep_files: If true, the files will also be kept.
        :param force: Delete files and directories, even if they are changed
            and even if the directories are not empty.
        """
        all_files = set() # specified and nested files

        if isinstance(files, basestring):
            files = [files]

        if to_file is None:
            to_file = sys.stdout

        files = list(all_files)

        if len(files) == 0:
            return # nothing to do

        # Sort needed to first handle directory content before the directory
        files.sort(reverse=True)

        def backup(file_to_backup):
            abs_path = self.abspath(file_to_backup)
            backup_name = self.controldir._available_backup_name(file_to_backup)
            osutils.rename(abs_path, self.abspath(backup_name))
            return "removed %s (but kept a copy: %s)" % (
                file_to_backup, backup_name)

        with self.lock_tree_write():
            for f in files:
                fid = self.path2id(f)
                if not fid:
                    message = "%s is not versioned." % (f,)
                else:
                    abs_path = self.abspath(f)
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
                    # FIXME: _unversion_path() is O(size-of-index) for directories
                    self._unversion_path(f)
                    message = "removed %s" % (f,)
                    if osutils.lexists(abs_path):
                        if (osutils.isdir(abs_path) and
                            len(os.listdir(abs_path)) > 0):
                            if force:
                                osutils.rmtree(abs_path)
                                message = "deleted %s" % (f,)
                            else:
                                message = backup(f)
                        else:
                            if not keep_files:
                                osutils.delete_any(abs_path)
                                message = "deleted %s" % (f,)

                # print only one message (if any) per file.
                if message is not None:
                    trace.note(message)
            self.flush()

    def _add(self, files, ids, kinds):
        for (path, file_id, kind) in zip(files, ids, kinds):
            if file_id is not None:
                raise workingtree.SettingFileIdUnsupported()
            self._index_add_entry(path, kind)

    def smart_add(self, file_list, recurse=True, action=None, save=True):
        added = []
        ignored = {}
        user_dirs = []
        with self.lock_tree_write():
            for filepath in osutils.canonical_relpaths(self.basedir, file_list):
                abspath = self.abspath(filepath)
                kind = osutils.file_kind(abspath)
                if action is not None:
                    file_id = action(self, None, filepath, kind)
                else:
                    file_id = None
                if kind in ("file", "symlink"):
                    if save:
                        self._index_add_entry(filepath, kind)
                    added.append(filepath)
                elif kind == "directory":
                    if recurse:
                        user_dirs.append(filepath)
                else:
                    raise errors.BadFileKindError(filename=abspath, kind=kind)
            for user_dir in user_dirs:
                abs_user_dir = self.abspath(user_dir)
                for name in os.listdir(abs_user_dir):
                    subp = os.path.join(user_dir, name)
                    if self.is_control_filename(subp) or self.mapping.is_special_file(subp):
                        continue
                    ignore_glob = self.is_ignored(subp)
                    if ignore_glob is not None:
                        ignored.setdefault(ignore_glob, []).append(subp)
                        continue
                    abspath = self.abspath(subp)
                    kind = osutils.file_kind(abspath)
                    if kind == "directory":
                        user_dirs.append(subp)
                    else:
                        if action is not None:
                            file_id = action(self, None, filepath, kind)
                        else:
                            file_id = None
                        if save:
                            self._index_add_entry(subp, kind)
            if added and save:
                self.flush()
            return added, ignored

    def _set_root_id(self, file_id):
        self._fileid_map.set_file_id("", file_id)

    def move(self, from_paths, to_dir=None, after=False):
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

    def rename_one(self, from_rel, to_rel, after=False):
        from_path = from_rel.encode("utf-8")
        to_path = to_rel.encode("utf-8")
        with self.lock_tree_write():
            if not self.has_filename(to_rel):
                raise errors.BzrMoveFailedError(from_rel, to_rel,
                    errors.NoSuchFile(to_rel))
            if not from_path in self.index:
                raise errors.BzrMoveFailedError(from_rel, to_rel,
                    errors.NotVersionedError(path=from_rel))
            if not after:
                os.rename(self.abspath(from_rel), self.abspath(to_rel))
            self.index[to_path] = self.index[from_path]
            del self.index[from_path]
            self.flush()

    def get_root_id(self):
        return self.path2id("")

    def _has_dir(self, path):
        if path == "":
            return True
        if self._versioned_dirs is None:
            self._load_dirs()
        return path in self._versioned_dirs

    def path2id(self, path):
        if type(path) is list:
            path = u"/".join(path)
        with self.lock_read():
            encoded_path = path.encode("utf-8")
            if self._is_versioned(encoded_path):
                return self._fileid_map.lookup_file_id(encoded_path)
            return None

    def _iter_files_recursive(self, from_dir=None):
        if from_dir is None:
            from_dir = ""
        for (dirpath, dirnames, filenames) in os.walk(self.abspath(from_dir)):
            dir_relpath = dirpath[len(self.basedir):].strip("/")
            if self.controldir.is_control_filename(dir_relpath):
                continue
            for filename in filenames:
                if not self.mapping.is_special_file(filename):
                    yield os.path.join(dir_relpath, filename)

    def extras(self):
        """Yield all unversioned files in this WorkingTree.
        """
        with self.lock_read():
            return set(self._iter_files_recursive()) - set(self.index)

    def flush(self):
        with self.lock_tree_write():
            # TODO: Maybe this should only write on dirty ?
            if self._lock_mode != 'w':
                raise errors.NotWriteLocked(self)
            self.index.write()

    def __iter__(self):
        with self.lock_read():
            for path in self.index:
                yield self.path2id(path)
            self._load_dirs()
            for path in self._versioned_dirs:
                yield self.path2id(path)

    def has_or_had_id(self, file_id):
        if self.has_id(file_id):
            return True
        if self.had_id(file_id):
            return True
        return False

    def had_id(self, file_id):
        path = self._basis_fileid_map.lookup_file_id(file_id)
        try:
            head = self.repository._git.head()
        except KeyError:
            # Assume no if basis is not accessible
            return False
        if head == ZERO_SHA:
            return False
        root_tree = self.store[head].tree
        try:
            tree_lookup_path(self.store.__getitem__, root_tree, path)
        except KeyError:
            return False
        else:
            return True

    def has_id(self, file_id):
        try:
            self.id2path(file_id)
        except errors.NoSuchId:
            return False
        else:
            return True

    def id2path(self, file_id):
        assert type(file_id) is str, "file id not a string: %r" % file_id
        file_id = osutils.safe_utf8(file_id)
        with self.lock_read():
            path = self._fileid_map.lookup_path(file_id)
            # FIXME: What about directories?
            if self._is_versioned(path):
                return path.decode("utf-8")
            raise errors.NoSuchId(self, file_id)

    def get_file_mtime(self, file_id, path=None):
        """See Tree.get_file_mtime."""
        if not path:
            path = self.id2path(file_id)
        return os.lstat(self.abspath(path)).st_mtime

    def is_ignored(self, filename):
        r"""Check whether the filename matches an ignore pattern.

        If the file is ignored, returns the pattern which caused it to
        be ignored, otherwise None.  So this can simply be used as a
        boolean if desired."""
        if getattr(self, '_global_ignoreglobster', None) is None:
            ignore_globs = set()
            ignore_globs.update(ignores.get_runtime_ignores())
            ignore_globs.update(ignores.get_user_ignores())
            self._global_ignoreglobster = globbing.ExceptionGlobster(ignore_globs)
        match = self._global_ignoreglobster.match(filename)
        if match is not None:
            return match
        if osutils.file_kind(self.abspath(filename)) == 'directory':
            filename += b'/'
        ignore_manager = self._get_ignore_manager()
        ps = list(ignore_manager.find_matching(filename))
        if not ps:
            return None
        if not ps[-1].is_exclude:
            return None
        return bytes(ps[-1])

    def _get_ignore_manager(self):
        ignoremanager = getattr(self, '_ignoremanager', None)
        if ignoremanager is not None:
            return ignoremanager

        ignore_manager = IgnoreFilterManager.from_repo(self.repository._git)
        self._ignoremanager = ignore_manager
        return ignore_manager

    def set_last_revision(self, revid):
        self._change_last_revision(revid)

    def _reset_data(self):
        try:
            head = self.repository._git.head()
        except KeyError, name:
            raise errors.NotBranchError("branch %s at %s" % (name,
                self.repository.base))
        if head == ZERO_SHA:
            self._basis_fileid_map = GitFileIdMap({}, self.mapping)
        else:
            self._basis_fileid_map = self.mapping.get_fileid_map(
                self.store.__getitem__, self.store[head].tree)

    def get_file_verifier(self, file_id, path=None, stat_value=None):
        with self.lock_read():
            if path is None:
                path = self.id2path(file_id)
            try:
                return ("GIT", self.index[path][-2])
            except KeyError:
                if self._has_dir(path):
                    return ("GIT", None)
                raise errors.NoSuchId(self, file_id)

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        with self.lock_read():
            if not path:
                path = self.id2path(file_id)
            abspath = self.abspath(path).encode(osutils._fs_enc)
            try:
                return osutils.sha_file_by_name(abspath)
            except OSError, (num, msg):
                if num in (errno.EISDIR, errno.ENOENT):
                    return None
                raise

    def revision_tree(self, revid):
        return self.repository.revision_tree(revid)

    def _is_versioned(self, path):
        assert self._lock_mode is not None
        return (path in self.index or self._has_dir(path))

    def filter_unversioned_files(self, files):
        return set([p for p in files if not self._is_versioned(p.encode("utf-8"))])

    def _get_dir_ie(self, path, parent_id):
        file_id = self.path2id(path)
        return inventory.InventoryDirectory(file_id,
            posixpath.basename(path).strip("/"), parent_id)

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

    def _get_file_ie(self, name, path, value, parent_id):
        assert isinstance(name, unicode)
        assert isinstance(path, unicode)
        assert isinstance(value, tuple) and len(value) == 10
        (ctime, mtime, dev, ino, mode, uid, gid, size, sha, flags) = value
        file_id = self.path2id(path)
        if type(file_id) != str:
            raise AssertionError
        kind = mode_kind(mode)
        ie = inventory.entry_factory[kind](file_id, name, parent_id)
        if kind == 'symlink':
            ie.symlink_target = self.get_symlink_target(file_id)
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

    def stored_kind(self, file_id, path=None):
        with self.lock_read():
            if path is None:
                path = self.id2path(file_id)
            try:
                return mode_kind(self.index[path.encode("utf-8")][4])
            except KeyError:
                # Maybe it's a directory?
                if self._has_dir(path):
                    return "directory"
                raise errors.NoSuchId(self, file_id)

    def is_executable(self, file_id, path=None):
        if getattr(self, "_supports_executable", osutils.supports_executable)():
            if not path:
                path = self.id2path(file_id)
            mode = os.lstat(self.abspath(path)).st_mode
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)
        else:
            basis_tree = self.basis_tree()
            if file_id in basis_tree:
                return basis_tree.is_executable(file_id)
            # Default to not executable
            return False

    def _is_executable_from_path_and_stat(self, path, stat_result):
        if getattr(self, "_supports_executable", osutils.supports_executable)():
            return self._is_executable_from_path_and_stat_from_stat(path, stat_result)
        else:
            return self._is_executable_from_path_and_stat_from_basis(path, stat_result)

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        if from_dir is None:
            from_dir = ""
        dir_ids = {}
        fk_entries = {'directory': workingtree.TreeDirectory,
                      'file': workingtree.TreeFile,
                      'symlink': workingtree.TreeLink}
        with self.lock_read():
            root_ie = self._get_dir_ie(u"", None)
            if include_root and not from_dir:
                yield "", "V", root_ie.kind, root_ie.file_id, root_ie
            dir_ids[u""] = root_ie.file_id
            if recursive:
                path_iterator = self._iter_files_recursive(from_dir)
            else:
                if from_dir is None:
                    start = self.basedir
                else:
                    start = os.path.join(self.basedir, from_dir)
                path_iterator = sorted([os.path.join(from_dir, name) for name in
                    os.listdir(start) if not self.controldir.is_control_filename(name)
                    and not self.mapping.is_special_file(name)])
            for path in path_iterator:
                try:
                    value = self.index[path]
                except KeyError:
                    value = None
                path = path.decode("utf-8")
                parent, name = posixpath.split(path)
                for dir_path, dir_ie in self._add_missing_parent_ids(parent, dir_ids):
                    yield dir_path, "V", dir_ie.kind, dir_ie.file_id, dir_ie
                if value is not None:
                    ie = self._get_file_ie(name, path, value, dir_ids[parent])
                    yield path, "V", ie.kind, ie.file_id, ie
                else:
                    kind = osutils.file_kind(self.abspath(path))
                    ie = fk_entries[kind]()
                    yield path, ("I" if self.is_ignored(path) else "?"), kind, None, ie

    def all_file_ids(self):
        with self.lock_read():
            ids = {u"": self.path2id("")}
            for path in self.index:
                if self.mapping.is_special_file(path):
                    continue
                path = path.decode("utf-8")
                parent = posixpath.dirname(path).strip("/")
                for e in self._add_missing_parent_ids(parent, ids):
                    pass
                ids[path] = self.path2id(path)
            return set(ids.values())

    def _directory_is_tree_reference(self, path):
        # FIXME: Check .gitsubmodules for path
        return False

    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        # FIXME: Is return order correct?
        if yield_parents:
            raise NotImplementedError(self.iter_entries_by_dir)
        with self.lock_read():
            if specific_file_ids is not None:
                specific_paths = [
                        self.id2path(file_id) for file_id in specific_file_ids]
                if specific_paths in ([u""], []):
                    specific_paths = None
                else:
                    specific_paths = set(specific_paths)
            else:
                specific_paths = None
            root_ie = self._get_dir_ie(u"", None)
            if specific_paths is None:
                yield u"", root_ie
            dir_ids = {u"": root_ie.file_id}
            for path, value in self.index.iteritems():
                if self.mapping.is_special_file(path):
                    continue
                path = path.decode("utf-8")
                if specific_paths is not None and not path in specific_paths:
                    continue
                (parent, name) = posixpath.split(path)
                try:
                    file_ie = self._get_file_ie(name, path, value, None)
                except IOError:
                    continue
                for (dir_path, dir_ie) in self._add_missing_parent_ids(parent,
                        dir_ids):
                    yield dir_path, dir_ie
                file_ie.parent_id = self.path2id(parent)
                yield path, file_ie

    def conflicts(self):
        with self.lock_read():
            # FIXME:
            return _mod_conflicts.ConflictList()

    def get_canonical_inventory_path(self, path):
        with self.lock_read():
            for p in self.index:
                if p.lower() == path.lower():
                    return p
            else:
                return path

    def _walkdirs(self, prefix=""):
        if prefix != "":
            prefix += "/"
        per_dir = defaultdict(list)
        for path, value in self.index.iteritems():
            if self.mapping.is_special_file(path):
                continue
            if not path.startswith(prefix):
                continue
            (dirname, child_name) = posixpath.split(path)
            dirname = dirname.decode("utf-8")
            dir_file_id = self.path2id(dirname)
            assert isinstance(value, tuple) and len(value) == 10
            (ctime, mtime, dev, ino, mode, uid, gid, size, sha, flags) = value
            stat_result = os.stat_result((mode, ino,
                    dev, 1, uid, gid, size,
                    0, mtime, ctime))
            per_dir[(dirname, dir_file_id)].append(
                (path.decode("utf-8"), child_name.decode("utf-8"),
                mode_kind(mode), stat_result,
                self.path2id(path.decode("utf-8")),
                mode_kind(mode)))
        return per_dir.iteritems()

    def _lookup_entry(self, path, update_index=False):
        assert type(path) == str
        entry = self.index[path]
        index_mode = entry[-6]
        index_sha = entry[-2]
        disk_path = os.path.join(self.basedir, path)
        try:
            disk_stat = os.lstat(disk_path)
        except OSError, (num, msg):
            if num in (errno.EISDIR, errno.ENOENT):
                raise KeyError(path)
            raise
        disk_mtime = disk_stat.st_mtime
        if isinstance(entry[1], tuple):
            index_mtime = entry[1][0]
        else:
            index_mtime = int(entry[1])
        mtime_delta = (disk_mtime - index_mtime)
        disk_mode = cleanup_mode(disk_stat.st_mode)
        if mtime_delta > 0 or disk_mode != index_mode:
            if stat.S_ISDIR(disk_mode):
                try:
                    subrepo = Repo(disk_path)
                except NotGitRepository:
                    return (None, None)
                else:
                    disk_mode = S_IFGITLINK
                    git_id = subrepo.head()
            elif stat.S_ISLNK(disk_mode):
                blob = Blob.from_string(os.readlink(disk_path).encode('utf-8'))
                git_id = blob.id
            elif stat.S_ISREG(disk_mode):
                with open(disk_path, 'r') as f:
                    blob = Blob.from_string(f.read())
                git_id = blob.id
            else:
                raise AssertionError
            if update_index:
                flags = 0 # FIXME
                self.index[path] = index_entry_from_stat(disk_stat, git_id, flags, disk_mode)
            return (git_id, disk_mode)
        return (index_sha, index_mode)


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    _tree_class = GitWorkingTree

    supports_versioned_directories = False

    supports_setting_file_ids = False

    @property
    def _matchingcontroldir(self):
        from .dir import LocalGitControlDirFormat
        return LocalGitControlDirFormat()

    def get_format_description(self):
        return "Git Working Tree"

    def initialize(self, a_controldir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """See WorkingTreeFormat.initialize()."""
        if not isinstance(a_controldir, LocalGitDir):
            raise errors.IncompatibleFormat(self, a_controldir)
        index = Index(a_controldir.root_transport.local_abspath(".git/index"))
        index.write()
        return GitWorkingTree(a_controldir, a_controldir.open_repository(),
            a_controldir.open_branch(), index)


class InterIndexGitTree(tree.InterTree):
    """InterTree that works between a Git revision tree and an index."""

    def __init__(self, source, target):
        super(InterIndexGitTree, self).__init__(source, target)
        self._index = target.index

    @classmethod
    def is_compatible(cls, source, target):
        from .repository import GitRevisionTree
        return (isinstance(source, GitRevisionTree) and
                isinstance(target, GitWorkingTree))

    def compare(self, want_unchanged=False, specific_files=None,
                extra_trees=None, require_versioned=False, include_root=False,
                want_unversioned=False):
        with self.lock_read():
            # FIXME: Handle include_root
            changes = changes_between_git_tree_and_index(
                self.source.store, self.source.tree,
                self.target, want_unchanged=want_unchanged,
                want_unversioned=want_unversioned)
            source_fileid_map = self.source._fileid_map
            target_fileid_map = self.target._fileid_map
            ret = tree_delta_from_git_changes(changes, self.target.mapping,
                (source_fileid_map, target_fileid_map),
                specific_file=specific_files, require_versioned=require_versioned)
            if want_unversioned:
                for e in self.target.extras():
                    ret.unversioned.append((e, None,
                        osutils.file_kind(self.target.abspath(e))))
            return ret

    def iter_changes(self, include_unchanged=False, specific_files=None,
        pb=None, extra_trees=[], require_versioned=True,
        want_unversioned=False):
        with self.lock_read():
            changes = changes_between_git_tree_and_index(
                self.source.store, self.source.tree,
                self.target, want_unchanged=include_unchanged,
                want_unversioned=want_unversioned)
            return changes_from_git_changes(
                    changes, self.target.mapping, specific_file=specific_files)


tree.InterTree.register_optimiser(InterIndexGitTree)


def changes_between_git_tree_and_index(object_store, tree, target,
        want_unchanged=False, want_unversioned=False, update_index=False):
    """Determine the changes between a git tree and a working tree with index.

    """

    names = target.index._byname.keys()
    for (name, mode, sha) in changes_from_tree(names, target._lookup_entry,
            object_store, tree, want_unchanged=want_unchanged):
        if name == (None, None):
            continue
        yield (name, mode, sha)
