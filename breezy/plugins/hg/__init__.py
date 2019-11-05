# Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Mercurial foreign branch support.

Currently only tells the user that Mercurial is not supported.
"""

from __future__ import absolute_import

from ... import version_info  # noqa: F401

from ... import (
    controldir,
    errors,
    )


class MercurialUnsupportedError(errors.UnsupportedFormatError):

    _fmt = ('Mercurial branches are not yet supported. '
            'To convert Mercurial branches to Bazaar branches or vice versa, '
            'use the fastimport format. ')


class HgDirFormat(controldir.ControlDirFormat):
    """Mercurial directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Mercurial control directory"

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
                             basedir=None):
        raise MercurialUnsupportedError()

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        LocalHgProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class LocalHgProber(controldir.Prober):

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport has a '.hg/' subdir."""
        if transport.has('.hg'):
            return HgDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        return [HgDirFormat()]


controldir.ControlDirFormat.register_prober(LocalHgProber)
