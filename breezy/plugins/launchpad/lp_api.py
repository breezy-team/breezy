# Copyright (C) 2009-2012 Canonical Ltd
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

"""Tools for dealing with the Launchpad API."""

# Importing this module will be expensive, since it imports launchpadlib and
# its dependencies. However, our plan is to only load this module when it is
# needed by a command that uses it.

import re

from ... import bedding, branch, errors, osutils, trace
from ...i18n import gettext


class LaunchpadlibMissing(errors.DependencyNotPresent):
    """Exception raised when launchpadlib is not available.

    This exception is raised when the launchpadlib library is not installed
    but is required for Launchpad API operations.
    """

    _fmt = (
        "launchpadlib is required for Launchpad API access. "
        "Please install the launchpadlib package."
    )

    def __init__(self, e):
        """Initialize the LaunchpadlibMissing exception.

        Args:
            e: The original exception that caused this dependency error.
        """
        super().__init__("launchpadlib", e)


try:
    import launchpadlib
except ModuleNotFoundError as e:
    raise LaunchpadlibMissing(e) from e

from launchpadlib.credentials import AccessToken, Credentials, CredentialStore
from launchpadlib.launchpad import Launchpad

# Declare the minimum version of launchpadlib that we need in order to work.
MINIMUM_LAUNCHPADLIB_VERSION = (1, 6, 3)


def get_cache_directory():
    """Return the directory to cache launchpadlib objects in."""
    return osutils.pathjoin(bedding.cache_dir(), "launchpad")


def parse_launchpadlib_version(version_number):
    """Parse a version number of the style used by launchpadlib."""
    return tuple(map(int, version_number.split(".")))


def check_launchpadlib_compatibility():
    """Raise an error if launchpadlib has the wrong version number."""
    installed_version = parse_launchpadlib_version(launchpadlib.__version__)
    if installed_version < MINIMUM_LAUNCHPADLIB_VERSION:
        raise errors.DependencyNotPresent(
            "launchpadlib",
            f"At least launchpadlib {MINIMUM_LAUNCHPADLIB_VERSION} is required, but installed version is {installed_version}",
        )


class NoLaunchpadBranch(errors.BzrError):
    """Exception raised when no Launchpad branch can be found for a given branch.

    This exception is raised when attempting to find a Launchpad branch
    corresponding to a local or remote branch, but no such branch exists
    on Launchpad.
    """

    _fmt = 'No launchpad branch could be found for branch "%(url)s".'

    def __init__(self, branch):
        """Initialize the NoLaunchpadBranch exception.

        Args:
            branch: The branch object for which no Launchpad branch was found.
        """
        errors.BzrError.__init__(self, branch=branch, url=branch.base)


def get_auth_engine(base_url):
    """Get the authorization engine for Launchpad API access.

    Args:
        base_url: The base URL for the Launchpad service.

    Returns:
        Authorization engine instance for authenticating with Launchpad.
    """
    return Launchpad.authorization_engine_factory(base_url, "breezy")


def get_credential_store():
    """Get the credential store for Launchpad API credentials.

    Returns:
        BreezyCredentialStore: A credential store instance for managing
            Launchpad API credentials within Breezy.
    """
    return BreezyCredentialStore()
    # return Launchpad.credential_store_factory()


class BreezyCredentialStore(CredentialStore):
    """Implementation of the launchpadlib CredentialStore API for Breezy."""

    def __init__(self, credential_save_failed=None):
        """Initialize the BreezyCredentialStore.

        Args:
            credential_save_failed: Optional callback function to handle
                credential save failures. Defaults to None.
        """
        super().__init__(credential_save_failed)
        from ...config import AuthenticationConfig

        self.auth_config = AuthenticationConfig()

    def do_save(self, credentials, unique_key):
        """Store newly-authorized credentials in the keyring."""
        self.auth_config._set_option(
            unique_key, "consumer_key", credentials.consumer.key
        )
        self.auth_config._set_option(
            unique_key, "consumer_secret", credentials.consumer.secret
        )
        self.auth_config._set_option(
            unique_key, "access_token", credentials.access_token.key
        )
        self.auth_config._set_option(
            unique_key, "access_secret", credentials.access_token.secret
        )

    def do_load(self, unique_key):
        """Retrieve credentials from the keyring."""
        auth_def = self.auth_config._get_config().get(unique_key)
        if auth_def and auth_def.get("access_secret"):
            access_token = AccessToken(
                auth_def.get("access_token"), auth_def.get("access_secret")
            )
            return Credentials(
                consumer_name=auth_def.get("consumer_key"),
                consumer_secret=auth_def.get("consumer_secret"),
                access_token=access_token,
                application_name="Breezy",
            )
        return None


