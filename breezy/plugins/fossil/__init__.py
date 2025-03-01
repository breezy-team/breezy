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
    vcs = "fossil"

    _fmt = (
        "Fossil branches are not yet supported. "
        "To interoperate with Fossil branches, use fastimport."
    )


class FossilDirFormat(controldir.ControlDirFormat):
    """Fossil directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Fossil control directory"

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(format=self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        raise FossilUnsupportedError(format=self)

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        RemoteFossilProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class RemoteFossilProber(controldir.Prober):
    @classmethod
    def priority(klass, transport):
        return 95

    @classmethod
    def probe_transport(klass, transport):
        from breezy.transport.http.urllib import HttpTransport

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
        return [FossilDirFormat()]


controldir.ControlDirFormat.register_prober(RemoteFossilProber)
