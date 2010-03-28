# Copyright (C) 2007 Canonical Ltd
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

"""An adapter between a Git control dir and a Bazaar BzrDir."""

from bzrlib import (
    bzrdir,
    errors as bzr_errors,
    lockable_files,
    urlutils,
    version_info as bzrlib_version,
    )

LockWarner = getattr(lockable_files, "_LockWarner", None)

from bzrlib.plugins.git import (
    LocalGitBzrDirFormat,
    get_rich_root_format,
    )


class GitLock(object):
    """A lock that thunks through to Git."""

    def lock_write(self, token=None):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass

    def peek(self):
        pass

    def validate_token(self, token):
        pass

    def break_lock(self):
        pass


class GitLockableFiles(lockable_files.LockableFiles):
    """Git specific lockable files abstraction."""

    def __init__(self, transport, lock):
        self._lock = lock
        self._transaction = None
        self._lock_mode = None
        self._transport = transport
        if LockWarner is None:
            # Bzr 1.13
            self._lock_count = 0
        else:
            self._lock_warner = LockWarner(repr(self))


class GitDir(bzrdir.BzrDir):
    """An adapter to the '.git' dir used by git."""

    def is_supported(self):
        return True

    def cloning_metadir(self, stacked=False):
        return get_rich_root_format(stacked)

    def _branch_name_to_ref(self, name):
        if name is None or name == "HEAD":
            return "HEAD"
        if not "/" in name:
            return "refs/heads/%s" % name
        else:
            return name


class LocalGitDir(GitDir):
    """An adapter to the '.git' dir used by git."""

    def _get_gitrepository_class(self):
        from bzrlib.plugins.git.repository import LocalGitRepository
        return LocalGitRepository

    _gitrepository_class = property(_get_gitrepository_class)

    def __init__(self, transport, lockfiles, gitrepo, format):
        self._format = format
        self.root_transport = transport
        self._git = gitrepo
        if gitrepo.bare:
            self.transport = transport
        else:
            self.transport = transport.clone('.git')
        self._lockfiles = lockfiles
        self._mode_check_done = None

    def is_control_filename(self, filename):
        return filename == '.git' or filename.startswith('.git/')

    def get_branch_transport(self, branch_format):
        if branch_format is None:
            return self.transport
        if isinstance(branch_format, LocalGitBzrDirFormat):
            return self.transport
        raise bzr_errors.IncompatibleFormat(branch_format, self._format)

    get_repository_transport = get_branch_transport
    get_workingtree_transport = get_branch_transport

    def _open_branch(self, name=None, ignore_fallbacks=None,
            unsupported=False):
        """'create' a branch for this dir."""
        repo = self.open_repository()
        from bzrlib.plugins.git.branch import LocalGitBranch
        return LocalGitBranch(self, repo, self._branch_name_to_ref(name),
            self._lockfiles)

    if bzrlib_version >= (2, 2):
        open_branch = _open_branch
    else:
        def open_branch(self, ignore_fallbacks=None, unsupported=False):
            return self._open_branch(name=None,
                ignore_fallbacks=ignore_fallbacks, unsupported=unsupported)

    def destroy_branch(self, name=None):
        del self._git.refs[self._branch_name_to_ref(name)]

    def list_branches(self):
        ret = []
        for name in self._git.get_refs():
            if name.startswith("refs/heads/"):
                ret.append(self.open_branch(name=name))
            elif name == "HEAD":
                ret.append(self.open_branch(name=None))
        return ret

    def open_repository(self, shared=False):
        """'open' a repository for this dir."""
        return self._gitrepository_class(self, self._lockfiles)

    def open_workingtree(self, recommend_upgrade=True):
        if not self._git.bare:
            from dulwich.errors import NoIndexPresent
            try:
                from bzrlib.plugins.git.workingtree import GitWorkingTree
                return GitWorkingTree(self, self.open_repository(),
                                                      self.open_branch())
            except NoIndexPresent:
                pass
        loc = urlutils.unescape_for_display(self.root_transport.base, 'ascii')
        raise bzr_errors.NoWorkingTree(loc)

    def create_repository(self, shared=False):
        return self.open_repository()

    def create_branch(self, name=None):
        refname = self._branch_name_to_ref(name)
        self._git.refs[refname] = "0" * 40
        return self.open_branch(name)

    def backup_bzrdir(self):
        if self._git.bare:
            self.root_transport.copy_tree(".git", ".git.backup")
            return (self.root_transport.abspath(".git"),
                    self.root_transport.abspath(".git.backup"))
        else:
            raise bzr_errors.BzrError("Unable to backup bare repositories")

    def create_workingtree(self, revision_id=None, from_branch=None,
        accelerator_tree=None, hardlink=False):
        if self._git.bare:
            raise bzr_errors.BzrError("Can't create working tree in a bare repo")
        from dulwich.index import write_index
        from dulwich.pack import SHA1Writer
        f = open(self.transport.local_abspath("index"), 'w+')
        try:
            f = SHA1Writer(f)
            write_index(f, [])
        finally:
            f.close()
        return self.open_workingtree()
