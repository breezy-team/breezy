# Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License or
# (at your option) a later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Mercurial foreign branch support.

Currently only tells the user that Mercurial is not supported.
"""

from ... import (
    controldir,
    errors,
    version_info,  # noqa: F401
)
from ... import transport as _mod_transport


class MercurialUnsupportedError(errors.UnsupportedVcs):
    """Exception raised when attempting to use Mercurial repositories.

    This error is raised because Breezy does not currently support direct
    interaction with Mercurial repositories. Users should use the fastimport
    format for interoperability with Mercurial.

    Attributes:
        vcs: The version control system identifier, always "hg" for Mercurial.
    """

    vcs = "hg"

    _fmt = (
        "Mercurial branches are not yet supported. "
        "To interoperate with Mercurial, use the fastimport format."
    )


class LocalHgDirFormat(controldir.ControlDirFormat):
    """Mercurial directory format."""

    def get_converter(self):
        """Get a converter for this format.

        This method is not implemented as Mercurial conversion is not supported.

        Raises:
            NotImplementedError: Always raised as conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this control directory format.

        Returns:
            str: A description of the format as "Local Mercurial control directory".
        """
        return "Local Mercurial control directory"

    def initialize_on_transport(self, transport):
        """Initialize a new control directory on a transport.

        This method always fails as Mercurial repository creation is not supported.

        Args:
            transport: The transport where the control directory would be created.

        Raises:
            errors.UninitializableFormat: Always raised as initialization is not supported.
        """
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Check if this format is supported by the current version of Breezy.

        Returns:
            bool: Always False as Mercurial format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check for support.

        Returns:
            bool: Always False as no transports are supported for Mercurial.
        """
        return False

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Check if this format is supported and raise an error if not.

        Args:
            allow_unsupported: Whether to allow unsupported formats.
            recommend_upgrade: Whether to recommend upgrading the format.
            basedir: The base directory of the control directory (optional).

        Raises:
            MercurialUnsupportedError: Always raised to indicate Mercurial is not supported.
        """
        raise MercurialUnsupportedError(format=self)

    def open(self, transport):
        """Open an existing control directory.

        This method first verifies that a Mercurial repository exists at the
        transport location, then fails as opening is not supported.

        Args:
            transport: The transport pointing to the control directory.

        Raises:
            NotBranchError: If no Mercurial repository is found.
            NotImplementedError: If a repository is found (as opening is not supported).
        """
        # Raise NotBranchError if there is nothing there
        LocalHgProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class LocalHgProber(controldir.Prober):
    """Prober for local Mercurial repositories.

    This class is responsible for detecting Mercurial repositories on local
    file systems by checking for the presence of .hg directories and their
    required files.
    """

    @classmethod
    def priority(klass, transport):
        """Return the priority for probing with this prober.

        Args:
            transport: The transport to probe.

        Returns:
            int: Priority value of 100 for local Mercurial repositories.
        """
        return 100

    @staticmethod
    def _has_hg_dumb_repository(transport):
        """Check if a transport contains a dumb Mercurial repository.

        A dumb repository is identified by the presence of either .hg/requires
        or .hg/00changelog.i files.

        Args:
            transport: The transport to check.

        Returns:
            bool: True if Mercurial repository files are found, False otherwise.
        """
        try:
            return transport.has_any([".hg/requires", ".hg/00changelog.i"])
        except (
            _mod_transport.NoSuchFile,
            errors.PermissionDenied,
            errors.InvalidHttpResponse,
        ):
            return False

    @classmethod
    def probe_transport(klass, transport):
        """Probe a transport to detect if it contains a Mercurial repository.

        Our format is present if the transport has a '.hg/' subdir with the
        required Mercurial files.

        Args:
            transport: The transport to probe.

        Returns:
            LocalHgDirFormat: An instance of the format if a repository is found.

        Raises:
            errors.NotBranchError: If no Mercurial repository is found.
        """
        if klass._has_hg_dumb_repository(transport):
            return LocalHgDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Return the known formats that this prober can detect.

        Returns:
            list: A list containing a single LocalHgDirFormat instance.
        """
        return [LocalHgDirFormat()]


