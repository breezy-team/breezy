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

from ... import version_info  # noqa: F401

from ... import (
    controldir,
    errors,
    )
from ...transport import register_transport_proto


class CVSUnsupportedError(errors.UnsupportedFormatError):

    _fmt = ("CVS working trees are not supported. To convert CVS projects to "
            "bzr, please see http://bazaar-vcs.org/BzrMigration and/or "
            "https://launchpad.net/launchpad-bazaar/+faq/26.")


class CVSDirFormat(controldir.ControlDirFormat):
    """The CVS directory control format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "CVS control directory."

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
                             basedir=None):
        raise CVSUnsupportedError(format=self)

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        CVSProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class CVSProber(controldir.Prober):

    @classmethod
    def priority(klass, transport):
        return 100

    @classmethod
    def probe_transport(klass, transport):
        # little ugly, but works
        # try a manual probe first, its a little faster perhaps ?
        if transport.has('CVS') and transport.has('CVS/Repository'):
            return CVSDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        return [CVSDirFormat()]


controldir.ControlDirFormat.register_prober(CVSProber)

register_transport_proto(
    'cvs+pserver://', help="The pserver access protocol for CVS.")
