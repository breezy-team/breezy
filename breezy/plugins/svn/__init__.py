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

from ... import version_info  # noqa: F401

from ... import (
    controldir,
    errors,
    transport as _mod_transport,
    )
from ...revisionspec import (
    revspec_registry,
    )


class SubversionUnsupportedError(errors.UnsupportedFormatError):

    _fmt = ('Subversion branches are not yet supported. '
            'To interoperate with Subversion branches, use fastimport.')


class SvnWorkingTreeDirFormat(controldir.ControlDirFormat):
    """Subversion directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Subversion working directory"

    def initialize_on_transport(self, transport):
        raise errors.UninitializableFormat(format=self)

    def is_supported(self):
        return False

    def supports_transport(self, transport):
        return False

    def check_support_status(self, allow_unsupported, recommend_upgrade=True,
                             basedir=None):
        raise SubversionUnsupportedError(format=self)

    def open(self, transport):
        # Raise NotBranchError if there is nothing there
        SvnWorkingTreeProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class SvnWorkingTreeProber(controldir.Prober):

    @classmethod
    def priority(klass, transport):
        return 100

    def probe_transport(self, transport):
        try:
            transport.local_abspath('.')
        except errors.NotLocalUrl:
            raise errors.NotBranchError(path=transport.base)
        else:
            if transport.has(".svn"):
                return SvnWorkingTreeDirFormat()
            raise errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        return [SvnWorkingTreeDirFormat()]


class SvnRepositoryFormat(controldir.ControlDirFormat):
    """Subversion directory format."""

    def get_converter(self):
        raise NotImplementedError(self.get_converter)

    def get_format_description(self):
        return "Subversion repository"

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
        SvnRepositoryProber().probe_transport(transport)
        raise NotImplementedError(self.open)


class SvnRepositoryProber(controldir.Prober):

    _supported_schemes = ["http", "https", "file", "svn"]

    @classmethod
    def priority(klass, transport):
        if 'svn' in transport.base:
            return 90
        return 100

    def probe_transport(self, transport):
        try:
            url = transport.external_url()
        except errors.InProcessTransport:
            raise errors.NotBranchError(path=transport.base)

        scheme = url.split(":")[0]
        if scheme.startswith("svn+") or scheme == "svn":
            raise SubversionUnsupportedError()

        if scheme not in self._supported_schemes:
            raise errors.NotBranchError(path=transport.base)

        if scheme == 'file':
            # Cheaper way to figure out if there is a svn repo
            maybe = False
            subtransport = transport
            while subtransport:
                try:
                    if all([subtransport.has(name)
                            for name in ["format", "db", "conf"]]):
                        maybe = True
                        break
                except UnicodeEncodeError:
                    pass
                prevsubtransport = subtransport
                subtransport = prevsubtransport.clone("..")
                if subtransport.base == prevsubtransport.base:
                    break
            if not maybe:
                raise errors.NotBranchError(path=transport.base)

        # If this is a HTTP transport, use the existing connection to check
        # that the remote end supports version control.
        if scheme in ("http", "https"):
            priv_transport = getattr(transport, "_decorated", transport)
            try:
                headers = priv_transport._options('.')
            except (errors.InProcessTransport, _mod_transport.NoSuchFile,
                    errors.InvalidHttpResponse):
                raise errors.NotBranchError(path=transport.base)
            else:
                dav_entries = set()
                for key, value in headers:
                    if key.upper() == 'DAV':
                        dav_entries.update(
                            [x.strip() for x in value.split(',')])
                if "version-control" not in dav_entries:
                    raise errors.NotBranchError(path=transport.base)

        return SvnRepositoryFormat()

    @classmethod
    def known_formats(cls):
        return [SvnRepositoryFormat()]


controldir.ControlDirFormat.register_prober(SvnWorkingTreeProber)
controldir.ControlDirFormat.register_prober(SvnRepositoryProber)


revspec_registry.register_lazy("svn:", __name__ + ".revspec", "RevisionSpec_svn")


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
