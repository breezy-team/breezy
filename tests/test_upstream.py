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

from __future__ import absolute_import

from base64 import standard_b64encode

import bz2
import os
import shutil
import tempfile
import tarfile
import zipfile

from ....revision import (
    NULL_REVISION,
    Revision,
    )
from ....tests import (
    TestCase,
    )
from ....errors import NoSuchFile
from ....tests.features import (
    ModuleAvailableFeature,
    PluginLoadedFeature,
    )
from ..config import (
    DebBuildConfig,
    )
from ..errors import (
    MissingUpstreamTarball,
    PackageVersionNotPresent,
    )

from . import (
    LzmaFeature,
    XzFeature,
    make_new_upstream_tarball_xz,
    TestCaseWithTransport,
    )
from ..upstream import (
    AptSource,
    StackedUpstreamSource,
    TarfileSource,
    UpstreamProvider,
    UpstreamSource,
    UScanSource,
    UScanError,
    extract_tarball_version,
    gather_orig_files,
    new_tarball_name,
    )
from ..util import (
    component_from_orig_tarball,
    )
from ..upstream.branch import (
    guess_upstream_revspec,
    get_export_upstream_revision,
    get_snapshot_revision,
    LazyUpstreamBranchSource,
    UpstreamBranchSource,
    _upstream_branch_version,
    upstream_tag_to_version,
    upstream_version_add_revision
    )
from ..upstream.pristinetar import (
    PristineTarSource,
    is_upstream_tag,
    revision_pristine_tar_format,
    revision_pristine_tar_delta,
    upstream_tag_version,
    )


svn_plugin = ModuleAvailableFeature('breezy.plugins.svn.mapping')
dulwich = ModuleAvailableFeature('dulwich')


