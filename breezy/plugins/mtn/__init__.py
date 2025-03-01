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
    vcs = "mtn"

    _fmt = (
        "Monotone branches are not yet supported. "
        "To interoperate with Monotone branches, "
        "use fastimport."
    )


class MonotoneDirFormat(controldir.ControlDirFormat):
    """Monotone directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Monotone control directory"

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        raise MonotoneUnsupportedError(format=self)

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        MonotoneProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class MonotoneProber(controldir.Prober):
    @classmethod
    def priority(klass, transport):
        return 100

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport has a '_MTN/' subdir."""
        if transport.has("_MTN"):
            return MonotoneDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        return [MonotoneDirFormat()]


controldir.ControlDirFormat.register_prober(MonotoneProber)
