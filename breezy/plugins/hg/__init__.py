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

from ... import (
    controldir,
    errors,
    transport as _mod_transport,
    )

from ... import version_info  # noqa: F401


class MercurialUnsupportedError(errors.UnsupportedFormatError):

    _fmt = ('Mercurial branches are not yet supported. '
            'To interoperate with Mercurial, use the fastimport format.')


class LocalHgDirFormat(controldir.ControlDirFormat):
    """Mercurial directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Local Mercurial control directory"

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
                             basedir=None):
        raise MercurialUnsupportedError(format=self)

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        LocalHgProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class LocalHgProber(controldir.Prober):

    @classmethod
    def priority(klass, transport):
        return 100

    @staticmethod
    def _has_hg_dumb_repository(transport):
        try:
            return transport.has_any([".hg/requires", ".hg/00changelog.i"])
        except (_mod_transport.NoSuchFile, errors.PermissionDenied,
                errors.InvalidHttpResponse):
            return False

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport has a '.hg/' subdir."""
        if klass._has_hg_dumb_repository(transport):
            return LocalHgDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        return [LocalHgDirFormat()]


class SmartHgDirFormat(controldir.ControlDirFormat):
    """Mercurial directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Smart Mercurial control directory"

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
        SmartHgProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class SmartHgProber(controldir.Prober):

    # Perhaps retrieve list from mercurial.hg.schemes ?
    _supported_schemes = ["http", "https"]

    @classmethod
    def priority(klass, transport):
        if 'hg' in transport.base:
            return 90
        # hgweb repositories are prone to return *a* page for every possible URL,
        # making probing hard for other formats so use 99 here rather than 100.
        return 99

    @staticmethod
    def _has_hg_http_smart_server(transport, external_url):
        """Check if there is a Mercurial smart server at the remote location.

        :param transport: Transport to check
        :param externa_url: External URL for transport
        :return: Boolean indicating whether transport is backed onto hg
        """
        from breezy.urlutils import urlparse
        parsed_url = urlparse.urlparse(external_url)
        parsed_url = parsed_url._replace(query='cmd=capabilities')
        url = urlparse.urlunparse(parsed_url)
        resp = transport.request(
            'GET', url, headers={'Accept': 'application/mercurial-0.1'})
        if resp.status == 404:
            return False
        if resp.status == 406:
            # The server told us that it can't handle our Accept header.
            return False
        ct = resp.getheader("Content-Type")
        if ct is None:
            return False
        return ct.startswith("application/mercurial")

    @classmethod
    def probe_transport(klass, transport):
        try:
            external_url = transport.external_url()
        except errors.InProcessTransport:
            raise errors.NotBranchError(path=transport.base)
        scheme = external_url.split(":")[0]
        if scheme not in klass._supported_schemes:
            raise errors.NotBranchError(path=transport.base)
        from breezy import urlutils
        external_url = urlutils.strip_segment_parameters(external_url)
        # Explicitly check for .hg directories here, so we avoid
        # loading foreign branches through Mercurial.
        if (external_url.startswith("http:") or
                external_url.startswith("https:")):
            if klass._has_hg_http_smart_server(transport, external_url):
                return SmartHgDirFormat()
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        return [SmartHgDirFormat()]


controldir.ControlDirFormat.register_prober(LocalHgProber)
controldir.ControlDirFormat.register_prober(SmartHgProber)
