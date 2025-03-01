# Copyright (C) 2007-2010 Canonical Ltd
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


from .. import bugtracker, urlutils
from . import TestCase, TestCaseWithMemoryTransport


class ErrorsTest(TestCaseWithMemoryTransport):
    def test_unknown_bug_tracker_abbreviation(self):
        """Test the formatting of UnknownBugTrackerAbbreviation."""
        branch = self.make_branch("some_branch")
        error = bugtracker.UnknownBugTrackerAbbreviation("xxx", branch)
        self.assertEqual(
            "Cannot find registered bug tracker called xxx on %s" % branch, str(error)
        )

    def test_malformed_bug_identifier(self):
        """Test the formatting of MalformedBugIdentifier."""
        error = bugtracker.MalformedBugIdentifier("bogus", "reason for bogosity")
        self.assertEqual(
            "Did not understand bug identifier bogus: reason for bogosity. "
            'See "brz help bugs" for more information on this feature.',
            str(error),
        )

    def test_incorrect_url(self):
        err = bugtracker.InvalidBugTrackerURL("foo", "http://bug.example.com/")
        self.assertEqual(
            (
                'The URL for bug tracker "foo" doesn\'t contain {id}: '
                "http://bug.example.com/"
            ),
            str(err),
        )


class TestGetBugURL(TestCaseWithMemoryTransport):
    """Tests for bugtracker.get_bug_url"""

    class TransientTracker:
        """An transient tracker used for testing."""

        @classmethod
        def get(klass, abbreviation, branch):
            klass.log.append(("get", abbreviation, branch))
            if abbreviation != "transient":
                return None
            return klass()

        def get_bug_url(self, bug_id):
            self.log.append(("get_bug_url", bug_id))
            return "http://bugs.example.com/%s" % bug_id

    def setUp(self):
        super().setUp()
        self.tracker_type = TestGetBugURL.TransientTracker
        self.tracker_type.log = []
        bugtracker.tracker_registry.register("transient", self.tracker_type)
        self.addCleanup(bugtracker.tracker_registry.remove, "transient")

    def test_get_bug_url_for_transient_tracker(self):
        branch = self.make_branch("some_branch")
        self.assertEqual(
            "http://bugs.example.com/1234",
            bugtracker.get_bug_url("transient", branch, "1234"),
        )
        self.assertEqual(
            [("get", "transient", branch), ("get_bug_url", "1234")],
            self.tracker_type.log,
        )

    def test_unrecognized_abbreviation_raises_error(self):
        """If the abbreviation is unrecognized, then raise an error."""
        branch = self.make_branch("some_branch")
        self.assertRaises(
            bugtracker.UnknownBugTrackerAbbreviation,
            bugtracker.get_bug_url,
            "xxx",
            branch,
            "1234",
        )
        self.assertEqual([("get", "xxx", branch)], self.tracker_type.log)


class TestBuiltinTrackers(TestCaseWithMemoryTransport):
    """Test that the builtin trackers are registered and return sane URLs."""

    def test_launchpad_registered(self):
        """The Launchpad bug tracker should be registered by default and
        generate Launchpad bug page URLs.
        """
        branch = self.make_branch("some_branch")
        tracker = bugtracker.tracker_registry.get_tracker("lp", branch)
        self.assertEqual("https://launchpad.net/bugs/1234", tracker.get_bug_url("1234"))

    def test_debian_registered(self):
        """The Debian bug tracker should be registered by default and generate
        bugs.debian.org bug page URLs.
        """
        branch = self.make_branch("some_branch")
        tracker = bugtracker.tracker_registry.get_tracker("deb", branch)
        self.assertEqual("http://bugs.debian.org/1234", tracker.get_bug_url("1234"))

    def test_gnome_registered(self):
        branch = self.make_branch("some_branch")
        tracker = bugtracker.tracker_registry.get_tracker("gnome", branch)
        self.assertEqual(
            "http://bugzilla.gnome.org/show_bug.cgi?id=1234",
            tracker.get_bug_url("1234"),
        )

    def test_trac_registered(self):
        """The Trac bug tracker should be registered by default and generate
        Trac bug page URLs when the appropriate configuration is present.
        """
        branch = self.make_branch("some_branch")
        config = branch.get_config()
        config.set_user_option("trac_foo_url", "http://bugs.example.com/trac")
        tracker = bugtracker.tracker_registry.get_tracker("foo", branch)
        self.assertEqual(
            "http://bugs.example.com/trac/ticket/1234", tracker.get_bug_url("1234")
        )

    def test_bugzilla_registered(self):
        """The Bugzilla bug tracker should be registered by default and
        generate Bugzilla bug page URLs when the appropriate configuration is
        present.
        """
        branch = self.make_branch("some_branch")
        config = branch.get_config()
        config.set_user_option("bugzilla_foo_url", "http://bugs.example.com")
        tracker = bugtracker.tracker_registry.get_tracker("foo", branch)
        self.assertEqual(
            "http://bugs.example.com/show_bug.cgi?id=1234", tracker.get_bug_url("1234")
        )

    def test_github(self):
        branch = self.make_branch("some_branch")
        tracker = bugtracker.tracker_registry.get_tracker("github", branch)
        self.assertEqual(
            "https://github.com/breezy-team/breezy/issues/1234",
            tracker.get_bug_url("breezy-team/breezy/1234"),
        )

    def test_generic_registered(self):
        branch = self.make_branch("some_branch")
        config = branch.get_config()
        config.set_user_option(
            "bugtracker_foo_url", "http://bugs.example.com/{id}/view.html"
        )
        tracker = bugtracker.tracker_registry.get_tracker("foo", branch)
        self.assertEqual(
            "http://bugs.example.com/1234/view.html", tracker.get_bug_url("1234")
        )

    def test_generic_registered_non_integer(self):
        branch = self.make_branch("some_branch")
        config = branch.get_config()
        config.set_user_option(
            "bugtracker_foo_url", "http://bugs.example.com/{id}/view.html"
        )
        tracker = bugtracker.tracker_registry.get_tracker("foo", branch)
        self.assertEqual(
            "http://bugs.example.com/ABC-1234/view.html",
            tracker.get_bug_url("ABC-1234"),
        )

    def test_generic_incorrect_url(self):
        branch = self.make_branch("some_branch")
        config = branch.get_config()
        config.set_user_option(
            "bugtracker_foo_url", "http://bugs.example.com/view.html"
        )
        tracker = bugtracker.tracker_registry.get_tracker("foo", branch)
        self.assertRaises(bugtracker.InvalidBugTrackerURL, tracker.get_bug_url, "1234")


