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

from __future__ import absolute_import

from breezy import (
    controldir,
    errors,
    )


class DarcsDirFormat(controldir.ControlDirFormat):
    """Darcs directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "darcs control directory"

    def initialize_on_transport(self, transport):
        raise NotImplementedError(self.get_converter)

    @classmethod
    def _known_formats(self):
        return set([DarcsDirFormat()])

    def open(self, transport, _found=False):
        """Open this directory."""
        raise errors.BzrCommandError(
            'Darcs branches are not yet supported. '
            'To convert darcs branches to Bazaar branches or vice versa, '
            'use bzr-fastimport. See http://bazaar-vcs.org/BzrMigration.')

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport has a '_darcs/' subdir."""
        format = klass()
        if transport.has('_darcs'):
            return format
        raise errors.NotBranchError(path=transport.base)


controldir.ControlDirFormat.register_control_format(DarcsDirFormat)
