# Copyright (C) 2010-2012 Jelmer Vernooij <jelmer@samba.org>
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

"""Monotone foreign branch support.

Currently only tells the user that Monotone is not supported.
"""

from ... import (
    controldir,
    errors,
    version_info,  # noqa: F401
)


class MonotoneUnsupportedError(errors.UnsupportedVcs):
    """Error raised when attempting to use unsupported Monotone repositories.

    This error is raised when Breezy encounters a Monotone repository but cannot
    work with it directly. Users should use fastimport tools for interoperability.

    Attributes:
        vcs: The version control system name ("mtn").
    """

    vcs = "mtn"

    _fmt = (
        "Monotone branches are not yet supported. "
        "To interoperate with Monotone branches, "
        "use fastimport."
    )


class MonotoneDirFormat(controldir.ControlDirFormat):
    """Monotone directory format."""

    def get_converter(self):
        """Get a converter object for this format.

        This method is not implemented for Monotone as conversion is not supported.
        Users should use fastimport/fastexport tools instead.

        Raises:
            NotImplementedError: Always raised as Monotone conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this control directory format.

        Returns:
            str: A description of the Monotone control directory format.
        """
        return "Monotone control directory"

    def initialize_on_transport(self, transport):
        """Initialize a new Monotone repository on the given transport.

        This method is not supported as Breezy cannot create Monotone repositories.

        Args:
            transport: The transport where the repository would be initialized.

        Raises:
            errors.UninitializableFormat: Always raised as initialization is not supported.
        """
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Check if this format is supported by Breezy.

        Returns:
            bool: Always False as Monotone format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check for support.

        Returns:
            bool: Always False as Monotone format is not supported.
        """
        return False

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Check if this format is supported and raise appropriate errors.

        Args:
            allow_unsupported: Whether to allow unsupported formats.
            recommend_upgrade: Whether to recommend upgrading (unused).
            basedir: The base directory of the repository (unused).

        Raises:
            MonotoneUnsupportedError: Always raised to inform users about lack of support.
        """
        raise MonotoneUnsupportedError(format=self)

    def open(self, transport):
        """Open an existing Monotone repository.

        This method first verifies that a Monotone repository exists at the transport
        location, then raises NotImplementedError as opening is not supported.

        Args:
            transport: The transport pointing to the repository location.

        Raises:
            errors.NotBranchError: If no Monotone repository exists at the location.
            NotImplementedError: If a repository exists but cannot be opened.
        """
        # Raise NotBranchError if there is nothing there
        MonotoneProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class MonotoneProber(controldir.Prober):
    """Prober for detecting Monotone repositories.

    This prober checks for the presence of Monotone-specific directories
    to determine if a location contains a Monotone repository.
    """

    @classmethod
    def priority(klass, transport):
        """Get the priority of this prober for the given transport.

        Args:
            transport: The transport to check.

        Returns:
            int: Priority value (100) for this prober.
        """
        return 100

    @classmethod
    def probe_transport(klass, transport):
        """Probe a transport to determine if it contains a Monotone repository.

        Our format is present if the transport has a '_MTN/' subdir.

        Args:
            transport: The transport to probe.

        Returns:
            MonotoneDirFormat: If a Monotone repository is detected.

        Raises:
            errors.NotBranchError: If no Monotone repository is found.
        """
        if transport.has("_MTN"):
            return MonotoneDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Get the list of control directory formats known by this prober.

        Returns:
            list: A list containing the MonotoneDirFormat instance.
        """
        return [MonotoneDirFormat()]


controldir.ControlDirFormat.register_prober(MonotoneProber)
