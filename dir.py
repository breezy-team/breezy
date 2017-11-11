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

from __future__ import absolute_import

import urllib

from ... import (
    branch as _mod_branch,
    errors as bzr_errors,
    trace,
    osutils,
    revision as _mod_revision,
    urlutils,
    )
from ...bzr.bzrdir import CreateRepository
from ...transport import do_catching_redirections

from ...controldir import (
    ControlDir,
    ControlDirFormat,
    format_registry,
    )


class GitDirConfig(object):

    def get_default_stack_on(self):
        return None

    def set_default_stack_on(self, value):
        raise bzr_errors.BzrError("Cannot set configuration")


class GitControlDirFormat(ControlDirFormat):

    colocated_branches = True
    fixed_components = True

    def __eq__(self, other):
        return type(self) == type(other)

    def is_supported(self):
        return True

    def network_name(self):
        return "git"


class GitDir(ControlDir):
    """An adapter to the '.git' dir used by git."""

    def is_supported(self):
        return True

    def can_convert_format(self):
        return False

    def break_lock(self):
        pass

    def cloning_metadir(self, stacked=False):
        return format_registry.make_controldir("default")

    def checkout_metadir(self, stacked=False):
        return format_registry.make_controldir("default")

    def _get_default_ref(self):
        return "HEAD"

    def _get_selected_ref(self, branch, ref=None):
        if ref is not None and branch is not None:
            raise bzr_errors.BzrError("can't specify both ref and branch")
        if ref is not None:
            return ref
        segment_parameters = getattr(
            self.user_transport, "get_segment_parameters", lambda: {})()
        ref = segment_parameters.get("ref")
        if ref is not None:
            return urlutils.unescape(ref)
        if branch is None and getattr(self, "_get_selected_branch", False):
            branch = self._get_selected_branch()
        if branch is not None:
            from .refs import branch_name_to_ref
            return branch_name_to_ref(branch)
        return self._get_default_ref()

    def get_config(self):
        return GitDirConfig()

    def _available_backup_name(self, base):
        return osutils.available_backup_name(base, self.root_transport.has)

    def sprout(self, url, revision_id=None, force_new_repo=False,
               recurse='down', possible_transports=None,
               accelerator_tree=None, hardlink=False, stacked=False,
               source_branch=None, create_tree_if_local=True):
        from ...repository import InterRepository
        from ...transport.local import LocalTransport
        from ...transport import get_transport
        target_transport = get_transport(url, possible_transports)
        target_transport.ensure_base()
        cloning_format = self.cloning_metadir()
        # Create/update the result branch
        result = cloning_format.initialize_on_transport(target_transport)
        source_branch = self.open_branch()
        source_repository = self.find_repository()
        try:
            result_repo = result.find_repository()
        except bzr_errors.NoRepositoryPresent:
            result_repo = result.create_repository()
            target_is_empty = True
        else:
            target_is_empty = None # Unknown
        if stacked:
            raise _mod_branch.UnstackableBranchFormat(self._format, self.user_url)
        interrepo = InterRepository.get(source_repository, result_repo)

        if revision_id is not None:
            determine_wants = interrepo.get_determine_wants_revids(
                [revision_id], include_tags=False)
        else:
            determine_wants = interrepo.determine_wants_all
        interrepo.fetch_objects(determine_wants=determine_wants,
            mapping=source_branch.mapping)
        result_branch = source_branch.sprout(result,
            revision_id=revision_id, repository=result_repo)
        if (create_tree_if_local
            and isinstance(target_transport, LocalTransport)
            and (result_repo is None or result_repo.make_working_trees())):
            wt = result.create_workingtree(accelerator_tree=accelerator_tree,
                hardlink=hardlink, from_branch=result_branch)
            wt.lock_write()
            try:
                if wt.path2id('') is None:
                    try:
                        wt.set_root_id(self.open_workingtree.get_root_id())
                    except bzr_errors.NoWorkingTree:
                        pass
            finally:
                wt.unlock()
        return result

    def clone_on_transport(self, transport, revision_id=None,
        force_new_repo=False, preserve_stacking=False, stacked_on=None,
        create_prefix=False, use_existing_dir=True, no_tree=False):
        """See ControlDir.clone_on_transport."""
        from ...repository import InterRepository
        from .mapping import default_mapping
        if no_tree:
            format = BareLocalGitControlDirFormat()
        else:
            format = LocalGitControlDirFormat()
        (target_repo, target_controldir, stacking, repo_policy) = format.initialize_on_transport_ex(transport, use_existing_dir=use_existing_dir, create_prefix=create_prefix, force_new_repo=force_new_repo)
        target_git_repo = target_repo._git
        source_repo = self.open_repository()
        source_git_repo = source_repo._git
        interrepo = InterRepository.get(source_repo, target_repo)
        if revision_id is not None:
            determine_wants = interrepo.get_determine_wants_revids([revision_id], include_tags=True)
        else:
            determine_wants = interrepo.determine_wants_all
        (pack_hint, _, refs) = interrepo.fetch_objects(determine_wants,
            mapping=default_mapping)
        for name, val in refs.iteritems():
            target_git_repo.refs[name] = val
        return self.__class__(transport, target_git_repo, format)

    def find_repository(self):
        """Find the repository that should be used.

        This does not require a branch as we use it to find the repo for
        new branches as well as to hook existing branches up to their
        repository.
        """
        return self.open_repository()

    def get_refs_container(self):
        """Retrieve the refs container.
        """
        raise NotImplementedError(self.get_refs_container)


