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

import os

from debian_bundle.changelog import Version

from bzrlib.tests import (
        TestCase,
        TestCaseWithTransport,
        )
from bzrlib.plugins.builddeb.errors import (
        MissingUpstreamTarball,
        )
from bzrlib.plugins.builddeb.upstream import (
        UpstreamProvider,
        UpstreamSource,
        AptSource,
        PristineTarSource,
        )
from bzrlib.plugins.builddeb.util import (
        get_parent_dir,
        tarball_name,
        )


class MockProvider(UpstreamSource):

    def create_target(self, path):
        parent_dir = get_parent_dir(path)
        if parent_dir != '' and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        f = open(path, "wb")
        try:
            f.write('')
        finally:
            f.close()


class MockAptProvider(MockProvider):

    def __init__(self, find=False):
        self.find = find
        self.called_times = 0
        self.package = None
        self.upstream_version = None
        self.target_dir = None

    def get_specific_version(self, package, upstream_version, target_dir):
        self.called_times += 1
        self.package = package
        self.upstream_version = upstream_version
        self.target_dir = target_dir
        if self.find:
            self.create_target(os.path.join(target_dir,
                    tarball_name(package, upstream_version)))
        return self.find


class MockUscanProvider(MockProvider):

    def __init__(self, find=False):
        self.find = find
        self.called_times = 0
        self.package = None
        self.upstream_version = None
        self.watch_file_contents = None
        self.target_dir = None

    def provide(self, package, upstream_version, watch_file, target_dir):
        self.called_times += 1
        self.package = package
        self.upstream_version = upstream_version
        f = open(watch_file, "rb")
        try:
            self.watch_file_contents = f.read()
        finally:
            f.close()
        self.target_dir = target_dir
        if self.find:
            self.create_target(os.path.join(target_dir,
                    tarball_name(package, upstream_version)))
        return self.find


class MockPristineProvider(MockProvider):

    def __init__(self, find=False):
        self.find = find
        self.called_times = 0
        self.tree = None
        self.branch = None
        self.package = None
        self.upstream_version = None
        self.target_filename = None

    def provide(self, tree, branch, package, upstream_version, target_filename):
        self.called_times += 1
        self.tree = tree
        self.branch = branch
        self.package = package
        self.upstream_version = upstream_version
        self.target_filename = target_filename
        if self.find:
            self.create_target(target_filename)
        return self.find


class MockOrigSourceProvider(MockProvider):

    def __init__(self, find=False):
        self.find = find
        self.called_times = 0
        self.source_dir = None
        self.desired_tarball_name = None
        self.target_dir = None

    def provide(self, source_dir, desired_tarball_name,
            target_dir):
        self.called_times += 1
        self.source_dir = source_dir
        self.desired_tarball_name = desired_tarball_name
        self.target_dir = target_dir
        if self.find:
            self.create_target(os.path.join(target_dir, desired_tarball_name))
        return self.find


class MockOtherBranchProvider(MockProvider):

    def __init__(self, find=False):
        self.find = find
        self.called_times = 0
        self.upstream_branch = None
        self.upstream_revision = None
        self.target_filename = None
        self.tarball_base = None

    def provide(self, upstream_branch, upstream_revision, target_filename,
            tarball_base):
        self.called_times += 1
        self.upstream_branch = upstream_branch
        self.upstream_revision = upstream_revision
        self.target_filename = target_filename
        self.tarball_base = tarball_base
        if self.find:
            self.create_target(target_filename)
        return self.find


class MockSplitProvider(MockProvider):

    def __init__(self, find=False):
        self.find = find
        self.called_times = 0
        self.tree = None
        self.package = None
        self.upstream_version = None
        self.target_filename = None

    def provide(self, tree, package, upstream_version, target_filename):
        self.called_times += 1
        self.tree = tree
        self.package = package
        self.upstream_version = upstream_version
        self.target_filename = target_filename
        if self.find:
            self.create_target(self.target_filename)
        return self.find


class MockSources(object):

    def __init__(self, versions):
        self.restart_called_times = 0
        self.lookup_called_times = 0
        self.lookup_package = None
        self.versions = versions
        self.Version = None

    def Restart(self):
        self.restart_called_times += 1

    def Lookup(self, package):
        self.lookup_called_times += 1
        assert not self.lookup_package or self.lookup_package == package
        self.lookup_package = package
        if self.lookup_called_times <= len(self.versions):
            self.Version = self.versions[self.lookup_called_times-1]
            return True
        else:
            self.Version = None
            return False


