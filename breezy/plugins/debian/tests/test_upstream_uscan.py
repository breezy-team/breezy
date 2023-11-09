#    test_upstream_uscan.py -- Test getting the upstream source from uscan
#    Copyright (C) 2012 Jelmer Vernooij
#
#    This file is part of brz-debian
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""Tests for the upstream uscan module."""

import tempfile

from ....tests import (
    TestCase,
    TestCaseWithTransport,
)
from ....transport import NoSuchFile
from ..upstream.uscan import (
    UScanError,
    UScanSource,
    _xml_report_extract_upstream_version,
    _xml_report_extract_warnings,
)


class UScanSourceTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.tree = self.make_branch_and_tree(".")

    def test_export_watchfile_none(self):
        src = UScanSource(self.tree, "", False)
        self.assertRaises(NoSuchFile, src._export_file, "watch", self.test_dir)

    def test_export_watchfile_top_level(self):
        src = UScanSource(self.tree, "", True)
        self.build_tree(["watch"])
        self.tree.add(["watch"])
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNot(src._export_file("watch", tmpdir), None)

    def test_export_watchfile(self):
        src = UScanSource(self.tree, "", False)
        self.build_tree(["debian/", "debian/watch"])
        self.tree.smart_add(["debian/watch"])
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNot(src._export_file("watch", tmpdir), None)


class UScanOutputParsingTests(TestCase):
    def test__xml_report_extract_upstream_version(self):
        text = b"""
<dehs>
<package>tdb</package>
<debian-uversion>1.2.8</debian-uversion>
<debian-mangled-uversion>1.2.8</debian-mangled-uversion>
<upstream-version>1.2.9</upstream-version>
<upstream-url>ftp://ftp.samba.org/pub/tdb/tdb-1.2.9.tar.gz</upstream-url>
<status>Newer version available</status>
</dehs>"""
        self.assertEqual("1.2.9", _xml_report_extract_upstream_version(text))

    def test__xml_report_extract_warnings(self):
        text = b"""
<dehs>
<package>tdb</package>
<debian-uversion>1.2.8</debian-uversion>
<debian-mangled-uversion>1.2.8</debian-mangled-uversion>
<upstream-version>1.2.9</upstream-version>
<upstream-url>ftp://ftp.samba.org/pub/tdb/tdb-1.2.9.tar.gz</upstream-url>
<status>Newer version available</status>
<warnings>this is a warning
with a newline</warnings>
</dehs>"""
        self.assertEqual(
            ["this is a warning\nwith a newline"],
            list(_xml_report_extract_warnings(text)),
        )

    def test__xml_report_extract_upstream_version_warnings(self):
        text = b"""
<dehs>
<package>tdb</package>
<warnings>uscan warning: Unable to determine current version
in debian/watch, skipping:
ftp://ftp.samba.org/pub/tdb/tdb-(.+).tar.gz</warnings>
</dehs>
"""
        self.assertIs(None, _xml_report_extract_upstream_version(text))

    def test__xml_report_extract_upstream_version_noise(self):
        text = b"""
<dehs>
blahf =>
<package>tdb</package>
<debian-uversion>1.2.8</debian-uversion>
<upstream-version>1.2.9</upstream-version>
<warnings>uscan warning: Unable to determine current version
in debian/watch, skipping:
ftp://ftp.samba.org/pub/tdb/tdb-(.+).tar.gz</warnings>
</dehs>
"""
        self.assertEqual("1.2.9", _xml_report_extract_upstream_version(text))

    def test__xml_report_extract_upstream_version_errors(self):
        text = b"""
<dehs>
blahf =>
<package>tdb</package>
<debian-uversion>1.2.8</debian-uversion>
<errors>something something signature</errors>
</dehs>
"""
        self.assertRaises(UScanError, _xml_report_extract_upstream_version, text)