class TestUniqueIntegerBugTracker(TestCaseWithMemoryTransport):
    def test_appends_id_to_base_url(self):
        """The URL of a bug is the base URL joined to the identifier."""
        tracker = bugtracker.UniqueIntegerBugTracker(
            "xxx", "http://bugs.example.com/foo"
        )
        self.assertEqual("http://bugs.example.com/foo1234", tracker.get_bug_url("1234"))

    def test_returns_tracker_if_abbreviation_matches(self):
        """The get() method should return an instance of the tracker if the
        given abbreviation matches the tracker's abbreviated name.
        """
        tracker = bugtracker.UniqueIntegerBugTracker("xxx", "http://bugs.example.com/")
        branch = self.make_branch("some_branch")
        self.assertIs(tracker, tracker.get("xxx", branch))

    def test_returns_none_if_abbreviation_doesnt_match(self):
        """The get() method should return None if the given abbreviated name
        doesn't match the tracker's abbreviation.
        """
        tracker = bugtracker.UniqueIntegerBugTracker("xxx", "http://bugs.example.com/")
        branch = self.make_branch("some_branch")
        self.assertIs(None, tracker.get("yyy", branch))

    def test_doesnt_consult_branch(self):
        """A UniqueIntegerBugTracker shouldn't consult the branch for tracker
        information.
        """
        tracker = bugtracker.UniqueIntegerBugTracker("xxx", "http://bugs.example.com/")
        self.assertIs(tracker, tracker.get("xxx", None))
        self.assertIs(None, tracker.get("yyy", None))

    def test_check_bug_id_only_accepts_integers(self):
        """A UniqueIntegerBugTracker accepts integers as bug IDs."""
        tracker = bugtracker.UniqueIntegerBugTracker("xxx", "http://bugs.example.com/")
        tracker.check_bug_id("1234")

    def test_check_bug_id_doesnt_accept_non_integers(self):
        """A UniqueIntegerBugTracker rejects non-integers as bug IDs."""
        tracker = bugtracker.UniqueIntegerBugTracker("xxx", "http://bugs.example.com/")
        self.assertRaises(
            bugtracker.MalformedBugIdentifier, tracker.check_bug_id, "red"
        )


class TestProjectIntegerBugTracker(TestCaseWithMemoryTransport):
    def test_appends_id_to_base_url(self):
        """The URL of a bug is the base URL joined to the identifier."""
        tracker = bugtracker.ProjectIntegerBugTracker(
            "xxx", "http://bugs.example.com/{project}/{id}"
        )
        self.assertEqual(
            "http://bugs.example.com/foo/1234", tracker.get_bug_url("foo/1234")
        )

    def test_returns_tracker_if_abbreviation_matches(self):
        """The get() method should return an instance of the tracker if the
        given abbreviation matches the tracker's abbreviated name.
        """
        tracker = bugtracker.ProjectIntegerBugTracker(
            "xxx", "http://bugs.example.com/{project}/{id}"
        )
        branch = self.make_branch("some_branch")
        self.assertIs(tracker, tracker.get("xxx", branch))

    def test_returns_none_if_abbreviation_doesnt_match(self):
        """The get() method should return None if the given abbreviated name
        doesn't match the tracker's abbreviation.
        """
        tracker = bugtracker.ProjectIntegerBugTracker(
            "xxx", "http://bugs.example.com/{project}/{id}"
        )
        branch = self.make_branch("some_branch")
        self.assertIs(None, tracker.get("yyy", branch))

    def test_doesnt_consult_branch(self):
        """Shouldn't consult the branch for tracker information."""
        tracker = bugtracker.ProjectIntegerBugTracker(
            "xxx", "http://bugs.example.com/{project}/{id}"
        )
        self.assertIs(tracker, tracker.get("xxx", None))
        self.assertIs(None, tracker.get("yyy", None))

    def test_check_bug_id_only_accepts_project_integers(self):
        """Accepts integers as bug IDs."""
        tracker = bugtracker.ProjectIntegerBugTracker(
            "xxx", "http://bugs.example.com/{project}/{id}"
        )
        tracker.check_bug_id("project/1234")

    def test_check_bug_id_doesnt_accept_non_project_integers(self):
        """Rejects non-integers as bug IDs."""
        tracker = bugtracker.ProjectIntegerBugTracker(
            "xxx", "http://bugs.example.com/{project}/{id}"
        )
        self.assertRaises(
            bugtracker.MalformedBugIdentifier, tracker.check_bug_id, "red"
        )
        self.assertRaises(
            bugtracker.MalformedBugIdentifier, tracker.check_bug_id, "1234"
        )