class MockSources(object):

    def __init__(self, versions, files):
        self.restart_called_times = 0
        self.lookup_called_times = 0
        self.lookup_package = None
        self.versions = versions
        self.version = None
        self.filess = files
        self.files = None

    def restart(self):
        self.restart_called_times += 1

    def lookup(self, package):
        self.lookup_called_times += 1
        assert not self.lookup_package or self.lookup_package == package
        self.lookup_package = package
        if self.lookup_called_times <= len(self.versions):
            self.version = self.versions[self.lookup_called_times-1]
            self.files = self.filess[self.lookup_called_times-1]
            return True
        else:
            self.version = None
            self.files = None
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
        self.assertEqual(
            "apt-get source -y --only-source --tar-only "
            "apackage=someversion",
            AptSource()._get_command("apackage", "someversion"))

    def test_apt_provider_no_package(self):
        caller = MockAptCaller()
        sources = MockSources([], [])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(
            PackageVersionNotPresent, src.fetch_tarballs,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(1, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_wrong_version(self):
        caller = MockAptCaller()
        sources = MockSources(
            ["0.1-1"],
            [[("checksum", 0, "apackage_0.1.orig.tar.gz", "tar")]])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(
            PackageVersionNotPresent, src.fetch_tarballs,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_multiple_tarballs(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"],
            [[("checksum", 0, "apackage_0.1.orig.tar.gz", "tar")],
             [("checksum", 0, "apackage_0.2.orig.tar.bz2", "tar"),
              ("checksum", 1, "apackage_0.2.orig-extra.tar.gz", "tar")]])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        paths = src.fetch_tarballs("apackage", "0.2", "target",
            _apt_pkg=apt_pkg)
        self.assertEquals(paths, [
            "target/apackage_0.2.orig.tar.bz2",
            "target/apackage_0.2.orig-extra.tar.gz"])

    def test_apt_provider_right_version_bz2(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"],
            [[("checksum", 0, "apackage_0.1.orig.tar.gz", "tar")],
             [("checksum", 0, "apackage_0.2.orig.tar.bz2", "tar")]])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        paths = src.fetch_tarballs("apackage", "0.2", "target",
            _apt_pkg=apt_pkg)
        self.assertEquals(paths, ["target/apackage_0.2.orig.tar.bz2"])

    def test_apt_provider_right_version_xz(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"],
            [[("checksum", 0, "apackage_0.1.orig.tar.gz", "tar")],
             [("checksum", 0, "apackage_0.2.orig.tar.xz", "tar")]])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        paths = src.fetch_tarballs("apackage", "0.2", "target",
            _apt_pkg=apt_pkg)
        self.assertEquals(paths, ["target/apackage_0.2.orig.tar.xz"])

    def test_apt_provider_right_version(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"],
            [[("checksum", 0, "apackage_0.1.orig.tar.gz", "tar")],
             [("checksum", 0, "apackage_0.2.orig.tar.gz", "tar")]])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        paths = src.fetch_tarballs("apackage", "0.2", "target",
            _apt_pkg=apt_pkg)
        self.assertEquals(paths, ["target/apackage_0.2.orig.tar.gz"])
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
        sources = MockSources(["0.1-1", "0.2-1"],
            [[("checksum", 0, "apackage_0.1.orig.tar.gz", "tar")],
             [("checksum", 0, "apackage_0.2.orig.tar.gz", "tar")]])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarballs,
            "apackage", "0.2", "target",
            _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        # Only called twice means it stops when the command fails.
        self.assertEqual(3, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(1, caller.called)
        self.assertEqual("apackage", caller.package)
        self.assertEqual("0.2-1", caller.version_str)
        self.assertEqual("target", caller.target_dir)

    def test_apt_provider_right_version_is_native(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"],
            [[("checksum", 0, "apackage_0.1.orig.tar.gz", "tar")],
             [("checksum", 0, "apackage_0.2-1.orig.tar.gz", "tar")]])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarballs,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(3, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)


class RecordingSource(UpstreamSource):

    def __init__(self, succeed, latest=None, recent=None):
        self._succeed = succeed
        self._specific_versions = []
        if recent:
            recent.sort()
        if latest is None and recent:
            latest = recent[-1]
        self._latest = latest
        if recent is None and latest:
            recent = [latest]
        self._recent = recent

    def get_latest_version(self, package, current_version):
        return self._latest

    def get_recent_versions(self, package, since_version=None):
        return [v for v in self._recent
                if since_version is None or v > since_version]

    def fetch_tarballs(self, package, version, target_dir, components=None):
        self._specific_versions.append((package, version, target_dir))
        if not self._succeed:
            raise PackageVersionNotPresent(package, version, self)
        return [self._tarball_path(package, version, None, target_dir)]

    def __repr__(self):
        return "%s()" % self.__class__.__name__


class StackedUpstreamSourceTests(TestCase):

    def test_fetch_tarballs_first_wins(self):
        a = RecordingSource(False)
        b = RecordingSource(True)
        c = RecordingSource(False)
        stack = StackedUpstreamSource([a, b, c])
        stack.fetch_tarballs("mypkg", "1.0", "bla")
        self.assertEquals([("mypkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("mypkg", "1.0", "bla")], a._specific_versions)
        self.assertEquals([], c._specific_versions)

    def test_get_latest_version_first_wins(self):
        a = RecordingSource(False, latest="1.1")
        b = RecordingSource(False, latest="1.2")
        stack = StackedUpstreamSource([a, b])
        self.assertEquals("1.1", stack.get_latest_version("mypkg", "1.0"))

    def test_get_recent_versions(self):
        a = RecordingSource(False, recent=["1.0", "1.1"])
        b = RecordingSource(False, recent=["1.1", "1.2"])
        stack = StackedUpstreamSource([a, b])
        self.assertEquals(
            ["1.0", "1.1", "1.2"], stack.get_recent_versions("mypkg", "0.9"))
        self.assertEquals(
            ["1.0", "1.1", "1.2"], stack.get_recent_versions("mypkg"))
        self.assertEquals(
            ["1.2"], stack.get_recent_versions("mypkg", "1.1"))

    def test_repr(self):
        self.assertEquals(
            "StackedUpstreamSource([])",
            repr(StackedUpstreamSource([])))
        self.assertEquals(
            "StackedUpstreamSource([RecordingSource()])",
            repr(StackedUpstreamSource([RecordingSource(False)])))

    def test_none(self):
        a = RecordingSource(False)
        b = RecordingSource(False)
        stack = StackedUpstreamSource([a, b])
        self.assertRaises(PackageVersionNotPresent,
                stack.fetch_tarballs, "pkg", "1.0", "bla")
        self.assertEquals([("pkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("pkg", "1.0", "bla")], a._specific_versions)


class UScanSourceTests(TestCaseWithTransport):

    def setUp(self):
        super(UScanSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')

    def test_export_watchfile_none(self):
        src = UScanSource(self.tree, '', False)
        self.assertRaises(NoSuchFile, src._export_file, 'watch', self.test_dir)

    def test_export_watchfile_top_level(self):
        src = UScanSource(self.tree, '', True)
        self.build_tree(['watch'])
        self.tree.add(['watch'])
        tmpdir = tempfile.mkdtemp()
        try:
            self.assertIsNot(src._export_file('watch', tmpdir), None)
        finally:
            shutil.rmtree(tmpdir)

    def test_export_watchfile(self):
        src = UScanSource(self.tree, '', False)
        self.build_tree(['debian/', 'debian/watch'])
        self.tree.smart_add(['debian/watch'])
        tmpdir = tempfile.mkdtemp()
        try:
            self.assertIsNot(src._export_file('watch', tmpdir), None)
        finally:
            shutil.rmtree(tmpdir)

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
        self.assertEquals("1.2.9",
            UScanSource._xml_report_extract_upstream_version(text))

    def test__xml_report_extract_upstream_version_warnings(self):
        text = b"""
<dehs>
<package>tdb</package>
<warnings>uscan warning: Unable to determine current version
in debian/watch, skipping:
ftp://ftp.samba.org/pub/tdb/tdb-(.+).tar.gz</warnings>
</dehs>
"""
        self.assertIs(
            None,
            UScanSource._xml_report_extract_upstream_version(text))

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
        self.assertEquals("1.2.9",
            UScanSource._xml_report_extract_upstream_version(text))

    def test__xml_report_extract_upstream_version_errors(self):
        text = b"""
<dehs>
blahf =>
<package>tdb</package>
<debian-uversion>1.2.8</debian-uversion>
<errors>something something signature</errors>
</dehs>
"""
        self.assertRaises(
            UScanError,
            UScanSource._xml_report_extract_upstream_version, text)


class GuessUpstreamRevspecTests(TestCase):

    def test_guess_upstream_revspec(self):
        self.assertEqual(
                [u'tag:1.2', u'tag:foo-1.2', u'tag:v1.2', u'tag:v.1.2'],
                list(guess_upstream_revspec('foo', '1.2')))

    def test_snapshot(self):
        self.assertEqual(
                [u'revno:1200', u'tag:1.2+bzr1200', u'tag:foo-1.2+bzr1200',
                 u'tag:v1.2+bzr1200', u'tag:v.1.2+bzr1200'],
                list(guess_upstream_revspec('foo', '1.2+bzr1200')))
        self.assertEqual(
                [u'revno:1200', u'tag:1.2~bzr1200', u'tag:foo-1.2~bzr1200',
                 u'tag:v1.2~bzr1200', u'tag:v.1.2~bzr1200'],
                list(guess_upstream_revspec('foo', '1.2~bzr1200')))
        self.assertEqual(
                [u'git:abc1def', u'date:2018-01-01', u'tag:1.2~git20180101.abc1def',
                 u'tag:foo-1.2~git20180101.abc1def',
                 u'tag:v1.2~git20180101.abc1def',
                 u'tag:v.1.2~git20180101.abc1def'],
                list(guess_upstream_revspec('foo', '1.2~git20180101.abc1def')))
        self.assertEqual(
                [u'git:abc1def', u'date:2018-01-01', u'tag:1.2~git20180101.0.abc1def',
                 u'tag:foo-1.2~git20180101.0.abc1def',
                 u'tag:v1.2~git20180101.0.abc1def',
                 u'tag:v.1.2~git20180101.0.abc1def'],
                list(guess_upstream_revspec('foo', '1.2~git20180101.0.abc1def')))
        self.assertEqual(
                [u'date:2018-01-01', u'tag:1.2~git20180101',
                 u'tag:foo-1.2~git20180101',
                 u'tag:v1.2~git20180101', u'tag:v.1.2~git20180101'],
                list(guess_upstream_revspec('foo', '1.2~git20180101')))


class UpstreamBranchSourceTests(TestCaseWithTransport):
    """Tests for UpstreamBranchSource."""

    def setUp(self):
        super(UpstreamBranchSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('upstream')

    def test_fetch_tarballs(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("1.0", self.tree.branch.last_revision())
        source = UpstreamBranchSource(self.tree.branch,
            {"1.0": self.tree.branch.last_revision().decode('utf-8')})
        os.mkdir("mydir")
        self.assertEquals(["mydir/foo_1.0.orig.tar.gz"],
            source.fetch_tarballs("foo", "1.0", "mydir"))
        self.assertPathExists("mydir/foo_1.0.orig.tar.gz")

    def test_fetch_tarballs_not_found(self):
        source = UpstreamBranchSource(self.tree.branch)
        self.tree.commit("msg")
        self.assertRaises(PackageVersionNotPresent,
            source.fetch_tarballs, "foo", "1.0", "mydir")

    def test_get_latest_version(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        source = UpstreamBranchSource(self.tree.branch,
            {"2.1": self.tree.branch.last_revision().decode('utf-8')})
        self.assertEquals("2.1", source.get_latest_version("foo", "1.0"))
        self.tree.commit("msg")
        self.assertEquals("2.1+bzr2", source.get_latest_version("foo", "1.0"))

    def test_get_recent_versions(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        source = UpstreamBranchSource(
            self.tree.branch,
            {"2.1": self.tree.branch.last_revision().decode('utf-8')})
        self.assertEquals(["2.1"], source.get_recent_versions("foo", "1.0"))
        revid2 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag('2.2', revid2)
        self.assertEquals(
            ["2.1", "2.2"],
            source.get_recent_versions("foo", "1.0"))

    def test_version_as_revisions(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        config = DebBuildConfig(
            [('user.conf', True), ('default.conf', False)],
            branch=self.tree.branch)
        source = UpstreamBranchSource(self.tree.branch,
            {"2.1": self.tree.branch.last_revision().decode('utf-8')},
            config=config)
        revid2 = self.tree.commit("msg")
        self.assertEquals(revid2,
            source.version_as_revision("foo", u"2.1+bzr2"))
        self.assertEquals({None: revid1}, source.version_as_revisions("foo", u"2.1"))

    def test_version_as_revision(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        config = DebBuildConfig(
            [('user.conf', True), ('default.conf', False)],
            branch=self.tree.branch)
        source = UpstreamBranchSource(self.tree.branch,
            {"2.1": self.tree.branch.last_revision().decode('utf-8')},
            config=config)
        revid2 = self.tree.commit("msg")
        self.assertEquals(revid2,
            source.version_as_revision("foo", "2.1+bzr2"))
        self.assertEquals(revid1, source.version_as_revision("foo", "2.1"))

    def test_version_as_revision_no_revspec(self):
        # There is no relevant revspec known
        config = DebBuildConfig(
            [('user.conf', True), ('default.conf', False)],
            branch=self.tree.branch)
        source = UpstreamBranchSource(self.tree.branch, {}, config=config)
        self.assertRaises(PackageVersionNotPresent,
            source.version_as_revision, "foo", "2.1")

    def test_version_as_revision_invalid_revspec(self):
        # There is no relevant revspec known
        config = DebBuildConfig(
            [('user.conf', True), ('default.conf', False)],
            branch=self.tree.branch)
        source = UpstreamBranchSource(self.tree.branch, {}, config=config)
        self.assertRaises(PackageVersionNotPresent,
            source.version_as_revision, "foo", "2.1+bzr4242")

    def test_version_as_revision_no_tag(self):
        # There is no relevant revspec known
        config = DebBuildConfig(
            [('user.conf', True), ('default.conf', False)],
            branch=self.tree.branch)
        source = UpstreamBranchSource(
            self.tree.branch, {"2.1": "tag:foo"}, config=config)
        self.assertRaises(
            PackageVersionNotPresent,
            source.version_as_revision, "foo", u"2.1")

    def test_get_latest_version_no_random_access(self):
        local_repo = self.make_repository('local')
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        self.tree.branch.repository.supports_random_access = False
        source = UpstreamBranchSource.from_branch(
            self.tree.branch,
            {"2.1": self.tree.branch.last_revision().decode('utf-8')},
            local_dir=local_repo.controldir)
        self.assertEquals("2.1", source.get_latest_version("foo", "1.0"))
        self.tree.commit("msg")
        source = UpstreamBranchSource.from_branch(
            self.tree.branch,
            {"2.1": self.tree.branch.last_revision().decode('utf-8')},
            local_dir=local_repo.controldir)
        self.assertEquals("2.1+bzr2", source.get_latest_version("foo", "1.0"))


class LazyUpstreamBranchSourceTests(TestCaseWithTransport):
    """Tests for LazyUpstreamBranchSource."""

    def setUp(self):
        super(LazyUpstreamBranchSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')

    def test_fetch_tarballs(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("1.0", self.tree.branch.last_revision())
        source = LazyUpstreamBranchSource(self.tree.branch.base,
            {"1.0": self.tree.branch.last_revision().decode('utf-8')})
        self.assertIs(None, source._upstream_branch)
        os.mkdir("mydir")
        self.assertEquals(["mydir/foo_1.0.orig.tar.gz"],
            source.fetch_tarballs("foo", "1.0", "mydir"))
        self.assertPathExists("mydir/foo_1.0.orig.tar.gz")
        self.assertIsNot(None, source._upstream_branch)

    def test_fetch_tarballs_not_found(self):
        source = LazyUpstreamBranchSource(self.tree.branch.base)
        self.assertIs(None, source._upstream_branch)
        self.tree.commit("msg")
        self.assertRaises(PackageVersionNotPresent,
            source.fetch_tarballs, "foo", "1.0", "mydir")
        self.assertIsNot(None, source._upstream_branch)

    def test_get_latest_version(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        source = LazyUpstreamBranchSource(self.tree.branch.base,
            {"2.1": self.tree.branch.last_revision()})
        self.assertIs(None, source._upstream_branch)
        self.assertEquals("2.1", source.get_latest_version("foo", "1.0"))
        self.tree.commit("msg")
        self.assertEquals("2.1+bzr2", source.get_latest_version("foo", "1.0"))
        self.assertIsNot(None, source._upstream_branch)

    def test_get_recent_versions(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", revid1)
        source = LazyUpstreamBranchSource(
            self.tree.branch.base,
            {"2.1": self.tree.branch.last_revision()})
        self.assertIs(None, source._upstream_branch)
        self.assertEquals(["2.1"], source.get_recent_versions("foo", "1.0"))
        revid2 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.2", revid2)
        self.assertEquals(
            ["2.1", "2.2"],
            source.get_recent_versions("foo", "1.0"))
        self.assertIsNot(None, source._upstream_branch)

    def test_version_as_revision(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        config = DebBuildConfig(
            [('user.conf', True), ('default.conf', False)],
            branch=self.tree.branch)
        source = LazyUpstreamBranchSource(self.tree.branch.base,
            {"2.1": self.tree.branch.last_revision().decode('utf-8')},
            config=config)
        self.assertIs(None, source._upstream_branch)
        revid2 = self.tree.commit("msg")
        self.assertEquals(revid2,
            source.version_as_revision("foo", "2.1+bzr2"))
        self.assertEquals(revid1, source.version_as_revision("foo", "2.1"))
        self.assertIsNot(None, source._upstream_branch)


class TestUpstreamBranchVersion(TestCase):
    """Test that the upstream version of a branch can be determined correctly.
    """

    def get_suffix(self, version_string, revid):
        revno = len(self.revhistory) - self.revhistory.index(revid)
        if "bzr" in version_string:
            return "%sbzr%d" % (version_string.split("bzr")[0], revno)
        return "%s+bzr%d" % (version_string, revno)

    def test_snapshot_none_existing(self):
      self.revhistory = [b"somerevid"]
      self.assertEquals("1.2+bzr1",
          _upstream_branch_version(self.revhistory, b"somerevid", {}, "bla", "1.2", self.get_suffix))

    def test_snapshot_nothing_new(self):
      self.revhistory = []
      self.assertEquals("1.2",
          _upstream_branch_version(self.revhistory, NULL_REVISION, {}, "bla", "1.2", self.get_suffix))

    def test_new_tagged_release(self):
      """Last revision is tagged - use as upstream version."""
      self.revhistory = [b"somerevid"]
      self.assertEquals("1.3",
          _upstream_branch_version(self.revhistory, b"somerevid", {b"somerevid": [u"1.3"]}, "bla", "1.2", self.get_suffix))

    def test_refresh_snapshot_pre(self):
      self.revhistory = [b"somerevid", b"oldrevid"]
      self.assertEquals("1.3~bzr2",
          _upstream_branch_version(self.revhistory, b"somerevid", {}, "bla", "1.3~bzr1",
              self.get_suffix))

    def test_refresh_snapshot_post(self):
      self.revhistory = [b"somerevid", b"oldrevid"]
      self.assertEquals("1.3+bzr2",
          _upstream_branch_version(self.revhistory, b"somerevid", {}, "bla", "1.3+bzr1",
              self.get_suffix))

    def test_new_tag_refresh_snapshot(self):
      self.revhistory = [b"newrevid", b"somerevid", b"oldrevid"]
      self.assertEquals("1.3+bzr3",
            _upstream_branch_version(self.revhistory, b"newrevid",
                {b"somerevid": [u"1.3"]}, "bla", "1.2+bzr1", self.get_suffix))


class TestUpstreamTagToVersion(TestCase):

    def test_prefix(self):
        self.assertEquals("5.0", upstream_tag_to_version(u"release-5.0"))

    def test_gibberish(self):
        self.assertIs(None, upstream_tag_to_version(u"blabla"))

    def test_vprefix(self):
        self.assertEquals("2.0", upstream_tag_to_version(u"v2.0"))

    def test_plain(self):
        self.assertEquals("2.0", upstream_tag_to_version(u"2.0"))

    def test_package_prefix(self):
        self.assertEquals("42.0", upstream_tag_to_version(u"bla-42.0", "bla"))

    def test_unicode(self):
        self.assertEquals(
                u"42.0\xa9",
                upstream_tag_to_version(u"bla-42.0\xa9", "bla"))


class TestUpstreamVersionAddRevision(TestCaseWithTransport):
    """Test that updating the version string works."""

    def setUp(self):
        super(TestUpstreamVersionAddRevision, self).setUp()
        self.revnos = {}
        self.svn_revnos = {b"somesvnrev": 45}
        self.git_shas = {b"somegitrev": b"e7f47cf254a6ddd4996fe41fa6115bd32eff5437"}
        self.revnos = {b"somerev": 42, b"somesvnrev": 12, b"somegitrev": 66}
        self.repository = self

    def revision_id_to_revno(self, revid):
        return self.revnos[revid]

    def revision_id_to_dotted_revno(self, revid):
        return (self.revnos[revid], )

    def get_revision(self, revid):
        rev = Revision(revid)
        if revid in self.svn_revnos:
            self.requireFeature(svn_plugin)
            # Fake a bzr-svn revision
            rev.foreign_revid = ("uuid", "bp", self.svn_revnos[revid])
            from ...svn import mapping
            rev.mapping = mapping.mapping_registry.get_default()()
        if revid in self.git_shas:
            self.requireFeature(dulwich)
            # Fake a bzr-svn revision
            rev.foreign_revid = self.git_shas[revid]
            from ....git import mapping
            rev.mapping = mapping.mapping_registry.get_default()()
            rev.timestamp = 1514772000
            rev.timezone = 0
        return rev

    def test_update_plus_rev(self):
        self.assertEquals("1.3+bzr42",
          upstream_version_add_revision(self, "1.3+bzr23", b"somerev"))

    def test_update_tilde_rev(self):
        self.assertEquals("1.3~bzr42",
          upstream_version_add_revision(self, "1.3~bzr23", b"somerev"))

    def test_new_rev(self):
        self.assertEquals("1.3+bzr42",
          upstream_version_add_revision(self, "1.3", b"somerev"))

    def test_svn_new_rev(self):
        self.assertEquals("1.3+svn45",
          upstream_version_add_revision(self, "1.3", b"somesvnrev"))

    def test_svn_plus_rev(self):
        self.assertEquals("1.3+svn45",
          upstream_version_add_revision(self, "1.3+svn3", b"somesvnrev"))

    def test_svn_tilde_rev(self):
        self.assertEquals("1.3~svn45",
            upstream_version_add_revision(self, "1.3~svn800", b"somesvnrev"))

    def test_git_tilde_rev(self):
        self.assertEquals(
            "1.3~git20180101.e7f47cf",
            upstream_version_add_revision(
                self, "1.3~git20171201.11b1d57", b"somegitrev"))

    def test_git_new_rev(self):
        self.assertEquals(
            "1.3+git20180101.e7f47cf",
            upstream_version_add_revision(
                self, "1.3", b"somegitrev"))
        self.assertEquals(
            "1.0~git20180101",
            upstream_version_add_revision(
                self, "1.0~git20160320", b"somegitrev"))
        self.assertEquals(
            "1.0~git20180101.1.e7f47cf",
            upstream_version_add_revision(
                self, "1.0~git20180101.0.11b1d57", b"somegitrev"))
        self.assertEquals(
            "1.0~git20180101.0.e7f47cf",
            upstream_version_add_revision(
                self, "1.0~git20170101.0.11b1d57", b"somegitrev"))


class GetExportUpstreamRevisionTests(TestCase):

    def test_snapshot_rev(self):
        config = DebBuildConfig([])
        self.assertEquals("34",
            get_export_upstream_revision(config, "0.1+bzr34"))

    def test_export_upstream_rev(self):
        config = DebBuildConfig([
            ({"BUILDDEB": {"export-upstream-revision": "tag:foobar"}}, True)])
        self.assertEquals("tag:foobar",
            get_export_upstream_revision(config, "0.1"))

    def test_export_upstream_rev_var(self):
        config = DebBuildConfig([({"BUILDDEB":
            {"export-upstream-revision": "tag:foobar-$UPSTREAM_VERSION"}},
            True)])
        self.assertEquals("tag:foobar-0.1",
            get_export_upstream_revision(config, "0.1"))

    def test_export_upstream_rev_not_set(self):
        config = DebBuildConfig([])
        self.assertEquals(None,
            get_export_upstream_revision(config, "0.1"))


class GetRevisionSnapshotTests(TestCase):

    def test_with_snapshot(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4~bzr30"))

    def test_with_snapshot_plus(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4+bzr30"))

    def test_without_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4"))

    def test_non_numeric_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4~bzra"))

    def test_with_svn_snapshot(self):
        self.assertEquals("svn:4242", get_snapshot_revision("0.4.4~svn4242"))

    def test_with_svn_snapshot_plus(self):
        self.assertEquals("svn:2424", get_snapshot_revision("0.4.4+svn2424"))

    def test_git(self):
        self.assertEquals(
            "date:20190101",
            get_snapshot_revision("0.4.4+git20190101"))
        self.assertEquals(
            "git:abc1def",
            get_snapshot_revision("0.4.4+git20190101.abc1def"))


class TestIsUpstreamTag(TestCase):

    def test_plain_version(self):
        self.assertFalse(is_upstream_tag('2.1'))

    def test_simple_upstream(self):
        self.assertTrue(is_upstream_tag('upstream-2.1'))

    def test_distro_upstream(self):
        self.assertTrue(is_upstream_tag('upstream-debian-2.1'))

    def test_git_upstream(self):
        self.assertTrue(is_upstream_tag('upstream/2.1'))

    def test_svn_upstream(self):
        self.assertTrue(is_upstream_tag('upstream_2.1'))


class TestUpstreamTagVersion(TestCase):

    def test_simple_upstream(self):
        self.assertEqual((None, '2.1'), upstream_tag_version('upstream-2.1'))

    def test_distro_upstream(self):
        self.assertEqual((None, '2.1'),
            upstream_tag_version('upstream-debian-2.1'))

    def test_svn_upstream(self):
        self.assertEqual((None, '2.1'), upstream_tag_version('upstream_2.1'))

    def test_git_upstream(self):
        self.assertEqual((None, '2.1'), upstream_tag_version('upstream/2.1'))

    def test_git_upstream_component(self):
        self.assertEqual(("lib", '2.1'), upstream_tag_version('upstream/2.1/lib'))

    def test_simple_upstream_component(self):
        self.assertEqual(("lib", '2.1'), upstream_tag_version('upstream-2.1/lib'))

    def test_distro_upstream_component(self):
        self.assertEqual(("lib", '2.1'),
            upstream_tag_version('upstream-debian-2.1/lib'))


class GenericPristineTarSourceTests(TestCase):

    def test_pristine_tar_format_gz(self):
        rev = Revision("myrevid")
        rev.properties[u"deb-pristine-delta"] = "1"
        self.assertEquals("gz", revision_pristine_tar_format(rev))

    def test_pristine_tar_format_bz2(self):
        rev = Revision("myrevid")
        rev.properties[u"deb-pristine-delta-bz2"] = "1"
        self.assertEquals("bz2", revision_pristine_tar_format(rev))

    def test_pristine_tar_format_xz(self):
        rev = Revision("myrevid")
        rev.properties[u"deb-pristine-delta-xz"] = "1"
        self.assertEquals("xz", revision_pristine_tar_format(rev))

    def test_pristine_tar_format_unknown(self):
        rev = Revision("myrevid")
        self.assertRaises(AssertionError,
            revision_pristine_tar_format, rev)

    def test_pristine_tar_delta_unknown(self):
        rev = Revision("myrevid")
        self.assertRaises(AssertionError,
            revision_pristine_tar_delta, rev)

    def test_pristine_tar_delta_gz(self):
        rev = Revision("myrevid")
        rev.properties[u"deb-pristine-delta"] = standard_b64encode(b"bla")
        self.assertEquals(b"bla", revision_pristine_tar_delta(rev))


class PristineTarSourceTests(TestCaseWithTransport):

    def setUp(self):
        super(PristineTarSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('unstable')
        self.source = PristineTarSource(self.tree.branch)

    def test_gbp_tag_format(self):
        self.build_tree_contents([
            ('unstable/debian/', ),
            ('unstable/debian/gbp.conf', """\
[DEFAULT]
upstream-tag = blah-%(version)s
""")])
        self.source = PristineTarSource.from_tree(
            self.tree.branch, self.tree)
        upstream_v_no = "0.1"
        self.assertEqual(
            self.source.tag_name(upstream_v_no),
            "blah-" + upstream_v_no)

    def test_gbp_tag_format_unusual(self):
        self.build_tree_contents([
            ('unstable/debian/', ),
            ('unstable/debian/gbp.conf', """\
[DEFAULT]
upstream-tag = blah-%(version%~%-)s
""")])
        self.source = PristineTarSource.from_tree(
            self.tree.branch, self.tree)
        self.assertEqual(
            self.source.tag_name("0.1~1"),
            "blah-0.1-1")

    def test_upstream_tag_name(self):
        upstream_v_no = "0.1"
        self.assertEqual(
            self.source.tag_name(upstream_v_no),
            "upstream-" + upstream_v_no)

    def test_tag_name_distro(self):
        self.assertEquals(
            self.source.tag_name("0.3", distro="ubuntu"),
            "upstream-ubuntu-0.3")

    def test_version(self):
        self.assertEquals(
            ['upstream/3.3', 'upstream-3.3', 'upstream_3.3', '3.3',
             'v3.3', 'pkg-3.3'],
            self.source.possible_tag_names("pkg", "3.3", component=None))

    def test_version_with_tilde(self):
        self.assertEquals([
            'upstream/3.3~brz232',
            'upstream-3.3~brz232',
            'upstream/3.3_brz232',
            'upstream_3.3~brz232',
            '3.3~brz232',
            'v3.3~brz232',
            'pkg-3.3~brz232'],
            self.source.possible_tag_names('pkg', "3.3~brz232", component=None))

    def test_version_component(self):
        self.assertEquals([
            'upstream-3.3/extlib'],
            self.source.possible_tag_names('pkg', "3.3", component="extlib"))

    def test_version_as_revisions_missing(self):
        self.assertRaises(PackageVersionNotPresent,
            self.source.version_as_revisions, None, "1.2")

    def test_version_as_revisions_single(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("upstream-2.1", revid1)
        self.assertEquals({None: revid1},
            self.source.version_as_revisions(None, "2.1"))

    def test_version_component_as_revision(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("upstream-2.1/lib", revid1)
        self.assertEquals(revid1,
            self.source.version_component_as_revision(None, "2.1", "lib"))

    def test_version_as_revisions(self):
        revid1 = self.tree.commit("msg")
        revid2 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("upstream-2.1", revid1)
        self.tree.branch.tags.set_tag("upstream-2.1/lib", revid2)
        self.assertEquals({ None: revid1, "lib": revid2 },
                self.source.version_as_revisions(None, "2.1", [
            ("upstream_2.1.orig.tar.gz", None, "somemd5sum"),
            ("upstream_2.1.orig-lib.tar.gz", "lib", "othermd5sum")]))

    def test_version_as_revisions_partially_missing(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("upstream-2.1", revid1)
        self.assertRaises(PackageVersionNotPresent,
                self.source.version_as_revisions, 'pkg', "2.1", [
            ("upstream_2.1.orig.tar.gz", None, "somemd5sum"),
            ("upstream_2.1.orig-lib.tar.gz", "lib", "othermd5sum")])

    def test_has_version_multiple(self):
        revid1 = self.tree.commit("msg")
        revid2 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("upstream-2.1", revid1)
        self.tree.branch.tags.set_tag("upstream-2.1/lib", revid2)
        self.assertTrue(
                self.source.has_version(None, "2.1", [
            ("upstream_2.1.orig.tar.gz", None, "somemd5sum"),
            ("upstream_2.1.orig-lib.tar.gz", "lib", "othermd5sum")]))

    def test_has_version_partially_missing(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("upstream-2.1", revid1)
        self.assertFalse(
                self.source.has_version(None, "2.1", [
            ("upstream_2.1.orig.tar.gz", None, "somemd5sum"),
            ("upstream_2.1.orig-lib.tar.gz", "lib", "othermd5sum")]))


class TarfileSourceTests(TestCaseWithTransport):
    """Tests for TarfileSource."""

    def setUp(self):
        super(TarfileSourceTests, self).setUp()
        tar = tarfile.open("foo-1.0.tar.gz", "w:gz")
        tar.close()

    def test_version(self):
        source = TarfileSource("foo-1.0.tar.gz", "1.0")
        self.assertEquals(
            "1.0", source.get_latest_version("foo", "0.9"))

    def test_version_unicode(self):
        source = TarfileSource(u"foo-1.0.tar.gz", u"1.0")
        latest_version = source.get_latest_version("foo", "0.9")
        self.assertEquals("1.0", latest_version)
        self.assertIsInstance(latest_version, str)

    def test_version_unicode_not_specified(self):
        source = TarfileSource(u"foo-1.0.tar.gz")
        latest_version = source.get_latest_version("foo", u"0.9")
        self.assertEquals("1.0", latest_version)
        self.assertIsInstance(latest_version, str)

    def test_get_latest_version_parses(self):
        source = TarfileSource("foo-1.0.tar.gz")
        self.assertEquals("1.0", source.get_latest_version("foo", "0.9"))

    def test_get_recent_versions(self):
        source = TarfileSource("foo-1.0.tar.gz")
        self.assertEquals(["1.0"], source.get_recent_versions("foo", "0.9"))

    def test_fetch_tarballs(self):
        source = TarfileSource("foo-1.0.tar.gz", "1.0")
        os.mkdir("bar")
        self.assertEquals(["bar/foo_1.0.orig.tar.gz"],
            source.fetch_tarballs("foo", "1.0", "bar"))
        self.assertPathExists("bar/foo_1.0.orig.tar.gz")

    def test_fetch_zip_tarballs_repack(self):
        zf = zipfile.ZipFile("bla-2.0.zip", "w")
        zf.writestr('avoid', 'empty zip to make the repacker happy\n')
        zf.close()
        source = TarfileSource("bla-2.0.zip", "2.0")
        os.mkdir("bar")
        self.assertEquals(["bar/foo_2.0.orig.tar.gz"],
            source.fetch_tarballs("foo", "2.0", "bar"))
        self.assertPathExists("bar/foo_2.0.orig.tar.gz")

    def test_fetch_tarballs_not_present(self):
        source = TarfileSource("foo-1.0.tar.gz", "1.0")
        os.mkdir("bar")
        self.assertRaises(PackageVersionNotPresent,
            source.fetch_tarballs, "foo", "0.9", "bar")

    def test_fetch_tarballs_bz2(self):
        tar = tarfile.open("foo-1.0.tar.bz2", "w:bz2")
        tar.close()
        # verify this is a bzip2 file
        os.mkdir("foo-1.0")
        zf = bz2.BZ2File("foo-1.0.tar.bz2", 'w')
        try:
            tar = tarfile.open("foo-1.0.tar", "w", zf)
            try:
                tar.add("foo-1.0")
            finally:
                tar.close()
        finally:
            zf.close()
        source = TarfileSource("foo-1.0.tar.bz2", "1.0")
        os.mkdir("bar")
        self.assertEquals(["bar/foo_1.0.orig.tar.bz2"],
            source.fetch_tarballs("foo", "1.0", "bar"))
        self.assertPathExists("bar/foo_1.0.orig.tar.bz2")
        tarfile.open("bar/foo_1.0.orig.tar.bz2", "r:bz2").close()

    def test_fetch_tarball_xz(self):
        self.requireFeature(LzmaFeature)
        self.requireFeature(XzFeature)
        import lzma
        os.mkdir("empty")
        make_new_upstream_tarball_xz("empty", "foo-1.0.tar.xz")
        source = TarfileSource("foo-1.0.tar.xz", "1.0")
        os.mkdir("bar")
        self.assertEquals(["bar/foo_1.0.orig.tar.xz"],
            source.fetch_tarballs("foo", "1.0", "bar"))
        self.assertPathExists("bar/foo_1.0.orig.tar.xz")
        lzma.LZMAFile("bar/foo_1.0.orig.tar.xz").close()


class _MissingUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self):
        pass

    def provide(self, target_dir):
        raise MissingUpstreamTarball("test_tarball", "1.0")


class _TouchUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self, desired_tarball_name):
        self.desired_tarball_name = desired_tarball_name

    def provide(self, target_dir):
        path = os.path.join(target_dir, self.desired_tarball_name)
        with open(path, "wb") as f:
            f.write(b"I am a tarball, honest\n")
        return [path]


class _SimpleUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self, package, version, store_dir):
        self.package = package
        self.version = version
        self.store_dir = store_dir

    def provide(self, target_dir):
        paths = (self.already_exists_in_target(target_dir)
                or self.provide_from_store_dir(target_dir))
        if paths is not None:
            return [(p, component_from_orig_tarball(p, self.package,
                self.version)) for p in paths]
        raise MissingUpstreamTarball(self.package, self.version)


class ExtractTarballVersionTests(TestCase):

    def test_unknown_extension(self):
        self.assertEquals(None,
            extract_tarball_version("/tmp/foo-1.2.tar.bla", "foo"))

    def test_debian_style(self):
        self.assertEquals("1.2+testfix",
            extract_tarball_version("/tmp/foo_1.2+testfix.orig.tar.gz", "foo"))

    def test_traditional_style(self):
        self.assertEquals("1.2b2",
            extract_tarball_version("/tmp/foo-1.2b2.zip", "foo"))


class NewTarballNameTests(TestCase):

    def test_bz2(self):
        self.assertEquals("foo_1.0.orig.tar.bz2",
            new_tarball_name("foo", "1.0", "bla.tar.bz2"))

    def test_gz(self):
        self.assertEquals("foo_1.0.orig.tar.gz",
            new_tarball_name("foo", "1.0", "bla.tar.gz"))

    def test_zip(self):
        self.assertEquals("foo_1.0.orig.tar.gz",
            new_tarball_name("foo", "1.0", "bla.zip"))


class TestGatherOrigTarballs(TestCaseWithTransport):

    def test_no_dir(self):
        self.assertIs(None, gather_orig_files("mypkg", "1.0", "idontexist"))

    def test_empty(self):
        self.build_tree(["empty/"])
        self.assertIs(None, gather_orig_files("mypkg", "1.0", "empty"))

    def test_single(self):
        self.build_tree(["mypkg_1.0.orig.tar.gz"])
        self.assertEquals(
            [os.path.join(self.test_dir, "mypkg_1.0.orig.tar.gz")],
            gather_orig_files("mypkg", "1.0", "."))

    def test_multiple(self):
        self.build_tree(["mypkg_1.0.orig.tar.gz", "mypkg_1.0.orig-foo.tar.gz"])
        self.assertEquals(
            set([os.path.join(self.test_dir, "mypkg_1.0.orig.tar.gz"),
             os.path.join(self.test_dir, "mypkg_1.0.orig-foo.tar.gz")]),
            set(gather_orig_files("mypkg", "1.0", ".")))

    def test_utf8_invalid_file(self):
        with open("\xf6o.tar.gz", "w") as f:
            f.write("foo")
        self.build_tree(["mypkg_1.0.orig.tar.gz"])
        self.assertEquals(
            [os.path.join(self.test_dir, "mypkg_1.0.orig.tar.gz")],
            gather_orig_files(u"mypkg", "1.0", "."))
