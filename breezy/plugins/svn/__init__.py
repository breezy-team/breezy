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

from __future__ import absolute_import

from ... import version_info  # noqa: F401

from ... import (
    controldir,
    errors,
    transport as _mod_transport,
    )


class SubversionUnsupportedError(errors.UnsupportedFormatError):

    _fmt = ('Subversion branches are not yet supported. '
            'To convert Subversion branches to Bazaar branches or vice versa, '
            'use the fastimport format.')


class SvnWorkingTreeDirFormat(controldir.ControlDirFormat):
    """Subversion directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Subversion working directory"

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
                             basedir=None):
        raise SubversionUnsupportedError()

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        SvnWorkingTreeProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class SvnWorkingTreeProber(controldir.Prober):

    def probe_transport(self, transport):
        from breezy.transport.local import LocalTransport

        if (not isinstance(transport, LocalTransport)
                or not transport.has(".svn")):
            raise errors.NotBranchError(path=transport.base)

        return SvnWorkingTreeDirFormat()

    @classmethod
    def known_formats(cls):
        return [SvnWorkingTreeDirFormat()]


controldir.ControlDirFormat.register_prober(SvnWorkingTreeProber)


_mod_transport.register_transport_proto(
    'svn+ssh://',
    help="Access using the Subversion smart server tunneled over SSH.")
_mod_transport.register_transport_proto(
    'svn+http://')
_mod_transport.register_transport_proto(
    'svn+https://')
_mod_transport.register_transport_proto(
    'svn://',
    help="Access using the Subversion smart server.")