class TestURLParametrizedBugTracker(TestCaseWithMemoryTransport):
    """Tests for URLParametrizedBugTracker."""

    def setUp(self):
        super().setUp()
        self.url = "http://twistedmatrix.com/trac"
        self.tracker = bugtracker.URLParametrizedBugTracker("some", "ticket/")

    def test_get_with_unsupported_tag(self):
        """If asked for an unrecognized or unconfigured tag, return None."""
        branch = self.make_branch("some_branch")
        self.assertEqual(None, self.tracker.get("lp", branch))
        self.assertEqual(None, self.tracker.get("twisted", branch))

    def test_get_with_supported_tag(self):
        """If asked for a valid tag, return a tracker instance that can map bug
        IDs to <base_url>/<bug_area> + <bug_id>.
        """
        bugtracker.tracker_registry.register("some", self.tracker)
        self.addCleanup(bugtracker.tracker_registry.remove, "some")

        branch = self.make_branch("some_branch")
        config = branch.get_config()
        config.set_user_option("some_twisted_url", self.url)
        tracker = self.tracker.get("twisted", branch)
        self.assertEqual(
            urlutils.join(self.url, "ticket/") + "1234", tracker.get_bug_url("1234")
        )

    def test_get_bug_url_for_integer_id(self):
        self.tracker.check_bug_id("1234")

    def test_get_bug_url_for_non_integer_id(self):
        self.tracker.check_bug_id("ABC-1234")


class TestURLParametrizedIntegerBugTracker(TestCaseWithMemoryTransport):
    """Tests for URLParametrizedIntegerBugTracker."""

    def setUp(self):
        super().setUp()
        self.url = "http://twistedmatrix.com/trac"
        self.tracker = bugtracker.URLParametrizedIntegerBugTracker("some", "ticket/")

    def test_get_bug_url_for_bad_bug(self):
        """When given a bug identifier that is invalid for Trac, get_bug_url
        should raise an error.
        """
        self.assertRaises(
            bugtracker.MalformedBugIdentifier, self.tracker.get_bug_url, "bad"
        )


class TestPropertyEncoding(TestCase):
    """Tests for how the bug URLs are encoded as revision properties."""

    def test_encoding_one(self):
        self.assertEqual(
            "http://example.com/bugs/1 fixed",
            bugtracker.encode_fixes_bug_urls([("http://example.com/bugs/1", "fixed")]),
        )

    def test_encoding_zero(self):
        self.assertEqual("", bugtracker.encode_fixes_bug_urls([]))

    def test_encoding_two(self):
        self.assertEqual(
            "http://example.com/bugs/1 fixed\nhttp://example.com/bugs/2 related",
            bugtracker.encode_fixes_bug_urls(
                [
                    ("http://example.com/bugs/1", "fixed"),
                    ("http://example.com/bugs/2", "related"),
                ]
            ),
        )

    def test_encoding_with_space(self):
        self.assertRaises(
            bugtracker.InvalidBugUrl,
            bugtracker.encode_fixes_bug_urls,
            [("http://example.com/bugs/ 1", "fixed")],
        )


class TestPropertyDecoding(TestCase):
    """Tests for parsing bug revision properties."""

    def test_decoding_one(self):
        self.assertEqual(
            [("http://example.com/bugs/1", "fixed")],
            list(bugtracker.decode_bug_urls("http://example.com/bugs/1 fixed")),
        )

    def test_decoding_zero(self):
        self.assertEqual([], list(bugtracker.decode_bug_urls("")))

    def test_decoding_two(self):
        self.assertEqual(
            [
                ("http://example.com/bugs/1", "fixed"),
                ("http://example.com/bugs/2", "related"),
            ],
            list(
                bugtracker.decode_bug_urls(
                    "http://example.com/bugs/1 fixed\nhttp://example.com/bugs/2 related"
                )
            ),
        )

    def test_decoding_invalid(self):
        self.assertRaises(
            bugtracker.InvalidLineInBugsProperty,
            list,
            bugtracker.decode_bug_urls("http://example.com/bugs/ 1 fixed\n"),
        )
