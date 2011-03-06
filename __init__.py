# Copyright (C) 2006-2009 Canonical Ltd

# Authors: Robert Collins <robert.collins@canonical.com>
#          Jelmer Vernooij <jelmer@samba.org>
#          John Carr <john.carr@unrouted.co.uk>
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


"""A GIT branch and repository format implementation for bzr."""

import os
import sys

import bzrlib
import bzrlib.api

from info import (
    bzr_compatible_versions,
    bzr_plugin_version as version_info,
    dulwich_minimum_version,
    )

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string

bzrlib.api.require_any_api(bzrlib, bzr_compatible_versions)


from bzrlib import (
    errors as bzr_errors,
    )

from bzrlib.controldir import (
    ControlDirFormat,
    Prober,
    format_registry,
    )

from bzrlib.foreign import (
    foreign_vcs_registry,
    )
from bzrlib.help_topics import (
    topic_registry,
    )
from bzrlib.lockable_files import (
    TransportLock,
    )
from bzrlib.transport import (
    register_lazy_transport,
    register_transport_proto,
    )
from bzrlib.commands import (
    plugin_cmds,
    )
from bzrlib.send import (
    format_registry as send_format_registry,
    )


if getattr(sys, "frozen", None):
    # allow import additional libs from ./_lib for bzr.exe only
    sys.path.append(os.path.normpath(
        os.path.join(os.path.dirname(__file__), '_lib')))


def import_dulwich():
    try:
        from dulwich import __version__ as dulwich_version
    except ImportError:
        raise bzr_errors.DependencyNotPresent("dulwich",
            "bzr-git: Please install dulwich, https://launchpad.net/dulwich")
    else:
        if dulwich_version < dulwich_minimum_version:
            raise bzr_errors.DependencyNotPresent("dulwich",
                "bzr-git: Dulwich is too old; at least %d.%d.%d is required" %
                    dulwich_minimum_version)


_versions_checked = False
def lazy_check_versions():
    global _versions_checked
    if _versions_checked:
        return
    import_dulwich()
    _versions_checked = True

format_registry.register_lazy('git',
    "bzrlib.plugins.git", "LocalGitControlDirFormat",
    help='GIT repository.', native=False, experimental=False,
    )

format_registry.register_lazy('git-bare',
    "bzrlib.plugins.git", "BareLocalGitControlDirFormat",
    help='Bare GIT repository (no working tree).', native=False,
    experimental=False,
    )

from bzrlib.revisionspec import revspec_registry
revspec_registry.register_lazy("git:", "bzrlib.plugins.git.revspec",
    "RevisionSpec_git")

from bzrlib.revisionspec import dwim_revspecs, RevisionSpec_dwim
if getattr(RevisionSpec_dwim, "append_possible_lazy_revspec", None):
    RevisionSpec_dwim.append_possible_lazy_revspec(
        "bzrlib.plugins.git.revspec", "RevisionSpec_git")
else: # bzr < 2.4
    from bzrlib.plugins.git.revspec import RevisionSpec_git
    dwim_revspecs.append(RevisionSpec_git)


class GitControlDirFormat(ControlDirFormat):

    _lock_class = TransportLock

    colocated_branches = True
    fixed_components = True

    def __eq__(self, other):
        return type(self) == type(other)

    def is_supported(self):
        return True

    def network_name(self):
        return "git"


class LocalGitProber(Prober):

    def probe_transport(self, transport):
        try:
            if not transport.has_any(['info/refs', '.git/branches',
                                      'branches']):
                raise bzr_errors.NotBranchError(path=transport.base)
        except bzr_errors.NoSuchFile:
            raise bzr_errors.NotBranchError(path=transport.base)
        from bzrlib import urlutils
        if urlutils.split(transport.base)[1] == ".git":
            raise bzr_errors.NotBranchError(path=transport.base)
        lazy_check_versions()
        import dulwich
        from bzrlib.plugins.git.transportgit import TransportRepo
        try:
            gitrepo = TransportRepo(transport)
        except dulwich.errors.NotGitRepository, e:
            raise bzr_errors.NotBranchError(path=transport.base)
        else:
            if gitrepo.bare:
                return BareLocalGitControlDirFormat()
            else:
                return LocalGitControlDirFormat()


class LocalGitControlDirFormat(GitControlDirFormat):
    """The .git directory control format."""

    bare = False

    @classmethod
    def _known_formats(self):
        return set([LocalGitControlDirFormat()])

    @property
    def repository_format(self):
        from bzrlib.plugins.git.repository import GitRepositoryFormat
        return GitRepositoryFormat()

    def get_branch_format(self):
        from bzrlib.plugins.git.branch import GitBranchFormat
        return GitBranchFormat()

    def open(self, transport, _found=None):
        """Open this directory.

        """
        lazy_check_versions()
        from bzrlib.plugins.git.transportgit import TransportRepo
        gitrepo = TransportRepo(transport)
        from bzrlib.plugins.git.dir import LocalGitDir, GitLockableFiles, GitLock
        lockfiles = GitLockableFiles(transport, GitLock())
        return LocalGitDir(transport, lockfiles, gitrepo, self)

    @classmethod
    def probe_transport(klass, transport):
        prober = LocalGitProber()
        return prober.probe_transport(transport)

    def get_format_description(self):
        return "Local Git Repository"

    def initialize_on_transport(self, transport):
        lazy_check_versions()
        from bzrlib.plugins.git.transportgit import TransportRepo
        TransportRepo.init(transport, bare=self.bare)
        return self.open(transport)

    def initialize_on_transport_ex(self, transport, use_existing_dir=False,
        create_prefix=False, force_new_repo=False, stacked_on=None,
        stack_on_pwd=None, repo_format_name=None, make_working_trees=None,
        shared_repo=False, vfs_only=False):
        from bzrlib import trace
        from bzrlib.bzrdir import CreateRepository
        from bzrlib.transport import do_catching_redirections
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


