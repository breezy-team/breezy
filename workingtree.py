# Copyright (C) 2008-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
    build_index_from_tree,
    changes_from_tree,
    cleanup_mode,
    commit_tree,
    index_entry_from_stat,
    iter_fresh_blobs,
    blob_from_path_and_stat,
    FLAG_STAGEMASK,
    validate_path,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )
from dulwich.objects import (
    Blob,
    Tree,
    S_IFGITLINK,
    S_ISGITLINK,
    )
from dulwich.repo import Repo
import os
import posixpath
import re
import stat
import sys

from ... import (
    conflicts as _mod_conflicts,
    errors,
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
    MutableGitIndexTree,
    )
from .mapping import (
    GitFileIdMap,
    mode_kind,
    )

IGNORE_FILENAME = ".gitignore"


class GitWorkingTree(MutableGitIndexTree,workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, controldir, repo, branch, index):
        MutableGitIndexTree.__init__(self)
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
        self.views = self._make_views()
        self._rules_searcher = None
        self._detect_case_handling()
        self._reset_data()

    def supports_tree_reference(self):
        return False

    def supports_rename_tracking(self):
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

        def backup(file_to_backup):
            abs_path = self.abspath(file_to_backup)
            backup_name = self.controldir._available_backup_name(file_to_backup)
            osutils.rename(abs_path, self.abspath(backup_name))
            return "removed %s (but kept a copy: %s)" % (
                file_to_backup, backup_name)

        # Sort needed to first handle directory content before the directory
        files_to_backup = []

        all_files = set()

        def recurse_directory_to_add_files(directory):
            # Recurse directory and add all files
            # so we can check if they have changed.
            for parent_info, file_infos in self.walkdirs(directory):
                for relpath, basename, kind, lstat, fileid, kind in file_infos:
                    # Is it versioned or ignored?
                    if self.is_versioned(relpath):
                        # Add nested content for deletion.
                        all_files.add(relpath)
                    else:
                        # Files which are not versioned
                        # should be treated as unknown.
                        files_to_backup.append(relpath)

        with self.lock_tree_write():
            for filepath in files:
                # Get file name into canonical form.
                abspath = self.abspath(filepath)
                filepath = self.relpath(abspath)

                if filepath:
                    all_files.add(filepath)
                    recurse_directory_to_add_files(filepath)

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
                        files_to_backup.extend(osutils.parent_directories(path[1]))
                    elif (content_change and (kind[1] is not None) and
                            osutils.is_inside_any(files, path[1])):
                        # Versioned and changed, but not deleted, and still
                        # in one of the dirs to be deleted.
                        files_to_backup.append(path[1])
                        files_to_backup.extend(osutils.parent_directories(path[1]))

            for f in files:
                if f == '':
                    continue

                try:
                    kind = self.kind(f)
                except errors.NoSuchFile:
                    kind = None

                abs_path = self.abspath(f)
                if verbose:
                    # having removed it, it must be either ignored or unknown
                    if self.is_ignored(f):
                        new_status = 'I'
                    else:
                        new_status = '?'
                    kind_ch = osutils.kind_marker(kind)
                    to_file.write(new_status + '       ' + f + kind_ch + '\n')
                if kind is None:
                    message = "%s does not exist" % (f, )
                else:
                    if not keep_files:
                        if f in files_to_backup and not force:
                            message = backup(f)
                        else:
                            if kind == 'directory':
                                osutils.rmtree(abs_path)
                            else:
                                osutils.delete_any(abs_path)
                            message = "deleted %s" % (f,)
                    else:
                        message = "removed %s" % (f,)
                self._unversion_path(f)

                # print only one message (if any) per file.
                if message is not None:
                    trace.note(message)
            self._versioned_dirs = None
            self.flush()

    def smart_add(self, file_list, recurse=True, action=None, save=True):
        if not file_list:
            file_list = [u'.']

        # expand any symlinks in the directory part, while leaving the
        # filename alone
        # only expanding if symlinks are supported avoids windows path bugs
        if osutils.has_symlinks():
            file_list = list(map(osutils.normalizepath, file_list))

        conflicts_related = set()
        for c in self.conflicts():
            conflicts_related.update(c.associated_filenames())

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
                filepath, can_access = osutils.normalized_filename(filepath)
                if not can_access:
                    raise errors.InvalidNormalization(filepath)

                abspath = self.abspath(filepath)
                kind = osutils.file_kind(abspath)
                if kind in ("file", "symlink"):
                    if filepath in self.index:
                        # Already present
                        continue
                    call_action(filepath, kind)
                    if save:
                        self._index_add_entry(filepath, kind)
                    added.append(filepath)
                elif kind == "directory":
                    if filepath not in self.index:
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
                        if subp in self.index:
                            # Already present
                            continue
                        if subp in conflicts_related:
                            continue
                        call_action(filepath, kind)
                        if save:
                            self._index_add_entry(subp, kind)
                        added.append(subp)
            if added and save:
                self.flush()
            return added, ignored

    def has_filename(self, filename):
        return osutils.lexists(self.abspath(filename))

    def _iter_files_recursive(self, from_dir=None, include_dirs=False):
        if from_dir is None:
            from_dir = ""
        for (dirpath, dirnames, filenames) in os.walk(self.abspath(from_dir).encode(osutils._fs_enc)):
            dir_relpath = dirpath[len(self.basedir):].strip("/")
            if self.controldir.is_control_filename(dir_relpath):
                continue
            for name in list(dirnames):
                if self.controldir.is_control_filename(name):
                    dirnames.remove(name)
                    continue
                relpath = os.path.join(dir_relpath, name)
                if include_dirs:
                    try:
                        yield relpath.decode(osutils._fs_enc)
                    except UnicodeDecodeError as e:
                        raise errors.BadFilenameEncoding(
                            relpath, osutils._fs_enc)
                if not self._has_dir(relpath):
                    dirnames.remove(name)
            for name in filenames:
                if not self.mapping.is_special_file(name):
                    yp = os.path.join(dir_relpath, name)
                    try:
                        yield yp.decode(osutils._fs_enc)
                    except UnicodeDecodeError:
                        raise errors.BadFilenameEncoding(
                            yp, osutils._fs_enc)

    def extras(self):
        """Yield all unversioned files in this WorkingTree.
        """
        with self.lock_read():
            for p in (set(self._iter_files_recursive(include_dirs=True)) - set(self.index)):
                try:
                    up = p.decode(osutils._fs_enc)
                except UnicodeDecodeError:
                    raise errors.BadFilenameEncoding(
                        p, osutils._fs_enc)
                if not self._has_dir(up):
                    yield up

    def flush(self):
        # TODO: Maybe this should only write on dirty ?
        if self._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        self.index.write()

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

    def get_file_mtime(self, path, file_id=None):
        """See Tree.get_file_mtime."""
        try:
            return self._lstat(path).st_mtime
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
        self._fileid_map = self._basis_fileid_map.copy()

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

    def filter_unversioned_files(self, files):
        return set([p for p in files if not self.is_versioned(p)])

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

    def _lstat(self, path):
        return os.lstat(self.abspath(path))

    def is_executable(self, path, file_id=None):
        if getattr(self, "_supports_executable", osutils.supports_executable)():
            mode = self._lstat(path).st_mode
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
                try:
                    path = path.decode("utf-8")
                except UnicodeDecodeError:
                    raise errors.BadFilenameEncoding(
                        path, osutils._fs_enc)
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
                file_ie = self._get_file_ie(
                        name.decode('utf-8'),
                        item_path.decode('utf-8'), value, parent_id)
            yield file_ie
        if not found_any and path != u'':
            raise errors.NoSuchFile(path)

    def conflicts(self):
        with self.lock_read():
            conflicts = _mod_conflicts.ConflictList()
            for item_path, value in self.index.iteritems():
                if value.flags & FLAG_STAGEMASK:
                    conflicts.append(_mod_conflicts.TextConflict(item_path.decode('utf-8')))
            return conflicts

    def set_conflicts(self, conflicts):
        by_path = set()
        for conflict in conflicts:
            if conflict.typestring in ('text conflict', 'contents conflict'):
                by_path.add(conflict.path.encode('utf-8'))
            else:
                raise errors.UnsupportedOperation(self.set_conflicts, self)
        with self.lock_tree_write():
            for path in self.index:
                self._set_conflicted(path, path in by_path)
            self.flush()

    def _set_conflicted(self, path, conflicted):
        trace.mutter('change conflict: %r -> %r', path, conflicted)
        value = self.index[path]
        if conflicted:
            self.index[path] = (value[:9] + (value[9] | FLAG_STAGEMASK, ))
        else:
            self.index[path] = (value[:9] + (value[9] &~ FLAG_STAGEMASK, ))

    def add_conflicts(self, new_conflicts):
        with self.lock_tree_write():
            for conflict in new_conflicts:
                if conflict.typestring in ('text conflict', 'contents conflict'):
                    try:
                        self._set_conflicted(conflict.path.encode('utf-8'), True)
                    except KeyError:
                        raise errors.UnsupportedOperation(self.add_conflicts, self)
                else:
                    raise errors.UnsupportedOperation(self.add_conflicts, self)
            self.flush()

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
        per_dir = defaultdict(set)
        if prefix == "":
            per_dir[('', self.get_root_id())] = set()
        def add_entry(path, kind):
            if path == '' or not path.startswith(prefix):
                return
            (dirname, child_name) = posixpath.split(path)
            add_entry(dirname, 'directory')
            dirname = dirname.decode("utf-8")
            dir_file_id = self.path2id(dirname)
            if not isinstance(value, tuple) or len(value) != 10:
                raise ValueError(value)
            per_dir[(dirname, dir_file_id)].add(
                (path.decode("utf-8"), child_name.decode("utf-8"),
                kind, None,
                self.path2id(path.decode("utf-8")),
                kind))
        for path, value in self.index.iteritems():
            if self.mapping.is_special_file(path):
                continue
            if not path.startswith(prefix):
                continue
            add_entry(path, mode_kind(value.mode))
        return ((k, sorted(v)) for (k, v) in sorted(per_dir.iteritems()))

    def get_shelf_manager(self):
        raise workingtree.ShelvingUnsupported()

    def store_uncommitted(self):
        raise errors.StoringUncommittedNotSupported(self)

    def apply_inventory_delta(self, changes):
        for (old_path, new_path, file_id, ie) in changes:
            if old_path is not None:
                try:
                    del self.index[old_path.encode('utf-8')]
                except KeyError:
                    pass
                else:
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

    def _rename_one(self, from_rel, to_rel):
        os.rename(self.abspath(from_rel), self.abspath(to_rel))

    def _build_checkout_with_index(self):
        build_index_from_tree(
            self.user_transport.local_abspath('.'),
            self.control_transport.local_abspath("index"),
            self.store,
            None if self.branch.head is None else self.store[self.branch.head].tree)

    def reset_state(self, revision_ids=None):
        """Reset the state of the working tree.

        This does a hard-reset to a last-known-good state. This is a way to
        fix if something got corrupted (like the .git/index file)
        """
        with self.lock_tree_write():
            if revision_ids is not None:
                self.set_parent_ids(revision_ids)
            self.index.clear()
            if self.branch.head is not None:
                for entry in self.store.iter_tree_contents(self.store[self.branch.head].tree):
                    if not validate_path(entry.path):
                        continue

                    if S_ISGITLINK(entry.mode):
                        pass # TODO(jelmer): record and return submodule paths
                    else:
                        # Let's at least try to use the working tree file:
                        try:
                            st = self._lstat(self.abspath(entry.path))
                        except OSError, (num, msg):
                            # But if it doesn't exist, we'll make something up.
                            obj = self.store[entry.sha]
                            st = os.stat_result((entry.mode, 0, 0, 0,
                                  0, 0, len(obj.as_raw_string()), 0,
                                  0, 0))
                    self.index[entry.path] = index_entry_from_stat(st, entry.sha, 0)
            self.flush()


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    _tree_class = GitWorkingTree

    supports_versioned_directories = False

    supports_setting_file_ids = False

    supports_store_uncommitted = False

    supports_leftmost_parent_id_as_ghost = False

    supports_righthand_parent_id_as_ghost = False

    requires_normalized_unicode_filenames = True

    supports_merge_modified = False

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
            require_versioned=False, include_root=False, extra_trees=None):
        trees = [self.source]
        if extra_trees is not None:
            trees.extend(extra_trees)
        if specific_files is not None:
            specific_files = self.target.find_related_paths_across_trees(
                    specific_files, trees,
                    require_versioned=require_versioned)
            for path in specific_files:
                if (not self.source.is_versioned(path) and
                    not self.target.is_versioned(path)):
                    raise errors.PathsNotVersionedError(path)
        # TODO(jelmer): Restrict to specific_files, for performance reasons.
        with self.lock_read():
            return changes_between_git_tree_and_working_copy(
                self.source.store, self.source.tree,
                self.target, want_unchanged=want_unchanged,
                include_root=include_root)

    def compare(self, want_unchanged=False, specific_files=None,
                extra_trees=None, require_versioned=False, include_root=False,
                want_unversioned=False):
        with self.lock_read():
            changes = self._iter_git_changes(
                    want_unchanged=want_unchanged,
                    specific_files=specific_files,
                    require_versioned=require_versioned,
                    include_root=include_root,
                    extra_trees=extra_trees)
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
                    require_versioned=require_versioned,
                    extra_trees=extra_trees)
            if want_unversioned:
                changes = itertools.chain(
                        changes,
                        untracked_changes(self.target))
            return changes_from_git_changes(
                    changes, self.target.mapping,
                    specific_files=specific_files,
                    include_unchanged=include_unchanged)