class LocalGitControlDirFormat(GitControlDirFormat):
    """The .git directory control format."""

    bare = False

    @classmethod
    def _known_formats(self):
        return set([LocalGitControlDirFormat()])

    @property
    def repository_format(self):
        from .repository import GitRepositoryFormat
        return GitRepositoryFormat()

    def get_branch_format(self):
        from .branch import GitBranchFormat
        return GitBranchFormat()

    def open(self, transport, _found=None):
        """Open this directory.

        """
        from .transportgit import TransportRepo
        gitrepo = TransportRepo(transport, self.bare,
                refs_text=getattr(self, "_refs_text", None))
        return LocalGitDir(transport, gitrepo, self)

    def get_format_description(self):
        return "Local Git Repository"

    def initialize_on_transport(self, transport):
        from .transportgit import TransportRepo
        repo = TransportRepo.init(transport, bare=self.bare)
        del repo.refs["HEAD"]
        return self.open(transport)

    def initialize_on_transport_ex(self, transport, use_existing_dir=False,
        create_prefix=False, force_new_repo=False, stacked_on=None,
        stack_on_pwd=None, repo_format_name=None, make_working_trees=None,
        shared_repo=False, vfs_only=False):
        def make_directory(transport):
            transport.mkdir('.')
            return transport
        def redirected(transport, e, redirection_notice):
            trace.note(redirection_notice)
            return transport._redirected_to(e.source, e.target)
        try:
            transport = do_catching_redirections(make_directory, transport,
                redirected)
        except bzr_errors.FileExists:
            if not use_existing_dir:
                raise
        except bzr_errors.NoSuchFile:
            if not create_prefix:
                raise
            transport.create_prefix()
        controldir = self.initialize_on_transport(transport)
        repository = controldir.open_repository()
        repository.lock_write()
        return (repository, controldir, False, CreateRepository(controldir))

    def is_supported(self):
        return True

    def supports_transport(self, transport):
        try:
            external_url = transport.external_url()
        except bzr_errors.InProcessTransport:
            raise bzr_errors.NotBranchError(path=transport.base)
        return (external_url.startswith("http:") or
                external_url.startswith("https:") or
                external_url.startswith("file:"))


class BareLocalGitControlDirFormat(LocalGitControlDirFormat):

    bare = True
    supports_workingtrees = False

    def get_format_description(self):
        return "Local Git Repository (bare)"


