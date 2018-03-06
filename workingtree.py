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

import itertools
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
    commit_tree,
    index_entry_from_stat,
    iter_fresh_blobs,
    blob_from_path_and_stat,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )
from dulwich.objects import (
    Blob,
    S_IFGITLINK,
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
    controldir as _mod_controldir,
    globbing,
    ignores,
    lock,
    osutils,
    revision as _mod_revision,
    trace,
    transport as _mod_transport,
    tree,
    workingtree,
    )
from ...bzr import (
    inventory,
    )
from ...mutabletree import (
    MutableTree,
    )


from .dir import (
    LocalGitDir,
    )
from .tree import (
    changes_from_git_changes,
    tree_delta_from_git_changes,
    InterGitTrees,
    )
from .mapping import (
    GitFileIdMap,
    mode_kind,
    )

IGNORE_FILENAME = ".gitignore"


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


class GitWorkingTree(workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, controldir, repo, branch, index):
        basedir = controldir.root_transport.local_abspath('.')
        self.basedir = osutils.realpath(basedir)
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

    def set_merge_modified(self, modified_hashes):
        raise errors.UnsupportedOperation(self.set_merge_modified, self)

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        self.set_parent_ids([p for p, t in parents_list])

    def _set_merges_from_parent_ids(self, rhs_parent_ids):
        try:
            merges = [self.branch.lookup_bzr_revision_id(revid)[0] for revid in rhs_parent_ids]
        except errors.NoSuchRevision as e:
            raise errors.GhostRevisionUnusableHere(e.revision)
        if merges:
            self.control_transport.put_bytes('MERGE_HEAD', '\n'.join(merges),
                mode=self.controldir._get_file_mode())
        else:
            try:
                self.control_transport.delete('MERGE_HEAD')
            except errors.NoSuchFile:
                pass

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
        with self.lock_tree_write():
            self._check_parents_for_ghosts(revision_ids,
                allow_leftmost_as_ghost=allow_leftmost_as_ghost)
            for revision_id in revision_ids:
                _mod_revision.check_not_reserved_id(revision_id)

            revision_ids = self._filter_parent_ids_by_ancestry(revision_ids)

            if len(revision_ids) > 0:
                self.set_last_revision(revision_ids[0])
            else:
                self.set_last_revision(_mod_revision.NULL_REVISION)

            self._set_merges_from_parent_ids(revision_ids[1:])

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
            merges_bytes = self.control_transport.get_bytes('MERGE_HEAD')
        except errors.NoSuchFile:
            pass
        else:
            for l in osutils.split_lines(merges_bytes):
                revision_id = l.rstrip('\n')
                parents.append(self.branch.lookup_foreign_revision_id(revision_id))
        return parents

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

    def _index_add_entry(self, path, kind, flags=0):
        assert self._lock_mode is not None
        assert isinstance(path, basestring)
        if kind == "directory":
            # Git indexes don't contain directories
            return
        if kind == "file":
            blob = Blob()
            try:
                file, stat_val = self.get_file_with_stat(path)
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
                self.get_symlink_target(path).encode("utf-8"))
        else:
            raise AssertionError("unknown kind '%s'" % kind)
        # Add object to the repository if it didn't exist yet
        if not blob.id in self.store:
            self.store.add_object(blob)
        # Add an entry to the index or update the existing entry
        ensure_normalized_path(path)
        encoded_path = path.encode("utf-8")
        if b'\r' in encoded_path or b'\n' in encoded_path:
            # TODO(jelmer): Why do we need to do this?
            trace.mutter('ignoring path with invalid newline in it: %r', path)
            return
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
        count = 0
        try:
            del self.index[encoded_path]
        except KeyError:
            # A directory, perhaps?
            for p in list(self.index):
                if p.startswith(encoded_path+b"/"):
                    count += 1
                    del self.index[p]
        else:
            count = 1
        self._versioned_dirs = None
        return count

    def unversion(self, paths, file_ids=None):
        with self.lock_tree_write():
            for path in paths:
                encoded_path = path.encode("utf-8")
                try:
                    del self.index[encoded_path]
                except KeyError:
                    if not self._has_dir(path):
                        raise errors.NoSuchFile(path)
            self._versioned_dirs = None
            self.flush()

    def update_basis_by_delta(self, revid, delta):
        # TODO(jelmer): This shouldn't be called, it's inventory specific.
        for (old_path, new_path, file_id, ie) in delta:
            if old_path is not None and old_path.encode('utf-8') in self.index:
                del self.index[old_path.encode('utf-8')]
                self._versioned_dirs = None
            if new_path is not None and ie.kind != 'directory':
                self._index_add_entry(new_path, ie.kind)
        self.flush()
        self._set_merges_from_parent_ids([])

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
        if isinstance(files, basestring):
            files = [files]

        if to_file is None:
            to_file = sys.stdout

        files = list(files)

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
                if f == '':
                    continue
                else:
                    abs_path = self.abspath(f)
                    if verbose:
                        # having removed it, it must be either ignored or unknown
                        if self.is_ignored(f):
                            new_status = 'I'
                        else:
                            new_status = '?'
                        # XXX: Really should be a more abstract reporter interface
                        kind_ch = osutils.kind_marker(self.kind(f))
                        to_file.write(new_status + '       ' + f + kind_ch + '\n')
                    # Unversion file
                    # TODO(jelmer): _unversion_path() is O(size-of-index) for directories
                    if self._unversion_path(f) == 0:
                        if (osutils.isdir(abs_path) and
                            len(os.listdir(abs_path)) == 0):
                            if not keep_files:
                                osutils.delete_any(abs_path)
                            message = "removed %s" % (f,)
                        else:
                            message = "%s is not versioned." % (f,)
                    else:
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
        if not file_list:
            file_list = [u'.']

        # expand any symlinks in the directory part, while leaving the
        # filename alone
        # only expanding if symlinks are supported avoids windows path bugs
        if osutils.has_symlinks():
            file_list = list(map(osutils.normalizepath, file_list))

        added = []
        ignored = {}
        user_dirs = []
        def call_action(filepath, kind):
            if action is not None:
                parent_path = posixpath.dirname(filepath)
                parent_id = self.path2id(parent_path)
                parent_ie = self._get_dir_ie(parent_path, parent_id)
                file_id = action(self, parent_ie, filepath, kind)
                if file_id is not None:
                    raise workingtree.SettingFileIdUnsupported()

        with self.lock_tree_write():
            for filepath in osutils.canonical_relpaths(self.basedir, file_list):
                filepath = osutils.normalized_filename(filepath)[0]
                abspath = self.abspath(filepath)
                kind = osutils.file_kind(abspath)
                if kind in ("file", "symlink"):
                    call_action(filepath, kind)
                    if save:
                        self._index_add_entry(filepath, kind)
                    added.append(filepath)
                elif kind == "directory":
                    call_action(filepath, kind)
                    if recurse:
                        user_dirs.append(filepath)
                else:
                    raise errors.BadFileKindError(filename=abspath, kind=kind)
            for user_dir in user_dirs:
                abs_user_dir = self.abspath(user_dir)
                if user_dir != '':
                    try:
                        transport = _mod_transport.get_transport_from_path(abs_user_dir)
                        _mod_controldir.ControlDirFormat.find_format(transport)
                        subtree = True
                    except errors.NotBranchError:
                        subtree = False
                    except errors.UnsupportedFormatError:
                        subtree = False
                else:
                    subtree = False
                if subtree:
                    trace.warning('skipping nested tree %r', abs_user_dir)
                    continue

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
                        call_action(filepath, kind)
                        if save:
                            self._index_add_entry(subp, kind)
                        added.append(subp)
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
        ensure_normalized_path(to_rel)
        to_path = to_rel.encode("utf-8")
        with self.lock_tree_write():
            if not after:
                if not self.has_filename(from_rel):
                    raise errors.BzrMoveFailedError(from_rel, to_rel,
                        errors.NoSuchFile(from_rel))
            else:
                if not self.has_filename(to_rel):
                    raise errors.BzrMoveFailedError(from_rel, to_rel,
                        errors.NoSuchFile(to_rel))

            kind = self.kind(from_rel)
            if not from_path in self.index and kind != 'directory':
                # It's not a file
                raise errors.BzrMoveFailedError(from_rel, to_rel,
                    errors.NotVersionedError(path=from_rel))

            if not after:
                try:
                    os.rename(self.abspath(from_rel), self.abspath(to_rel))
                except OSError as e:
                    if e.errno == errno.ENOENT:
                        raise errors.BzrMoveFailedError(from_rel, to_rel,
                            errors.NoSuchFile(to_rel))
                    raise
            if kind != 'directory':
                self.index[to_path] = self.index[from_path]
                del self.index[from_path]
            self._versioned_dirs = None
            self.flush()

    def get_root_id(self):
        return self.path2id("")

    def has_filename(self, filename):
        return osutils.lexists(self.abspath(filename))

    def _has_dir(self, path):
        if path == "":
            return True
        if self._versioned_dirs is None:
            self._load_dirs()
        return path in self._versioned_dirs

    def path2id(self, path):
        with self.lock_read():
            path = path.rstrip('/')
            if self.is_versioned(path.rstrip('/')):
                return self._fileid_map.lookup_file_id(path.encode("utf-8"))
            return None

    def _iter_files_recursive(self, from_dir=None, include_dirs=False):
        if from_dir is None:
            from_dir = ""
        for (dirpath, dirnames, filenames) in os.walk(self.abspath(from_dir)):
            dir_relpath = dirpath[len(self.basedir):].strip("/")
            if self.controldir.is_control_filename(dir_relpath):
                continue
            for name in list(dirnames):
                if self.controldir.is_control_filename(name):
                    dirnames.remove(name)
                    continue
                relpath = os.path.join(dir_relpath, name)
                if include_dirs:
                    yield relpath
                if not self._has_dir(relpath):
                    dirnames.remove(name)
            for name in filenames:
                if not self.mapping.is_special_file(name):
                    yield os.path.join(dir_relpath, name)

    def extras(self):
        """Yield all unversioned files in this WorkingTree.
        """
        with self.lock_read():
            return set(self._iter_files_recursive()) - set(self.index)

    def flush(self):
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
        try:
            root_tree = self.store[head].tree
        except KeyError:
            return False
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
            try:
                path = self._fileid_map.lookup_path(file_id)
            except ValueError:
                raise errors.NoSuchId(self, file_id)
            path = path.decode('utf-8')
            if self.is_versioned(path):
                return path
            raise errors.NoSuchId(self, file_id)

    def get_file_mtime(self, path, file_id=None):
        """See Tree.get_file_mtime."""
        try:
            return os.lstat(self.abspath(path)).st_mtime
        except OSError, (num, msg):
            if num == errno.ENOENT:
                raise errors.NoSuchFile(path)
            raise

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
        try:
            if self.kind(filename) == 'directory':
                filename += b'/'
        except errors.NoSuchFile:
            pass
        filename = filename.lstrip(b'/')
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

    def _flush_ignore_list_cache(self):
        self._ignoremanager = None

    def set_last_revision(self, revid):
        if _mod_revision.is_null(revid):
            self.branch.set_last_revision_info(0, revid)
            return False
        _mod_revision.check_not_reserved_id(revid)
        try:
            self.branch.generate_revision_history(revid)
        except errors.NoSuchRevision:
            raise errors.GhostRevisionUnusableHere(revid)

    def _reset_data(self):
        try:
            head = self.repository._git.head()
        except KeyError:
            self._basis_fileid_map = GitFileIdMap({}, self.mapping)
        else:
            self._basis_fileid_map = self.mapping.get_fileid_map(
                self.store.__getitem__, self.store[head].tree)

    def get_file_verifier(self, path, file_id=None, stat_value=None):
        with self.lock_read():
            try:
                return ("GIT", self.index[path][-2])
            except KeyError:
                if self._has_dir(path):
                    return ("GIT", None)
                raise errors.NoSuchFile(path)

    def get_file_sha1(self, path, file_id=None, stat_value=None):
        with self.lock_read():
            if not self.is_versioned(path):
                raise errors.NoSuchFile(path)
            abspath = self.abspath(path)
            try:
                return osutils.sha_file_by_name(abspath)
            except OSError, (num, msg):
                if num in (errno.EISDIR, errno.ENOENT):
                    return None
                raise

    def revision_tree(self, revid):
        return self.repository.revision_tree(revid)

    def is_versioned(self, path):
        with self.lock_read():
            path = path.rstrip('/').encode('utf-8')
            return (path in self.index or self._has_dir(path))

    def filter_unversioned_files(self, files):
        return set([p for p in files if not self.is_versioned(p)])

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
            ie.symlink_target = self.get_symlink_target(path, file_id)
        else:
            data = self.get_file_text(path, file_id)
            ie.text_sha1 = osutils.sha_string(data)
            ie.text_size = len(data)
            ie.executable = self.is_executable(path, file_id)
        ie.revision = None
        return ie

    def _is_executable_from_path_and_stat_from_stat(self, path, stat_result):
        mode = stat_result.st_mode
        return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    def _is_executable_from_path_and_stat_from_basis(self, path, stat_result):
        return self.basis_tree().is_executable(path)

    def stored_kind(self, path, file_id=None):
        with self.lock_read():
            try:
                return mode_kind(self.index[path.encode("utf-8")][4])
            except KeyError:
                # Maybe it's a directory?
                if self._has_dir(path):
                    return "directory"
                raise errors.NoSuchFile(path)

    def is_executable(self, path, file_id=None):
        if getattr(self, "_supports_executable", osutils.supports_executable)():
            mode = os.lstat(self.abspath(path)).st_mode
        else:
            try:
                mode = self.index[path.encode('utf-8')].mode
            except KeyError:
                mode = 0
        return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    def _is_executable_from_path_and_stat(self, path, stat_result):
        if getattr(self, "_supports_executable", osutils.supports_executable)():
            return self._is_executable_from_path_and_stat_from_stat(path, stat_result)
        else:
            return self._is_executable_from_path_and_stat_from_basis(path, stat_result)

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        if from_dir is None:
            from_dir = ""
        dir_ids = {}
        fk_entries = {'directory': tree.TreeDirectory,
                      'file': tree.TreeFile,
                      'symlink': tree.TreeLink}
        with self.lock_read():
            root_ie = self._get_dir_ie(u"", None)
            if include_root and not from_dir:
                yield "", "V", root_ie.kind, root_ie.file_id, root_ie
            dir_ids[u""] = root_ie.file_id
            if recursive:
                path_iterator = sorted(self._iter_files_recursive(from_dir, include_dirs=True))
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
                kind = osutils.file_kind(self.abspath(path))
                parent, name = posixpath.split(path)
                for dir_path, dir_ie in self._add_missing_parent_ids(parent, dir_ids):
                    pass
                if kind == 'directory':
                    if path != from_dir:
                        if self._has_dir(path):
                            ie = self._get_dir_ie(path, self.path2id(path))
                            status = "V"
                            file_id = ie.file_id
                        elif self.is_ignored(path):
                            status = "I"
                            ie = fk_entries[kind]()
                            file_id = None
                        else:
                            status = "?"
                            ie = fk_entries[kind]()
                            file_id = None
                        yield posixpath.relpath(path, from_dir), status, kind, file_id, ie
                    continue
                if value is not None:
                    ie = self._get_file_ie(name, path, value, dir_ids[parent])
                    yield posixpath.relpath(path, from_dir), "V", ie.kind, ie.file_id, ie
                else:
                    ie = fk_entries[kind]()
                    yield posixpath.relpath(path, from_dir), ("I" if self.is_ignored(path) else "?"), kind, None, ie

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

    def all_versioned_paths(self):
        with self.lock_read():
            paths = {u""}
            for path in self.index:
                if self.mapping.is_special_file(path):
                    continue
                path = path.decode("utf-8")
                paths.add(path)
                while path != "":
                    path = posixpath.dirname(path).strip("/")
                    if path in paths:
                        break
                    paths.add(path)
            return paths

    def _directory_is_tree_reference(self, path):
        # FIXME: Check .gitsubmodules for path
        return False

    def iter_child_entries(self, path, file_id=None):
        encoded_path = path.encode('utf-8')
        parent_id = self.path2id(path)
        found_any = False
        seen_children = set()
        for item_path, value in self.index.iteritems():
            if self.mapping.is_special_file(item_path):
                continue
            if not osutils.is_inside(encoded_path, item_path):
                continue
            found_any = True
            subpath = posixpath.relpath(item_path, encoded_path)
            if b'/' in subpath:
                dirname = subpath.split(b'/', 1)[0]
                file_ie = self._get_dir_ie(posixpath.join(path, dirname), parent_id)
            else:
                (parent, name) = posixpath.split(item_path)
                try:
                    file_ie = self._get_file_ie(name, item_path, value, parent_id)
                except IOError:
                    continue
            yield file_ie
        if not found_any:
            raise errors.NoSuchFile(path)

    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        if yield_parents:
            raise NotImplementedError(self.iter_entries_by_dir)
        with self.lock_read():
            if specific_file_ids is not None:
                specific_paths = []
                for file_id in specific_file_ids:
                    if file_id is None:
                        continue
                    try:
                        specific_paths.append(self.id2path(file_id))
                    except errors.NoSuchId:
                        pass
                if specific_paths in ([u""], []):
                    specific_paths = None
                else:
                    specific_paths = set(specific_paths)
            else:
                specific_paths = None
            root_ie = self._get_dir_ie(u"", None)
            ret = {}
            if specific_paths is None:
                ret[(None, u"")] = root_ie
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
                except errors.NoSuchFile:
                    continue
                if yield_parents or specific_file_ids is None:
                    for (dir_path, dir_ie) in self._add_missing_parent_ids(parent,
                            dir_ids):
                        ret[(posixpath.dirname(dir_path), dir_path)] = dir_ie
                file_ie.parent_id = self.path2id(parent)
                ret[(posixpath.dirname(path), path)] = file_ie
            return ((path, ie) for ((_, path), ie) in sorted(ret.items()))

    def conflicts(self):
        with self.lock_read():
            # FIXME:
            return _mod_conflicts.ConflictList()

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
        from bisect import bisect_left
        import operator
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
                        ('.git', '.git'))
                    if (bzrdir_loc < len(cur_disk_dir_content)
                        and self.controldir.is_control_filename(
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
            per_dir[(dirname, dir_file_id)].append(
                (path.decode("utf-8"), child_name.decode("utf-8"),
                mode_kind(value.mode), None,
                self.path2id(path.decode("utf-8")),
                mode_kind(value.mode)))
        return ((k, sorted(v)) for (k, v) in per_dir.iteritems())

    def _lookup_entry(self, path, update_index=False):
        assert type(path) == str
        entry = self.index[path]
        index_mode = entry[-6]
        index_sha = entry[-2]
        disk_path = self.abspath(path.decode('utf-8')).encode(
            osutils._fs_enc)
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
                blob = Blob.from_string(os.readlink(disk_path))
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

    def get_shelf_manager(self):
        raise workingtree.ShelvingUnsupported()

    def store_uncommitted(self):
        raise errors.StoringUncommittedNotSupported(self)

    def apply_inventory_delta(self, changes):
        for (old_path, new_path, file_id, ie) in changes:
            if old_path is not None:
                del self.index[old_path.encode('utf-8')]
                self._versioned_dirs = None
            if new_path is not None and ie.kind != 'directory':
                self._index_add_entry(new_path, ie.kind)
        self.flush()

    def annotate_iter(self, path, file_id=None,
                      default_revision=_mod_revision.CURRENT_REVISION):
        """See Tree.annotate_iter

        This implementation will use the basis tree implementation if possible.
        Lines not in the basis are attributed to CURRENT_REVISION

        If there are pending merges, lines added by those merges will be
        incorrectly attributed to CURRENT_REVISION (but after committing, the
        attribution will be correct).
        """
        with self.lock_read():
            maybe_file_parent_keys = []
            for parent_id in self.get_parent_ids():
                try:
                    parent_tree = self.revision_tree(parent_id)
                except errors.NoSuchRevisionInTree:
                    parent_tree = self.branch.repository.revision_tree(
                            parent_id)
                with parent_tree.lock_read():
                    # TODO(jelmer): Use rename/copy tracker to find path name in parent
                    parent_path = path
                    try:
                        kind = parent_tree.kind(parent_path)
                    except errors.NoSuchFile:
                        continue
                    if kind != 'file':
                        # Note: this is slightly unnecessary, because symlinks and
                        # directories have a "text" which is the empty text, and we
                        # know that won't mess up annotations. But it seems cleaner
                        continue
                    parent_text_key = (
                        parent_path,
                        parent_tree.get_file_revision(parent_path))
                    if parent_text_key not in maybe_file_parent_keys:
                        maybe_file_parent_keys.append(parent_text_key)
            graph = self.branch.repository.get_file_graph()
            heads = graph.heads(maybe_file_parent_keys)
            file_parent_keys = []
            for key in maybe_file_parent_keys:
                if key in heads:
                    file_parent_keys.append(key)

            # Now we have the parents of this content
            from breezy.annotate import Annotator
            from .annotate import AnnotateProvider
            annotator = Annotator(AnnotateProvider(
                self.branch.repository._file_change_scanner))
            text = self.get_file_text(path)
            this_key = (path, default_revision)
            annotator.add_special_text(this_key, file_parent_keys, text)
            annotations = [(key[-1], line)
                           for key, line in annotator.annotate_flat(this_key)]
            return annotations


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    _tree_class = GitWorkingTree

    supports_versioned_directories = False

    supports_setting_file_ids = False

    supports_store_uncommitted = False

    supports_leftmost_parent_id_as_ghost = False

    supports_righthand_parent_id_as_ghost = False

    requires_normalized_unicode_filenames = True

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
        branch = a_controldir.open_branch()
        if revision_id is not None:
            branch.set_last_revision(revision_id)
        wt = GitWorkingTree(
                a_controldir, a_controldir.open_repository(), branch, index)
        for hook in MutableTree.hooks['post_build_tree']:
            hook(wt)
        return wt


class InterIndexGitTree(InterGitTrees):
    """InterTree that works between a Git revision tree and an index."""

    def __init__(self, source, target):
        super(InterIndexGitTree, self).__init__(source, target)
        self._index = target.index

    @classmethod
    def is_compatible(cls, source, target):
        from .repository import GitRevisionTree
        return (isinstance(source, GitRevisionTree) and
                isinstance(target, GitWorkingTree))

    def _iter_git_changes(self, want_unchanged=False, specific_files=None,
            require_versioned=False, include_root=False):
        # TODO(jelmer): Handle include_root
        # TODO(jelmer): Handle require_versioned
        # TODO(jelmer): Restrict to specific_files, for performance reasons.
        with self.lock_read():
            return changes_between_git_tree_and_working_copy(
                self.source.store, self.source.tree,
                self.target, want_unchanged=want_unchanged)

    def compare(self, want_unchanged=False, specific_files=None,
                extra_trees=None, require_versioned=False, include_root=False,
                want_unversioned=False):
        with self.lock_read():
            changes = self._iter_git_changes(
                    want_unchanged=want_unchanged,
                    specific_files=specific_files,
                    require_versioned=require_versioned,
                    include_root=include_root)
            source_fileid_map = self.source._fileid_map
            target_fileid_map = self.target._fileid_map
            ret = tree_delta_from_git_changes(changes, self.target.mapping,
                (source_fileid_map, target_fileid_map),
                specific_files=specific_files, require_versioned=require_versioned,
                include_root=include_root)
            if want_unversioned:
                for e in self.target.extras():
                    ret.unversioned.append(
                        (osutils.normalized_filename(e)[0], None,
                        osutils.file_kind(self.target.abspath(e))))
            return ret

    def iter_changes(self, include_unchanged=False, specific_files=None,
                     pb=None, extra_trees=[], require_versioned=True,
                     want_unversioned=False):
        with self.lock_read():
            changes = self._iter_git_changes(
                    want_unchanged=include_unchanged,
                    specific_files=specific_files,
                    require_versioned=require_versioned)
            if want_unversioned:
                changes = itertools.chain(
                        changes,
                        untracked_changes(self.target))
            return changes_from_git_changes(
                    changes, self.target.mapping,
                    specific_files=specific_files)


tree.InterTree.register_optimiser(InterIndexGitTree)


def untracked_changes(tree):
    for e in tree.extras():
        ap = tree.abspath(e)
        st = os.stat(ap)
        try:
            np, accessible  = osutils.normalized_filename(e)
        except UnicodeDecodeError:
            raise errors.BadFilenameEncoding(
                e, osutils._fs_enc)
        yield ((None, np), (None, st.st_mode),
               (None, blob_from_path_and_stat(ap.encode('utf-8'), st).id))


def changes_between_git_tree_and_index(store, from_tree_sha, target,
        want_unchanged=False, update_index=False):
    """Determine the changes between a git tree and a working tree with index.

    """
    to_tree_sha = target.index.commit(store)
    return store.tree_changes(from_tree_sha, to_tree_sha, include_trees=True,
            want_unchanged=want_unchanged)


def changes_between_git_tree_and_working_copy(store, from_tree_sha, target,
        want_unchanged=False, update_index=False):
    """Determine the changes between a git tree and a working tree with index.

    """
    blobs = iter_fresh_blobs(target.index, target.abspath('.').encode(sys.getfilesystemencoding()))
    to_tree_sha = commit_tree(store, blobs)
    return store.tree_changes(from_tree_sha, to_tree_sha, include_trees=True,
            want_unchanged=want_unchanged)