class MockAptPkg(object):

    def __init__(self, sources):
        self.init_called_times = 0
        self.get_pkg_source_records_called_times = 0
        self.sources = sources

    def init(self):
        self.init_called_times += 1

    def GetPkgSrcRecords(self):
        self.get_pkg_source_records_called_times += 1
        return self.sources


class UpstreamProviderTests(TestCaseWithTransport):

    def setUp(self):
        super(UpstreamProviderTests, self).setUp()
        self.tree = self.make_branch_and_tree(".")
        self.branch = self.tree.branch
        self.package = "package"
        self.version = Version("0.1-1")
        self.upstream_version = self.version.upstream_version
        self.desired_tarball_name = tarball_name(self.package,
                self.upstream_version)
        self.tarball_base = "%s-%s" % (self.package, self.upstream_version)
        self.store_dir = "store"
        self.provider = UpstreamProvider(self.tree, self.branch,
                self.package, self.version, self.store_dir)
        self.provider._sources = []
        self.providers = {}
        self.providers["apt"] = MockAptProvider()
        self.provider._sources.append(self.providers["apt"])
        self.providers["uscan"] = MockUscanProvider()
        self.provider._sources.append(self.providers["uscan"])
        self.providers["pristine"] = MockPristineProvider()
        self.provider._sources.append(self.providers["pristine"])
        self.providers["orig"] = MockOrigSourceProvider()
        self.provider._sources.append(self.providers["orig"])
        self.providers["upstream"] = MockOtherBranchProvider()
        self.provider._sources.append(self.providers["upstream"])
        self.provider._upstream_branch_provider = \
                                self.providers["upstream"].provide
        self.providers["split"] = MockSplitProvider()
        self.provider._sources.append(self.providers["split"])
        self.target_dir = "target"
        self.target_filename = os.path.join(self.target_dir,
                self.desired_tarball_name)
        self.store_filename = os.path.join(self.store_dir,
                tarball_name(self.package, self.version.upstream_version))

    def assertProvidersCalled(self, providers):
        for provider_name, provider in self.providers.items():
            if provider_name in providers:
                self.assertCalledCorrectly(provider_name)
            else:
                self.assertEqual(provider.called_times, 0,
                        "%s wasn't expected to be called" % provider_name)

    def call_provider(self):
        self.assertEqual(self.provider.provide(self.target_dir),
                self.target_filename)

    def test_already_in_target(self):
        os.makedirs(self.target_dir)
        f = open(self.target_filename, "wb")
        f.close()
        self.call_provider()
        self.failUnlessExists(self.target_filename)
        # Should this be copied across?
        self.failIfExists(self.store_filename)
        self.assertProvidersCalled({})

    def test_already_in_store(self):
        os.makedirs(self.store_dir)
        f = open(self.store_filename, "wb")
        f.close()
        self.call_provider()
        self.failUnlessExists(self.target_filename)
        self.failUnlessExists(self.store_filename)
        self.assertProvidersCalled({})

    def assertCalledCorrectly(self, provider_name):
        provider = self.providers[provider_name]
        for attr_name in provider.__dict__:
            if attr_name in ("find", "provide", "source_dir"):
                continue
            if attr_name == "called_times":
                self.assertEqual(provider.called_times, 1,
                        "%s was not called" % provider_name)
                continue
            if attr_name == "target_filename":
                self.assertEqual(provider.target_filename,
                        self.store_filename)
                continue
            if attr_name == "target_dir":
                self.assertEqual(provider.target_dir,
                        self.store_dir)
                continue
            if attr_name == "fetch_dir":
                self.assertEqual(provider.fetch_dir,
                        os.path.dirname(provider.source_dir))
                continue
            attr = getattr(provider, attr_name)
            correct_attr = getattr(self, attr_name)
            self.assertEqual(correct_attr, attr,
                    "%s doesn't match\nexpected: %s\ngot: %s"
                    % (attr_name, correct_attr, attr))

    def assertSuccesfulCall(self, provider, other_providers):
        self.providers[provider].find = True
        self.call_provider()
        self.failUnlessExists(self.target_filename)
        self.failUnlessExists(self.store_filename)
        self.assertProvidersCalled([provider] + other_providers)

    def test_from_pristine_tar(self):
        self.assertSuccesfulCall("pristine", [])

    def test_from_apt(self):
        self.assertSuccesfulCall("apt", ["pristine"])

    def test_from_uscan(self):
        self.build_tree(["watch", "debian/", "debian/watch"])
        self.tree.add(["watch", "debian/", "debian/watch"])
        self.watch_file_contents = "contents of debian/watch\n"
        self.assertSuccesfulCall("uscan", ["pristine", "apt"])

    def test_uscan_not_called_if_not_watch(self):
        self.build_tree(["watch"])
        self.tree.add(["watch"])
        self.assertRaises(MissingUpstreamTarball, self.provider.provide,
                self.target_dir)
        self.failIfExists(self.target_filename)
        self.failIfExists(self.store_filename)
        self.assertProvidersCalled(["pristine", "apt"])

    def test_uscan_in_larstiq(self):
        self.build_tree(["watch", "debian/", "debian/watch"])
        self.tree.add(["watch", "debian/", "debian/watch"])
        self.watch_file_contents = "contents of watch\n"
        self.provider.larstiq = True
        self.assertSuccesfulCall("uscan", ["pristine", "apt"])

    def test_from_get_orig_source(self):
        self.build_tree(["rules", "debian/", "debian/rules"])
        self.tree.add(["rules", "debian/", "debian/rules"])
        self.watch_file_contents = "contents of debian/rules\n"
        self.assertSuccesfulCall("orig", ["pristine", "apt"])

    def test_get_orig_source_not_called_if_no_rules(self):
        self.build_tree(["rules"])
        self.tree.add(["rules"])
        self.assertRaises(MissingUpstreamTarball, self.provider.provide,
                self.target_dir)
        self.failIfExists(self.target_filename)
        self.failIfExists(self.store_filename)
        self.assertProvidersCalled(["pristine", "apt"])

    def test_get_orig_source_in_larstiq(self):
        self.build_tree(["rules", "debian/", "debian/rules"])
        self.tree.add(["rules", "debian/", "debian/rules"])
        self.watch_file_contents = "contents of rules\n"
        self.provider.larstiq = True
        self.assertSuccesfulCall("orig", ["pristine", "apt"])

    def test_from_upstream_branch(self):
        upstream_tree = self.make_branch_and_tree("upstream")
        self.build_tree(["upstream/foo"])
        upstream_tree.add(["foo"])
        self.upstream_branch = upstream_tree.branch
        self.upstream_revision = upstream_tree.commit("upstream one")
        self.provider.upstream_revision = self.upstream_revision
        self.provider.upstream_branch = self.upstream_branch
        self.assertSuccesfulCall("upstream", ["pristine", "apt"])

    def test_from_split(self):
        self.provider.allow_split = True
        self.assertSuccesfulCall("split", ["pristine", "apt"])

    def test_upstream_before_orig_source(self):
        upstream_tree = self.make_branch_and_tree("upstream")
        self.build_tree(["upstream/foo"])
        upstream_tree.add(["foo"])
        self.upstream_branch = upstream_tree.branch
        self.upstream_revision = upstream_tree.commit("upstream one")
        self.provider.upstream_revision = self.upstream_revision
        self.provider.upstream_branch = self.upstream_branch
        self.build_tree(["rules", "debian/", "debian/rules"])
        self.tree.add(["rules", "debian/", "debian/rules"])
        self.watch_file_contents = "contents of debian/rules\n"
        self.assertSuccesfulCall("upstream", ["pristine", "apt"])

    def test_get_orig_source_before_uscan(self):
        self.build_tree(["rules", "debian/", "debian/rules"])
        self.tree.add(["rules", "debian/", "debian/rules"])
        self.watch_file_contents = "contents of debian/rules\n"
        self.build_tree(["watch", "debian/watch"])
        self.tree.add(["watch", "debian/watch"])
        self.watch_file_contents = "contents of debian/watch\n"
        self.assertSuccesfulCall("orig", ["pristine", "apt"])

    def test_uscan_before_split(self):
        self.build_tree(["watch", "debian/", "debian/watch"])
        self.tree.add(["watch", "debian/", "debian/watch"])
        self.watch_file_contents = "contents of debian/watch\n"
        self.provider.allow_split = True
        self.assertSuccesfulCall("uscan", ["pristine", "apt"])


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
        self.assertEqual(False, AptSource().get_specific_version(
            "apackage", "0.2", "target", _apt_pkg=apt_pkg, _apt_caller=caller))
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
        self.assertEqual(False, AptSource().get_specific_version(
            "apackage", "0.2", "target", _apt_pkg=apt_pkg, _apt_caller=caller))
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
        self.assertEqual(True, AptSource().get_specific_version(
            "apackage", "0.2", "target", 
            _apt_pkg=apt_pkg, _apt_caller=caller.call))
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
        self.assertEqual(False, AptSource().get_specific_version(
            "apackage", "0.2", "target", 
            _apt_pkg=apt_pkg, _apt_caller=caller.call))
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
