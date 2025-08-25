# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2006-2009 Canonical Ltd

# Authors: Robert Collins <robert.collins@canonical.com>
#          Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""A GIT branch and repository format implementation for bzr."""

import os
import sys

dulwich_minimum_version = (0, 19, 11)

from .. import __version__ as breezy_version
from .. import errors as brz_errors
from .. import trace, urlutils
from ..commands import plugin_cmds
from ..controldir import ControlDirFormat, Prober, format_registry
from ..controldir import network_format_registry as controldir_network_format_registry
from ..transport import (
    register_lazy_transport,
    register_transport_proto,
    transport_server_registry,
)

if getattr(sys, "frozen", None):
    # allow import additional libs from ./_lib for bzr.exe only
    sys.path.append(os.path.normpath(os.path.join(os.path.dirname(__file__), "_lib")))


def import_dulwich():
    """Import dulwich and verify it meets minimum version requirements.

    Raises:
        DependencyNotPresent: If dulwich is not installed or version is too old.
    """
    try:
        from dulwich import __version__ as dulwich_version
    except ModuleNotFoundError as e:
        raise brz_errors.DependencyNotPresent(
            "dulwich", "bzr-git: Please install dulwich, https://www.dulwich.io/"
        ) from e
    else:
        if dulwich_version < dulwich_minimum_version:
            raise brz_errors.DependencyNotPresent(
                "dulwich",
                "bzr-git: Dulwich is too old; at least %d.%d.%d is required"
                % dulwich_minimum_version,
            )


_versions_checked = False


def lazy_check_versions():
    """Lazily check dulwich version requirements.

    This function ensures dulwich is imported and verified only once,
    when first needed.
    """
    global _versions_checked
    if _versions_checked:
        return
    import_dulwich()
    _versions_checked = True


format_registry.register_lazy(
    "git",
    __name__ + ".dir",
    "LocalGitControlDirFormat",
    help="GIT repository.",
    native=False,
    experimental=False,
)

format_registry.register_lazy(
    "git-bare",
    __name__ + ".dir",
    "BareLocalGitControlDirFormat",
    help="Bare GIT repository (no working tree).",
    native=False,
    experimental=False,
)

from ..revisionspec import RevisionSpec_dwim, revspec_registry

revspec_registry.register_lazy("git:", __name__ + ".revspec", "RevisionSpec_git")
RevisionSpec_dwim.append_possible_lazy_revspec(
    __name__ + ".revspec", "RevisionSpec_git"
)


