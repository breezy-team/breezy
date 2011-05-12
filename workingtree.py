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
from collections import defaultdict
import errno
from dulwich.index import (
    Index,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )
from dulwich.objects import (
    Blob,
    ZERO_SHA,
    )
import os
import posix
import posixpath
import stat
import sys

from bzrlib import (
    errors,
    conflicts as _mod_conflicts,
    ignores,
    inventory,
    lockable_files,
    lockdir,
    osutils,
    trace,
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
        self.store = self.repository._git.object_store
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
        self._versioned_dirs = None
        self.views = self._make_views()
        self._rules_searcher = None
        self._detect_case_handling()
        self._reset_data()
        self._fileid_map = self._basis_fileid_map.copy()

    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        self.set_parent_ids([p for p, t in parents_list])

    def _index_add_entry(self, path, file_id, kind):
        assert isinstance(path, basestring)
        assert type(file_id) == str
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
        if not blob.id in self.store:
            self.store.add_object(blob)
        # Add an entry to the index or update the existing entry
        flags = 0 # FIXME
        encoded_path = path.encode("utf-8")
        self.index[encoded_path] = (stat_val.st_ctime,
                stat_val.st_mtime, stat_val.st_dev, stat_val.st_ino,
                stat_val.st_mode, stat_val.st_uid, stat_val.st_gid,
                stat_val.st_size, blob.id, flags)
        if self._versioned_dirs is not None:
            self._ensure_versioned_dir(encoded_path)

    def _ensure_versioned_dir(self, dirname):
        if dirname in self._versioned_dirs:
            return
        if dirname != "":
            self._ensure_versioned_dir(posixpath.dirname(dirname))
        self._versioned_dirs.add(dirname)

    def _load_dirs(self):
        self._versioned_dirs = set()
        for p in self.index:
            self._ensure_versioned_dir(posixpath.dirname(p))

    def _unversion_path(self, path):
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
        for file_id in file_ids:
            path = self.id2path(file_id)
            self._unversion_path(path)

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
            backup_name = self.bzrdir._available_backup_name(file_to_backup)
            osutils.rename(abs_path, self.abspath(backup_name))
            return "removed %s (but kept a copy: %s)" % (
                file_to_backup, backup_name)

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

    def _add(self, files, ids, kinds):
        for (path, file_id, kind) in zip(files, ids, kinds):
            if file_id is not None:
                self._fileid_map.set_file_id(path.encode("utf-8"), file_id)
            else:
                file_id = self._fileid_map.lookup_file_id(path.encode("utf-8"))
            self._index_add_entry(path, file_id, kind)

    def smart_add(self, file_list, recurse=True, action=None, save=True):
        added = []
        ignored = {}
        user_dirs = []
        for filepath in osutils.canonical_relpaths(self.basedir, file_list):
            if action is not None:
                file_id = action()
            else:
                file_id = None
            abspath = self.abspath(filepath)
            kind = osutils.file_kind(abspath)
            if kind in ("file", "symlink"):
                if not save:
                    self._index_add_entry(filepath, file_id, kind)
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
                if self.is_control_filename(subp):
                    trace.mutter("skip control directory %r", subp)
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
                        file_id = action()
                    else:
                        file_id = None
                    if not save:
                        self._index_add_entry(subp, file_id, kind)
        return added, ignored

    def _set_root_id(self, file_id):
        self._fileid_map.set_file_id("", file_id)

    def move(self, from_paths, to_dir=None, after=False):
        rename_tuples = []
        to_abs = self.abspath(to_dir)
        if not os.path.isdir(to_abs):
            raise errors.BzrMoveFailedError('', to_dir,
                errors.NotADirectory(to_abs))

        for from_rel in from_paths:
            from_tail = os.path.split(from_rel)[-1]
            to_rel = os.path.join(to_dir, from_tail)
            self.rename_one(from_rel, to_rel, after=after)
            rename_tuples.append((from_rel, to_rel))
        return rename_tuples

    def rename_one(self, from_rel, to_rel, after=False):
        if not after:
            os.rename(self.abspath(from_rel), self.abspath(to_rel))
        from_path = from_rel.encode("utf-8")
        to_path = to_rel.encode("utf-8")
        if not self.has_filename(to_rel):
            raise errors.BzrMoveFailedError(from_rel, to_rel,
                errors.NoSuchFile(to_rel))
        if not from_path in self.index:
            raise errors.BzrMoveFailedError(from_rel, to_rel,
                errors.NotVersionedError(path=from_rel))
        self.index[to_path] = self.index[from_path]
        del self.index[from_path]

    def get_root_id(self):
        return self.path2id("")

    def _has_dir(self, path):
        if self._versioned_dirs is None:
            self._load_dirs()
        return path in self._versioned_dirs

    @needs_read_lock
    def path2id(self, path):
        encoded_path = path.encode("utf-8")
        if self._is_versioned(encoded_path):
            return self._fileid_map.lookup_file_id(encoded_path)
        return None

    def extras(self):
        """Yield all unversioned files in this WorkingTree.
        """
        for (dirpath, dirnames, filenames) in os.walk(self.basedir):
            if self.bzrdir.is_control_filename(dirpath[len(self.basedir):].strip("/")):
                continue
            for filename in filenames:
                relpath = os.path.join(dirpath[len(self.basedir):].strip("/"), filename)
                if not self._is_versioned(relpath):
                    yield relpath

    def unlock(self):
        # non-implementation specific cleanup
        self._cleanup()

        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()

    def flush(self):
        # TODO: Maybe this should only write on dirty ?
        if self._control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        self.index.write()

    def __iter__(self):
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
        if type(file_id) != str:
            raise AssertionError
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
                # FIXME: Parse git file format, rather than assuming it's
                # the same as for bzr's native formats.
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
        if head == ZERO_SHA:
            self._basis_fileid_map = GitFileIdMap({}, self.mapping)
        else:
            self._basis_fileid_map = self.mapping.get_fileid_map(self.store.__getitem__,
                self.store[head].tree)

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

    def _is_versioned(self, path):
        return (path in self.index or self._has_dir(path))

    def filter_unversioned_files(self, files):
        return set([p for p in files if self._is_versioned(p.encode("utf-8"))])

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

    def _get_file_ie(self, path, value, parent_id):
        assert isinstance(path, unicode)
        assert isinstance(value, tuple) and len(value) == 10
        (ctime, mtime, dev, ino, mode, uid, gid, size, sha, flags) = value
        file_id = self.path2id(path)
        if type(file_id) != str:
            raise AssertionError
        kind = mode_kind(mode)
        ie = inventory.entry_factory[kind](file_id,
            posixpath.basename(path), parent_id)
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
        if path is None:
            path = self.id2path(file_id)
        head = self.repository._git.head()
        if head == ZERO_SHA:
            raise errors.NoSuchId(self, file_id)
        root_tree = self.store[head].tree
        (mode, hexsha) = tree_lookup_path(self.store.__getitem__, root_tree, path)
        return mode_kind(mode)

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
        root_ie = self._get_dir_ie(u"", None)
        if include_root and not from_dir:
            yield "", "V", root_ie.kind, root_ie.file_id, root_ie
        dir_ids[u""] = root_ie.file_id
        for path, value in self.index.iteritems():
            path = path.decode("utf-8")
            parent = posixpath.dirname(path).strip("/")
            for dir_path, dir_ie in self._add_missing_parent_ids(parent, dir_ids):
                yield dir_path, "V", dir_ie.kind, dir_ie.file_id, dir_ie
            ie = self._get_file_ie(path, value, dir_ids[parent])
            yield path, "V", ie.kind, ie.file_id, ie

    def all_file_ids(self):
        ids = {u"": self.path2id("")}
        for path in self.index:
            path = path.decode("utf-8")
            parent = posixpath.dirname(path).strip("/")
            for e in self._add_missing_parent_ids(parent, ids):
                pass
            ids[path] = self.path2id(path)
        return set(ids.values())

    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        # FIXME: Is return order correct?
        if yield_parents:
            raise NotImplementedError(self.iter_entries_by_dir)
        if specific_file_ids is not None:
            specific_paths = [self.id2path(file_id) for file_id in specific_file_ids]
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
            path = path.decode("utf-8")
            if specific_paths is not None and not path in specific_paths:
                continue
            try:
                file_ie = self._get_file_ie(path, value, None)
            except IOError:
                continue
            parent = posixpath.dirname(path).strip("/")
            for (dir_path, dir_ie) in self._add_missing_parent_ids(parent,
                    dir_ids):
                yield dir_path, dir_ie
            file_ie.parent_id = self.path2id(parent)
            yield path, file_ie

    @needs_read_lock
    def conflicts(self):
        # FIXME:
        return _mod_conflicts.ConflictList()

    def update_basis_by_delta(self, new_revid, delta):
        # The index just contains content, which won't have changed.
        self._reset_data()

    def _walkdirs(self, prefix=""):
        if prefix != "":
            prefix += "/"
        per_dir = defaultdict(list)
        for path, value in self.index.iteritems():
            if not path.startswith(prefix):
                continue
            (dirname, child_name) = posixpath.split(path)
            dirname = dirname.decode("utf-8")
            dir_file_id = self.path2id(dirname)
            assert isinstance(value, tuple) and len(value) == 10
            (ctime, mtime, dev, ino, mode, uid, gid, size, sha, flags) = value
            stat_result = posix.stat_result((mode, ino,
                    dev, 1, uid, gid, size,
                    0, mtime, ctime))
            per_dir[(dirname, dir_file_id)].append(
                (path.decode("utf-8"), child_name.decode("utf-8"),
                mode_kind(mode), stat_result,
                self.path2id(path.decode("utf-8")),
                mode_kind(mode)))
        return per_dir.iteritems()

class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    _tree_class = GitWorkingTree

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
            self.source.store, self.source.tree, 
            want_unchanged=want_unchanged)
        source_fileid_map = self.source.mapping.get_fileid_map(
            self.source.store.__getitem__,
            self.source.tree)
        if self.target.mapping.BZR_FILE_IDS_FILE is not None:
            file_id = self.target.path2id(
                self.target.mapping.BZR_FILE_IDS_FILE)
            if file_id is None:
                target_fileid_map = {}
            else:
                target_fileid_map = self.target.mapping.import_fileid_map(
                    Blob.from_string(self.target.get_file_text(file_id)))
        else:
            target_fileid_map = {}
        target_fileid_map = GitFileIdMap(target_fileid_map,
                self.target.mapping)
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
        changes = self._index.changes_from_tree(
            self.source.store, self.source.tree,
            want_unchanged=include_unchanged)
        # FIXME: Handle want_unversioned
        return changes_from_git_changes(changes, self.target.mapping,
            specific_file=specific_files)


tree.InterTree.register_optimiser(InterIndexGitTree)
