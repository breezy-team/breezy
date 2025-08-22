# Copyright (C) 2019 Jelmer Vernooij <jelmer@samba.org>
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

"""Subversion foreign branch support.

Currently only tells the user that Subversion is not supported.
"""

from ... import (
    controldir,
    errors,
    version_info,  # noqa: F401
)
from ... import transport as _mod_transport
from ...revisionspec import revspec_registry


class SubversionUnsupportedError(errors.UnsupportedVcs):
    """Error raised when attempting to use unsupported Subversion functionality.

    This error is raised when trying to access Subversion repositories or working
    trees, as full Subversion support is not yet implemented in Breezy.

    Attributes:
        vcs: The version control system identifier ("svn").
        _fmt: The error message format string.
    """

    vcs = "svn"

    _fmt = (
        "Subversion branches are not yet supported. "
        "To interoperate with Subversion branches, use fastimport."
    )


class SvnWorkingTreeDirFormat(controldir.ControlDirFormat):
    """Control directory format for Subversion working trees.

    This class represents the format of Subversion working directories (those
    containing .svn subdirectories). It acts as a placeholder to detect SVN
    working trees and inform users that they are not yet supported.
    """

    def get_converter(self):
        """Get a converter for this format.

        Raises:
            NotImplementedError: Always raised as conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this format.

        Returns:
            str: Description string "Subversion working directory".
        """
        return "Subversion working directory"

    def initialize_on_transport(self, transport):
        """Initialize a new control directory on a transport.

        Args:
            transport: The transport where the directory should be initialized.

        Raises:
            UninitializableFormat: Always raised as SVN format cannot be created.
        """
        raise errors.UninitializableFormat(format=self)

    def is_supported(self):
        """Check if this format is supported.

        Returns:
            bool: Always False as SVN format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check compatibility with.

        Returns:
            bool: Always False as SVN format is not supported.
        """
        return False

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Check if this format is supported and recommend upgrades.

        Args:
            allow_unsupported: Whether to allow unsupported formats.
            recommend_upgrade: Whether to recommend upgrading (default True).
            basedir: The base directory path (optional).

        Raises:
            SubversionUnsupportedError: Always raised to indicate lack of support.
        """
        raise SubversionUnsupportedError(format=self)

    def open(self, transport):
        """Open an existing control directory.

        Args:
            transport: The transport pointing to the control directory.

        Raises:
            NotBranchError: If no SVN working tree is found at the location.
            NotImplementedError: If an SVN working tree is found (not supported).
        """
        # Raise NotBranchError if there is nothing there
        SvnWorkingTreeProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class SvnWorkingTreeProber(controldir.Prober):
    """Prober for detecting Subversion working trees.

    This class is responsible for detecting the presence of Subversion
    working directories by looking for .svn subdirectories.
    """

    @classmethod
    def priority(klass, transport):
        """Get the priority of this prober.

        Args:
            transport: The transport to probe.

        Returns:
            int: Priority value of 100 (lower priority).
        """
        return 100

    def probe_transport(self, transport):
        """Probe a transport to detect a Subversion working tree.

        Args:
            transport: The transport to probe for SVN working tree.

        Returns:
            SvnWorkingTreeDirFormat: If an SVN working tree is detected.

        Raises:
            NotBranchError: If the transport is not local or no .svn directory found.
        """
        try:
            transport.local_abspath(".")
        except errors.NotLocalUrl as err:
            raise errors.NotBranchError(path=transport.base) from err
        else:
            if transport.has(".svn"):
                return SvnWorkingTreeDirFormat()
            raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Get the list of known formats this prober can detect.

        Returns:
            list: A list containing a single SvnWorkingTreeDirFormat instance.
        """
        return [SvnWorkingTreeDirFormat()]


