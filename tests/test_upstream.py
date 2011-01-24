#    test_upstream.py -- Test getting the upstream source
#    Copyright (C) 2009 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
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

# We have a bit of a problem with testing the actual uscan etc. integration,
# so just mock them.

"""Tests for the upstream module."""


import os

from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    )
from bzrlib.plugins.builddeb.errors import (
    PackageVersionNotPresent,
    WatchFileMissing,
    )
from bzrlib.plugins.builddeb.upstream import (
    AptSource,
    StackedUpstreamSource,
    UpstreamBranchSource,
    UScanSource,
    )


class MockSources(object):

    def __init__(self, versions):
        self.restart_called_times = 0
        self.lookup_called_times = 0
        self.lookup_package = None
        self.versions = versions
        self.version = None

    def restart(self):
        self.restart_called_times += 1

    def lookup(self, package):
        self.lookup_called_times += 1
        assert not self.lookup_package or self.lookup_package == package
        self.lookup_package = package
        if self.lookup_called_times <= len(self.versions):
            self.version = self.versions[self.lookup_called_times-1]
            return True
        else:
            self.version = None
            return False


class MockAptPkg(object):

    def __init__(self, sources):
        self.init_called_times = 0
        self.get_pkg_source_records_called_times = 0
        self.sources = sources

    def init(self):
        self.init_called_times += 1

    def SourceRecords(self):
        self.get_pkg_source_records_called_times += 1
        return self.sources


class MockAptCaller(object):

    def __init__(self, work=False):
        self.work = work
        self.called = 0
        self.package = None
        self.version_str = None
        self.target_dir = None

    def call(self, package, version_str, target_dir):
        self.package = package
        self.version_str = version_str
        self.target_dir = target_dir
        self.called += 1
        return self.work


