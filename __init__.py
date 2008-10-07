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


"""CVS working tree support for bzr.

Currently limited to telling you you want to run CVS commands.
"""

import bzrlib.bzrdir
import bzrlib.errors


class CVSDirFormat(bzrlib.bzrdir.BzrDirFormat):
    """The CVS directory control format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "CVS control directory."

    def initialize_on_transport(self, transport):
        raise NotImplementedError(self.get_converter)

    @classmethod
    def _known_formats(self):
        return set([CVSDirFormat()])

    def open(self, transport, _found=False):
        """Open this directory."""
        raise bzrlib.errors.BzrCommandError(
            "CVS working trees are not supported. To convert CVS projects to "
            "bzr, please see http://bazaar-vcs.org/BzrMigration and/or "
            "https://edge.launchpad.net/launchpad-bazaar/+faq/26.")

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in 'CVS/'."""
        # little ugly, but works
        format = klass()
        # try a manual probe first, its a little faster perhaps ?
        if transport.has('CVS'):
            return format
        raise errors.NotBranchError(path=transport.base)


bzrlib.bzrdir.BzrDirFormat.register_control_format(CVSDirFormat)