class BareLocalGitControlDirFormat(LocalGitControlDirFormat):

    bare = True
    supports_workingtrees = False

    @classmethod
    def _known_formats(self):
        return set([RemoteGitControlDirFormat()])

    def get_format_description(self):
        return "Local Git Repository (bare)"


class RemoteGitProber(Prober):

    def probe_transport(self, transport):
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]
        if (not url.startswith("git://") and not url.startswith("git+")):
            raise bzr_errors.NotBranchError(transport.base)
        # little ugly, but works
        from bzrlib.plugins.git.remote import GitSmartTransport
        if not isinstance(transport, GitSmartTransport):
            raise bzr_errors.NotBranchError(transport.base)
        return RemoteGitControlDirFormat()



class RemoteGitControlDirFormat(GitControlDirFormat):
    """The .git directory control format."""

    supports_workingtrees = False

    @classmethod
    def _known_formats(self):
        return set([RemoteGitControlDirFormat()])

    def open(self, transport, _found=None):
        """Open this directory.

        """
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]
        if (not url.startswith("git://") and not url.startswith("git+")):
            raise bzr_errors.NotBranchError(transport.base)
        from bzrlib.plugins.git.remote import RemoteGitDir, GitSmartTransport
        if not isinstance(transport, GitSmartTransport):
            raise bzr_errors.NotBranchError(transport.base)
        from bzrlib.plugins.git.dir import GitLockableFiles, GitLock
        lockfiles = GitLockableFiles(transport, GitLock())
        return RemoteGitDir(transport, lockfiles, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        prober = RemoteGitProber()
        return prober.probe_transport(transport)

    def get_format_description(self):
        return "Remote Git Repository"

    def initialize_on_transport(self, transport):
        raise bzr_errors.UninitializableFormat(self)


ControlDirFormat.register_format(LocalGitControlDirFormat())
ControlDirFormat.register_format(BareLocalGitControlDirFormat())
ControlDirFormat.register_format(RemoteGitControlDirFormat())
ControlDirFormat.register_prober(LocalGitProber)
ControlDirFormat.register_prober(RemoteGitProber)

register_transport_proto('git://',
        help="Access using the Git smart server protocol.")
register_transport_proto('git+ssh://',
        help="Access using the Git smart server protocol over SSH.")

register_lazy_transport("git://", 'bzrlib.plugins.git.remote',
                        'TCPGitSmartTransport')
register_lazy_transport("git+ssh://", 'bzrlib.plugins.git.remote',
                        'SSHGitSmartTransport')

foreign_vcs_registry.register_lazy("git",
    "bzrlib.plugins.git.mapping", "foreign_git", "Stupid content tracker")

plugin_cmds.register_lazy("cmd_git_import", [], "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_object", ["git-objects", "git-cat"],
    "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_refs", [], "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_apply", [], "bzrlib.plugins.git.commands")

def update_stanza(rev, stanza):
    mapping = getattr(rev, "mapping", None)
    if mapping is not None and mapping.revid_prefix.startswith("git-"):
        stanza.add("git-commit", rev.foreign_revid)

try:
    from bzrlib.hooks import install_lazy_named_hook
except ImportError: # Compatibility with bzr < 2.4
    from bzrlib.version_info_formats.format_rio import (
        RioVersionInfoBuilder,
        )
    RioVersionInfoBuilder.hooks.install_named_hook('revision', update_stanza, 
        "git commits")
else:
    install_lazy_named_hook("bzrlib.version_info_formats.format_rio",
        "RioVersionInfoBuilder.hooks", "revision", update_stanza,
        "git commits")


from bzrlib.transport import transport_server_registry
transport_server_registry.register_lazy('git',
    'bzrlib.plugins.git.server',
    'serve_git',
    'Git Smart server protocol over TCP. (default port: 9418)')


from bzrlib.repository import (
    format_registry as repository_format_registry,
    network_format_registry as repository_network_format_registry,
    )
repository_network_format_registry.register_lazy('git',
    'bzrlib.plugins.git.repository', 'GitRepositoryFormat')

try:
    register_extra_lazy_repository_format = getattr(repository_format_registry,
        "register_extra_lazy")
except AttributeError: # bzr < 2.4
    pass
else:
    register_extra_lazy_repository_format('bzrlib.plugins.git.repository',
        'GitRepositoryFormat')

try:
    from bzrlib.branch import (
        format_registry as branch_format_registry,
        )
except ImportError: # bzr < 2.4
    pass
else:
    branch_format_registry.register_extra_lazy(
        'bzrlib.plugins.git.branch',
        'GitBranchFormat',
        )

try:
    from bzrlib.workingtree import (
        format_registry as workingtree_format_registry,
        )
except ImportError: # bzr < 2.4
    pass
else:
    workingtree_format_registry.register_extra_lazy(
        'bzrlib.plugins.git.workingtree',
        'GitWorkingTreeFormat',
        )

from bzrlib.controldir import (
    network_format_registry as controldir_network_format_registry,
    )
controldir_network_format_registry.register('git', GitControlDirFormat)

send_format_registry.register_lazy('git', 'bzrlib.plugins.git.send',
                                   'send_git', 'Git am-style diff format')

topic_registry.register_lazy('git',
                             'bzrlib.plugins.git.help',
                             'help_git', 'Using Bazaar with Git')

from bzrlib.diff import format_registry as diff_format_registry
diff_format_registry.register_lazy('git', 'bzrlib.plugins.git.send',
    'GitDiffTree', 'Git am-style diff format')

def test_suite():
    from bzrlib.plugins.git import tests
    return tests.test_suite()
