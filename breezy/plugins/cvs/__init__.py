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

from __future__ import absolute_import

from ... import version_info
from ...controldir import (
    ControlDirFormat,
    ControlDir,
    Prober,
    )

from ... import errors


class CVSUnsupportedError(errors.UnsupportedFormatError):

    _fmt = ("CVS working trees are not supported. To convert CVS projects to "
            "bzr, please see http://bazaar-vcs.org/BzrMigration and/or "
            "https://launchpad.net/launchpad-bazaar/+faq/26.")

    def __init__(self, format):
        bzrlib.errors.BzrError.__init__(self)
        self.format = format


class CVSDirFormat(ControlDirFormat):
    """The CVS directory control format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "CVS control directory."

    def initialize_on_transport(self, transport):
        raise bzrlib.errors.UninitializableFormat(self)

    def is_supported(self):
        return False

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
           basedir=None):
        raise CVSUnsupportedError(self)

    def supports_transport(self, transport):
        return False

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in 'CVS/'."""
        return CVSProber().probe_transport(transport)


class CVSProber(Prober):

    @classmethod
    def probe_transport(klass, transport):
        # little ugly, but works
        # try a manual probe first, its a little faster perhaps ?
        if not transport.has('CVS'):
            raise bzrlib.errors.NotBranchError(path=transport.base)
        if not transport.has('CVS/Repository'):
            raise bzrlib.errors.NotBranchError(path=transport.base)
        return CVSDirFormat()

    @classmethod
    def known_formats(cls):
        return set([CVSDirFormat()])

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        CVSProber().probe_transport(transport)
        raise NotImplementedError(self.open)


ControlDirFormat.register_prober(CVSProber)
ControlDirFormat.register_format(CVSDirFormat())
