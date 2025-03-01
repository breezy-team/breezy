# Copyright (C) 2006-2013, 2016 Canonical Ltd
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

"""Tests for the BzrDir facility and any format specific tests.

For interface contract tests, see tests/per_bzr_dir.
"""

import os
import subprocess
import sys

import breezy.branch
import breezy.bzr.branch

from ... import (
    branch,
    bzr,
    config,
    controldir,
    errors,
    help_topics,
    lock,
    osutils,
    repository,
    urlutils,
)
from ... import revision as _mod_revision
from ... import transport as _mod_transport
from ...errors import NotBranchError, UnknownFormatError, UnsupportedFormatError
from ...tests import (
    TestCase,
    TestCaseWithMemoryTransport,
    TestCaseWithTransport,
    http_server,
    http_utils,
)
from ...transport import memory, pathfilter
from ...transport.http.urllib import HttpTransport
from ...transport.nosmart import NoSmartTransportDecorator
from ...transport.readonly import ReadonlyTransportDecorator
from .. import bzrdir, knitpack_repo, knitrepo, remote, workingtree_3, workingtree_4
from ..fullhistory import BzrBranchFormat5


class TestDefaultFormat(TestCase):
    def test_get_set_default_format(self):
        old_format = bzrdir.BzrDirFormat.get_default_format()
        # default is BzrDirMetaFormat1
        self.assertIsInstance(old_format, bzrdir.BzrDirMetaFormat1)
        current_default = controldir.format_registry.aliases()["bzr"]
        controldir.format_registry.register("sample", SampleBzrDirFormat, help="Sample")
        self.addCleanup(controldir.format_registry.remove, "sample")
        controldir.format_registry.register_alias("bzr", "sample")
        # creating a bzr dir should now create an instrumented dir.
        try:
            result = bzrdir.BzrDir.create("memory:///")
            self.assertIsInstance(result, SampleBzrDir)
        finally:
            controldir.format_registry.register_alias("bzr", current_default)
        self.assertEqual(old_format, bzrdir.BzrDirFormat.get_default_format())


class DeprecatedBzrDirFormat(bzrdir.BzrDirFormat):
    """A deprecated bzr dir format."""


class TestFormatRegistry(TestCase):
    def make_format_registry(self):
        my_format_registry = controldir.ControlDirFormatRegistry()
        my_format_registry.register(
            "deprecated",
            DeprecatedBzrDirFormat,
            "Some format.  Slower and unawesome and deprecated.",
            deprecated=True,
        )
        my_format_registry.register_lazy(
            "lazy",
            __name__,
            "DeprecatedBzrDirFormat",
            "Format registered lazily",
            deprecated=True,
        )
        bzr.register_metadir(
            my_format_registry,
            "knit",
            "breezy.bzr.knitrepo.RepositoryFormatKnit1",
            "Format using knits",
        )
        my_format_registry.set_default("knit")
        bzr.register_metadir(
            my_format_registry,
            "branch6",
            "breezy.bzr.knitrepo.RepositoryFormatKnit3",
            "Experimental successor to knit.  Use at your own risk.",
            branch_format="breezy.bzr.branch.BzrBranchFormat6",
            experimental=True,
        )
        bzr.register_metadir(
            my_format_registry,
            "hidden format",
            "breezy.bzr.knitrepo.RepositoryFormatKnit3",
            "Experimental successor to knit.  Use at your own risk.",
            branch_format="breezy.bzr.branch.BzrBranchFormat6",
            hidden=True,
        )
        my_format_registry.register(
            "hiddendeprecated",
            DeprecatedBzrDirFormat,
            "Old format.  Slower and does not support things. ",
            hidden=True,
        )
        my_format_registry.register_lazy(
            "hiddenlazy",
            __name__,
            "DeprecatedBzrDirFormat",
            "Format registered lazily",
            deprecated=True,
            hidden=True,
        )
        return my_format_registry

    def test_format_registry(self):
        my_format_registry = self.make_format_registry()
        my_bzrdir = my_format_registry.make_controldir("lazy")
        self.assertIsInstance(my_bzrdir, DeprecatedBzrDirFormat)
        my_bzrdir = my_format_registry.make_controldir("deprecated")
        self.assertIsInstance(my_bzrdir, DeprecatedBzrDirFormat)
        my_bzrdir = my_format_registry.make_controldir("default")
        self.assertIsInstance(
            my_bzrdir.repository_format, knitrepo.RepositoryFormatKnit1
        )
        my_bzrdir = my_format_registry.make_controldir("knit")
        self.assertIsInstance(
            my_bzrdir.repository_format, knitrepo.RepositoryFormatKnit1
        )
        my_bzrdir = my_format_registry.make_controldir("branch6")
        self.assertIsInstance(
            my_bzrdir.get_branch_format(), breezy.bzr.branch.BzrBranchFormat6
        )

    def test_get_help(self):
        my_format_registry = self.make_format_registry()
        self.assertEqual(
            "Format registered lazily", my_format_registry.get_help("lazy")
        )
        self.assertEqual("Format using knits", my_format_registry.get_help("knit"))
        self.assertEqual("Format using knits", my_format_registry.get_help("default"))
        self.assertEqual(
            "Some format.  Slower and unawesome and deprecated.",
            my_format_registry.get_help("deprecated"),
        )

    def test_help_topic(self):
        topics = help_topics.HelpTopicRegistry()
        registry = self.make_format_registry()
        topics.register("current-formats", registry.help_topic, "Current formats")
        topics.register("other-formats", registry.help_topic, "Other formats")
        new = topics.get_detail("current-formats")
        rest = topics.get_detail("other-formats")
        experimental, deprecated = rest.split("Deprecated formats")
        self.assertContainsRe(new, "formats-help")
        self.assertContainsRe(
            new, ":knit:\n    \\(native\\) \\(default\\) Format using knits\n"
        )
        self.assertContainsRe(
            experimental, ":branch6:\n    \\(native\\) Experimental successor to knit"
        )
        self.assertContainsRe(
            deprecated, ":lazy:\n    \\(native\\) Format registered lazily\n"
        )
        self.assertNotContainsRe(new, "hidden")

    def test_set_default_repository(self):
        default_factory = controldir.format_registry.get("default")
        old_default = [
            k
            for k, v in controldir.format_registry.iteritems()
            if v == default_factory and k != "default"
        ][0]
        controldir.format_registry.set_default_repository("dirstate-with-subtree")
        try:
            self.assertIs(
                controldir.format_registry.get("dirstate-with-subtree"),
                controldir.format_registry.get("default"),
            )
            self.assertIs(
                repository.format_registry.get_default().__class__,
                knitrepo.RepositoryFormatKnit3,
            )
        finally:
            controldir.format_registry.set_default_repository(old_default)

    def test_aliases(self):
        a_registry = controldir.ControlDirFormatRegistry()
        a_registry.register(
            "deprecated",
            DeprecatedBzrDirFormat,
            "Old format.  Slower and does not support stuff",
            deprecated=True,
        )
        a_registry.register_alias("deprecatedalias", "deprecated")
        self.assertEqual({"deprecatedalias": "deprecated"}, a_registry.aliases())


class SampleBranch(breezy.branch.Branch):
    """A dummy branch for guess what, dummy use."""

    def __init__(self, dir):
        self.controldir = dir


class SampleRepository(breezy.repository.Repository):
    """A dummy repo."""

    def __init__(self, dir):
        self.controldir = dir


