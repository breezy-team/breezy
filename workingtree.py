# Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
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
import stat

from bzrlib import (
    errors,
    ignores,
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
from bzrlib.plugins.git.inventory import (
    GitIndexInventory,
    )
from bzrlib.plugins.git.tree import (
    changes_from_git_changes,
    tree_delta_from_git_changes,
    )
from bzrlib.plugins.git.mapping import (
    GitFileIdMap,
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
            if entry.kind == "directory":
                # Git indexes don't contain directories
                continue
            if entry.kind == "file":
                blob = Blob()
                try:
                    file, stat_val = self.get_file_with_stat(entry.file_id, path)
                except (errors.NoSuchFile, IOError):
                    # TODO: Rather than come up with something here, use the old index
                    file = StringIO()
                    from posix import stat_result
                    stat_val = stat_result((stat.S_IFREG | 0644, 0, 0, 0, 0, 0, 0, 0, 0, 0))
                blob.set_raw_string(file.read())
            elif entry.kind == "symlink":
                blob = Blob()
                try:
                    stat_val = os.lstat(self.abspath(path))
                except (errors.NoSuchFile, OSError):
                    # TODO: Rather than come up with something here, use the 
                    # old index
                    from posix import stat_result
                    stat_val = stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
                blob.set_raw_string(self.get_symlink_target(entry.file_id).encode("utf-8"))
            else:
                raise AssertionError("unknown kind '%s'" % entry.kind)
            # Add object to the repository if it didn't exist yet
            if not blob.id in self.repository._git.object_store:
                self.repository._git.object_store.add_object(blob)
            # Add an entry to the index or update the existing entry
            flags = 0 # FIXME
            self.index[path.encode("utf-8")] = (stat_val.st_ctime, stat_val.st_mtime, stat_val.st_dev, stat_val.st_ino, stat_val.st_mode, stat_val.st_uid, stat_val.st_gid, stat_val.st_size, blob.id, flags)

    def flush(self):
        # TODO: Maybe this should only write on dirty ?
        if self._control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        self._rewrite_index()
        self.index.write()
        self._inventory_is_modified = False

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
        self._inventory_is_modified = False
        try:
            head = self.repository._git.head()
        except KeyError, name:
            raise errors.NotBranchError("branch %s at %s" % (name, self.repository.base))
        basis_inv = self.repository.get_inventory(self.branch.lookup_foreign_revision_id(head))
        store = self.repository._git.object_store
        if head == ZERO_SHA:
            fileid_map = GitFileIdMap({}, self.mapping)
            basis_inv = None
        else:
            fileid_map = self.mapping.get_fileid_map(store.__getitem__,
                store[head].tree)
        result = GitIndexInventory(basis_inv, fileid_map, self.index, store)
        self._set_inventory(result, dirty=False)

    @needs_read_lock
    def get_file_sha1(self, file_id, path=None, stat_value=None):
        if not path:
            path = self._inventory.id2path(file_id)
        try:
            return osutils.sha_file_by_name(self.abspath(path).encode(osutils._fs_enc))
        except OSError, (num, msg):
            if num in (errno.EISDIR, errno.ENOENT):
                return None
            raise

    def revision_tree(self, revid):
        return self.repository.revision_tree(revid)

    @needs_read_lock
    def conflicts(self):
        # FIXME:
        return []


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
