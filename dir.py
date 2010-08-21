# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2010 Jelmer Vernooij
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

"""An adapter between a Git control dir and a Bazaar ControlDir."""

from bzrlib import (
    bzrdir,
    errors as bzr_errors,
    lockable_files,
    urlutils,
    version_info as bzrlib_version,
    )

LockWarner = getattr(lockable_files, "_LockWarner", None)

from bzrlib.plugins.git import (
    LocalGitControlDirFormat,
    )
try:
    from bzrlib.controldir import (
        ControlDir,
        )
except ImportError:
    # bzr < 2.3
    from bzrlib.bzrdir import (
        BzrDir,
        )
    ControlDir = BzrDir


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


class GitDir(ControlDir):
    """An adapter to the '.git' dir used by git."""

    def is_supported(self):
        return True

    def can_convert_format(self):
        return False

    def cloning_metadir(self, stacked=False):
        return bzrdir.format_registry.make_bzrdir("default")

    def _branch_name_to_ref(self, name):
        raise NotImplementedError(self._branch_name_to_ref)

    if bzrlib_version >= (2, 2):
        def open_branch(self, name=None, unsupported=False, 
            ignore_fallbacks=None):
            return self._open_branch(name=name,
                ignore_fallbacks=ignore_fallbacks, unsupported=unsupported)
    else:
        def open_branch(self, ignore_fallbacks=None, unsupported=False):
            return self._open_branch(name=None,
                ignore_fallbacks=ignore_fallbacks, unsupported=unsupported)


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

    def _branch_name_to_ref(self, name):
        from bzrlib.plugins.git.refs import branch_name_to_ref
        ref = branch_name_to_ref(name, None)
        if ref == "HEAD":
            from dulwich.repo import SYMREF
            refcontents = self._git.refs.read_ref(ref)
            if refcontents.startswith(SYMREF):
                ref = refcontents[len(SYMREF):]
        return ref

    def is_control_filename(self, filename):
        return filename == '.git' or filename.startswith('.git/')

    def get_branch_transport(self, branch_format, name=None):
        if branch_format is None:
            return self.transport
        if isinstance(branch_format, LocalGitControlDirFormat):
            return self.transport
        raise bzr_errors.IncompatibleFormat(branch_format, self._format)

    def get_repository_transport(self, format):
        if format is None:
            return self.transport
        if isinstance(format, LocalGitControlDirFormat):
            return self.transport
        raise bzr_errors.IncompatibleFormat(format, self._format)

    def get_workingtree_transport(self, format):
        if format is None:
            return self.transport
        if isinstance(format, LocalGitControlDirFormat):
            return self.transport
        raise bzr_errors.IncompatibleFormat(format, self._format)

    def _open_branch(self, name=None, ignore_fallbacks=None, unsupported=False):
        """'create' a branch for this dir."""
        repo = self.open_repository()
        from bzrlib.plugins.git.branch import LocalGitBranch
        return LocalGitBranch(self, repo, self._branch_name_to_ref(name),
            self._lockfiles)

    def destroy_branch(self, name=None):
        refname = self._branch_name_to_ref(name)
        if not refname in self._git.refs:
            raise bzr_errors.NotBranchError(self.root_transport.base,
                    bzrdir=self)
        del self._git.refs[refname]

    def destroy_repository(self):
        raise bzr_errors.UnsupportedOperation(self.destroy_repository, self)

    def destroy_workingtree(self):
        raise bzr_errors.UnsupportedOperation(self.destroy_workingtree, self)

    def needs_format_conversion(self, format=None):
        return not isinstance(self._format, format.__class__)

    def list_branches(self):
        ret = []
        for name in self._git.get_refs():
            if name.startswith("refs/heads/"):
                ret.append(self.open_branch(name=name))
        return ret

    def open_repository(self, shared=False):
        """'open' a repository for this dir."""
        return self._gitrepository_class(self, self._lockfiles)

    def open_workingtree(self, recommend_upgrade=True):
        if not self._git.bare:
            from dulwich.errors import NoIndexPresent
            repo = self.open_repository()
            try:
                index = repo._git.open_index()
            except NoIndexPresent:
                pass
            else:
                from bzrlib.plugins.git.workingtree import GitWorkingTree
                try:
                    branch = self.open_branch()
                except bzr_errors.NotBranchError:
                    pass
                else:
                    return GitWorkingTree(self, repo, branch, index)
        loc = urlutils.unescape_for_display(self.root_transport.base, 'ascii')
        raise bzr_errors.NoWorkingTree(loc)

    def create_repository(self, shared=False):
        return self.open_repository()

    def create_branch(self, name=None):
        refname = self._branch_name_to_ref(name)
        from dulwich.protocol import ZERO_SHA
        self._git.refs[refname or "HEAD"] = ZERO_SHA
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