class AptSourceTests(TestCase):

    def test_get_apt_command_for_source(self):
        self.assertEqual("apt-get source -y --only-source --tar-only "
                "apackage=someversion",
                AptSource()._get_command("apackage", "someversion"))

    def test_apt_provider_no_package(self):
        caller = MockAptCaller()
        sources = MockSources([])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarball,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(1, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_wrong_version(self):
        caller = MockAptCaller()
        sources = MockSources(["0.1-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarball,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_right_version(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        src.fetch_tarball("apackage", "0.2", "target", 
            _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        # Only called twice means it stops when the command works.
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(1, caller.called)
        self.assertEqual("apackage", caller.package)
        self.assertEqual("0.2-1", caller.version_str)
        self.assertEqual("target", caller.target_dir)

    def test_apt_provider_right_version_command_fails(self):
        caller = MockAptCaller()
        sources = MockSources(["0.1-1", "0.2-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarball,
            "apackage", "0.2", "target", 
            _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        # Only called twice means it stops when the command fails.
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(1, caller.called)
        self.assertEqual("apackage", caller.package)
        self.assertEqual("0.2-1", caller.version_str)
        self.assertEqual("target", caller.target_dir)


class RecordingSource(object):

    def __init__(self, succeed, latest=None):
        self._succeed = succeed
        self._specific_versions = []
        self._latest = latest

    def get_latest_version(self, package, current_version):
        return self._latest

    def fetch_tarball(self, package, version, target_dir):
        self._specific_versions.append((package, version, target_dir))
        if not self._succeed:
            raise PackageVersionNotPresent(package, version, self)

    def __repr__(self):
        return "%s()" % self.__class__.__name__


class StackedUpstreamSourceTests(TestCase):

    def test_fetch_tarball_first_wins(self):
        a = RecordingSource(False)
        b = RecordingSource(True)
        c = RecordingSource(False)
        stack = StackedUpstreamSource([a, b, c])
        stack.fetch_tarball("mypkg", "1.0", "bla")
        self.assertEquals([("mypkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("mypkg", "1.0", "bla")], a._specific_versions)
        self.assertEquals([], c._specific_versions)

    def test_get_latest_version_first_wins(self):
        a = RecordingSource(False, latest="1.1")
        b = RecordingSource(False, latest="1.2")
        stack = StackedUpstreamSource([a, b])
        self.assertEquals("1.1", stack.get_latest_version("mypkg", "1.0"))

    def test_repr(self):
        self.assertEquals("StackedUpstreamSource([])", 
                repr(StackedUpstreamSource([])))
        self.assertEquals("StackedUpstreamSource([RecordingSource()])", 
                repr(StackedUpstreamSource([RecordingSource(False)])))

    def test_none(self):
        a = RecordingSource(False)
        b = RecordingSource(False)
        stack = StackedUpstreamSource([a, b])
        self.assertRaises(PackageVersionNotPresent, 
                stack.fetch_tarball, "pkg", "1.0", "bla")
        self.assertEquals([("pkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("pkg", "1.0", "bla")], a._specific_versions)


class UScanSourceTests(TestCaseWithTransport):

    def setUp(self):
        super(UScanSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')

    def test_export_watchfile_none(self):
        src = UScanSource(self.tree, False)
        self.assertRaises(WatchFileMissing, src._export_watchfile)

    def test_export_watchfile_larstiq(self):
        src = UScanSource(self.tree, True)
        self.build_tree(['watch'])
        self.assertRaises(WatchFileMissing, src._export_watchfile)
        self.tree.add(['watch'])
        self.assertTrue(src._export_watchfile() is not None)

    def test_export_watchfile(self):
        src = UScanSource(self.tree, False)
        self.build_tree(['debian/', 'debian/watch'])
        self.assertRaises(WatchFileMissing, src._export_watchfile)
        self.tree.smart_add(['debian/watch'])
        self.assertTrue(src._export_watchfile() is not None)

    def test__xml_report_extract_upstream_version(self):
        self.assertEquals("1.2.9",
            UScanSource._xml_report_extract_upstream_version("""
<dehs>
<package>tdb</package>
<debian-uversion>1.2.8</debian-uversion>
<debian-mangled-uversion>1.2.8</debian-mangled-uversion>
<upstream-version>1.2.9</upstream-version>
<upstream-url>ftp://ftp.samba.org/pub/tdb/tdb-1.2.9.tar.gz</upstream-url>
<status>Newer version available</status>
</dehs>"""))

    def test__xml_report_extract_upstream_version_warnings(self):
        self.assertIs(None,
            UScanSource._xml_report_extract_upstream_version("""
<dehs>
<package>tdb</package>
<warnings>uscan warning: Unable to determine current version
in debian/watch, skipping:
ftp://ftp.samba.org/pub/tdb/tdb-(.+).tar.gz</warnings>
</dehs>
"""))

class UpstreamBranchSourceTests(TestCaseWithTransport):
    """Tests for UpstreamBranchSource."""

    def setUp(self):
        super(UpstreamBranchSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')

    def test_fetch_tarball(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("1.0", self.tree.branch.last_revision())
        source = UpstreamBranchSource(self.tree.branch,
            {"1.0": self.tree.branch.last_revision()})
        os.mkdir("mydir")
        self.assertEquals("mydir/foo_1.0.orig.tar.gz",
            source.fetch_tarball("foo", "1.0", "mydir"))
        self.failUnlessExists("mydir/foo_1.0.orig.tar.gz")

    def test_fetch_tarball_not_found(self):
        source = UpstreamBranchSource(self.tree.branch)
        self.tree.commit("msg")
        self.assertRaises(PackageVersionNotPresent,
            source.fetch_tarball, "foo", "1.0", "mydir")

    def test_get_latest_version(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        source = UpstreamBranchSource(self.tree.branch,
            {"2.1": self.tree.branch.last_revision()})
        self.assertEquals("2.1", source.get_latest_version("foo", "1.0"))
        self.tree.commit("msg")
        self.assertEquals("2.1+bzr2", source.get_latest_version("foo", "1.0"))

