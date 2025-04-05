# Copyright (C) 2011, 2012, 2016 Canonical Ltd
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

"""Tests for the branch open with specific URL policy code."""

from .. import urlutils
from ..branch import Branch
from ..bzr import BzrProber
from ..bzr.branch import BranchReferenceFormat
from ..controldir import ControlDir, ControlDirFormat
from ..errors import NotBranchError, RedirectRequested
from ..transport import (
    Transport,
    chroot,
    get_transport,
    register_transport,
    register_transport_proto,
    unregister_transport,
)
from ..url_policy_open import (
    BadUrl,
    BranchLoopError,
    BranchOpener,
    BranchReferenceForbidden,
    WhitelistPolicy,
    _BlacklistPolicy,
    open_only_scheme,
)
from . import TestCase, TestCaseWithTransport


class TestBranchOpenerCheckAndFollowBranchReference(TestCase):
    """Unit tests for `BranchOpener.check_and_follow_branch_reference`."""

    def setUp(self):
        super().setUp()
        BranchOpener.install_hook()

    class StubbedBranchOpener(BranchOpener):
        """BranchOpener that provides canned answers.

        We implement the methods we need to to be able to control all the
        inputs to the `follow_reference` method, which is what is
        being tested in this class.
        """

        def __init__(self, references, policy):
            parent_cls = TestBranchOpenerCheckAndFollowBranchReference
            super(parent_cls.StubbedBranchOpener, self).__init__(policy)
            self._reference_values = {}
            for i in range(len(references) - 1):
                self._reference_values[references[i]] = references[i + 1]
            self.follow_reference_calls = []

        def follow_reference(self, url):
            self.follow_reference_calls.append(url)
            return self._reference_values[url]

    def make_branch_opener(
        self, should_follow_references, references, unsafe_urls=None
    ):
        policy = _BlacklistPolicy(should_follow_references, unsafe_urls)
        opener = self.StubbedBranchOpener(references, policy)
        return opener

    def test_check_initial_url(self):
        # check_and_follow_branch_reference rejects all URLs that are not
        # allowed.
        opener = self.make_branch_opener(None, [], {"a"})
        self.assertRaises(BadUrl, opener.check_and_follow_branch_reference, "a")

    def test_not_reference(self):
        # When branch references are forbidden,
        # check_and_follow_branch_reference does not raise on non-references.
        opener = self.make_branch_opener(False, ["a", None])
        self.assertEqual("a", opener.check_and_follow_branch_reference("a"))
        self.assertEqual(["a"], opener.follow_reference_calls)

    def test_branch_reference_forbidden(self):
        # check_and_follow_branch_reference raises BranchReferenceForbidden if
        # branch references are forbidden and the source URL points to a
        # branch reference.
        opener = self.make_branch_opener(False, ["a", "b"])
        self.assertRaises(
            BranchReferenceForbidden, opener.check_and_follow_branch_reference, "a"
        )
        self.assertEqual(["a"], opener.follow_reference_calls)

    def test_allowed_reference(self):
        # check_and_follow_branch_reference does not raise if following
        # references is allowed and the source URL points to a branch reference
        # to a permitted location.
        opener = self.make_branch_opener(True, ["a", "b", None])
        self.assertEqual("b", opener.check_and_follow_branch_reference("a"))
        self.assertEqual(["a", "b"], opener.follow_reference_calls)

    def test_check_referenced_urls(self):
        # check_and_follow_branch_reference checks if the URL a reference
        # points to is safe.
        opener = self.make_branch_opener(True, ["a", "b", None], unsafe_urls=set("b"))
        self.assertRaises(BadUrl, opener.check_and_follow_branch_reference, "a")
        self.assertEqual(["a"], opener.follow_reference_calls)

    def test_self_referencing_branch(self):
        # check_and_follow_branch_reference raises BranchReferenceLoopError if
        # following references is allowed and the source url points to a
        # self-referencing branch reference.
        opener = self.make_branch_opener(True, ["a", "a"])
        self.assertRaises(
            BranchLoopError, opener.check_and_follow_branch_reference, "a"
        )
        self.assertEqual(["a"], opener.follow_reference_calls)

    def test_branch_reference_loop(self):
        # check_and_follow_branch_reference raises BranchReferenceLoopError if
        # following references is allowed and the source url points to a loop
        # of branch references.
        references = ["a", "b", "a"]
        opener = self.make_branch_opener(True, references)
        self.assertRaises(
            BranchLoopError, opener.check_and_follow_branch_reference, "a"
        )
        self.assertEqual(["a", "b"], opener.follow_reference_calls)


class TrackingProber(BzrProber):
    """Subclass of BzrProber which tracks URLs it has been asked to open."""

    seen_urls: list[str] = []

    @classmethod
    def probe_transport(klass, transport):
        klass.seen_urls.append(transport.base)
        return BzrProber.probe_transport(transport)


