# Copyright (C) 2006 Canonical Ltd

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

import bzrlib
import bzrlib.api
from bzrlib import bzrdir, errors as bzr_errors
from bzrlib.foreign import foreign_vcs_registry
from bzrlib.lockable_files import TransportLock
from bzrlib.transport import register_lazy_transport
from bzrlib.commands import plugin_cmds
from bzrlib.trace import warning

MINIMUM_DULWICH_VERSION = (0, 1, 0)
COMPATIBLE_BZR_VERSIONS = [(1, 11, 0), (1, 12, 0)]

_versions_checked = False
def lazy_check_versions():
    global _versions_checked
    if _versions_checked:
        return
    _versions_checked = True
    try:
        from dulwich import __version__ as dulwich_version
    except ImportError:
        warning("Please install dulwich, https://launchpad.net/dulwich")
        raise
    else:
        if dulwich_version < MINIMUM_DULWICH_VERSION:
            warning("Dulwich is too old; at least %d.%d.%d is required" % MINIMUM_DULWICH_VERSION)
            raise ImportError

bzrlib.api.require_any_api(bzrlib, COMPATIBLE_BZR_VERSIONS)

bzrdir.format_registry.register_lazy('git', 
    "bzrlib.plugins.git.dir", "LocalGitBzrDirFormat",
    help='GIT repository.', native=False, experimental=True,
    )

try:
    from bzrlib.revisionspec import revspec_registry
    revspec_registry.register_lazy("git:", "bzrlib.plugins.git.revspec", 
        "RevisionSpec_git")
except ImportError:
    lazy_check_versions()
    from bzrlib.revisionspec import SPEC_TYPES
    from bzrlib.plugins.git.revspec import RevisionSpec_git
    SPEC_TYPES.append(RevisionSpec_git)

class GitBzrDirFormat(bzrdir.BzrDirFormat):
    _lock_class = TransportLock

    def is_supported(self):
        return True


class LocalGitBzrDirFormat(GitBzrDirFormat):
    """The .git directory control format."""

    @classmethod
    def _known_formats(self):
        return set([LocalGitBzrDirFormat()])

    def open(self, transport, _found=None):
        """Open this directory.

        """
        import dulwich as git
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]

        try:
            gitrepo = git.repo.Repo(transport.local_abspath("."))
        except bzr_errors.NotLocalUrl:
            raise bzr_errors.NotBranchError(path=transport.base)
        from bzrlib.plugins.git.dir import LocalGitDir, GitLockableFiles, GitLock
        lockfiles = GitLockableFiles(transport, GitLock())
        return LocalGitDir(transport, lockfiles, gitrepo, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        from bzrlib.transport.local import LocalTransport

        if not isinstance(transport, LocalTransport):
            raise bzr_errors.NotBranchError(path=transport.base)

        # This should quickly filter out most things that are not 
        # git repositories, saving us the trouble from loading dulwich.
        if not transport.has(".git") and not transport.has("objects"):
            raise bzr_errors.NotBranchError(path=transport.base)

        import dulwich as git
        format = klass()
        try:
            format.open(transport)
            return format
        except git.errors.NotGitRepository, e:
            raise bzr_errors.NotBranchError(path=transport.base)
        raise bzr_errors.NotBranchError(path=transport.base)

    def get_format_description(self):
        return "Local Git Repository"

    def get_format_string(self):
        return "Local Git Repository"

    def initialize_on_transport(self, transport):
        from bzrlib.transport.local import LocalTransport

        if not isinstance(transport, LocalTransport):
            raise NotImplementedError(self.initialize, 
                "Can't create Git Repositories/branches on "
                "non-local transports")

        from dulwich.repo import Repo
        Repo.create(transport.local_abspath(".")) 
        return self.open(transport)

    def is_supported(self):
        return True


class RemoteGitBzrDirFormat(GitBzrDirFormat):
    """The .git directory control format."""

    @classmethod
    def _known_formats(self):
        return set([RemoteGitBzrDirFormat()])

    def open(self, transport, _found=None):
        """Open this directory.

        """
        from bzrlib.plugins.git.remote import RemoteGitDir, GitSmartTransport
        if not isinstance(transport, GitSmartTransport):
            raise bzr_errors.NotBranchError(transport.base)
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]

        from bzrlib.plugins.git.dir import GitLockableFiles, GitLock
        lockfiles = GitLockableFiles(transport, GitLock())
        return RemoteGitDir(transport, lockfiles, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        # little ugly, but works
        format = klass()
        from bzrlib.plugins.git.remote import GitSmartTransport
        if not isinstance(transport, GitSmartTransport):
            raise bzr_errors.NotBranchError(transport.base)
        # The only way to know a path exists and contains a valid repository 
        # is to do a request against it:
        try:
            transport.fetch_pack(lambda x: [], None, lambda x: None, 
                                 lambda x: mutter("git: %s" % x))
        except errors.git_errors.GitProtocolError:
            raise bzr_errors.NotBranchError(path=transport.base)
        else:
            return format
        raise bzr_errors.NotBranchError(path=transport.base)

    def get_format_description(self):
        return "Remote Git Repository"

    def get_format_string(self):
        return "Remote Git Repository"

    def initialize_on_transport(self, transport):
        raise bzr_errors.UninitializableFormat(self)


bzrdir.BzrDirFormat.register_control_format(LocalGitBzrDirFormat)
bzrdir.BzrDirFormat.register_control_format(RemoteGitBzrDirFormat)

register_lazy_transport("git://", 'bzrlib.plugins.git.remote',
                        'GitSmartTransport')

foreign_vcs_registry.register_lazy("git", 
                        "bzrlib.plugins.git.mapping", 
                        "foreign_git",
                        "Stupid content tracker")

plugin_cmds.register_lazy("cmd_git_serve", [], "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_import", [], "bzrlib.plugins.git.commands")

def test_suite():
    from bzrlib.plugins.git import tests
    return tests.test_suite()
