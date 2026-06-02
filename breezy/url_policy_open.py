# Copyright (C) 2011 Canonical Ltd
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

"""Branch opening with URL-based restrictions."""

import threading

from . import errors, trace, urlutils
from .branch import Branch
from .controldir import ControlDirFormat
from .transport import do_catching_redirections, get_transport


class BadUrl(errors.BzrError):
    """Error raised when trying to access a URL that is not allowed."""

    _fmt = "Tried to access a branch from bad URL %(url)s."


class BranchReferenceForbidden(errors.BzrError):
    """Error raised when branch references are forbidden but encountered."""

    _fmt = (
        "Trying to mirror a branch reference and the branch type "
        "does not allow references."
    )


class BranchLoopError(errors.BzrError):
    """Encountered a branch cycle.

    A URL may point to a branch reference or it may point to a stacked branch.
    In either case, it's possible for there to be a cycle in these references,
    and this exception is raised when we detect such a cycle.
    """

    _fmt = "Encountered a branch cycle"


class BranchOpenPolicy:
    """Policy on how to open branches.

    In particular, a policy determines which branches are okay to open by
    checking their URLs and deciding whether or not to follow branch
    references.
    """

    def should_follow_references(self):
        """Whether we traverse references when mirroring.

        Subclasses must override this method.

        If we encounter a branch reference and this returns false, an error is
        raised.

        :returns: A boolean to indicate whether to follow a branch reference.
        """
        raise NotImplementedError(self.should_follow_references)

    def transform_fallback_location(self, branch, url):
        """Validate, maybe modify, 'url' to be used as a stacked-on location.

        :param branch:  The branch that is being opened.
        :param url: The URL that the branch provides for its stacked-on
            location.
        :return: (new_url, check) where 'new_url' is the URL of the branch to
            actually open and 'check' is true if 'new_url' needs to be
            validated by check_and_follow_branch_reference.
        """
        raise NotImplementedError(self.transform_fallback_location)

    def check_one_url(self, url):
        """Check a URL.

        Subclasses must override this method.

        :param url: The source URL to check.
        :raise BadUrl: subclasses are expected to raise this or a subclass
            when it finds a URL it deems to be unacceptable.
        """
        raise NotImplementedError(self.check_one_url)


class _BlacklistPolicy(BranchOpenPolicy):
    """Branch policy that forbids certain URLs.

    This doesn't cope with various alternative spellings of URLs,
    with e.g. url encoding. It's mostly useful for tests.
    """

    def __init__(self, should_follow_references, bad_urls=None):
        if bad_urls is None:
            bad_urls = set()
        self._bad_urls = bad_urls
        self._should_follow_references = should_follow_references

    def should_follow_references(self):
        return self._should_follow_references

    def check_one_url(self, url):
        if url in self._bad_urls:
            raise BadUrl(url)

    def transform_fallback_location(self, branch, url):
        """See `BranchOpenPolicy.transform_fallback_location`.

        This class is not used for testing our smarter stacking features so we
        just do the simplest thing: return the URL that would be used anyway
        and don't check it.
        """
        return urlutils.join(branch.base, url), False


class AcceptAnythingPolicy(_BlacklistPolicy):
    """Accept anything, to make testing easier."""

    def __init__(self):
        """Initialize AcceptAnythingPolicy."""
        super().__init__(True, set())


class WhitelistPolicy(BranchOpenPolicy):
    """Branch policy that only allows certain URLs."""

    def __init__(self, should_follow_references, allowed_urls=None, check=False):
        """Initialize WhitelistPolicy.

        Args:
            should_follow_references: Whether to follow branch references.
            allowed_urls: List of URLs that are allowed.
            check: Whether to check URLs.
        """
        if allowed_urls is None:
            allowed_urls = []
        self._should_follow_references = should_follow_references
        self.allowed_urls = {url.rstrip("/") for url in allowed_urls}
        self.check = check

    def should_follow_references(self):
        """Return whether to follow branch references."""
        return self._should_follow_references

    def check_one_url(self, url):
        """Check if a URL is allowed.

        Args:
            url: URL to check.

        Raises:
            BadUrl: If the URL is not in the allowed list.
        """
        if url.rstrip("/") not in self.allowed_urls:
            raise BadUrl(url)

    def transform_fallback_location(self, branch, url):
        """See `BranchOpenPolicy.transform_fallback_location`.

        Here we return the URL that would be used anyway and optionally check
        it.
        """
        return urlutils.join(branch.base, url), self.check


class SingleSchemePolicy(BranchOpenPolicy):
    """Branch open policy that rejects URLs not on the given scheme."""

    def __init__(self, allowed_scheme):
        """Initialize SingleSchemePolicy.

        Args:
            allowed_scheme: The URL scheme that is allowed.
        """
        self.allowed_scheme = allowed_scheme

    def should_follow_references(self):
        """Return whether to follow branch references (always True)."""
        return True

    def transform_fallback_location(self, branch, url):
        """Transform a fallback location URL.

        Args:
            branch: The branch object.
            url: The fallback URL.

        Returns:
            Tuple of (new_url, check_required).
        """
        return urlutils.join(branch.base, url), True

    def check_one_url(self, url):
        """Check that `url` is okay to open."""
        if urlutils.URL.from_string(str(url)).scheme != self.allowed_scheme:
            raise BadUrl(url)