class LocalGitProber(Prober):
    """Prober for local Git repositories.

    This prober detects Git repositories on the local filesystem,
    supporting both regular repositories with working trees and
    bare repositories.
    """

    @classmethod
    def priority(klass, transport):
        """Return the priority for this prober.

        Args:
            transport: The transport to probe.

        Returns:
            int: Priority value (10 for local Git repositories).
        """
        return 10

    def probe_transport(self, transport):
        """Probe a transport to detect if it contains a Git repository.

        Args:
            transport: The transport to probe.

        Returns:
            LocalGitControlDirFormat or BareLocalGitControlDirFormat if a Git
            repository is found.

        Raises:
            NotBranchError: If no Git repository is found.
        """
        try:
            external_url = transport.external_url()
        except brz_errors.InProcessTransport as err:
            raise brz_errors.NotBranchError(path=transport.base) from err
        if external_url.startswith("http:") or external_url.startswith("https:"):
            # Already handled by RemoteGitProber
            raise brz_errors.NotBranchError(path=transport.base)
        if urlutils.split(transport.base)[1] == ".git":
            raise brz_errors.NotBranchError(path=transport.base)
        if not transport.has_any(["objects", ".git/objects", ".git"]):
            raise brz_errors.NotBranchError(path=transport.base)
        lazy_check_versions()
        from .dir import BareLocalGitControlDirFormat, LocalGitControlDirFormat

        if transport.has_any([".git/objects", ".git"]):
            return LocalGitControlDirFormat()
        if transport.has("info") and transport.has("objects"):
            return BareLocalGitControlDirFormat()
        raise brz_errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Return the list of control dir formats known by this prober.

        Returns:
            list: List of known Git control directory formats.
        """
        from .dir import BareLocalGitControlDirFormat, LocalGitControlDirFormat

        return [BareLocalGitControlDirFormat(), LocalGitControlDirFormat()]


def user_agent_for_github():
    """Return a User-Agent string suitable for GitHub.

    GitHub requires a Git-compatible User-Agent string.
    See: https://github.com/dulwich/dulwich/issues/562

    Returns:
        str: User-Agent string in the format "git/Breezy/{version}".
    """
    # GitHub requires we lie. https://github.com/dulwich/dulwich/issues/562
    return f"git/Breezy/{breezy_version}"


def is_github_url(url):
    """Check if a URL points to GitHub or similar services.

    Args:
        url: The URL to check.

    Returns:
        bool: True if the URL is for github.com or gopkg.in.
    """
    (scheme, user, password, host, port, path) = urlutils.parse_url(url)
    return host in ("github.com", "gopkg.in")


class RemoteGitProber(Prober):
    """Prober for remote Git repositories.

    This prober detects Git repositories accessed over network protocols
    including HTTP/HTTPS and the Git smart protocol.
    """

    @classmethod
    def priority(klass, transport):
        """Return the priority for this prober.

        Uses a heuristic based on whether 'git' appears in the URL.

        Args:
            transport: The transport to probe.

        Returns:
            int: Priority value (-15 if URL contains 'git', -10 otherwise).
        """
        # This is a surprisingly good heuristic to determine whether this
        # prober is more likely to succeed than the Bazaar one.
        if "git" in transport.base:
            return -15
        return -10

    def probe_http_transport(self, transport):
        """Probe an HTTP transport to detect if it contains a Git repository.

        This function is optimized to avoid importing heavy dependencies unless
        necessary, as it's called for all HTTP repositories.

        Args:
            transport: The HTTP transport to probe.

        Returns:
            RemoteGitControlDirFormat or BareLocalGitControlDirFormat if a Git
            repository is found.

        Raises:
            NotBranchError: If no Git repository is found.
        """
        # This function intentionally doesn't use any of the support code under
        # breezy.git, since it's called for every repository that's
        # accessed over HTTP, whether it's Git, Bzr or something else.
        # Importing Dulwich and the other support code adds unnecessray slowdowns.
        base_url = urlutils.strip_segment_parameters(transport.external_url())
        url = urlutils.URL.from_string(base_url)
        url.user = url.quoted_user = None
        url.password = url.quoted_password = None
        url = urlutils.join(str(url), "info/refs") + "?service=git-upload-pack"
        headers = {
            "Content-Type": "application/x-git-upload-pack-request",
            "Accept": "application/x-git-upload-pack-result",
        }
        if is_github_url(url):
            # GitHub requires we lie.
            # https://github.com/dulwich/dulwich/issues/562
            headers["User-Agent"] = user_agent_for_github()
        resp = transport.request("GET", url, headers=headers)
        if resp.status in (404, 405):
            raise brz_errors.NotBranchError(transport.base)
        elif resp.status == 400 and resp.reason == "no such method: info":
            # hgweb :(
            raise brz_errors.NotBranchError(transport.base)
        elif resp.status != 200:
            raise brz_errors.UnexpectedHttpStatus(
                url, resp.status, headers=resp.getheaders()
            )

        ct = resp.getheader("Content-Type")
        if ct and ct.startswith("application/x-git"):
            from .remote import RemoteGitControlDirFormat

            return RemoteGitControlDirFormat()
        elif not ct:
            from .dir import BareLocalGitControlDirFormat

            ret = BareLocalGitControlDirFormat()
            ret._refs_text = resp.read()
            return ret
        raise brz_errors.NotBranchError(transport.base)

    def probe_transport(self, transport):
        """Probe a transport to detect if it contains a Git repository.

        Args:
            transport: The transport to probe.

        Returns:
            RemoteGitControlDirFormat if a Git repository is found.

        Raises:
            NotBranchError: If no Git repository is found.
        """
        try:
            external_url = transport.external_url()
        except brz_errors.InProcessTransport as err:
            raise brz_errors.NotBranchError(path=transport.base) from err

        if external_url.startswith("http:") or external_url.startswith("https:"):
            return self.probe_http_transport(transport)

        if not external_url.startswith("git://") and not external_url.startswith(
            "git+"
        ):
            raise brz_errors.NotBranchError(transport.base)

        # little ugly, but works
        from .remote import GitSmartTransport, RemoteGitControlDirFormat

        if isinstance(transport, GitSmartTransport):
            return RemoteGitControlDirFormat()
        raise brz_errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Return the list of control dir formats known by this prober.

        Returns:
            list: List containing RemoteGitControlDirFormat.
        """
        from .remote import RemoteGitControlDirFormat

        return [RemoteGitControlDirFormat()]


ControlDirFormat.register_prober(LocalGitProber)
ControlDirFormat.register_prober(RemoteGitProber)

register_transport_proto("git://", help="Access using the Git smart server protocol.")
register_transport_proto(
    "git+ssh://", help="Access using the Git smart server protocol over SSH."
)

register_lazy_transport("git://", __name__ + ".remote", "TCPGitSmartTransport")
register_lazy_transport("git+ssh://", __name__ + ".remote", "SSHGitSmartTransport")


