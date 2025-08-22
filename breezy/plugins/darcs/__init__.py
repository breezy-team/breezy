# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""Darcs foreign branch support.

Currently only tells the user to use fastimport/fastexport.
"""

from breezy import controldir, errors

from ... import version_info  # noqa: F401


class DarcsUnsupportedError(errors.UnsupportedVcs):
    """Error raised when attempting to use unsupported Darcs repositories.

    This error is raised when Breezy encounters a Darcs repository but cannot
    work with it directly. Users should use fastimport tools for interoperability.

    Attributes:
        vcs: The version control system name ("darcs").
    """

    vcs = "darcs"

    _fmt = (
        "Darcs branches are not yet supported. "
        "To interoperate with darcs branches, use fastimport."
    )


class DarcsDirFormat(controldir.ControlDirFormat):
    """Darcs directory format."""

    def get_converter(self):
        """Get a converter object for this format.

        This method is not implemented for Darcs as conversion is not supported.
        Users should use fastimport/fastexport tools instead.

        Raises:
            NotImplementedError: Always raised as Darcs conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this control directory format.

        Returns:
            str: A description of the Darcs control directory format.
        """
        return "darcs control directory"

    def initialize_on_transport(self, transport):
        """Initialize a new Darcs repository on the given transport.

        This method is not supported as Breezy cannot create Darcs repositories.

        Args:
            transport: The transport where the repository would be initialized.

        Raises:
            errors.UninitializableFormat: Always raised as initialization is not supported.
        """
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Check if this format is supported by Breezy.

        Returns:
            bool: Always False as Darcs format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check for support.

        Returns:
            bool: Always False as Darcs format is not supported.
        """
        return False

    @classmethod
    def _known_formats(self):
        """Get the set of known Darcs directory formats.

        Returns:
            set: A set containing the DarcsDirFormat instance.
        """
        return {DarcsDirFormat()}

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Check if this format is supported and raise appropriate errors.

        Args:
            allow_unsupported: Whether to allow unsupported formats.
            recommend_upgrade: Whether to recommend upgrading (unused).
            basedir: The base directory of the repository (unused).

        Raises:
            DarcsUnsupportedError: Always raised to inform users about lack of support.
        """
        raise DarcsUnsupportedError()

    def open(self, transport):
        """Open an existing Darcs repository.

        This method first verifies that a Darcs repository exists at the transport
        location, then raises NotImplementedError as opening is not supported.

        Args:
            transport: The transport pointing to the repository location.

        Raises:
            errors.NotBranchError: If no Darcs repository exists at the location.
            NotImplementedError: If a repository exists but cannot be opened.
        """
        # Raise NotBranchError if there is nothing there
        DarcsProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class DarcsProber(controldir.Prober):
    """Prober for detecting Darcs repositories.

    This prober checks for the presence of Darcs-specific files and directories
    to determine if a location contains a Darcs repository.
    """

    @classmethod
    def priority(klass, transport):
        """Get the priority of this prober for the given transport.

        Gives higher priority (lower value) if "darcs" appears in the transport URL.

        Args:
            transport: The transport to check.

        Returns:
            int: Priority value (90 if "darcs" in URL, 100 otherwise).
        """
        if "darcs" in transport.base:
            return 90
        return 100

    @classmethod
    def probe_transport(klass, transport):
        """Probe a transport to determine if it contains a Darcs repository.

        Checks for the presence of Darcs-specific files (_darcs/format or
        _darcs/inventory) to identify a Darcs repository.

        Args:
            transport: The transport to probe.

        Returns:
            DarcsDirFormat: If a Darcs repository is detected.

        Raises:
            errors.NotBranchError: If no Darcs repository is found.
        """
        if transport.has_any(["_darcs/format", "_darcs/inventory"]):
            return DarcsDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Get the list of control directory formats known by this prober.

        Returns:
            list: A list containing the DarcsDirFormat instance.
        """
        return [DarcsDirFormat()]


controldir.ControlDirFormat.register_prober(DarcsProber)