tree.InterTree.register_optimiser(InterIndexGitTree)


def untracked_changes(tree):
    for e in tree.extras():
        ap = tree.abspath(e)
        st = os.lstat(ap)
        try:
            np, accessible  = osutils.normalized_filename(e)
        except UnicodeDecodeError:
            raise errors.BadFilenameEncoding(
                e, osutils._fs_enc)
        if stat.S_ISDIR(st.st_mode):
            obj_id = Tree().id
        else:
            obj_id = blob_from_path_and_stat(ap.encode('utf-8'), st).id
        yield ((None, np), (None, st.st_mode), (None, obj_id))


def changes_between_git_tree_and_index(store, from_tree_sha, target,
        want_unchanged=False, update_index=False):
    """Determine the changes between a git tree and a working tree with index.

    """
    to_tree_sha = target.index.commit(store)
    return store.tree_changes(from_tree_sha, to_tree_sha, include_trees=True,
            want_unchanged=want_unchanged, change_type_same=True)


def changes_between_git_tree_and_working_copy(store, from_tree_sha, target,
        want_unchanged=False, update_index=False, include_root=False):
    """Determine the changes between a git tree and a working tree with index.

    """
    blobs = iter_fresh_blobs(target.index, target.abspath('.').encode(sys.getfilesystemencoding()))
    to_tree_sha = commit_tree(store, blobs)
    return store.tree_changes(from_tree_sha, to_tree_sha, include_trees=True,
            want_unchanged=want_unchanged, change_type_same=True)
