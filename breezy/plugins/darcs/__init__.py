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

from ... import version_info  # noqa: F401
from breezy import (
    controldir,
    errors,
    )


class DarcsUnsupportedError(errors.UnsupportedFormatError):

    _fmt = ('Darcs branches are not yet supported. '
            'To interoperate with darcs branches, use fastimport.')


class DarcsDirFormat(controldir.ControlDirFormat):
    """Darcs directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "darcs control directory"

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    @classmethod
    def _known_formats(self):
        return set([DarcsDirFormat()])

    def open(self, transport, _found=False):
        """Open this directory."""
        raise DarcsUnsupportedError()

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
                             basedir=None):
        raise DarcsUnsupportedError()

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        DarcsProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class DarcsProber(controldir.Prober):

    @classmethod
    def priority(klass, transport):
        if 'darcs' in transport.base:
            return 90
        return 100

    @classmethod
    def probe_transport(klass, transport):
        if transport.has_any(['_darcs/format', '_darcs/inventory']):
            return DarcsDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        return [DarcsDirFormat()]


controldir.ControlDirFormat.register_prober(DarcsProber)
