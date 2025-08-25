# Copyright (C) 2008 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""CVS working tree support.

Currently limited to referencing tools for migration.
"""

from ... import (
    controldir,
    errors,
    version_info,  # noqa: F401
)
from ...transport import register_transport_proto


class CVSUnsupportedError(errors.UnsupportedVcs):
    """Error raised when attempting to use unsupported CVS working trees.

    This error is raised when Breezy encounters a CVS working tree but cannot
    work with it directly. Users are directed to migration tools for converting
    CVS projects to Bazaar/Breezy.

    Attributes:
        vcs: The version control system name ("cvs").
    """

    vcs = "cvs"

    _fmt = (
        "CVS working trees are not supported. To convert CVS projects to "
        "bzr, please see http://bazaar-vcs.org/BzrMigration and/or "
        "https://launchpad.net/launchpad-bazaar/+faq/26."
    )


class CVSDirFormat(controldir.ControlDirFormat):
    """The CVS directory control format."""

    def get_converter(self):
        """Get a converter object for this format.

        This method is not implemented for CVS as direct conversion is not supported.
        Users should use migration tools referenced in the error message.

        Raises:
            NotImplementedError: Always raised as CVS conversion is not supported.
        """
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        """Get a human-readable description of this control directory format.

        Returns:
            str: A description of the CVS control directory format.
        """
        return "CVS control directory."

    def initialize_on_transport(self, transport):
        """Initialize a new CVS repository on the given transport.

        This method is not supported as Breezy cannot create CVS repositories.

        Args:
            transport: The transport where the repository would be initialized.

        Raises:
            errors.UninitializableFormat: Always raised as initialization is not supported.
        """
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Check if this format is supported by Breezy.

        Returns:
            bool: Always False as CVS format is not supported.
        """
        return False

    def supports_transport(self, transport):
        """Check if this format supports the given transport.

        Args:
            transport: The transport to check for support.

        Returns:
            bool: Always False as CVS format is not supported.
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
            CVSUnsupportedError: Always raised to inform users about lack of support
                and direct them to migration tools.
        """
        raise CVSUnsupportedError(format=self)

    def open(self, transport):
        """Open an existing CVS working tree.

        This method first verifies that a CVS working tree exists at the transport
        location, then raises NotImplementedError as opening is not supported.

        Args:
            transport: The transport pointing to the working tree location.

        Raises:
            errors.NotBranchError: If no CVS working tree exists at the location.
            NotImplementedError: If a working tree exists but cannot be opened.
        """
        # Raise NotBranchError if there is nothing there
        CVSProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class CVSProber(controldir.Prober):
    """Prober for detecting CVS working trees.

    This prober checks for the presence of CVS-specific directories and files
    to determine if a location contains a CVS working tree.
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
        """Probe a transport to determine if it contains a CVS working tree.

        Checks for the presence of CVS-specific directories (CVS/ and CVS/Repository)
        to identify a CVS working tree.

        Args:
            transport: The transport to probe.

        Returns:
            CVSDirFormat: If a CVS working tree is detected.

        Raises:
            errors.NotBranchError: If no CVS working tree is found.
        """
        # little ugly, but works
        # try a manual probe first, its a little faster perhaps ?
        if transport.has("CVS") and transport.has("CVS/Repository"):
            return CVSDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        """Get the list of control directory formats known by this prober.

        Returns:
            list: A list containing the CVSDirFormat instance.
        """
        return [CVSDirFormat()]


controldir.ControlDirFormat.register_prober(CVSProber)

register_transport_proto("cvs+pserver://", help="The pserver access protocol for CVS.")
