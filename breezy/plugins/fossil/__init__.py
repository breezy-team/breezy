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

"""Fossil foreign branch support.

Currently only tells the user that Fossil is not supported.
"""

from ... import (
    controldir,
    errors,
    version_info,  # noqa: F401
)


class FossilUnsupportedError(errors.UnsupportedVcs):
    """Error raised when attempting to use unsupported Fossil repositories.

    This error is raised when Breezy encounters a Fossil repository but cannot
    work with it directly. Users should use fastimport tools for interoperability.

    Attributes:
        vcs: The version control system name ("fossil").
    """

    vcs = "fossil"

    _fmt = (
        "Fossil branches are not yet supported. "
        "To interoperate with Fossil branches, use fastimport."
    )


class FossilDirFormat(controldir.ControlDirFormat):
    """Fossil directory format."""

    def get_converter(self):
        """Get a converter object for this format.

        This method is not implemented for Fossil as conversion is not supported.
        Users should use fastimport/fastexport tools instead.

        Raises:
            NotImplementedError: Always raised as Fossil conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this control directory format.

        Returns:
            str: A description of the Fossil control directory format.
        """
        return "Fossil control directory"

    def initialize_on_transport(self, transport):
        """Initialize a new Fossil repository on the given transport.

        This method is not supported as Breezy cannot create Fossil repositories.

        Args:
            transport: The transport where the repository would be initialized.

        Raises:
            errors.UninitializableFormat: Always raised as initialization is not supported.
        """
        raise errors.UninitializableFormat(format=self)

    def is_supported(self):
        """Check if this format is supported by Breezy.

        Returns:
            bool: Always False as Fossil format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check for support.

        Returns:
            bool: Always False as Fossil format is not supported.
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
            FossilUnsupportedError: Always raised to inform users about lack of support.
        """
        raise FossilUnsupportedError(format=self)

    def open(self, transport):
        """Open an existing Fossil repository.

        This method first verifies that a Fossil repository exists at the transport
        location, then raises NotImplementedError as opening is not supported.

        Args:
            transport: The transport pointing to the repository location.

        Raises:
            errors.NotBranchError: If no Fossil repository exists at the location.
            NotImplementedError: If a repository exists but cannot be opened.
        """
        # Raise NotBranchError if there is nothing there
        RemoteFossilProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class RemoteFossilProber(controldir.Prober):
    """Prober for detecting remote Fossil repositories over HTTP.

    This prober checks if a remote HTTP endpoint is a Fossil repository by
    sending a POST request with the appropriate content type and checking
    the response.
    """

    @classmethod
    def priority(klass, transport):
        """Get the priority of this prober for the given transport.

        Args:
            transport: The transport to check.

        Returns:
            int: Priority value (95) for this prober.
        """
        return 95

    @classmethod
    def probe_transport(klass, transport):
        """Probe a transport to determine if it contains a Fossil repository.

        This method sends an HTTP POST request with Fossil-specific headers
        to check if the remote endpoint is a Fossil repository.

        Args:
            transport: The transport to probe.

        Returns:
            FossilDirFormat: If a Fossil repository is detected.

        Raises:
            errors.NotBranchError: If the transport is not HTTP or no Fossil
                repository is detected.
        """
        from ...transport.http.urllib import HttpTransport

        if not isinstance(transport, HttpTransport):
            raise errors.NotBranchError(path=transport.base)
        response = transport.request(
            "POST", transport.base, headers={"Content-Type": "application/x-fossil"}
        )
        if response.status == 501:
            raise errors.NotBranchError(path=transport.base)
        ct = response.getheader("Content-Type")
        if ct is None:
            raise errors.NotBranchError(path=transport.base)
        if ct.split(";")[0] != "application/x-fossil":
            raise errors.NotBranchError(path=transport.base)
        return FossilDirFormat()

    @classmethod
    def known_formats(cls):
        """Get the list of control directory formats known by this prober.

        Returns:
            list: A list containing the FossilDirFormat instance.
        """
        return [FossilDirFormat()]


controldir.ControlDirFormat.register_prober(RemoteFossilProber)