class BranchOpener:
    """Branch opener which uses a URL policy.

    All locations that are opened (stacked-on branches, references) are
    checked against a policy object.

    The policy object is expected to have the following methods:
    * check_one_url
    * should_follow_references
    * transform_fallback_location
    """

    _threading_data = threading.local()

    def __init__(self, policy, probers=None):
        """Create a new BranchOpener.

        :param policy: The opener policy to use.
        :param probers: Optional list of probers to allow.
            Defaults to local and remote bzr probers.
        """
        self.policy = policy
        self._seen_urls = set()
        if probers is None:
            probers = ControlDirFormat.all_probers()
        self.probers = probers

    @classmethod
    def install_hook(cls):
        """Install the ``transform_fallback_location`` hook.

        This is done at module import time, but transform_fallback_locationHook
        doesn't do anything unless the `_active_openers` threading.Local
        object has a 'opener' attribute in this thread.

        This is in a module-level function rather than performed at module
        level so that it can be called in setUp for testing `BranchOpener`
        as breezy.tests.TestCase.setUp clears hooks.
        """
        Branch.hooks.install_named_hook(
            "transform_fallback_location",
            cls.transform_fallback_locationHook,
            "BranchOpener.transform_fallback_locationHook",
        )

    def check_and_follow_branch_reference(self, url):
        """Check URL (and possibly the referenced URL).

        This method checks that `url` passes the policy's `check_one_url`
        method, and if `url` refers to a branch reference, it checks whether
        references are allowed and whether the reference's URL passes muster
        also -- recursively, until a real branch is found.

        :param url: URL to check
        :raise BranchLoopError: If the branch references form a loop.
        :raise BranchReferenceForbidden: If this opener forbids branch
            references.
        """
        while True:
            if url in self._seen_urls:
                raise BranchLoopError()
            self._seen_urls.add(url)
            self.policy.check_one_url(url)
            next_url = self.follow_reference(url)
            if next_url is None:
                return url
            url = next_url
            if not self.policy.should_follow_references():
                raise BranchReferenceForbidden(url)

    @classmethod
    def transform_fallback_locationHook(cls, branch, url):
        """Installed as the 'transform_fallback_location' Branch hook.

        This method calls `transform_fallback_location` on the policy object
        and either returns the url it provides or passes it back to
        check_and_follow_branch_reference.
        """
        try:
            opener = cls._threading_data.opener
        except AttributeError:
            return url
        new_url, check = opener.policy.transform_fallback_location(branch, url)
        if check:
            return opener.check_and_follow_branch_reference(new_url)
        else:
            return new_url

    def run_with_transform_fallback_location_hook_installed(
        self, callable, *args, **kw
    ):
        """Run callable with transform fallback location hook installed.

        Args:
            callable: Function to call.
            *args: Arguments to pass to callable.
            **kw: Keyword arguments to pass to callable.

        Returns:
            Result of calling callable.
        """
        if (
            self.transform_fallback_locationHook
            not in Branch.hooks["transform_fallback_location"]
        ):
            raise AssertionError("hook not installed")
        self._threading_data.opener = self
        try:
            return callable(*args, **kw)
        finally:
            del self._threading_data.opener
            # We reset _seen_urls here to avoid multiple calls to open giving
            # spurious loop exceptions.
            self._seen_urls = set()

    def _open_dir(self, url):
        """Simple BzrDir.open clone that only uses specific probers.

        :param url: URL to open
        :return: ControlDir instance
        """

        def redirected(transport, e, redirection_notice):
            self.policy.check_one_url(e.target)
            redirected_transport = transport._redirected_to(e.source, e.target)
            if redirected_transport is None:
                raise errors.NotBranchError(e.source)
            trace.note(
                "%s is%s redirected to %s",
                transport.base,
                e.permanently,
                redirected_transport.base,
            )
            return redirected_transport

        def find_format(transport):
            last_error = errors.NotBranchError(transport.base)
            for prober_kls in self.probers:
                prober = prober_kls()
                try:
                    return transport, prober.probe_transport(transport)
                except errors.NotBranchError as e:
                    last_error = e
            else:
                raise last_error

        transport = get_transport(url)
        transport, format = do_catching_redirections(find_format, transport, redirected)
        return format.open(transport)

    def follow_reference(self, url):
        """Get the branch-reference value at the specified url.

        This exists as a separate method only to be overriden in unit tests.
        """
        controldir = self._open_dir(url)
        return controldir.get_branch_reference()

    def open(self, url, ignore_fallbacks=False):
        """Open the Bazaar branch at url, first checking it.

        What is acceptable means is defined by the policy's `follow_reference`
        and `check_one_url` methods.
        """
        if not isinstance(url, str):
            raise TypeError

        url = self.check_and_follow_branch_reference(url)

        def open_branch(url, ignore_fallbacks):
            dir = self._open_dir(url)
            return dir.open_branch(ignore_fallbacks=ignore_fallbacks)

        return self.run_with_transform_fallback_location_hook_installed(
            open_branch, url, ignore_fallbacks
        )


def open_only_scheme(allowed_scheme, url):
    """Open the branch at `url`, only accessing URLs on `allowed_scheme`.

    :raises BadUrl: An attempt was made to open a URL that was not on
        `allowed_scheme`.
    """
    return BranchOpener(SingleSchemePolicy(allowed_scheme)).open(url)


BranchOpener.install_hook()
