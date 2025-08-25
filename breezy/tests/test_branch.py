# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for the Branch facility that are not interface  tests.

For interface tests see `tests/per_branch/*.py`.

For concrete class tests see this file, and for meta-branch tests
also see this file.
"""

from io import StringIO

from .. import bedding, config, controldir, errors, tests, trace, urlutils
from .. import branch as _mod_branch
from ..bzr import branch as _mod_bzrbranch
from ..bzr import bzrdir
from ..bzr.fullhistory import BzrBranch5, BzrBranchFormat5


class TestErrors(tests.TestCase):
    def test_unstackable_branch_format(self):
        format = "foo"
        url = "/foo"
        error = _mod_branch.UnstackableBranchFormat(format, url)
        self.assertEqualDiff(
            "The branch '/foo'(foo) is not a stackable format. "
            "You will need to upgrade the branch to permit branch stacking.",
            str(error),
        )


class TestDefaultFormat(tests.TestCase):
    def test_default_format(self):
        # update this if you change the default branch format
        self.assertIsInstance(
            _mod_branch.format_registry.get_default(), _mod_bzrbranch.BzrBranchFormat7
        )

    def test_default_format_is_same_as_bzrdir_default(self):
        # XXX: it might be nice if there was only one place the default was
        # set, but at the moment that's not true -- mbp 20070814 --
        # https://bugs.launchpad.net/bzr/+bug/132376
        self.assertEqual(
            _mod_branch.format_registry.get_default(),
            bzrdir.BzrDirFormat.get_default_format().get_branch_format(),
        )

    def test_get_set_default_format(self):
        # set the format and then set it back again
        old_format = _mod_branch.format_registry.get_default()
        _mod_branch.format_registry.set_default(SampleBranchFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize("memory:///")
            result = dir.create_branch()
            self.assertEqual(result, "A branch")
        finally:
            _mod_branch.format_registry.set_default(old_format)
        self.assertEqual(old_format, _mod_branch.format_registry.get_default())


class TestBranchFormat5(tests.TestCaseWithTransport):
    """Tests specific to branch format 5."""

    def test_branch_format_5_uses_lockdir(self):
        url = self.get_url()
        bdir = bzrdir.BzrDirMetaFormat1().initialize(url)
        bdir.create_repository()
        branch = BzrBranchFormat5().initialize(bdir)
        t = self.get_transport()
        self.log(f"branch instance is {branch!r}")
        self.assertIsInstance(branch, BzrBranch5)
        self.assertIsDirectory(".", t)
        self.assertIsDirectory(".bzr/branch", t)
        self.assertIsDirectory(".bzr/branch/lock", t)
        branch.lock_write()
        self.addCleanup(branch.unlock)
        self.assertIsDirectory(".bzr/branch/lock/held", t)

    def test_set_push_location(self):
        config.LocationConfig.from_string("# comment\n", ".", save=True)

        branch = self.make_branch(".", format="knit")
        branch.set_push_location("foo")
        local_path = urlutils.local_path_from_url(branch.base[:-1])
        self.assertFileEqual(
            b"# comment\n"
            b"[%s]\n"
            b"push_location = foo\n"
            b"push_location:policy = norecurse\n" % local_path.encode("utf-8"),
            bedding.locations_config_path(),
        )

    # TODO RBC 20051029 test getting a push location from a branch in a
    # recursive section - that is, it appends the branch name.


class SampleBranchFormat(_mod_bzrbranch.BranchFormatMetadir):
    """A sample format.

    this format is initializable, unsupported to aid in testing the
    open and open_downlevel routines.
    """

    @classmethod
    def get_format_string(cls):
        """See BzrBranchFormat.get_format_string()."""
        return b"Sample branch format."

    def initialize(
        self, a_controldir, name=None, repository=None, append_revisions_only=None
    ):
        """Format 4 branches cannot be created."""
        t = a_controldir.get_branch_transport(self, name=name)
        t.put_bytes("format", self.get_format_string())
        return "A branch"

    def is_supported(self):
        return False

    def open(
        self,
        transport,
        name=None,
        _found=False,
        ignore_fallbacks=False,
        possible_transports=None,
    ):
        return "opened branch."


# Demonstrating how lazy loading is often implemented:
# A constant string is created.
SampleSupportedBranchFormatString = b"Sample supported branch format."

# And the format class can then reference the constant to avoid skew.


class SampleSupportedBranchFormat(_mod_bzrbranch.BranchFormatMetadir):
    """A sample supported format."""

    @classmethod
    def get_format_string(cls):
        """See BzrBranchFormat.get_format_string()."""
        return SampleSupportedBranchFormatString

    def initialize(self, a_controldir, name=None, append_revisions_only=None):
        t = a_controldir.get_branch_transport(self, name=name)
        t.put_bytes("format", self.get_format_string())
        return "A branch"

    def open(
        self,
        transport,
        name=None,
        _found=False,
        ignore_fallbacks=False,
        possible_transports=None,
    ):
        return "opened supported branch."


class SampleExtraBranchFormat(_mod_branch.BranchFormat):
    """A sample format that is not usable in a metadir."""

    def get_format_string(self):
        # This format is not usable in a metadir.
        return None

    def network_name(self):
        # Network name always has to be provided.
        return "extra"

    def initialize(self, a_controldir, name=None):
        raise NotImplementedError(self.initialize)

    def open(
        self,
        transport,
        name=None,
        _found=False,
        ignore_fallbacks=False,
        possible_transports=None,
    ):
        raise NotImplementedError(self.open)


class TestBzrBranchFormat(tests.TestCaseWithTransport):
    """Tests for the BzrBranchFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as
        self.build_tree(["foo/", "bar/"])

        def check_format(format, url):
            dir = format._matchingcontroldir.initialize(url)
            dir.create_repository()
            format.initialize(dir)
            found_format = _mod_bzrbranch.BranchFormatMetadir.find_format(dir)
            self.assertIsInstance(found_format, format.__class__)

        check_format(BzrBranchFormat5(), "bar")

    def test_from_string(self):
        self.assertIsInstance(
            SampleBranchFormat.from_string(b"Sample branch format."), SampleBranchFormat
        )
        self.assertRaises(
            AssertionError, SampleBranchFormat.from_string, b"Different branch format."
        )

    def test_find_format_not_branch(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        self.assertRaises(
            errors.NotBranchError, _mod_bzrbranch.BranchFormatMetadir.find_format, dir
        )

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        SampleBranchFormat().initialize(dir)
        self.assertRaises(
            errors.UnknownFormatError,
            _mod_bzrbranch.BranchFormatMetadir.find_format,
            dir,
        )

    def test_find_format_with_features(self):
        tree = self.make_branch_and_tree(".", format="2a")
        tree.branch.update_feature_flags({b"name": b"optional"})
        found_format = _mod_bzrbranch.BranchFormatMetadir.find_format(tree.controldir)
        self.assertIsInstance(found_format, _mod_bzrbranch.BranchFormatMetadir)
        self.assertEqual(found_format.features.get(b"name"), b"optional")
        tree.branch.update_feature_flags({b"name": None})
        branch = _mod_branch.Branch.open(".")
        self.assertEqual(branch._format.features, {})


class TestBranchFormatRegistry(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.registry = _mod_branch.BranchFormatRegistry()

    def test_default(self):
        self.assertIs(None, self.registry.get_default())
        format = SampleBranchFormat()
        self.registry.set_default(format)
        self.assertEqual(format, self.registry.get_default())

    def test_register_unregister_format(self):
        format = SampleBranchFormat()
        self.registry.register(format)
        self.assertEqual(format, self.registry.get(b"Sample branch format."))
        self.registry.remove(format)
        self.assertRaises(KeyError, self.registry.get, b"Sample branch format.")

    def test_get_all(self):
        format = SampleBranchFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register(format)
        self.assertEqual([format], self.registry._get_all())

    def test_register_extra(self):
        format = SampleExtraBranchFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra(format)
        self.assertEqual([format], self.registry._get_all())

    def test_register_extra_lazy(self):
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra_lazy(
            "breezy.tests.test_branch", "SampleExtraBranchFormat"
        )
        formats = self.registry._get_all()
        self.assertEqual(1, len(formats))
        self.assertIsInstance(formats[0], SampleExtraBranchFormat)


class TestBranch67:
    """Common tests for both branch 6 and 7 which are mostly the same."""

    def get_format_name(self):
        raise NotImplementedError(self.get_format_name)

    def get_format_name_subtree(self):
        raise NotImplementedError(self.get_format_name)

    def get_class(self):
        raise NotImplementedError(self.get_class)

    def test_creation(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.set_branch_format(_mod_bzrbranch.BzrBranchFormat6())
        branch = self.make_branch("a", format=format)
        self.assertIsInstance(branch, self.get_class())
        branch = self.make_branch("b", format=self.get_format_name())
        self.assertIsInstance(branch, self.get_class())
        branch = _mod_branch.Branch.open("a")
        self.assertIsInstance(branch, self.get_class())

    def test_layout(self):
        self.make_branch("a", format=self.get_format_name())
        self.assertPathExists("a/.bzr/branch/last-revision")
        self.assertPathDoesNotExist("a/.bzr/branch/revision-history")
        self.assertPathDoesNotExist("a/.bzr/branch/references")

    def test_config(self):
        """Ensure that all configuration data is stored in the branch."""
        branch = self.make_branch("a", format=self.get_format_name())
        branch.set_parent("http://example.com")
        self.assertPathDoesNotExist("a/.bzr/branch/parent")
        self.assertEqual("http://example.com", branch.get_parent())
        branch.set_push_location("sftp://example.com")
        conf = branch.get_config_stack()
        self.assertEqual("sftp://example.com", conf.get("push_location"))
        branch.set_bound_location("ftp://example.com")
        self.assertPathDoesNotExist("a/.bzr/branch/bound")
        self.assertEqual("ftp://example.com", branch.get_bound_location())

    def do_checkout_test(self, lightweight):
        tree = self.make_branch_and_tree(
            "source", format=self.get_format_name_subtree()
        )
        subtree = self.make_branch_and_tree(
            "source/subtree", format=self.get_format_name_subtree()
        )
        subsubtree = self.make_branch_and_tree(
            "source/subtree/subsubtree", format=self.get_format_name_subtree()
        )
        self.build_tree(["source/subtree/file", "source/subtree/subsubtree/file"])
        subsubtree.add("file")
        subtree.add("file")
        subtree.add_reference(subsubtree)
        subtree.set_reference_info("subsubtree", subsubtree.branch.user_url)
        tree.add_reference(subtree)
        tree.set_reference_info("subtree", subtree.branch.user_url)
        tree.commit("a revision")
        subtree.commit("a subtree file")
        subsubtree.commit("a subsubtree file")
        tree.branch.create_checkout("target", lightweight=lightweight)
        self.assertPathExists("target")
        self.assertPathExists("target/subtree")
        self.assertPathExists("target/subtree/file")
        self.assertPathExists("target/subtree/subsubtree/file")
        subbranch = _mod_branch.Branch.open("target/subtree/subsubtree")
        if lightweight:
            self.assertEndsWith(subbranch.base, "source/subtree/subsubtree/")
        else:
            self.assertEndsWith(subbranch.base, "target/subtree/subsubtree/")

    def test_checkout_with_references(self):
        self.do_checkout_test(lightweight=False)

    def test_light_checkout_with_references(self):
        self.do_checkout_test(lightweight=True)


class TestBranch6(TestBranch67, tests.TestCaseWithTransport):
    def get_class(self):
        return _mod_bzrbranch.BzrBranch6

    def get_format_name(self):
        return "dirstate-tags"

    def get_format_name_subtree(self):
        return "dirstate-with-subtree"

    def test_set_stacked_on_url_errors(self):
        branch = self.make_branch("a", format=self.get_format_name())
        self.assertRaises(
            _mod_branch.UnstackableBranchFormat, branch.set_stacked_on_url, None
        )

    def test_default_stacked_location(self):
        branch = self.make_branch("a", format=self.get_format_name())
        self.assertRaises(
            _mod_branch.UnstackableBranchFormat, branch.get_stacked_on_url
        )


class TestBranch7(TestBranch67, tests.TestCaseWithTransport):
    def get_class(self):
        return _mod_bzrbranch.BzrBranch7

    def get_format_name(self):
        return "1.9"

    def get_format_name_subtree(self):
        return "development-subtree"

    def test_set_stacked_on_url_unstackable_repo(self):
        repo = self.make_repository("a", format="dirstate-tags")
        control = repo.controldir
        branch = _mod_bzrbranch.BzrBranchFormat7().initialize(control)
        target = self.make_branch("b")
        self.assertRaises(
            errors.UnstackableRepositoryFormat, branch.set_stacked_on_url, target.base
        )

    def test_clone_stacked_on_unstackable_repo(self):
        repo = self.make_repository("a", format="dirstate-tags")
        control = repo.controldir
        _mod_bzrbranch.BzrBranchFormat7().initialize(control)
        # Calling clone should not raise UnstackableRepositoryFormat.
        control.clone("cloned")

    def _test_default_stacked_location(self):
        branch = self.make_branch("a", format=self.get_format_name())
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)

    def test_stack_and_unstack(self):
        branch = self.make_branch("a", format=self.get_format_name())
        target = self.make_branch_and_tree("b", format=self.get_format_name())
        branch.set_stacked_on_url(target.branch.base)
        self.assertEqual(target.branch.base, branch.get_stacked_on_url())
        revid = target.commit("foo")
        self.assertTrue(branch.repository.has_revision(revid))
        branch.set_stacked_on_url(None)
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)
        self.assertFalse(branch.repository.has_revision(revid))

    def test_open_opens_stacked_reference(self):
        branch = self.make_branch("a", format=self.get_format_name())
        target = self.make_branch_and_tree("b", format=self.get_format_name())
        branch.set_stacked_on_url(target.branch.base)
        branch = branch.controldir.open_branch()
        revid = target.commit("foo")
        self.assertTrue(branch.repository.has_revision(revid))


class BzrBranch8(tests.TestCaseWithTransport):
    def make_branch(self, location, format=None):
        if format is None:
            format = controldir.format_registry.make_controldir("1.9")
            format.set_branch_format(_mod_bzrbranch.BzrBranchFormat8())
        return tests.TestCaseWithTransport.make_branch(self, location, format=format)

    def create_branch_with_reference(self):
        branch = self.make_branch("branch")
        branch._set_all_reference_info({b"file-id": ("location", "path")})
        return branch

    @staticmethod
    def instrument_branch(branch, gets):
        class WrapTransport:
            __slots__ = ("t",)

            def __init__(self, t):
                self.t = t

            def get(self, *args, **kwargs):
                gets.append((args, kwargs))
                return self.t.get(*args, **kwargs)

            def __getattr__(self, n):
                return getattr(self.t, n)

        branch._transport = WrapTransport(branch._transport)

    def test_reference_info_caching_read_locked(self):
        gets = []
        branch = self.create_branch_with_reference()
        branch.lock_read()
        self.addCleanup(branch.unlock)
        self.instrument_branch(branch, gets)
        branch.get_reference_info(b"file-id")
        branch.get_reference_info(b"file-id")
        self.assertEqual(1, len(gets))

    def test_reference_info_caching_read_unlocked(self):
        gets = []
        branch = self.create_branch_with_reference()
        self.instrument_branch(branch, gets)
        branch.get_reference_info("path")
        branch.get_reference_info("path")
        self.assertEqual(2, len(gets))

    def test_reference_info_caching_write_locked(self):
        gets = []
        branch = self.make_branch("branch")
        branch.lock_write()
        self.instrument_branch(branch, gets)
        self.addCleanup(branch.unlock)
        branch._set_all_reference_info({b"file-id": ("location2", "path2")})
        location, path = branch.get_reference_info(b"file-id")
        self.assertEqual(0, len(gets))
        self.assertEqual("path2", path)
        self.assertEqual("location2", location)

    def test_reference_info_caches_cleared(self):
        branch = self.make_branch("branch")
        with branch.lock_write():
            branch.set_reference_info(b"file-id", "location2", "path2")
        doppelganger = _mod_branch.Branch.open("branch")
        doppelganger.set_reference_info(b"file-id", "location3", "path3")
        self.assertEqual(("location3", "path3"), branch.get_reference_info(b"file-id"))

    def _recordParentMapCalls(self, repo):
        self._parent_map_calls = []
        orig_get_parent_map = repo.revisions.get_parent_map

        def get_parent_map(q):
            q = list(q)
            self._parent_map_calls.extend([e[0] for e in q])
            return orig_get_parent_map(q)

        repo.revisions.get_parent_map = get_parent_map


class TestBranchReference(tests.TestCaseWithTransport):
    """Tests for the branch reference facility."""

    def test_create_open_reference(self):
        bzrdirformat = bzrdir.BzrDirMetaFormat1()
        t = self.get_transport()
        t.mkdir("repo")
        dir = bzrdirformat.initialize(self.get_url("repo"))
        dir.create_repository()
        target_branch = dir.create_branch()
        t.mkdir("branch")
        branch_dir = bzrdirformat.initialize(self.get_url("branch"))
        made_branch = _mod_bzrbranch.BranchReferenceFormat().initialize(
            branch_dir, target_branch=target_branch
        )
        self.assertEqual(made_branch.base, target_branch.base)
        opened_branch = branch_dir.open_branch()
        self.assertEqual(opened_branch.base, target_branch.base)

    def test_get_reference(self):
        """For a BranchReference, get_reference should return the location."""
        branch = self.make_branch("target")
        checkout = branch.create_checkout("checkout", lightweight=True)
        reference_url = branch.controldir.root_transport.abspath("") + "/"
        # if the api for create_checkout changes to return different checkout types
        # then this file read will fail.
        self.assertFileEqual(
            reference_url.encode("utf-8"), "checkout/.bzr/branch/location"
        )
        self.assertEqual(
            reference_url,
            _mod_bzrbranch.BranchReferenceFormat().get_reference(checkout.controldir),
        )


class TestHooks(tests.TestCaseWithTransport):
    def test_constructor(self):
        """Check that creating a BranchHooks instance has the right defaults."""
        hooks = _mod_branch.BranchHooks()
        self.assertIn("post_push", hooks, f"post_push not in {hooks}")
        self.assertIn("post_commit", hooks, f"post_commit not in {hooks}")
        self.assertIn("pre_commit", hooks, f"pre_commit not in {hooks}")
        self.assertIn("post_pull", hooks, f"post_pull not in {hooks}")
        self.assertIn("post_uncommit", hooks, f"post_uncommit not in {hooks}")
        self.assertIn(
            "post_change_branch_tip", hooks, f"post_change_branch_tip not in {hooks}"
        )
        self.assertIn("post_branch_init", hooks, f"post_branch_init not in {hooks}")
        self.assertIn("post_switch", hooks, f"post_switch not in {hooks}")

    def test_installed_hooks_are_BranchHooks(self):
        """The installed hooks object should be a BranchHooks."""
        # the installed hooks are saved in self._preserved_hooks.
        self.assertIsInstance(
            self._preserved_hooks[_mod_branch.Branch][1], _mod_branch.BranchHooks
        )

    def test_post_branch_init_hook(self):
        calls = []
        _mod_branch.Branch.hooks.install_named_hook(
            "post_branch_init", calls.append, None
        )
        self.assertLength(0, calls)
        self.make_branch("a")
        self.assertLength(1, calls)
        params = calls[0]
        self.assertIsInstance(params, _mod_branch.BranchInitHookParams)
        self.assertTrue(hasattr(params, "controldir"))
        self.assertTrue(hasattr(params, "branch"))

    def test_post_branch_init_hook_repr(self):
        param_reprs = []
        _mod_branch.Branch.hooks.install_named_hook(
            "post_branch_init", lambda params: param_reprs.append(repr(params)), None
        )
        self.make_branch("a")
        self.assertLength(1, param_reprs)
        param_repr = param_reprs[0]
        self.assertStartsWith(param_repr, "<BranchInitHookParams of ")

    def test_post_switch_hook(self):
        from .. import switch

        calls = []
        _mod_branch.Branch.hooks.install_named_hook("post_switch", calls.append, None)
        tree = self.make_branch_and_tree("branch-1")
        self.build_tree(["branch-1/file-1"])
        tree.add("file-1")
        tree.commit("rev1")
        to_branch = tree.controldir.sprout("branch-2").open_branch()
        self.build_tree(["branch-1/file-2"])
        tree.add("file-2")
        tree.remove("file-1")
        tree.commit("rev2")
        checkout = tree.branch.create_checkout("checkout")
        self.assertLength(0, calls)
        switch.switch(checkout.controldir, to_branch)
        self.assertLength(1, calls)
        params = calls[0]
        self.assertIsInstance(params, _mod_branch.SwitchHookParams)
        self.assertTrue(hasattr(params, "to_branch"))
        self.assertTrue(hasattr(params, "revision_id"))


class TestBranchOptions(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.branch = self.make_branch(".")
        self.config_stack = self.branch.get_config_stack()

    def check_append_revisions_only(self, expected_value, value=None):
        """Set append_revisions_only in config and check its interpretation."""
        if value is not None:
            self.config_stack.set("append_revisions_only", value)
        self.assertEqual(expected_value, self.branch.get_append_revisions_only())

    def test_valid_append_revisions_only(self):
        self.assertEqual(None, self.config_stack.get("append_revisions_only"))
        self.check_append_revisions_only(None)
        self.check_append_revisions_only(False, "False")
        self.check_append_revisions_only(True, "True")
        # The following values will cause compatibility problems on projects
        # using older bzr versions (<2.2) but are accepted
        self.check_append_revisions_only(False, "false")
        self.check_append_revisions_only(True, "true")

    def test_invalid_append_revisions_only(self):
        """Ensure warning is noted on invalid settings."""
        self.warnings = []

        def warning(*args):
            self.warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)
        self.check_append_revisions_only(None, "not-a-bool")
        self.assertLength(1, self.warnings)
        self.assertEqual(
            'Value "not-a-bool" is not valid for "append_revisions_only"',
            self.warnings[0],
        )

    def test_use_fresh_values(self):
        copy = _mod_branch.Branch.open(self.branch.base)
        copy.lock_write()
        try:
            copy.get_config_stack().set("foo", "bar")
        finally:
            copy.unlock()
        self.assertFalse(self.branch.is_locked())
        # Since the branch is locked, the option value won't be saved on disk
        # so trying to access the config of locked branch via another older
        # non-locked branch object pointing to the same branch is not supported
        self.assertEqual(None, self.branch.get_config_stack().get("foo"))
        # Using a newly created branch object works as expected
        fresh = _mod_branch.Branch.open(self.branch.base)
        self.assertEqual("bar", fresh.get_config_stack().get("foo"))

    def test_set_from_config_get_from_config_stack(self):
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        self.branch.get_config().set_user_option("foo", "bar")
        result = self.branch.get_config_stack().get("foo")
        # https://bugs.launchpad.net/bzr/+bug/948344
        self.expectFailure(
            "BranchStack uses cache after set_user_option",
            self.assertEqual,
            "bar",
            result,
        )

    def test_set_from_config_stack_get_from_config(self):
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        self.branch.get_config_stack().set("foo", "bar")
        # Since the branch is locked, the option value won't be saved on disk
        # so mixing get() and get_user_option() is broken by design.
        self.assertEqual(None, self.branch.get_config().get_user_option("foo"))

    def test_set_delays_write_when_branch_is_locked(self):
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        self.branch.get_config_stack().set("foo", "bar")
        copy = _mod_branch.Branch.open(self.branch.base)
        result = copy.get_config_stack().get("foo")
        # Accessing from a different branch object is like accessing from a
        # different process: the option has not been saved yet and the new
        # value cannot be seen.
        self.assertIs(None, result)


class TestPullResult(tests.TestCase):
    def test_report_changed(self):
        r = _mod_branch.PullResult()
        r.old_revid = b"old-revid"
        r.old_revno = 10
        r.new_revid = b"new-revid"
        r.new_revno = 20
        f = StringIO()
        r.report(f)
        self.assertEqual("Now on revision 20.\n", f.getvalue())

    def test_report_unchanged(self):
        r = _mod_branch.PullResult()
        r.old_revid = b"same-revid"
        r.new_revid = b"same-revid"
        f = StringIO()
        r.report(f)
        self.assertEqual("No revisions or tags to pull.\n", f.getvalue())