plugin_cmds.register_lazy("cmd_git_import", [], __name__ + ".commands")
plugin_cmds.register_lazy(
    "cmd_git_object", ["git-objects", "git-cat"], __name__ + ".commands"
)
plugin_cmds.register_lazy("cmd_git_refs", [], __name__ + ".commands")
plugin_cmds.register_lazy("cmd_git_apply", [], __name__ + ".commands")
plugin_cmds.register_lazy(
    "cmd_git_push_pristine_tar_deltas",
    ["git-push-pristine-tar", "git-push-pristine"],
    __name__ + ".commands",
)


def extract_git_foreign_revid(rev):
    """Extract the Git commit ID from a revision.

    Args:
        rev: A revision object that may contain a Git foreign revision ID.

    Returns:
        str: The Git commit SHA.

    Raises:
        InvalidRevisionId: If the revision is not a Git revision.
    """
    try:
        foreign_revid = rev.foreign_revid
    except AttributeError:
        from .mapping import mapping_registry

        foreign_revid, mapping = mapping_registry.parse_revision_id(rev.revision_id)
        return foreign_revid
    else:
        from .mapping import foreign_vcs_git

        if rev.mapping.vcs == foreign_vcs_git:
            return foreign_revid
        else:
            raise brz_errors.InvalidRevisionId(rev.revision_id, None)


def update_stanza(rev, stanza):
    """Update a Rio stanza with Git commit information.

    This is a hook function that adds Git commit SHA to version info stanzas.

    Args:
        rev: The revision to extract Git information from.
        stanza: The Rio stanza to update.
    """
    try:
        git_commit = extract_git_foreign_revid(rev)
    except brz_errors.InvalidRevisionId:
        pass
    else:
        stanza.add("git-commit", git_commit)


from ..hooks import install_lazy_named_hook

install_lazy_named_hook(
    "breezy.version_info_formats.format_rio",
    "RioVersionInfoBuilder.hooks",
    "revision",
    update_stanza,
    "git commits",
)


def rewrite_instead_of(location, purpose):
    """Rewrite a URL using Git's insteadOf/pushInsteadOf configuration.

    This implements Git's URL rewriting feature for compatibility.

    Args:
        location: The original URL to potentially rewrite.
        purpose: The purpose of the URL access ('read' or other for push).

    Returns:
        str: The rewritten URL, or the original if no rewrite rules apply.
    """
    from dulwich.config import StackedConfig, iter_instead_of

    config = StackedConfig.default()

    push = purpose != "read"

    longest_needle = ""
    updated_url = location
    for needle, replacement in iter_instead_of(config, push):
        if not location.startswith(needle):
            continue
        if len(longest_needle) < len(needle):
            longest_needle = needle
            if longest_needle == "lp:":
                # Leave the lp: prefix to the launchpad plugin, if loaded
                import breezy.plugins

                if hasattr(breezy.plugins, "launchpad"):
                    trace.warning(
                        "Ignoring insteadOf lp: in git config, because the Launchpad plugin is loaded."
                    )
                    continue
            updated_url = replacement + location[len(needle) :]
    return updated_url


from ..location import hooks as location_hooks

location_hooks.install_named_hook(
    "rewrite_location", rewrite_instead_of, "apply Git insteadOf / pushInsteadOf"
)

transport_server_registry.register_lazy(
    "git",
    __name__ + ".server",
    "serve_git",
    "Git Smart server protocol over TCP. (default port: 9418)",
)

transport_server_registry.register_lazy(
    "git-receive-pack",
    __name__ + ".server",
    "serve_git_receive_pack",
    help="Git Smart server receive pack command. (inetd mode only)",
)
transport_server_registry.register_lazy(
    "git-upload-pack",
    __name__ + "git.server",
    "serve_git_upload_pack",
    help="Git Smart server upload pack command. (inetd mode only)",
)

from ..repository import format_registry as repository_format_registry
from ..repository import network_format_registry as repository_network_format_registry

repository_network_format_registry.register_lazy(
    b"git", __name__ + ".repository", "GitRepositoryFormat"
)

register_extra_lazy_repository_format = repository_format_registry.register_extra_lazy
register_extra_lazy_repository_format(__name__ + ".repository", "GitRepositoryFormat")

from ..branch import network_format_registry as branch_network_format_registry

branch_network_format_registry.register_lazy(
    b"git", __name__ + ".branch", "LocalGitBranchFormat"
)


from ..branch import format_registry as branch_format_registry

branch_format_registry.register_extra_lazy(
    __name__ + ".branch",
    "LocalGitBranchFormat",
)
branch_format_registry.register_extra_lazy(
    __name__ + ".remote",
    "RemoteGitBranchFormat",
)