def connect_launchpad(
    base_url, timeout=None, proxy_info=None, version=Launchpad.DEFAULT_VERSION
):
    """Log in to the Launchpad API.

    :return: The root `Launchpad` object from launchpadlib.
    """
    if proxy_info is None:
        import httplib2

        proxy_info = httplib2.proxy_info_from_environment("https")
    try:
        cache_directory = get_cache_directory()
    except OSError:
        cache_directory = None
    credential_store = get_credential_store()
    authorization_engine = get_auth_engine(base_url)
    from .account import get_lp_login

    lp_user = get_lp_login()
    if lp_user is None:
        trace.mutter("Accessing launchpad API anonymously, since no username is set.")
        return Launchpad.login_anonymously(
            consumer_name="breezy",
            service_root=base_url,
            launchpadlib_dir=cache_directory,
            timeout=timeout,
            proxy_info=proxy_info,
            version=version,
        )
    else:
        return Launchpad.login_with(
            application_name="breezy",
            service_root=base_url,
            launchpadlib_dir=cache_directory,
            timeout=timeout,
            credential_store=credential_store,
            authorization_engine=authorization_engine,
            proxy_info=proxy_info,
            version=version,
        )


class LaunchpadBranch:
    """Provide bzr and lp API access to a Launchpad branch."""

    def __init__(self, lp_branch, bzr_url, bzr_branch=None, check_update=True):
        """Constructor.

        :param lp_branch: The Launchpad branch.
        :param bzr_url: The URL of the Bazaar branch.
        :param bzr_branch: An instance of the Bazaar branch.
        """
        self.bzr_url = bzr_url
        self._bzr = bzr_branch
        self._push_bzr = None
        self._check_update = check_update
        self.lp = lp_branch

    @property
    def bzr(self):
        """Return the bzr branch for this branch."""
        if self._bzr is None:
            self._bzr = branch.Branch.open(self.bzr_url)
        return self._bzr

    @property
    def push_bzr(self):
        """Return the push branch for this branch."""
        if self._push_bzr is None:
            self._push_bzr = branch.Branch.open(self.lp.bzr_identity)
        return self._push_bzr

    @staticmethod
    def plausible_launchpad_url(url):
        """Is 'url' something that could conceivably be pushed to LP?

        :param url: A URL that may refer to a Launchpad branch.
        :return: A boolean.
        """
        if url is None:
            return False
        if url.startswith("lp:"):
            return True
        regex = re.compile("([a-z]*\\+)*(bzr\\+ssh|http)://bazaar.*.launchpad.net")
        return bool(regex.match(url))

    def get_target(self):
        """Return the 'LaunchpadBranch' for the target of this one."""
        lp_branch = self.lp
        if lp_branch.project is not None:
            dev_focus = lp_branch.project.development_focus
            if dev_focus is None:
                raise errors.BzrError(
                    gettext("%s has no development focus.") % lp_branch.bzr_identity
                )
            target = dev_focus.branch
            if target is None:
                raise errors.BzrError(
                    gettext("development focus %s has no branch.") % dev_focus
                )
        elif lp_branch.sourcepackage is not None:
            target = lp_branch.sourcepackage.getBranch(pocket="Release")
            if target is None:
                raise errors.BzrError(
                    gettext("source package %s has no branch.")
                    % lp_branch.sourcepackage
                )
        else:
            raise errors.BzrError(
                gettext("%s has no associated product or source package.")
                % lp_branch.bzr_identity
            )
        return LaunchpadBranch(target, target.bzr_identity)

    def update_lp(self):
        """Update the Launchpad copy of this branch."""
        if not self._check_update:
            return
        with self.bzr.lock_read():
            if self.lp.last_scanned_id is not None:
                if self.bzr.last_revision() == self.lp.last_scanned_id:
                    trace.note(
                        gettext("%s is already up-to-date.") % self.lp.bzr_identity
                    )
                    return
                graph = self.bzr.repository.get_graph()
                if not graph.is_ancestor(
                    self.lp.last_scanned_id.encode("utf-8"), self.bzr.last_revision()
                ):
                    raise errors.DivergedBranches(self.bzr, self.push_bzr)
                trace.note(gettext("Pushing to %s") % self.lp.bzr_identity)
            self.bzr.push(self.push_bzr)

    def find_lca_tree(self, other):
        """Find the revision tree for the LCA of this branch and other.

        :param other: Another LaunchpadBranch
        :return: The RevisionTree of the LCA of this branch and other.
        """
        graph = self.bzr.repository.get_graph(other.bzr.repository)
        lca = graph.find_unique_lca(self.bzr.last_revision(), other.bzr.last_revision())
        return self.bzr.repository.revision_tree(lca)