class SampleBzrDir(bzrdir.BzrDir):
    """A sample BzrDir implementation to allow testing static methods."""

    def create_repository(self, shared=False):
        """See ControlDir.create_repository."""
        return "A repository"

    def open_repository(self):
        """See ControlDir.open_repository."""
        return SampleRepository(self)

    def create_branch(self, name=None):
        """See ControlDir.create_branch."""
        if name is not None:
            raise controldir.NoColocatedBranchSupport(self)
        return SampleBranch(self)

    def create_workingtree(self):
        """See ControlDir.create_workingtree."""
        return "A tree"


class SampleBzrDirFormat(bzrdir.BzrDirFormat):
    """A sample format.

    this format is initializable, unsupported to aid in testing the
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return b"Sample .bzr dir format."

    def initialize_on_transport(self, t):
        """Create a bzr dir."""
        t.mkdir(".bzr")
        t.put_bytes(".bzr/branch-format", self.get_format_string())
        return SampleBzrDir(t, self)

    def is_supported(self):
        return False

    def open(self, transport, _found=None):
        return "opened branch."

    @classmethod
    def from_string(cls, format_string):
        return cls()


class BzrDirFormatTest1(bzrdir.BzrDirMetaFormat1):
    @staticmethod
    def get_format_string():
        return b"Test format 1"


class BzrDirFormatTest2(bzrdir.BzrDirMetaFormat1):
    @staticmethod
    def get_format_string():
        return b"Test format 2"


class TestBzrDirFormat(TestCaseWithTransport):
    """Tests for the BzrDirFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        bzr.BzrProber.formats.register(
            BzrDirFormatTest1.get_format_string(), BzrDirFormatTest1()
        )
        self.addCleanup(
            bzr.BzrProber.formats.remove, BzrDirFormatTest1.get_format_string()
        )
        bzr.BzrProber.formats.register(
            BzrDirFormatTest2.get_format_string(), BzrDirFormatTest2()
        )
        self.addCleanup(
            bzr.BzrProber.formats.remove, BzrDirFormatTest2.get_format_string()
        )
        t = self.get_transport()
        self.build_tree(["foo/", "bar/"], transport=t)

        def check_format(format, url):
            format.initialize(url)
            t = _mod_transport.get_transport_from_path(url)
            found_format = bzrdir.BzrDirFormat.find_format(t)
            self.assertIsInstance(found_format, format.__class__)

        check_format(BzrDirFormatTest1(), "foo")
        check_format(BzrDirFormatTest2(), "bar")

    def test_find_format_nothing_there(self):
        self.assertRaises(
            NotBranchError,
            bzrdir.BzrDirFormat.find_format,
            _mod_transport.get_transport_from_path("."),
        )

    def test_find_format_unknown_format(self):
        t = self.get_transport()
        t.mkdir(".bzr")
        t.put_bytes(".bzr/branch-format", b"")
        self.assertRaises(
            UnknownFormatError,
            bzrdir.BzrDirFormat.find_format,
            _mod_transport.get_transport_from_path("."),
        )

    def test_find_format_line_endings(self):
        t = self.get_transport()
        t.mkdir(".bzr")
        t.put_bytes(".bzr/branch-format", b"Corrupt line endings\r\n")
        self.assertRaises(
            bzr.LineEndingError,
            bzrdir.BzrDirFormat.find_format,
            _mod_transport.get_transport_from_path("."),
        )

    def test_find_format_html(self):
        t = self.get_transport()
        t.mkdir(".bzr")
        t.put_bytes(
            ".bzr/branch-format",
            b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">',
        )
        self.assertRaises(
            NotBranchError,
            bzrdir.BzrDirFormat.find_format,
            _mod_transport.get_transport_from_path("."),
        )

    def test_register_unregister_format(self):
        format = SampleBzrDirFormat()
        url = self.get_url()
        # make a bzrdir
        format.initialize(url)
        # register a format for it.
        bzr.BzrProber.formats.register(format.get_format_string(), format)
        # which bzrdir.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, bzrdir.BzrDir.open, url)
        # which bzrdir.open_containing will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, bzrdir.BzrDir.open_containing, url)
        # but open_downlevel will work
        t = _mod_transport.get_transport_from_url(url)
        self.assertEqual(format.open(t), bzrdir.BzrDir.open_unsupported(url))
        # unregister the format
        bzr.BzrProber.formats.remove(format.get_format_string())
        # now open_downlevel should fail too.
        self.assertRaises(UnknownFormatError, bzrdir.BzrDir.open_unsupported, url)

    def test_create_branch_and_repo_uses_default(self):
        format = SampleBzrDirFormat()
        branch = bzrdir.BzrDir.create_branch_and_repo(self.get_url(), format=format)
        self.assertTrue(isinstance(branch, SampleBranch))

    def test_create_branch_and_repo_under_shared(self):
        # creating a branch and repo in a shared repo uses the
        # shared repository
        format = controldir.format_registry.make_controldir("knit")
        self.make_repository(".", shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_and_repo(
            self.get_url("child"), format=format
        )
        self.assertRaises(errors.NoRepositoryPresent, branch.controldir.open_repository)

    def test_create_branch_and_repo_under_shared_force_new(self):
        # creating a branch and repo in a shared repo can be forced to
        # make a new repo
        format = controldir.format_registry.make_controldir("knit")
        self.make_repository(".", shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_and_repo(
            self.get_url("child"), force_new_repo=True, format=format
        )
        branch.controldir.open_repository()

    def test_create_standalone_working_tree(self):
        format = SampleBzrDirFormat()
        # note this is deliberately readonly, as this failure should
        # occur before any writes.
        self.assertRaises(
            errors.NotLocalUrl,
            bzrdir.BzrDir.create_standalone_workingtree,
            self.get_readonly_url(),
            format=format,
        )
        tree = bzrdir.BzrDir.create_standalone_workingtree(".", format=format)
        self.assertEqual("A tree", tree)

    def test_create_standalone_working_tree_under_shared_repo(self):
        # create standalone working tree always makes a repo.
        format = controldir.format_registry.make_controldir("knit")
        self.make_repository(".", shared=True, format=format)
        # note this is deliberately readonly, as this failure should
        # occur before any writes.
        self.assertRaises(
            errors.NotLocalUrl,
            bzrdir.BzrDir.create_standalone_workingtree,
            self.get_readonly_url("child"),
            format=format,
        )
        tree = bzrdir.BzrDir.create_standalone_workingtree("child", format=format)
        tree.controldir.open_repository()

    def test_create_branch_convenience(self):
        # outside a repo the default convenience output is a repo+branch_tree
        format = controldir.format_registry.make_controldir("knit")
        branch = bzrdir.BzrDir.create_branch_convenience(".", format=format)
        branch.controldir.open_workingtree()
        branch.controldir.open_repository()

    def test_create_branch_convenience_possible_transports(self):
        """Check that the optional 'possible_transports' is recognized."""
        format = controldir.format_registry.make_controldir("knit")
        t = self.get_transport()
        branch = bzrdir.BzrDir.create_branch_convenience(
            ".", format=format, possible_transports=[t]
        )
        branch.controldir.open_workingtree()
        branch.controldir.open_repository()

    def test_create_branch_convenience_root(self):
        """Creating a branch at the root of a fs should work."""
        self.vfs_transport_factory = memory.MemoryServer
        # outside a repo the default convenience output is a repo+branch_tree
        format = controldir.format_registry.make_controldir("knit")
        branch = bzrdir.BzrDir.create_branch_convenience(self.get_url(), format=format)
        self.assertRaises(errors.NoWorkingTree, branch.controldir.open_workingtree)
        branch.controldir.open_repository()

    def test_create_branch_convenience_under_shared_repo(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy
        format = controldir.format_registry.make_controldir("knit")
        self.make_repository(".", shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_convenience("child", format=format)
        branch.controldir.open_workingtree()
        self.assertRaises(errors.NoRepositoryPresent, branch.controldir.open_repository)

    def test_create_branch_convenience_under_shared_repo_force_no_tree(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy but we can override that
        format = controldir.format_registry.make_controldir("knit")
        self.make_repository(".", shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_convenience(
            "child", force_new_tree=False, format=format
        )
        self.assertRaises(errors.NoWorkingTree, branch.controldir.open_workingtree)
        self.assertRaises(errors.NoRepositoryPresent, branch.controldir.open_repository)

    def test_create_branch_convenience_under_shared_repo_no_tree_policy(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy
        format = controldir.format_registry.make_controldir("knit")
        repo = self.make_repository(".", shared=True, format=format)
        repo.set_make_working_trees(False)
        branch = bzrdir.BzrDir.create_branch_convenience("child", format=format)
        self.assertRaises(errors.NoWorkingTree, branch.controldir.open_workingtree)
        self.assertRaises(errors.NoRepositoryPresent, branch.controldir.open_repository)

    def test_create_branch_convenience_under_shared_repo_no_tree_policy_force_tree(
        self,
    ):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy but we can override that
        format = controldir.format_registry.make_controldir("knit")
        repo = self.make_repository(".", shared=True, format=format)
        repo.set_make_working_trees(False)
        branch = bzrdir.BzrDir.create_branch_convenience(
            "child", force_new_tree=True, format=format
        )
        branch.controldir.open_workingtree()
        self.assertRaises(errors.NoRepositoryPresent, branch.controldir.open_repository)

    def test_create_branch_convenience_under_shared_repo_force_new_repo(self):
        # inside a repo the default convenience output is overridable to give
        # repo+branch+tree
        format = controldir.format_registry.make_controldir("knit")
        self.make_repository(".", shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_convenience(
            "child", force_new_repo=True, format=format
        )
        branch.controldir.open_repository()
        branch.controldir.open_workingtree()


class TestRepositoryAcquisitionPolicy(TestCaseWithTransport):
    def test_acquire_repository_standalone(self):
        """The default acquisition policy should create a standalone branch."""
        my_bzrdir = self.make_controldir(".")
        repo_policy = my_bzrdir.determine_repository_policy()
        repo, is_new = repo_policy.acquire_repository()
        self.assertEqual(
            repo.controldir.root_transport.base, my_bzrdir.root_transport.base
        )
        self.assertFalse(repo.is_shared())

    def test_determine_stacking_policy(self):
        parent_bzrdir = self.make_controldir(".")
        child_bzrdir = self.make_controldir("child")
        parent_bzrdir.get_config().set_default_stack_on("http://example.org")
        repo_policy = child_bzrdir.determine_repository_policy()
        self.assertEqual("http://example.org", repo_policy._stack_on)

    def test_determine_stacking_policy_relative(self):
        parent_bzrdir = self.make_controldir(".")
        child_bzrdir = self.make_controldir("child")
        parent_bzrdir.get_config().set_default_stack_on("child2")
        repo_policy = child_bzrdir.determine_repository_policy()
        self.assertEqual("child2", repo_policy._stack_on)
        self.assertEqual(parent_bzrdir.root_transport.base, repo_policy._stack_on_pwd)

    def prepare_default_stacking(self, child_format="1.6"):
        parent_bzrdir = self.make_controldir(".")
        child_branch = self.make_branch("child", format=child_format)
        parent_bzrdir.get_config().set_default_stack_on(child_branch.base)
        new_child_transport = parent_bzrdir.transport.clone("child2")
        return child_branch, new_child_transport

    def test_clone_on_transport_obeys_stacking_policy(self):
        child_branch, new_child_transport = self.prepare_default_stacking()
        new_child = child_branch.controldir.clone_on_transport(new_child_transport)
        self.assertEqual(
            child_branch.base, new_child.open_branch().get_stacked_on_url()
        )

    def test_default_stacking_with_stackable_branch_unstackable_repo(self):
        # Make stackable source branch with an unstackable repo format.
        source_bzrdir = self.make_controldir("source")
        knitpack_repo.RepositoryFormatKnitPack1().initialize(source_bzrdir)
        breezy.bzr.branch.BzrBranchFormat7().initialize(source_bzrdir)
        # Make a directory with a default stacking policy
        parent_bzrdir = self.make_controldir("parent")
        stacked_on = self.make_branch("parent/stacked-on", format="pack-0.92")
        parent_bzrdir.get_config().set_default_stack_on(stacked_on.base)
        # Clone source into directory
        source_bzrdir.clone(self.get_url("parent/target"))

    def test_format_initialize_on_transport_ex_stacked_on(self):
        # trunk is a stackable format.  Note that its in the same server area
        # which is what launchpad does, but not sufficient to exercise the
        # general case.
        self.make_branch("trunk", format="1.9")
        t = self.get_transport("stacked")
        old_fmt = controldir.format_registry.make_controldir("pack-0.92")
        repo_name = old_fmt.repository_format.network_name()
        # Should end up with a 1.9 format (stackable)
        repo, control, require_stacking, repo_policy = (
            old_fmt.initialize_on_transport_ex(
                t,
                repo_format_name=repo_name,
                stacked_on="../trunk",
                stack_on_pwd=t.base,
            )
        )
        if repo is not None:
            # Repositories are open write-locked
            self.assertTrue(repo.is_write_locked())
            self.addCleanup(repo.unlock)
        else:
            repo = control.open_repository()
        self.assertIsInstance(control, bzrdir.BzrDir)
        opened = bzrdir.BzrDir.open(t.base)
        if not isinstance(old_fmt, remote.RemoteBzrDirFormat):
            self.assertEqual(control._format.network_name(), old_fmt.network_name())
            self.assertEqual(
                control._format.network_name(), opened._format.network_name()
            )
        self.assertEqual(control.__class__, opened.__class__)
        self.assertLength(1, repo._fallback_repositories)

    def test_sprout_obeys_stacking_policy(self):
        child_branch, new_child_transport = self.prepare_default_stacking()
        new_child = child_branch.controldir.sprout(new_child_transport.base)
        self.assertEqual(
            child_branch.base, new_child.open_branch().get_stacked_on_url()
        )

    def test_clone_ignores_policy_for_unsupported_formats(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format="pack-0.92"
        )
        new_child = child_branch.controldir.clone_on_transport(new_child_transport)
        self.assertRaises(
            branch.UnstackableBranchFormat, new_child.open_branch().get_stacked_on_url
        )

    def test_sprout_ignores_policy_for_unsupported_formats(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format="pack-0.92"
        )
        new_child = child_branch.controldir.sprout(new_child_transport.base)
        self.assertRaises(
            branch.UnstackableBranchFormat, new_child.open_branch().get_stacked_on_url
        )

    def test_sprout_upgrades_format_if_stacked_specified(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format="pack-0.92"
        )
        new_child = child_branch.controldir.sprout(
            new_child_transport.base, stacked=True
        )
        self.assertEqual(
            child_branch.controldir.root_transport.base,
            new_child.open_branch().get_stacked_on_url(),
        )
        repo = new_child.open_repository()
        self.assertTrue(repo._format.supports_external_lookups)
        self.assertFalse(repo.supports_rich_root())

    def test_clone_on_transport_upgrades_format_if_stacked_on_specified(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format="pack-0.92"
        )
        new_child = child_branch.controldir.clone_on_transport(
            new_child_transport, stacked_on=child_branch.controldir.root_transport.base
        )
        self.assertEqual(
            child_branch.controldir.root_transport.base,
            new_child.open_branch().get_stacked_on_url(),
        )
        repo = new_child.open_repository()
        self.assertTrue(repo._format.supports_external_lookups)
        self.assertFalse(repo.supports_rich_root())

    def test_sprout_upgrades_to_rich_root_format_if_needed(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format="rich-root-pack"
        )
        new_child = child_branch.controldir.sprout(
            new_child_transport.base, stacked=True
        )
        repo = new_child.open_repository()
        self.assertTrue(repo._format.supports_external_lookups)
        self.assertTrue(repo.supports_rich_root())

    def test_add_fallback_repo_handles_absolute_urls(self):
        stack_on = self.make_branch("stack_on", format="1.6")
        repo = self.make_repository("repo", format="1.6")
        policy = bzrdir.UseExistingRepository(repo, stack_on.base)
        policy._add_fallback(repo)

    def test_add_fallback_repo_handles_relative_urls(self):
        stack_on = self.make_branch("stack_on", format="1.6")
        repo = self.make_repository("repo", format="1.6")
        policy = bzrdir.UseExistingRepository(repo, ".", stack_on.base)
        policy._add_fallback(repo)

    def test_configure_relative_branch_stacking_url(self):
        stack_on = self.make_branch("stack_on", format="1.6")
        stacked = self.make_branch("stack_on/stacked", format="1.6")
        policy = bzrdir.UseExistingRepository(stacked.repository, ".", stack_on.base)
        policy.configure_branch(stacked)
        self.assertEqual("..", stacked.get_stacked_on_url())

    def test_relative_branch_stacking_to_absolute(self):
        self.make_branch("stack_on", format="1.6")
        stacked = self.make_branch("stack_on/stacked", format="1.6")
        policy = bzrdir.UseExistingRepository(
            stacked.repository, ".", self.get_readonly_url("stack_on")
        )
        policy.configure_branch(stacked)
        self.assertEqual(
            self.get_readonly_url("stack_on"), stacked.get_stacked_on_url()
        )


class ChrootedTests(TestCaseWithTransport):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super().setUp()
        if self.vfs_transport_factory != memory.MemoryServer:
            self.transport_readonly_server = http_server.HttpServer

    def local_branch_path(self, branch):
        return os.path.realpath(urlutils.local_path_from_url(branch.base))

    def test_open_containing(self):
        self.assertRaises(
            NotBranchError, bzrdir.BzrDir.open_containing, self.get_readonly_url("")
        )
        self.assertRaises(
            NotBranchError,
            bzrdir.BzrDir.open_containing,
            self.get_readonly_url("g/p/q"),
        )
        bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url(""))
        self.assertEqual("", relpath)
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url("g/p/q"))
        self.assertEqual("g/p/q", relpath)

    def test_open_containing_tree_branch_or_repository_empty(self):
        self.assertRaises(
            errors.NotBranchError,
            bzrdir.BzrDir.open_containing_tree_branch_or_repository,
            self.get_readonly_url(""),
        )

    def test_open_containing_tree_branch_or_repository_all(self):
        self.make_branch_and_tree("topdir")
        tree, branch, repo, relpath = (
            bzrdir.BzrDir.open_containing_tree_branch_or_repository("topdir/foo")
        )
        self.assertEqual(os.path.realpath("topdir"), os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath("topdir"), self.local_branch_path(branch))
        self.assertEqual(
            osutils.realpath(os.path.join("topdir", ".bzr", "repository")),
            repo.controldir.transport.local_abspath("repository"),
        )
        self.assertEqual(relpath, "foo")

    def test_open_containing_tree_branch_or_repository_no_tree(self):
        self.make_branch("branch")
        tree, branch, repo, relpath = (
            bzrdir.BzrDir.open_containing_tree_branch_or_repository("branch/foo")
        )
        self.assertEqual(tree, None)
        self.assertEqual(os.path.realpath("branch"), self.local_branch_path(branch))
        self.assertEqual(
            osutils.realpath(os.path.join("branch", ".bzr", "repository")),
            repo.controldir.transport.local_abspath("repository"),
        )
        self.assertEqual(relpath, "foo")

    def test_open_containing_tree_branch_or_repository_repo(self):
        self.make_repository("repo")
        tree, branch, repo, relpath = (
            bzrdir.BzrDir.open_containing_tree_branch_or_repository("repo")
        )
        self.assertEqual(tree, None)
        self.assertEqual(branch, None)
        self.assertEqual(
            osutils.realpath(os.path.join("repo", ".bzr", "repository")),
            repo.controldir.transport.local_abspath("repository"),
        )
        self.assertEqual(relpath, "")

    def test_open_containing_tree_branch_or_repository_shared_repo(self):
        self.make_repository("shared", shared=True)
        bzrdir.BzrDir.create_branch_convenience("shared/branch", force_new_tree=False)
        tree, branch, repo, relpath = (
            bzrdir.BzrDir.open_containing_tree_branch_or_repository("shared/branch")
        )
        self.assertEqual(tree, None)
        self.assertEqual(
            os.path.realpath("shared/branch"), self.local_branch_path(branch)
        )
        self.assertEqual(
            osutils.realpath(os.path.join("shared", ".bzr", "repository")),
            repo.controldir.transport.local_abspath("repository"),
        )
        self.assertEqual(relpath, "")

    def test_open_containing_tree_branch_or_repository_branch_subdir(self):
        self.make_branch_and_tree("foo")
        self.build_tree(["foo/bar/"])
        tree, branch, repo, relpath = (
            bzrdir.BzrDir.open_containing_tree_branch_or_repository("foo/bar")
        )
        self.assertEqual(os.path.realpath("foo"), os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath("foo"), self.local_branch_path(branch))
        self.assertEqual(
            osutils.realpath(os.path.join("foo", ".bzr", "repository")),
            repo.controldir.transport.local_abspath("repository"),
        )
        self.assertEqual(relpath, "bar")

    def test_open_containing_tree_branch_or_repository_repo_subdir(self):
        self.make_repository("bar")
        self.build_tree(["bar/baz/"])
        tree, branch, repo, relpath = (
            bzrdir.BzrDir.open_containing_tree_branch_or_repository("bar/baz")
        )
        self.assertEqual(tree, None)
        self.assertEqual(branch, None)
        self.assertEqual(
            osutils.realpath(os.path.join("bar", ".bzr", "repository")),
            repo.controldir.transport.local_abspath("repository"),
        )
        self.assertEqual(relpath, "baz")

    def test_open_containing_from_transport(self):
        self.assertRaises(
            NotBranchError,
            bzrdir.BzrDir.open_containing_from_transport,
            _mod_transport.get_transport_from_url(self.get_readonly_url("")),
        )
        self.assertRaises(
            NotBranchError,
            bzrdir.BzrDir.open_containing_from_transport,
            _mod_transport.get_transport_from_url(self.get_readonly_url("g/p/q")),
        )
        bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing_from_transport(
            _mod_transport.get_transport_from_url(self.get_readonly_url(""))
        )
        self.assertEqual("", relpath)
        branch, relpath = bzrdir.BzrDir.open_containing_from_transport(
            _mod_transport.get_transport_from_url(self.get_readonly_url("g/p/q"))
        )
        self.assertEqual("g/p/q", relpath)

    def test_open_containing_tree_or_branch(self):
        self.make_branch_and_tree("topdir")
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            "topdir/foo"
        )
        self.assertEqual(os.path.realpath("topdir"), os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath("topdir"), self.local_branch_path(branch))
        self.assertIs(tree.controldir, branch.controldir)
        self.assertEqual("foo", relpath)
        # opening from non-local should not return the tree
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            self.get_readonly_url("topdir/foo")
        )
        self.assertEqual(None, tree)
        self.assertEqual("foo", relpath)
        # without a tree:
        self.make_branch("topdir/foo")
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            "topdir/foo"
        )
        self.assertIs(tree, None)
        self.assertEqual(os.path.realpath("topdir/foo"), self.local_branch_path(branch))
        self.assertEqual("", relpath)

    def test_open_tree_or_branch(self):
        self.make_branch_and_tree("topdir")
        tree, branch = bzrdir.BzrDir.open_tree_or_branch("topdir")
        self.assertEqual(os.path.realpath("topdir"), os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath("topdir"), self.local_branch_path(branch))
        self.assertIs(tree.controldir, branch.controldir)
        # opening from non-local should not return the tree
        tree, branch = bzrdir.BzrDir.open_tree_or_branch(
            self.get_readonly_url("topdir")
        )
        self.assertEqual(None, tree)
        # without a tree:
        self.make_branch("topdir/foo")
        tree, branch = bzrdir.BzrDir.open_tree_or_branch("topdir/foo")
        self.assertIs(tree, None)
        self.assertEqual(os.path.realpath("topdir/foo"), self.local_branch_path(branch))

    def test_open_tree_or_branch_named(self):
        tree = self.make_branch_and_tree("topdir")
        self.assertRaises(
            NotBranchError, bzrdir.BzrDir.open_tree_or_branch, "topdir", name="missing"
        )
        tree.branch.controldir.create_branch("named")
        tree, branch = bzrdir.BzrDir.open_tree_or_branch("topdir", name="named")
        self.assertEqual(os.path.realpath("topdir"), os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath("topdir"), self.local_branch_path(branch))
        self.assertEqual(branch.name, "named")
        self.assertIs(tree.controldir, branch.controldir)

    def test_open_from_transport(self):
        # transport pointing at bzrdir should give a bzrdir with root transport
        # set to the given transport
        bzrdir.BzrDir.create(self.get_url())
        t = self.get_transport()
        opened_bzrdir = bzrdir.BzrDir.open_from_transport(t)
        self.assertEqual(t.base, opened_bzrdir.root_transport.base)
        self.assertIsInstance(opened_bzrdir, bzrdir.BzrDir)

    def test_open_from_transport_no_bzrdir(self):
        t = self.get_transport()
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_from_transport, t)

    def test_open_from_transport_bzrdir_in_parent(self):
        bzrdir.BzrDir.create(self.get_url())
        t = self.get_transport()
        t.mkdir("subdir")
        t = t.clone("subdir")
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_from_transport, t)

    def test_sprout_recursive(self):
        tree = self.make_branch_and_tree("tree1")
        sub_tree = self.make_branch_and_tree("tree1/subtree")
        sub_tree.set_root_id(b"subtree-root")
        tree.add_reference(sub_tree)
        tree.set_reference_info("subtree", sub_tree.branch.user_url)
        self.build_tree(["tree1/subtree/file"])
        sub_tree.add("file")
        tree.commit("Initial commit")
        tree2 = tree.controldir.sprout("tree2").open_workingtree()
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        self.assertPathExists("tree2/subtree/file")
        self.assertEqual("tree-reference", tree2.kind("subtree"))

    def test_cloning_metadir(self):
        """Ensure that cloning metadir is suitable."""
        bzrdir = self.make_controldir("bzrdir")
        bzrdir.cloning_metadir()
        branch = self.make_branch("branch", format="knit")
        format = branch.controldir.cloning_metadir()
        self.assertIsInstance(
            format.workingtree_format, workingtree_4.WorkingTreeFormat6
        )

    def test_sprout_recursive_treeless(self):
        tree = self.make_branch_and_tree("tree1", format="development-subtree")
        sub_tree = self.make_branch_and_tree(
            "tree1/subtree", format="development-subtree"
        )
        tree.add_reference(sub_tree)
        tree.set_reference_info("subtree", sub_tree.branch.user_url)
        self.build_tree(["tree1/subtree/file"])
        sub_tree.add("file")
        tree.commit("Initial commit")
        # The following line force the orhaning to reveal bug #634470
        tree.branch.get_config_stack().set("transform.orphan_policy", "move")
        tree.controldir.destroy_workingtree()
        # FIXME: subtree/.bzr is left here which allows the test to pass (or
        # fail :-( ) -- vila 20100909
        repo = self.make_repository("repo", shared=True, format="development-subtree")
        repo.set_make_working_trees(False)
        # FIXME: we just deleted the workingtree and now we want to use it ????
        # At a minimum, we should use tree.branch below (but this fails too
        # currently) or stop calling this test 'treeless'. Specifically, I've
        # turn the line below into an assertRaises when 'subtree/.bzr' is
        # orphaned and sprout tries to access the branch there (which is left
        # by bzrdir.BzrDirMeta1.destroy_workingtree when it ignores the
        # [DeletingParent('Not deleting', u'subtree', None)] conflict). See bug
        # #634470.  -- vila 20100909
        tree.controldir.sprout("repo/tree2")
        self.assertPathExists("repo/tree2/subtree")
        self.assertPathDoesNotExist("repo/tree2/subtree/file")

    def make_foo_bar_baz(self):
        foo = bzrdir.BzrDir.create_branch_convenience("foo").controldir
        bar = self.make_branch("foo/bar").controldir
        baz = self.make_branch("baz").controldir
        return foo, bar, baz

    def test_find_controldirs(self):
        foo, bar, baz = self.make_foo_bar_baz()
        t = self.get_transport()
        self.assertEqualBzrdirs([baz, foo, bar], bzrdir.BzrDir.find_controldirs(t))

    def make_fake_permission_denied_transport(self, transport, paths):
        """Create a transport that raises PermissionDenied for some paths."""

        def filter(path):
            if path in paths:
                raise errors.PermissionDenied(path)
            return path

        path_filter_server = pathfilter.PathFilteringServer(transport, filter)
        path_filter_server.start_server()
        self.addCleanup(path_filter_server.stop_server)
        path_filter_transport = pathfilter.PathFilteringTransport(
            path_filter_server, "."
        )
        return (path_filter_server, path_filter_transport)

    def assertBranchUrlsEndWith(self, expect_url_suffix, actual_bzrdirs):
        """Check that each branch url ends with the given suffix."""
        for actual_bzrdir in actual_bzrdirs:
            self.assertEndsWith(actual_bzrdir.user_url, expect_url_suffix)

    def test_find_controldirs_permission_denied(self):
        foo, bar, baz = self.make_foo_bar_baz()
        t = self.get_transport()
        path_filter_server, path_filter_transport = (
            self.make_fake_permission_denied_transport(t, ["foo"])
        )
        # local transport
        self.assertBranchUrlsEndWith(
            "/baz/", bzrdir.BzrDir.find_controldirs(path_filter_transport)
        )
        # smart server
        smart_transport = self.make_smart_server(".", backing_server=path_filter_server)
        self.assertBranchUrlsEndWith(
            "/baz/", bzrdir.BzrDir.find_controldirs(smart_transport)
        )

    def test_find_controldirs_list_current(self):
        def list_current(transport):
            return [s for s in transport.list_dir("") if s != "baz"]

        foo, bar, baz = self.make_foo_bar_baz()
        t = self.get_transport()
        self.assertEqualBzrdirs(
            [foo, bar], bzrdir.BzrDir.find_controldirs(t, list_current=list_current)
        )

    def test_find_controldirs_evaluate(self):
        def evaluate(bzrdir):
            try:
                bzrdir.open_repository()
            except errors.NoRepositoryPresent:
                return True, bzrdir.root_transport.base
            else:
                return False, bzrdir.root_transport.base

        foo, bar, baz = self.make_foo_bar_baz()
        t = self.get_transport()
        self.assertEqual(
            [baz.root_transport.base, foo.root_transport.base],
            list(bzrdir.BzrDir.find_controldirs(t, evaluate=evaluate)),
        )

    def assertEqualBzrdirs(self, first, second):
        first = list(first)
        second = list(second)
        self.assertEqual(len(first), len(second))
        for x, y in zip(first, second):
            self.assertEqual(x.root_transport.base, y.root_transport.base)

    def test_find_branches(self):
        self.make_repository("", shared=True)
        foo, bar, baz = self.make_foo_bar_baz()
        self.make_controldir("foo/qux")
        t = self.get_transport()
        branches = bzrdir.BzrDir.find_branches(t)
        self.assertEqual(baz.root_transport.base, branches[0].base)
        self.assertEqual(foo.root_transport.base, branches[1].base)
        self.assertEqual(bar.root_transport.base, branches[2].base)

        # ensure this works without a top-level repo
        branches = bzrdir.BzrDir.find_branches(t.clone("foo"))
        self.assertEqual(foo.root_transport.base, branches[0].base)
        self.assertEqual(bar.root_transport.base, branches[1].base)


class TestMissingRepoBranchesSkipped(TestCaseWithMemoryTransport):
    def test_find_controldirs_missing_repo(self):
        t = self.get_transport()
        arepo = self.make_repository("arepo", shared=True)
        abranch_url = arepo.user_url + "/abranch"
        bzrdir.BzrDir.create(abranch_url).create_branch()
        t.delete_tree("arepo/.bzr")
        self.assertRaises(errors.NoRepositoryPresent, branch.Branch.open, abranch_url)
        self.make_branch("baz")
        for actual_bzrdir in bzrdir.BzrDir.find_branches(t):
            self.assertEndsWith(actual_bzrdir.user_url, "/baz/")


class TestMeta1DirFormat(TestCaseWithTransport):
    """Tests specific to the meta1 dir format."""

    def test_right_base_dirs(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        t = dir.transport
        branch_base = t.clone("branch").base
        self.assertEqual(branch_base, dir.get_branch_transport(None).base)
        self.assertEqual(branch_base, dir.get_branch_transport(BzrBranchFormat5()).base)
        repository_base = t.clone("repository").base
        self.assertEqual(repository_base, dir.get_repository_transport(None).base)
        repository_format = repository.format_registry.get_default()
        self.assertEqual(
            repository_base, dir.get_repository_transport(repository_format).base
        )
        checkout_base = t.clone("checkout").base
        self.assertEqual(checkout_base, dir.get_workingtree_transport(None).base)
        self.assertEqual(
            checkout_base,
            dir.get_workingtree_transport(workingtree_3.WorkingTreeFormat3()).base,
        )

    def test_meta1dir_uses_lockdir(self):
        """Meta1 format uses a LockDir to guard the whole directory, not a file."""
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        t = dir.transport
        self.assertIsDirectory("branch-lock", t)

    def test_comparison(self):
        """Equality and inequality behave properly.

        Metadirs should compare equal iff they have the same repo, branch and
        tree formats.
        """
        mydir = controldir.format_registry.make_controldir("knit")
        self.assertEqual(mydir, mydir)
        self.assertFalse(mydir != mydir)
        otherdir = controldir.format_registry.make_controldir("knit")
        self.assertEqual(otherdir, mydir)
        self.assertFalse(otherdir != mydir)
        otherdir2 = controldir.format_registry.make_controldir("development-subtree")
        self.assertNotEqual(otherdir2, mydir)
        self.assertFalse(otherdir2 == mydir)

    def test_with_features(self):
        tree = self.make_branch_and_tree("tree", format="2a")
        tree.controldir.update_feature_flags({b"bar": b"required"})
        self.assertRaises(bzrdir.MissingFeature, bzrdir.BzrDir.open, "tree")
        bzrdir.BzrDirMetaFormat1.register_feature(b"bar")
        self.addCleanup(bzrdir.BzrDirMetaFormat1.unregister_feature, b"bar")
        dir = bzrdir.BzrDir.open("tree")
        self.assertEqual(b"required", dir._format.features.get(b"bar"))
        tree.controldir.update_feature_flags({b"bar": None, b"nonexistant": None})
        dir = bzrdir.BzrDir.open("tree")
        self.assertEqual({}, dir._format.features)

    def test_needs_conversion_different_working_tree(self):
        # meta1dirs need an conversion if any element is not the default.
        new_format = controldir.format_registry.make_controldir("dirstate")
        tree = self.make_branch_and_tree("tree", format="knit")
        self.assertTrue(tree.controldir.needs_format_conversion(new_format))

    def test_initialize_on_format_uses_smart_transport(self):
        self.setup_smart_server_with_call_log()
        new_format = controldir.format_registry.make_controldir("dirstate")
        transport = self.get_transport("target")
        transport.ensure_base()
        self.reset_smart_call_log()
        instance = new_format.initialize_on_transport(transport)
        self.assertIsInstance(instance, remote.RemoteBzrDir)
        rpc_count = len(self.hpss_calls)
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertEqual(2, rpc_count)


class NonLocalTests(TestCaseWithTransport):
    """Tests for bzrdir static behaviour on non local paths."""

    def setUp(self):
        super().setUp()
        self.vfs_transport_factory = memory.MemoryServer

    def test_create_branch_convenience(self):
        # outside a repo the default convenience output is a repo+branch_tree
        format = controldir.format_registry.make_controldir("knit")
        branch = bzrdir.BzrDir.create_branch_convenience(
            self.get_url("foo"), format=format
        )
        self.assertRaises(errors.NoWorkingTree, branch.controldir.open_workingtree)
        branch.controldir.open_repository()

    def test_create_branch_convenience_force_tree_not_local_fails(self):
        # outside a repo the default convenience output is a repo+branch_tree
        format = controldir.format_registry.make_controldir("knit")
        self.assertRaises(
            errors.NotLocalUrl,
            bzrdir.BzrDir.create_branch_convenience,
            self.get_url("foo"),
            force_new_tree=True,
            format=format,
        )
        t = self.get_transport()
        self.assertFalse(t.has("foo"))

    def test_clone(self):
        # clone into a nonlocal path works
        format = controldir.format_registry.make_controldir("knit")
        branch = bzrdir.BzrDir.create_branch_convenience("local", format=format)
        branch.controldir.open_workingtree()
        result = branch.controldir.clone(self.get_url("remote"))
        self.assertRaises(errors.NoWorkingTree, result.open_workingtree)
        result.open_branch()
        result.open_repository()

    def test_checkout_metadir(self):
        # checkout_metadir has reasonable working tree format even when no
        # working tree is present
        self.make_branch("branch-knit2", format="dirstate-with-subtree")
        my_bzrdir = bzrdir.BzrDir.open(self.get_url("branch-knit2"))
        checkout_format = my_bzrdir.checkout_metadir()
        self.assertIsInstance(
            checkout_format.workingtree_format, workingtree_4.WorkingTreeFormat4
        )


class TestHTTPRedirectionsBase:
    """Test redirection between two http servers.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithTwoWebservers.

    We can't inherit directly from TestCaseWithTwoWebservers or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    def create_transport_readonly_server(self):
        # We don't set the http protocol version, relying on the default
        return http_utils.HTTPServerRedirecting()

    def create_transport_secondary_server(self):
        # We don't set the http protocol version, relying on the default
        return http_utils.HTTPServerRedirecting()

    def setUp(self):
        super().setUp()
        # The redirections will point to the new server
        self.new_server = self.get_readonly_server()
        # The requests to the old server will be redirected
        self.old_server = self.get_secondary_server()
        # Configure the redirections
        self.old_server.redirect_to(self.new_server.host, self.new_server.port)

    def test_loop(self):
        # Both servers redirect to each other creating a loop
        self.new_server.redirect_to(self.old_server.host, self.old_server.port)
        # Starting from either server should loop
        old_url = self._qualified_url(self.old_server.host, self.old_server.port)
        oldt = self._transport(old_url)
        self.assertRaises(
            errors.NotBranchError, bzrdir.BzrDir.open_from_transport, oldt
        )
        new_url = self._qualified_url(self.new_server.host, self.new_server.port)
        newt = self._transport(new_url)
        self.assertRaises(
            errors.NotBranchError, bzrdir.BzrDir.open_from_transport, newt
        )

    def test_qualifier_preserved(self):
        self.make_branch_and_tree("branch")
        old_url = self._qualified_url(self.old_server.host, self.old_server.port)
        start = self._transport(old_url).clone("branch")
        bdir = bzrdir.BzrDir.open_from_transport(start)
        # Redirection should preserve the qualifier, hence the transport class
        # itself.
        self.assertIsInstance(bdir.root_transport, type(start))


class TestHTTPRedirections(
    TestHTTPRedirectionsBase, http_utils.TestCaseWithTwoWebservers
):
    """Tests redirections for urllib implementation."""

    _transport = HttpTransport

    def _qualified_url(self, host, port):
        result = "http://{}:{}".format(host, port)
        self.permit_url(result)
        return result


class TestHTTPRedirections_nosmart(
    TestHTTPRedirectionsBase, http_utils.TestCaseWithTwoWebservers
):
    """Tests redirections for the nosmart decorator."""

    _transport = NoSmartTransportDecorator

    def _qualified_url(self, host, port):
        result = "nosmart+http://{}:{}".format(host, port)
        self.permit_url(result)
        return result


class TestHTTPRedirections_readonly(
    TestHTTPRedirectionsBase, http_utils.TestCaseWithTwoWebservers
):
    """Tests redirections for readonly decoratror."""

    _transport = ReadonlyTransportDecorator

    def _qualified_url(self, host, port):
        result = "readonly+http://{}:{}".format(host, port)
        self.permit_url(result)
        return result


class TestDotBzrHidden(TestCaseWithTransport):
    ls = ["ls"]
    if sys.platform == "win32":
        ls = [os.environ["COMSPEC"], "/C", "dir", "/B"]

    def get_ls(self):
        f = subprocess.Popen(self.ls, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = f.communicate()
        self.assertEqual(0, f.returncode, "Calling {} failed: {}".format(self.ls, err))
        return out.splitlines()

    def test_dot_bzr_hidden(self):
        bzrdir.BzrDir.create(".")
        self.build_tree(["a"])
        self.assertEqual([b"a"], self.get_ls())

    def test_dot_bzr_hidden_with_url(self):
        bzrdir.BzrDir.create(urlutils.local_path_to_url("."))
        self.build_tree(["a"])
        self.assertEqual([b"a"], self.get_ls())


class _TestBzrDirFormat(bzrdir.BzrDirMetaFormat1):
    """Test BzrDirFormat implementation for TestBzrDirSprout."""

    def _open(self, transport):
        return _TestBzrDir(transport, self)


class _TestBzrDir(bzrdir.BzrDirMeta1):
    """Test BzrDir implementation for TestBzrDirSprout.

    When created a _TestBzrDir already has repository and a branch.  The branch
    is a test double as well.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.test_branch = _TestBranch(self.transport)
        self.test_branch.repository = self.create_repository()

    def open_branch(self, unsupported=False, possible_transports=None):
        return self.test_branch

    def cloning_metadir(self, require_stacking=False):
        return _TestBzrDirFormat()


class _TestBranchFormat(breezy.branch.BranchFormat):
    """Test Branch format for TestBzrDirSprout."""


class _TestBranch(breezy.branch.Branch):
    """Test Branch implementation for TestBzrDirSprout."""

    @property
    def control_transport(self):
        return self._transport

    def __init__(self, transport, *args, **kwargs):
        self._format = _TestBranchFormat()
        self._transport = transport
        self.base = transport.base
        super().__init__(*args, **kwargs)
        self.calls = []
        self._parent = None

    def sprout(self, *args, **kwargs):
        self.calls.append("sprout")
        return _TestBranch(self._transport)

    def copy_content_into(self, destination, revision_id=None):
        self.calls.append("copy_content_into")

    def last_revision(self):
        return _mod_revision.NULL_REVISION

    def get_parent(self):
        return self._parent

    def _get_config(self):
        return config.TransportConfig(self._transport, "branch.conf")

    def _get_config_store(self):
        return config.BranchStore(self)

    def set_parent(self, parent):
        self._parent = parent

    def lock_read(self):
        return lock.LogicalLockResult(self.unlock)

    def unlock(self):
        return


class TestBzrDirSprout(TestCaseWithMemoryTransport):
    def test_sprout_uses_branch_sprout(self):
        """BzrDir.sprout calls Branch.sprout.

        Usually, BzrDir.sprout should delegate to the branch's sprout method
        for part of the work.  This allows the source branch to control the
        choice of format for the new branch.

        There are exceptions, but this tests avoids them:
          - if there's no branch in the source bzrdir,
          - or if the stacking has been requested and the format needs to be
            overridden to satisfy that.
        """
        # Make an instrumented bzrdir.
        t = self.get_transport("source")
        t.ensure_base()
        source_bzrdir = _TestBzrDirFormat().initialize_on_transport(t)
        # The instrumented bzrdir has a test_branch attribute that logs calls
        # made to the branch contained in that bzrdir.  Initially the test
        # branch exists but no calls have been made to it.
        self.assertEqual([], source_bzrdir.test_branch.calls)

        # Sprout the bzrdir
        target_url = self.get_url("target")
        source_bzrdir.sprout(target_url, recurse="no")

        # The bzrdir called the branch's sprout method.
        self.assertSubset(["sprout"], source_bzrdir.test_branch.calls)

    def test_sprout_parent(self):
        grandparent_tree = self.make_branch("grandparent")
        parent = grandparent_tree.controldir.sprout("parent").open_branch()
        branch_tree = parent.controldir.sprout("branch").open_branch()
        self.assertContainsRe(branch_tree.get_parent(), "/parent/$")


class TestBzrDirHooks(TestCaseWithMemoryTransport):
    def test_pre_open_called(self):
        calls = []
        bzrdir.BzrDir.hooks.install_named_hook("pre_open", calls.append, None)
        transport = self.get_transport("foo")
        url = transport.base
        self.assertRaises(errors.NotBranchError, bzrdir.BzrDir.open, url)
        self.assertEqual([transport.base], [t.base for t in calls])

    def test_pre_open_actual_exceptions_raised(self):
        count = [0]

        def fail_once(transport):
            count[0] += 1
            if count[0] == 1:
                raise errors.BzrError("fail")

        bzrdir.BzrDir.hooks.install_named_hook("pre_open", fail_once, None)
        transport = self.get_transport("foo")
        url = transport.base
        err = self.assertRaises(errors.BzrError, bzrdir.BzrDir.open, url)
        self.assertEqual("fail", err._preformatted_string)

    def test_post_repo_init(self):
        from ...controldir import RepoInitHookParams

        calls = []
        bzrdir.BzrDir.hooks.install_named_hook("post_repo_init", calls.append, None)
        self.make_repository("foo")
        self.assertLength(1, calls)
        params = calls[0]
        self.assertIsInstance(params, RepoInitHookParams)
        self.assertTrue(hasattr(params, "controldir"))
        self.assertTrue(hasattr(params, "repository"))

    def test_post_repo_init_hook_repr(self):
        param_reprs = []
        bzrdir.BzrDir.hooks.install_named_hook(
            "post_repo_init", lambda params: param_reprs.append(repr(params)), None
        )
        self.make_repository("foo")
        self.assertLength(1, param_reprs)
        param_repr = param_reprs[0]
        self.assertStartsWith(param_repr, "<RepoInitHookParams for ")


class TestGenerateBackupName(TestCaseWithMemoryTransport):
    # FIXME: This may need to be unified with test_osutils.TestBackupNames or
    # moved to per_bzrdir or per_transport for better coverage ?
    # -- vila 20100909

    def setUp(self):
        super().setUp()
        self._transport = self.get_transport()
        bzrdir.BzrDir.create(self.get_url(), possible_transports=[self._transport])
        self._bzrdir = bzrdir.BzrDir.open_from_transport(self._transport)

    def test_new(self):
        self.assertEqual("a.~1~", self._bzrdir._available_backup_name("a"))

    def test_exiting(self):
        self._transport.put_bytes("a.~1~", b"some content")
        self.assertEqual("a.~2~", self._bzrdir._available_backup_name("a"))


class TestMeta1DirColoFormat(TestCaseWithTransport):
    """Tests specific to the meta1 dir with colocated branches format."""

    def test_supports_colo(self):
        format = bzrdir.BzrDirMetaFormat1Colo()
        self.assertTrue(format.colocated_branches)

    def test_upgrade_from_2a(self):
        tree = self.make_branch_and_tree(".", format="2a")
        format = bzrdir.BzrDirMetaFormat1Colo()
        self.assertTrue(tree.controldir.needs_format_conversion(format))
        converter = tree.controldir._format.get_converter(format)
        result = converter.convert(tree.controldir, None)
        self.assertIsInstance(result._format, bzrdir.BzrDirMetaFormat1Colo)
        self.assertFalse(result.needs_format_conversion(format))

    def test_downgrade_to_2a(self):
        tree = self.make_branch_and_tree(".", format="development-colo")
        format = bzrdir.BzrDirMetaFormat1()
        self.assertTrue(tree.controldir.needs_format_conversion(format))
        converter = tree.controldir._format.get_converter(format)
        result = converter.convert(tree.controldir, None)
        self.assertIsInstance(result._format, bzrdir.BzrDirMetaFormat1)
        self.assertFalse(result.needs_format_conversion(format))

    def test_downgrade_to_2a_too_many_branches(self):
        tree = self.make_branch_and_tree(".", format="development-colo")
        tree.controldir.create_branch(name="another-colocated-branch")
        converter = tree.controldir._format.get_converter(bzrdir.BzrDirMetaFormat1())
        result = converter.convert(tree.controldir, bzrdir.BzrDirMetaFormat1())
        self.assertIsInstance(result._format, bzrdir.BzrDirMetaFormat1)

    def test_nested(self):
        tree = self.make_branch_and_tree(".", format="development-colo")
        tree.controldir.create_branch(name="foo")
        tree.controldir.create_branch(name="fool/bla")
        self.assertRaises(
            errors.ParentBranchExists, tree.controldir.create_branch, name="foo/bar"
        )

    def test_parent(self):
        tree = self.make_branch_and_tree(".", format="development-colo")
        tree.controldir.create_branch(name="fool/bla")
        tree.controldir.create_branch(name="foo/bar")
        self.assertRaises(
            errors.AlreadyBranchError, tree.controldir.create_branch, name="foo"
        )

    def test_supports_relative_reference(self):
        tree = self.make_branch_and_tree(".", format="development-colo")
        target1 = tree.controldir.create_branch(name="target1")
        target2 = tree.controldir.create_branch(name="target2")
        source = tree.controldir.set_branch_reference(target1, name="source")
        self.assertEqual(
            target1.user_url, tree.controldir.open_branch("source").user_url
        )
        source.controldir.get_branch_transport(None, "source").put_bytes(
            "location", b"file:,branch=target2"
        )
        self.assertEqual(
            target2.user_url, tree.controldir.open_branch("source").user_url
        )


class SampleBzrFormat(bzrdir.BzrFormat):
    @classmethod
    def get_format_string(cls):
        return b"First line\n"


class TestBzrFormat(TestCase):
    """Tests for BzrFormat."""

    def test_as_string(self):
        format = SampleBzrFormat()
        format.features = {b"foo": b"required"}
        self.assertEqual(format.as_string(), b"First line\nrequired foo\n")
        format.features[b"another"] = b"optional"
        self.assertEqual(
            format.as_string(), b"First line\noptional another\nrequired foo\n"
        )

    def test_network_name(self):
        # The network string should include the feature info
        format = SampleBzrFormat()
        format.features = {b"foo": b"required"}
        self.assertEqual(b"First line\nrequired foo\n", format.network_name())

    def test_from_string_no_features(self):
        # No features
        format = SampleBzrFormat.from_string(b"First line\n")
        self.assertEqual({}, format.features)

    def test_from_string_with_feature(self):
        # Proper feature
        format = SampleBzrFormat.from_string(b"First line\nrequired foo\n")
        self.assertEqual(b"required", format.features.get(b"foo"))

    def test_from_string_format_string_mismatch(self):
        # The first line has to match the format string
        self.assertRaises(
            AssertionError, SampleBzrFormat.from_string, b"Second line\nrequired foo\n"
        )

    def test_from_string_missing_space(self):
        # At least one space is required in the feature lines
        self.assertRaises(
            errors.ParseFormatError, SampleBzrFormat.from_string, b"First line\nfoo\n"
        )

    def test_from_string_with_spaces(self):
        # Feature with spaces (in case we add stuff like this in the future)
        format = SampleBzrFormat.from_string(b"First line\nrequired foo with spaces\n")
        self.assertEqual(b"required", format.features.get(b"foo with spaces"))

    def test_eq(self):
        format1 = SampleBzrFormat()
        format1.features = {b"nested-trees": b"optional"}
        format2 = SampleBzrFormat()
        format2.features = {b"nested-trees": b"optional"}
        self.assertEqual(format1, format1)
        self.assertEqual(format1, format2)
        format3 = SampleBzrFormat()
        self.assertNotEqual(format1, format3)

    def test_check_support_status_optional(self):
        # Optional, so silently ignore
        format = SampleBzrFormat()
        format.features = {b"nested-trees": b"optional"}
        format.check_support_status(True)
        self.addCleanup(SampleBzrFormat.unregister_feature, b"nested-trees")
        SampleBzrFormat.register_feature(b"nested-trees")
        format.check_support_status(True)

    def test_check_support_status_required(self):
        # Optional, so trigger an exception
        format = SampleBzrFormat()
        format.features = {b"nested-trees": b"required"}
        self.assertRaises(bzrdir.MissingFeature, format.check_support_status, True)
        self.addCleanup(SampleBzrFormat.unregister_feature, b"nested-trees")
        SampleBzrFormat.register_feature(b"nested-trees")
        format.check_support_status(True)

    def test_check_support_status_unknown(self):
        # treat unknown necessity as required
        format = SampleBzrFormat()
        format.features = {b"nested-trees": b"unknown"}
        self.assertRaises(bzrdir.MissingFeature, format.check_support_status, True)
        self.addCleanup(SampleBzrFormat.unregister_feature, b"nested-trees")
        SampleBzrFormat.register_feature(b"nested-trees")
        format.check_support_status(True)

    def test_feature_already_registered(self):
        # a feature can only be registered once
        self.addCleanup(SampleBzrFormat.unregister_feature, b"nested-trees")
        SampleBzrFormat.register_feature(b"nested-trees")
        self.assertRaises(
            bzrdir.FeatureAlreadyRegistered,
            SampleBzrFormat.register_feature,
            b"nested-trees",
        )

    def test_feature_with_space(self):
        # spaces are not allowed in feature names
        self.assertRaises(ValueError, SampleBzrFormat.register_feature, b"nested trees")