class LocalGitDir(GitDir):
    """An adapter to the '.git' dir used by git."""

    def _get_gitrepository_class(self):
        from .repository import LocalGitRepository
        return LocalGitRepository

    def __repr__(self):
        return "<%s at %r>" % (
            self.__class__.__name__, self.root_transport.base)

    _gitrepository_class = property(_get_gitrepository_class)

    @property
    def user_transport(self):
        return self.root_transport

    @property
    def control_transport(self):
        return self.transport

    def __init__(self, transport, gitrepo, format):
        self._format = format
        self.root_transport = transport
        self._mode_check_done = False
        self._git = gitrepo
        if gitrepo.bare:
            self.transport = transport
        else:
            self.transport = transport.clone('.git')
        self._mode_check_done = None

    def is_control_filename(self, filename):
        return (filename == '.git' or
                filename.startswith('.git/') or
                filename.startswith('.git\\'))

    def _get_symref(self, ref):
        from dulwich.repo import SYMREF
        refcontents = self._git.refs.read_ref(ref)
        if refcontents is None: # no such ref
            return None
        if refcontents.startswith(SYMREF):
            return refcontents[len(SYMREF):].rstrip("\n")
        return None

    def set_branch_reference(self, target, name=None):
        if self.control_transport.base != target.controldir.control_transport.base:
            raise bzr_errors.IncompatibleFormat(target._format, self._format)
        ref = self._get_selected_ref(name)
        self._git.refs.set_symbolic_ref(ref, target.ref)

    def get_branch_reference(self, name=None):
        ref = self._get_selected_ref(name)
        target_ref = self._get_symref(ref)
        if target_ref is not None:
            return urlutils.join_segment_parameters(
                self.user_url.rstrip("/"), {"ref": urllib.quote(target_ref, '')})
        return None

    def find_branch_format(self, name=None):
        from .branch import (
            GitBranchFormat,
            GitSymrefBranchFormat,
            )
        ref = self._get_selected_ref(name)
        if self._get_symref(ref) is not None:
            return GitSymrefBranchFormat()
        else:
            return GitBranchFormat()

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

    def open_branch(self, name=None, unsupported=False, ignore_fallbacks=None,
            ref=None, possible_transports=None):
        """'create' a branch for this dir."""
        repo = self.open_repository()
        from .branch import LocalGitBranch
        ref = self._get_selected_ref(name, ref)
        ref_chain, sha = self._git.refs.follow(ref)
        if sha is None:
            raise bzr_errors.NotBranchError(self.root_transport.base,
                    controldir=self)
        return LocalGitBranch(self, repo, ref)

    def destroy_branch(self, name=None):
        refname = self._get_selected_ref(name)
        try:
            del self._git.refs[refname]
        except KeyError:
            raise bzr_errors.NotBranchError(self.root_transport.base,
                    controldir=self)

    def destroy_repository(self):
        raise bzr_errors.UnsupportedOperation(self.destroy_repository, self)

    def destroy_workingtree(self):
        wt = self.open_workingtree(recommend_upgrade=False)
        repository = wt.branch.repository
        empty = repository.revision_tree(_mod_revision.NULL_REVISION)
        # We ignore the conflicts returned by wt.revert since we're about to
        # delete the wt metadata anyway, all that should be left here are
        # detritus. But see bug #634470 about subtree .bzr dirs.
        conflicts = wt.revert(old_tree=empty)
        self.destroy_workingtree_metadata()

    def destroy_workingtree_metadata(self):
        self.transport.delete('index')

    def needs_format_conversion(self, format=None):
        return not isinstance(self._format, format.__class__)

    def list_branches(self):
        return self.get_branches().values()

    def get_branches(self):
        from .refs import ref_to_branch_name
        ret = {}
        for ref in self._git.refs.keys():
            try:
                branch_name = ref_to_branch_name(ref)
            except ValueError:
                continue
            except UnicodeDecodeError:
                trace.warning("Ignoring branch %r with unicode error ref", ref)
                continue
            ret[branch_name] = self.open_branch(ref=ref)
        return ret

    def open_repository(self):
        """'open' a repository for this dir."""
        return self._gitrepository_class(self)

    def open_workingtree(self, recommend_upgrade=True, unsupported=False):
        if not self._git.bare:
            from dulwich.errors import NoIndexPresent
            repo = self.open_repository()
            try:
                index = repo._git.open_index()
            except NoIndexPresent:
                pass
            else:
                from .workingtree import GitWorkingTree
                try:
                    branch = self.open_branch()
                except bzr_errors.NotBranchError:
                    pass
                else:
                    return GitWorkingTree(self, repo, branch, index)
        loc = urlutils.unescape_for_display(self.root_transport.base, 'ascii')
        raise bzr_errors.NoWorkingTree(loc)

    def create_repository(self, shared=False):
        from .repository import GitRepositoryFormat
        if shared:
            raise bzr_errors.IncompatibleFormat(GitRepositoryFormat(), self._format)
        return self.open_repository()

    def create_branch(self, name=None, repository=None,
                      append_revisions_only=None, ref=None):
        refname = self._get_selected_ref(name, ref)
        from dulwich.protocol import ZERO_SHA
        if refname in self._git.refs:
            raise bzr_errors.AlreadyBranchError(self.user_url)
        self._git.refs[refname] = ZERO_SHA
        branch = self.open_branch(name)
        if append_revisions_only:
            branch.set_append_revisions_only(append_revisions_only)
        return branch

    def backup_bzrdir(self):
        if not self._git.bare:
            self.root_transport.copy_tree(".git", ".git.backup")
            return (self.root_transport.abspath(".git"),
                    self.root_transport.abspath(".git.backup"))
        else:
            basename = urlutils.basename(self.root_transport.base)
            parent = self.root_transport.clone('..')
            parent.copy_tree(basename, basename + ".backup")

    def create_workingtree(self, revision_id=None, from_branch=None,
        accelerator_tree=None, hardlink=False):
        if self._git.bare:
            raise bzr_errors.UnsupportedOperation(self.create_workingtree, self)
        from dulwich.index import write_index
        from dulwich.pack import SHA1Writer
        f = open(self.transport.local_abspath("index"), 'w+')
        try:
            f = SHA1Writer(f)
            write_index(f, [])
        finally:
            f.close()
        return self.open_workingtree()

    def _find_or_create_repository(self, force_new_repo=None):
        return self.create_repository(shared=False)

    def _find_creation_modes(self):
        """Determine the appropriate modes for files and directories.

        They're always set to be consistent with the base directory,
        assuming that this transport allows setting modes.
        """
        # TODO: Do we need or want an option (maybe a config setting) to turn
        # this off or override it for particular locations? -- mbp 20080512
        if self._mode_check_done:
            return
        self._mode_check_done = True
        try:
            st = self.transport.stat('.')
        except bzr_errors.TransportNotPossible:
            self._dir_mode = None
            self._file_mode = None
        else:
            # Check the directory mode, but also make sure the created
            # directories and files are read-write for this user. This is
            # mostly a workaround for filesystems which lie about being able to
            # write to a directory (cygwin & win32)
            if (st.st_mode & 07777 == 00000):
                # FTP allows stat but does not return dir/file modes
                self._dir_mode = None
                self._file_mode = None
            else:
                self._dir_mode = (st.st_mode & 07777) | 00700
                # Remove the sticky and execute bits for files
                self._file_mode = self._dir_mode & ~07111

    def _get_file_mode(self):
        """Return Unix mode for newly created files, or None.
        """
        if not self._mode_check_done:
            self._find_creation_modes()
        return self._file_mode

    def _get_dir_mode(self):
        """Return Unix mode for newly created directories, or None.
        """
        if not self._mode_check_done:
            self._find_creation_modes()
        return self._dir_mode

    def get_refs_container(self):
        return self._git.refs

    def get_peeled(self, ref):
        return self._git.get_peeled(ref)