from ..workingtree import format_registry as workingtree_format_registry

workingtree_format_registry.register_extra_lazy(
    __name__ + ".workingtree",
    "GitWorkingTreeFormat",
)

controldir_network_format_registry.register_lazy(
    b"git", __name__ + ".dir", "GitControlDirFormat"
)


from ..diff import format_registry as diff_format_registry

diff_format_registry.register_lazy(
    "git", __name__ + ".send", "GitDiffTree", "Git am-style diff format"
)

from ..send import format_registry as send_format_registry

send_format_registry.register_lazy(
    "git", __name__ + ".send", "send_git", "Git am-style diff format"
)

from ..directory_service import directories

directories.register_lazy(
    "github:", __name__ + ".directory", "GitHubDirectory", "GitHub directory."
)
directories.register_lazy(
    "git@github.com:", __name__ + ".directory", "GitHubDirectory", "GitHub directory."
)

from ..help_topics import topic_registry

topic_registry.register_lazy(
    "git", __name__ + ".help", "help_git", "Using Bazaar with Git"
)

from ..foreign import foreign_vcs_registry

foreign_vcs_registry.register_lazy(
    "git", __name__ + ".mapping", "foreign_vcs_git", "Stupid content tracker"
)


def update_git_cache(repository, revid):
    """Update the git cache after a local commit.

    This function updates the Git object cache for Bazaar repositories
    that have an associated Git cache, ensuring the cache stays in sync
    with new commits.

    Args:
        repository: The repository to update.
        revid: The revision ID of the newly committed revision.
    """
    if getattr(repository, "_git", None) is not None:
        return  # No need to update cache for git repositories

    if not repository.control_transport.has("git"):
        return  # No existing cache, don't bother updating
    try:
        lazy_check_versions()
    except brz_errors.DependencyNotPresent as e:
        # dulwich is probably missing. silently ignore
        trace.mutter("not updating git map for %r: %s", repository, e)

    from .object_store import BazaarObjectStore

    store = BazaarObjectStore(repository)
    with store.lock_write():
        try:
            parent_revisions = set(repository.get_parent_map([revid])[revid])
        except KeyError:
            # Isn't this a bit odd - how can a revision that was just committed
            # be missing?
            return
        missing_revisions = store._missing_revisions(parent_revisions)
        if not missing_revisions:
            store._cache.idmap.start_write_group()
            try:
                # Only update if the cache was up to date previously
                store._update_sha_map_revision(revid)
            except BaseException:
                store._cache.idmap.abort_write_group()
                raise
            else:
                store._cache.idmap.commit_write_group()


def post_commit_update_cache(
    local_branch, master_branch, old_revno, old_revid, new_revno, new_revid
):
    """Post-commit hook to update Git caches.

    This hook ensures Git caches are updated after commits in both
    local and master branches.

    Args:
        local_branch: The local branch (may be None).
        master_branch: The master branch.
        old_revno: The old revision number.
        old_revid: The old revision ID.
        new_revno: The new revision number.
        new_revid: The new revision ID.
    """
    if local_branch is not None:
        update_git_cache(local_branch.repository, new_revid)
    update_git_cache(master_branch.repository, new_revid)


def loggerhead_git_hook(branch_app, environ):
    """Hook for Loggerhead to provide Git HTTP protocol support.

    Args:
        branch_app: The Loggerhead branch application.
        environ: The WSGI environment dictionary.

    Returns:
        Response object if Git HTTP is enabled and applicable, None otherwise.
    """
    branch = branch_app.branch
    config_stack = branch.get_config_stack()
    if not config_stack.get("git.http"):
        return None
    from .server import git_http_hook

    return git_http_hook(branch, environ["REQUEST_METHOD"], environ["PATH_INFO"])


install_lazy_named_hook(
    "breezy.branch",
    "Branch.hooks",
    "post_commit",
    post_commit_update_cache,
    "git cache",
)
install_lazy_named_hook(
    "breezy.plugins.loggerhead.apps.branch",
    "BranchWSGIApp.hooks",
    "controller",
    loggerhead_git_hook,
    "git support",
)


from ..config import Option, bool_from_store, option_registry

option_registry.register(
    Option(
        "git.http",
        default=None,
        from_unicode=bool_from_store,
        invalid="warning",
        help="""\
Allow fetching of Git packs over HTTP.

This enables support for fetching Git packs over HTTP in Loggerhead.
""",
    )
)


def test_suite():
    """Return the test suite for the Git plugin.

    Returns:
        unittest.TestSuite: The complete test suite for this module.
    """
    from . import tests

    return tests.test_suite()