class SmartHgDirFormat(controldir.ControlDirFormat):
    """Mercurial directory format."""

    def get_converter(self):
        """Get a converter for this format.

        This method is not implemented as Mercurial conversion is not supported.

        Raises:
            NotImplementedError: Always raised as conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this control directory format.

        Returns:
            str: A description of the format as "Smart Mercurial control directory".
        """
        return "Smart Mercurial control directory"

    def initialize_on_transport(self, transport):
        """Initialize a new control directory on a transport.

        This method always fails as Mercurial repository creation is not supported.

        Args:
            transport: The transport where the control directory would be created.

        Raises:
            errors.UninitializableFormat: Always raised as initialization is not supported.
        """
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Check if this format is supported by the current version of Breezy.

        Returns:
            bool: Always False as Mercurial format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check for support.

        Returns:
            bool: Always False as no transports are supported for Mercurial.
        """
        return False

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Check if this format is supported and raise an error if not.

        Args:
            allow_unsupported: Whether to allow unsupported formats.
            recommend_upgrade: Whether to recommend upgrading the format.
            basedir: The base directory of the control directory (optional).

        Raises:
            MercurialUnsupportedError: Always raised to indicate Mercurial is not supported.
        """
        raise MercurialUnsupportedError()

    def open(self, transport):
        """Open an existing control directory.

        This method first verifies that a Mercurial repository exists at the
        transport location, then fails as opening is not supported.

        Args:
            transport: The transport pointing to the control directory.

        Raises:
            NotBranchError: If no Mercurial repository is found.
            NotImplementedError: If a repository is found (as opening is not supported).
        """
        # Raise NotBranchError if there is nothing there
        SmartHgProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class SmartHgProber(controldir.Prober):
    """Prober for remote Mercurial repositories over HTTP/HTTPS.

    This class is responsible for detecting Mercurial repositories accessible
    via HTTP or HTTPS using the Mercurial smart server protocol.

    Attributes:
        _supported_schemes: List of URL schemes supported by this prober.
    """

    # Perhaps retrieve list from mercurial.hg.schemes ?
    _supported_schemes = ["http", "https"]

    @classmethod
    def priority(klass, transport):
        """Return the priority for probing with this prober.

        Returns a higher priority (lower number) if "hg" appears in the transport
        URL, otherwise returns a slightly lower priority than default to avoid
        false positives with hgweb servers.

        Args:
            transport: The transport to probe.

        Returns:
            int: Priority value of 90 if "hg" is in the URL, 99 otherwise.
        """
        if "hg" in transport.base:
            return 90
        # hgweb repositories are prone to return *a* page for every possible URL,
        # making probing hard for other formats so use 99 here rather than 100.
        return 99

    @staticmethod
    def _has_hg_http_smart_server(transport, external_url):
        """Check if there is a Mercurial smart server at the remote location.

        :param transport: Transport to check
        :param externa_url: External URL for transport
        :return: Boolean indicating whether transport is backed onto hg
        """
        from ...urlutils import urlparse

        parsed_url = urlparse.urlparse(external_url)
        parsed_url = parsed_url._replace(query="cmd=capabilities")
        url = urlparse.urlunparse(parsed_url)
        resp = transport.request(
            "GET", url, headers={"Accept": "application/mercurial-0.1"}
        )
        if resp.status == 404:
            return False
        if resp.status == 406:
            # The server told us that it can't handle our Accept header.
            return False
        ct = resp.getheader("Content-Type")
        if ct is None:
            return False
        return ct.startswith("application/mercurial")

    @classmethod
    def probe_transport(klass, transport):
        """Probe a transport to detect if it contains a remote Mercurial repository.

        This method checks if the transport points to a Mercurial repository
        accessible via HTTP/HTTPS smart server protocol.

        Args:
            transport: The transport to probe.

        Returns:
            SmartHgDirFormat: An instance of the format if a repository is found.

        Raises:
            errors.NotBranchError: If no Mercurial repository is found or if the
                transport is not supported.
        """
        try:
            external_url = transport.external_url()
        except errors.InProcessTransport as e:
            raise errors.NotBranchError(path=transport.base) from e
        scheme = external_url.split(":")[0]
        if scheme not in klass._supported_schemes:
            raise errors.NotBranchError(path=transport.base)
        from breezy import urlutils

        external_url = urlutils.strip_segment_parameters(external_url)
        # Explicitly check for .hg directories here, so we avoid
        # loading foreign branches through Mercurial.
        if external_url.startswith("http:") or external_url.startswith("https:"):
            if klass._has_hg_http_smart_server(transport, external_url):
                return SmartHgDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Return the known formats that this prober can detect.

        Returns:
            list: A list containing a single SmartHgDirFormat instance.
        """
        return [SmartHgDirFormat()]


controldir.ControlDirFormat.register_prober(LocalHgProber)
controldir.ControlDirFormat.register_prober(SmartHgProber)