class TestBranchOpenerStacking(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        BranchOpener.install_hook()

    def make_branch_opener(self, allowed_urls, probers=None):
        policy = WhitelistPolicy(True, allowed_urls, True)
        return BranchOpener(policy, probers)

    def test_probers(self):
        # Only the specified probers should be used
        b = self.make_branch("branch")
        opener = self.make_branch_opener([b.base], probers=[])
        self.assertRaises(NotBranchError, opener.open, b.base)
        opener = self.make_branch_opener([b.base], probers=[BzrProber])
        self.assertEqual(b.base, opener.open(b.base).base)

    def test_default_probers(self):
        # If no probers are specified to the constructor
        # of BranchOpener, then a safe set will be used,
        # rather than all probers registered in bzr.
        self.addCleanup(ControlDirFormat.unregister_prober, TrackingProber)
        ControlDirFormat.register_prober(TrackingProber)
        # Open a location without any branches, so that all probers are
        # tried.
        # First, check that the TrackingProber tracks correctly.
        TrackingProber.seen_urls = []
        opener = self.make_branch_opener(["."], probers=[TrackingProber])
        self.assertRaises(NotBranchError, opener.open, ".")
        self.assertEqual(1, len(TrackingProber.seen_urls))
        TrackingProber.seen_urls = []
        # And make sure it's registered in such a way that ControlDir.open
        # would use it.
        self.assertRaises(NotBranchError, ControlDir.open, ".")
        self.assertEqual(1, len(TrackingProber.seen_urls))

    def test_allowed_url(self):
        # the opener does not raise an exception for branches stacked on
        # branches with allowed URLs.
        stacked_on_branch = self.make_branch("base-branch", format="1.6")
        stacked_branch = self.make_branch("stacked-branch", format="1.6")
        stacked_branch.set_stacked_on_url(stacked_on_branch.base)
        opener = self.make_branch_opener([stacked_branch.base, stacked_on_branch.base])
        # This doesn't raise an exception.
        opener.open(stacked_branch.base)

    def test_nstackable_repository(self):
        # treats branches with UnstackableRepositoryFormats as
        # being not stacked.
        branch = self.make_branch("unstacked", format="knit")
        opener = self.make_branch_opener([branch.base])
        # This doesn't raise an exception.
        opener.open(branch.base)

    def test_allowed_relative_url(self):
        # passes on absolute urls to check_one_url, even if the
        # value of stacked_on_location in the config is set to a relative URL.
        stacked_on_branch = self.make_branch("base-branch", format="1.6")
        stacked_branch = self.make_branch("stacked-branch", format="1.6")
        stacked_branch.set_stacked_on_url("../base-branch")
        opener = self.make_branch_opener([stacked_branch.base, stacked_on_branch.base])
        # Note that stacked_on_branch.base is not '../base-branch', it's an
        # absolute URL.
        self.assertNotEqual("../base-branch", stacked_on_branch.base)
        # This doesn't raise an exception.
        opener.open(stacked_branch.base)

    def test_allowed_relative_nested(self):
        # Relative URLs are resolved relative to the stacked branch.
        self.get_transport().mkdir("subdir")
        a = self.make_branch("subdir/a", format="1.6")
        b = self.make_branch("b", format="1.6")
        b.set_stacked_on_url("../subdir/a")
        c = self.make_branch("subdir/c", format="1.6")
        c.set_stacked_on_url("../../b")
        opener = self.make_branch_opener([c.base, b.base, a.base])
        # This doesn't raise an exception.
        opener.open(c.base)

    def test_forbidden_url(self):
        # raises a BadUrl exception if a branch is stacked on a
        # branch with a forbidden URL.
        stacked_on_branch = self.make_branch("base-branch", format="1.6")
        stacked_branch = self.make_branch("stacked-branch", format="1.6")
        stacked_branch.set_stacked_on_url(stacked_on_branch.base)
        opener = self.make_branch_opener([stacked_branch.base])
        self.assertRaises(BadUrl, opener.open, stacked_branch.base)

    def test_forbidden_url_nested(self):
        # raises a BadUrl exception if a branch is stacked on a
        # branch that is in turn stacked on a branch with a forbidden URL.
        a = self.make_branch("a", format="1.6")
        b = self.make_branch("b", format="1.6")
        b.set_stacked_on_url(a.base)
        c = self.make_branch("c", format="1.6")
        c.set_stacked_on_url(b.base)
        opener = self.make_branch_opener([c.base, b.base])
        self.assertRaises(BadUrl, opener.open, c.base)

    def test_self_stacked_branch(self):
        # raises StackingLoopError if a branch is stacked on
        # itself. This avoids infinite recursion errors.
        a = self.make_branch("a", format="1.6")
        # Bazaar 1.17 and up make it harder to create branches like this.
        # It's still worth testing that we don't blow up in the face of them,
        # so we grovel around a bit to create one anyway.
        a.get_config().set_user_option("stacked_on_location", a.base)
        opener = self.make_branch_opener([a.base])
        self.assertRaises(BranchLoopError, opener.open, a.base)

    def test_loop_stacked_branch(self):
        # raises StackingLoopError if a branch is stacked in such
        # a way so that it is ultimately stacked on itself. e.g. a stacked on
        # b stacked on a.
        a = self.make_branch("a", format="1.6")
        b = self.make_branch("b", format="1.6")
        a.set_stacked_on_url(b.base)
        b.set_stacked_on_url(a.base)
        opener = self.make_branch_opener([a.base, b.base])
        self.assertRaises(BranchLoopError, opener.open, a.base)
        self.assertRaises(BranchLoopError, opener.open, b.base)

    def test_custom_opener(self):
        # A custom function for opening a control dir can be specified.
        a = self.make_branch("a", format="2a")
        b = self.make_branch("b", format="2a")
        b.set_stacked_on_url(a.base)

        TrackingProber.seen_urls = []
        opener = self.make_branch_opener([a.base, b.base], probers=[TrackingProber])
        opener.open(b.base)
        self.assertEqual(set(TrackingProber.seen_urls), {b.base, a.base})

    def test_custom_opener_with_branch_reference(self):
        # A custom function for opening a control dir can be specified.
        a = self.make_branch("a", format="2a")
        b_dir = self.make_controldir("b")
        b = BranchReferenceFormat().initialize(b_dir, target_branch=a)
        TrackingProber.seen_urls = []
        opener = self.make_branch_opener([a.base, b.base], probers=[TrackingProber])
        opener.open(b.base)
        self.assertEqual(set(TrackingProber.seen_urls), {b.base, a.base})


class TestRedirects(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        BranchOpener.install_hook()

    def setup_redirect(self, target_url):
        class RedirectingTransport(Transport):
            def get(self, name):
                raise RedirectRequested(self.base, target_url)

            def _redirected_to(self, source, target):
                return get_transport(target)

        register_transport_proto(
            "redirecting://", help="Test transport that redirects."
        )
        register_transport("redirecting://", RedirectingTransport)
        self.addCleanup(unregister_transport, "redirecting://", RedirectingTransport)

    def make_branch_opener(self, allowed_urls, probers=None):
        policy = WhitelistPolicy(True, allowed_urls, True)
        return BranchOpener(policy, probers)

    def test_redirect_forbidden(self):
        b = self.make_branch("b")
        self.setup_redirect(b.base)

        class TrackingProber(BzrProber):
            seen_urls = []

            @classmethod
            def probe_transport(klass, transport):
                klass.seen_urls.append(transport.base)
                return BzrProber.probe_transport(transport)

        opener = self.make_branch_opener(["redirecting:///"], probers=[TrackingProber])
        self.assertRaises(BadUrl, opener.open, "redirecting:///")

        opener = self.make_branch_opener(
            ["redirecting:///", b.base], probers=[TrackingProber]
        )
        opener.open("redirecting:///")


class TestOpenOnlyScheme(TestCaseWithTransport):
    """Tests for `open_only_scheme`."""

    def setUp(self):
        super().setUp()
        BranchOpener.install_hook()

    def test_hook_does_not_interfere(self):
        # The transform_fallback_location hook does not interfere with regular
        # stacked branch access outside of open_only_scheme.
        self.make_branch("stacked")
        self.make_branch("stacked-on")
        Branch.open("stacked").set_stacked_on_url("../stacked-on")
        Branch.open("stacked")

    def get_chrooted_scheme(self, relpath):
        """Create a server that is chrooted to `relpath`.

        :return: ``(scheme, get_url)`` where ``scheme`` is the scheme of the
            chroot server and ``get_url`` returns URLs on said server.
        """
        transport = self.get_transport(relpath)
        chroot_server = chroot.ChrootServer(transport)
        chroot_server.start_server()
        self.addCleanup(chroot_server.stop_server)

        def get_url(relpath):
            return chroot_server.get_url() + relpath

        return (urlutils.URL.from_string(chroot_server.get_url()).scheme, get_url)

    def test_stacked_within_scheme(self):
        # A branch that is stacked on a URL of the same scheme is safe to
        # open.
        self.get_transport().mkdir("inside")
        self.make_branch("inside/stacked")
        self.make_branch("inside/stacked-on")
        scheme, get_chrooted_url = self.get_chrooted_scheme("inside")
        Branch.open(get_chrooted_url("stacked")).set_stacked_on_url(
            get_chrooted_url("stacked-on")
        )
        open_only_scheme(scheme, get_chrooted_url("stacked"))

    def test_stacked_outside_scheme(self):
        # A branch that is stacked on a URL that is not of the same scheme is
        # not safe to open.
        self.get_transport().mkdir("inside")
        self.get_transport().mkdir("outside")
        self.make_branch("inside/stacked")
        self.make_branch("outside/stacked-on")
        scheme, get_chrooted_url = self.get_chrooted_scheme("inside")
        Branch.open(get_chrooted_url("stacked")).set_stacked_on_url(
            self.get_url("outside/stacked-on")
        )
        self.assertRaises(BadUrl, open_only_scheme, scheme, get_chrooted_url("stacked"))