class SvnRepositoryFormat(controldir.ControlDirFormat):
    """Control directory format for Subversion repositories.

    This class represents the format of Subversion repositories accessed
    over various protocols (HTTP, HTTPS, SVN, file). It acts as a placeholder
    to detect SVN repositories and inform users that they are not yet supported.
    """

    def get_converter(self):
        """Get a converter for this format.

        Raises:
            NotImplementedError: Always raised as conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this format.

        Returns:
            str: Description string "Subversion repository".
        """
        return "Subversion repository"

    def initialize_on_transport(self, transport):
        """Initialize a new repository on a transport.

        Args:
            transport: The transport where the repository should be initialized.

        Raises:
            UninitializableFormat: Always raised as SVN format cannot be created.
        """
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Check if this format is supported.

        Returns:
            bool: Always False as SVN format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check compatibility with.

        Returns:
            bool: Always False as SVN format is not supported.
        """
        return False

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Check if this format is supported and recommend upgrades.

        Args:
            allow_unsupported: Whether to allow unsupported formats.
            recommend_upgrade: Whether to recommend upgrading (default True).
            basedir: The base directory path (optional).

        Raises:
            SubversionUnsupportedError: Always raised to indicate lack of support.
        """
        raise SubversionUnsupportedError()

    def open(self, transport):
        """Open an existing repository.

        Args:
            transport: The transport pointing to the repository.

        Raises:
            NotBranchError: If no SVN repository is found at the location.
            NotImplementedError: If an SVN repository is found (not supported).
        """
        # Raise NotBranchError if there is nothing there
        SvnRepositoryProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class SvnRepositoryProber(controldir.Prober):
    """Prober for detecting Subversion repositories.

    This class is responsible for detecting Subversion repositories accessed
    through various protocols (HTTP, HTTPS, file, SVN). It performs protocol-specific
    checks to determine if a given URL points to an SVN repository.

    Attributes:
        _supported_schemes: List of URL schemes this prober can handle.
    """

    _supported_schemes = ["http", "https", "file", "svn"]

    @classmethod
    def priority(klass, transport):
        """Get the priority of this prober.

        Args:
            transport: The transport to probe.

        Returns:
            int: Priority value of 90 if "svn" in URL, otherwise 100.
        """
        if "svn" in transport.base:
            return 90
        return 100

    def probe_transport(self, transport):
        """Probe a transport to detect a Subversion repository.

        This method performs different checks based on the transport protocol:
        - For svn:// and svn+*:// URLs, immediately raises SubversionUnsupportedError
        - For file:// URLs, checks for repository structure (format, db, conf files)
        - For HTTP(S) URLs, checks WebDAV headers for version-control support

        Args:
            transport: The transport to probe for SVN repository.

        Returns:
            SvnRepositoryFormat: If an SVN repository is detected.

        Raises:
            NotBranchError: If no SVN repository is found or transport is invalid.
            SubversionUnsupportedError: If an SVN URL scheme is detected.
        """
        try:
            url = transport.external_url()
        except errors.InProcessTransport as err:
            raise errors.NotBranchError(path=transport.base) from err

        scheme = url.split(":")[0]
        if scheme.startswith("svn+") or scheme == "svn":
            raise SubversionUnsupportedError()

        if scheme not in self._supported_schemes:
            raise errors.NotBranchError(path=transport.base)

        if scheme == "file":
            # Cheaper way to figure out if there is a svn repo
            maybe = False
            subtransport = transport
            while subtransport:
                try:
                    if all(subtransport.has(name) for name in ["format", "db", "conf"]):
                        maybe = True
                        break
                except UnicodeEncodeError:
                    pass
                prevsubtransport = subtransport
                subtransport = prevsubtransport.clone("..")
                if subtransport.base == prevsubtransport.base:
                    break
            if not maybe:
                raise errors.NotBranchError(path=transport.base)

        # If this is a HTTP transport, use the existing connection to check
        # that the remote end supports version control.
        if scheme in ("http", "https"):
            priv_transport = getattr(transport, "_decorated", transport)
            try:
                headers = priv_transport._options(".")
            except (
                errors.InProcessTransport,
                _mod_transport.NoSuchFile,
                errors.InvalidHttpResponse,
            ) as err:
                raise errors.NotBranchError(path=transport.base) from err
            else:
                dav_entries = set()
                for key, value in headers:
                    if key.upper() == "DAV":
                        dav_entries.update([x.strip() for x in value.split(",")])
                if "version-control" not in dav_entries:
                    raise errors.NotBranchError(path=transport.base)

        return SvnRepositoryFormat()

    @classmethod
    def known_formats(cls):
        """Get the list of known formats this prober can detect.

        Returns:
            list: A list containing a single SvnRepositoryFormat instance.
        """
        return [SvnRepositoryFormat()]


controldir.ControlDirFormat.register_prober(SvnWorkingTreeProber)
controldir.ControlDirFormat.register_prober(SvnRepositoryProber)


revspec_registry.register_lazy("svn:", __name__ + ".revspec", "RevisionSpec_svn")


_mod_transport.register_transport_proto(
    "svn+ssh://", help="Access using the Subversion smart server tunneled over SSH."
)
_mod_transport.register_transport_proto("svn+http://")
_mod_transport.register_transport_proto("svn+https://")
_mod_transport.register_transport_proto(
    "svn://", help="Access using the Subversion smart server."
)
