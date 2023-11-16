# Copyright (C) 2006 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from ...testament import StrictTestament3
from ..bundle_data import BundleInfo
from . import _get_bundle_header
from .v08 import BundleReader, BundleSerializerV08

"""Serializer for bundle format 0.9"""


class BundleSerializerV09(BundleSerializerV08):
    """Serializer for bzr bundle format 0.9.

    This format supports rich root data, for the nested-trees work, but also
    supports repositories that don't have rich root data.  It cannot be
    used to transfer from a knit2 repo into a knit1 repo, because that would
    be lossy.
    """

    def check_compatible(self):
        pass

    def _write_main_header(self):
        """Write the header for the changes."""
        f = self.to_file
        f.write(_get_bundle_header("0.9") + b"#\n")

    def _testament_sha1(self, revision_id):
        return StrictTestament3.from_revision(self.source, revision_id).as_sha1()

    def read(self, f):
        """Read the rest of the bundles from the supplied file.

        :param f: The file to read from
        :return: A list of bundles
        """
        return BundleReaderV09(f).info


class BundleInfo09(BundleInfo):
    """BundleInfo that uses StrictTestament3.

    This means that the root data is included in the testament.
    """

    def _testament_sha1_from_revision(self, repository, revision_id):
        testament = StrictTestament3.from_revision(repository, revision_id)
        return testament.as_sha1()

    def _testament(self, revision, tree):
        return StrictTestament3(revision, tree)


class BundleReaderV09(BundleReader):
    """BundleReader for 0.9 bundles."""

    def _get_info(self):
        return BundleInfo09()
