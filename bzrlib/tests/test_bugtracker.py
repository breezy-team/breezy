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


from bzrlib import bugtracker, errors, urlutils
from bzrlib.tests import TestCase, TestCaseWithMemoryTransport


class TestGetBugURL(TestCaseWithMemoryTransport):
    """Tests for bugtracker.get_bug_url"""

    class TransientTracker(object):
        """An transient tracker used for testing."""

        @classmethod
        def get(klass, abbreviation, branch):
            klass.log.append(('get', abbreviation, branch))
            if abbreviation != 'transient':
                return None
            return klass()

        def get_bug_url(self, bug_id):
            self.log.append(('get_bug_url', bug_id))
            return "http://bugs.com/%s" % bug_id

    def setUp(self):
        super(TestGetBugURL, self).setUp()
        self.tracker_type = TestGetBugURL.TransientTracker
        self.tracker_type.log = []
        bugtracker.tracker_registry.register('transient', self.tracker_type)
        self.addCleanup(bugtracker.tracker_registry.remove, 'transient')

    def test_get_bug_url_for_transient_tracker(self):
        branch = self.make_branch('some_branch')
        self.assertEqual('http://bugs.com/1234',
                         bugtracker.get_bug_url('transient', branch, '1234'))
        self.assertEqual(
            [('get', 'transient', branch), ('get_bug_url', '1234')],
            self.tracker_type.log)

    def test_unrecognized_abbreviation_raises_error(self):
        """If the abbreviation is unrecognized, then raise an error."""
        branch = self.make_branch('some_branch')
        self.assertRaises(errors.UnknownBugTrackerAbbreviation,
                          bugtracker.get_bug_url, 'xxx', branch, '1234')
        self.assertEqual([('get', 'xxx', branch)], self.tracker_type.log)


class TestBuiltinTrackers(TestCaseWithMemoryTransport):
    """Test that the builtin trackers are registered and return sane URLs."""

    def test_launchpad_registered(self):
        """The Launchpad bug tracker should be registered by default and
        generate Launchpad bug page URLs.
        """
        branch = self.make_branch('some_branch')
        tracker = bugtracker.tracker_registry.get_tracker('lp', branch)
        self.assertEqual('https://launchpad.net/bugs/1234',
                         tracker.get_bug_url('1234'))

    def test_debian_registered(self):
        """The Debian bug tracker should be registered by default and generate
        bugs.debian.org bug page URLs.
        """
        branch = self.make_branch('some_branch')
        tracker = bugtracker.tracker_registry.get_tracker('deb', branch)
        self.assertEqual('http://bugs.debian.org/1234',
                         tracker.get_bug_url('1234'))

    def test_gnome_registered(self):
        branch = self.make_branch('some_branch')
        tracker = bugtracker.tracker_registry.get_tracker('gnome', branch)
        self.assertEqual('http://bugzilla.gnome.org/show_bug.cgi?id=1234',
                         tracker.get_bug_url('1234'))

    def test_trac_registered(self):
        """The Trac bug tracker should be registered by default and generate
        Trac bug page URLs when the appropriate configuration is present.
        """
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('trac_foo_url', 'http://bugs.com/trac')
        tracker = bugtracker.tracker_registry.get_tracker('foo', branch)
        self.assertEqual('http://bugs.com/trac/ticket/1234',
                         tracker.get_bug_url('1234'))

    def test_bugzilla_registered(self):
        """The Bugzilla bug tracker should be registered by default and
        generate Bugzilla bug page URLs when the appropriate configuration is
        present.
        """
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('bugzilla_foo_url', 'http://bugs.com')
        tracker = bugtracker.tracker_registry.get_tracker('foo', branch)
        self.assertEqual('http://bugs.com/show_bug.cgi?id=1234',
                         tracker.get_bug_url('1234'))

    def test_generic_registered(self):
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('bugtracker_foo_url', 'http://bugs.com/{id}/view.html')
        tracker = bugtracker.tracker_registry.get_tracker('foo', branch)
        self.assertEqual('http://bugs.com/1234/view.html',
                         tracker.get_bug_url('1234'))

    def test_generic_registered_non_integer(self):
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('bugtracker_foo_url', 'http://bugs.com/{id}/view.html')
        tracker = bugtracker.tracker_registry.get_tracker('foo', branch)
        self.assertEqual('http://bugs.com/ABC-1234/view.html',
                         tracker.get_bug_url('ABC-1234'))

    def test_generic_incorrect_url(self):
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('bugtracker_foo_url', 'http://bugs.com/view.html')
        tracker = bugtracker.tracker_registry.get_tracker('foo', branch)
        self.assertRaises(errors.InvalidBugTrackerURL, tracker.get_bug_url, '1234')


class TestUniqueIntegerBugTracker(TestCaseWithMemoryTransport):

    def test_appends_id_to_base_url(self):
        """The URL of a bug is the base URL joined to the identifier."""
        tracker = bugtracker.UniqueIntegerBugTracker('xxx',
                'http://bugs.com/foo')
        self.assertEqual('http://bugs.com/foo1234', tracker.get_bug_url('1234'))

    def test_returns_tracker_if_abbreviation_matches(self):
        """The get() method should return an instance of the tracker if the
        given abbreviation matches the tracker's abbreviated name.
        """
        tracker = bugtracker.UniqueIntegerBugTracker('xxx',
                'http://bugs.com/')
        branch = self.make_branch('some_branch')
        self.assertIs(tracker, tracker.get('xxx', branch))

    def test_returns_none_if_abbreviation_doesnt_match(self):
        """The get() method should return None if the given abbreviated name
        doesn't match the tracker's abbreviation.
        """
        tracker = bugtracker.UniqueIntegerBugTracker('xxx',
                'http://bugs.com/')
        branch = self.make_branch('some_branch')
        self.assertIs(None, tracker.get('yyy', branch))

    def test_doesnt_consult_branch(self):
        """A UniqueIntegerBugTracker shouldn't consult the branch for tracker
        information.
        """
        tracker = bugtracker.UniqueIntegerBugTracker('xxx',
                'http://bugs.com/')
        self.assertIs(tracker, tracker.get('xxx', None))
        self.assertIs(None, tracker.get('yyy', None))

    def test_check_bug_id_only_accepts_integers(self):
        """A UniqueIntegerBugTracker accepts integers as bug IDs."""
        tracker = bugtracker.UniqueIntegerBugTracker('xxx',
                'http://bugs.com/')
        tracker.check_bug_id('1234')

    def test_check_bug_id_doesnt_accept_non_integers(self):
        """A UniqueIntegerBugTracker rejects non-integers as bug IDs."""
        tracker = bugtracker.UniqueIntegerBugTracker('xxx',
                'http://bugs.com/')
        self.assertRaises(
            errors.MalformedBugIdentifier, tracker.check_bug_id, 'red')

class TestURLParametrizedBugTracker(TestCaseWithMemoryTransport):
    """Tests for URLParametrizedBugTracker."""

    def setUp(self):
        super(TestURLParametrizedBugTracker, self).setUp()
        self.url = 'http://twistedmatrix.com/trac'
        self.tracker = bugtracker.URLParametrizedBugTracker('some', 'ticket/')

    def test_get_with_unsupported_tag(self):
        """If asked for an unrecognized or unconfigured tag, return None."""
        branch = self.make_branch('some_branch')
        self.assertEqual(None, self.tracker.get('lp', branch))
        self.assertEqual(None, self.tracker.get('twisted', branch))

    def test_get_with_supported_tag(self):
        """If asked for a valid tag, return a tracker instance that can map bug
        IDs to <base_url>/<bug_area> + <bug_id>."""
        bugtracker.tracker_registry.register('some', self.tracker)
        self.addCleanup(bugtracker.tracker_registry.remove, 'some')

        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('some_twisted_url', self.url)
        tracker = self.tracker.get('twisted', branch)
        self.assertEqual(
            urlutils.join(self.url, 'ticket/') + '1234',
            tracker.get_bug_url('1234'))

    def test_get_bug_url_for_integer_id(self):
        self.tracker.check_bug_id('1234')

    def test_get_bug_url_for_non_integer_id(self):
        self.tracker.check_bug_id('ABC-1234')


class TestURLParametrizedIntegerBugTracker(TestCaseWithMemoryTransport):
    """Tests for URLParametrizedIntegerBugTracker."""

    def setUp(self):
        super(TestURLParametrizedIntegerBugTracker, self).setUp()
        self.url = 'http://twistedmatrix.com/trac'
        self.tracker = bugtracker.URLParametrizedIntegerBugTracker('some',
                                                                   'ticket/')

    def test_get_bug_url_for_bad_bug(self):
        """When given a bug identifier that is invalid for Trac, get_bug_url
        should raise an error.
        """
        self.assertRaises(
            errors.MalformedBugIdentifier, self.tracker.get_bug_url, 'bad')


class TestPropertyEncoding(TestCase):
    """Tests for how the bug URLs are encoded as revision properties."""

    def test_encoding_one(self):
        self.assertEqual(
            'http://example.com/bugs/1 fixed',
            bugtracker.encode_fixes_bug_urls(['http://example.com/bugs/1']))

    def test_encoding_zero(self):
        self.assertEqual('', bugtracker.encode_fixes_bug_urls([]))

    def test_encoding_two(self):
        self.assertEqual(
            'http://example.com/bugs/1 fixed\n'
            'http://example.com/bugs/2 fixed',
            bugtracker.encode_fixes_bug_urls(
                ['http://example.com/bugs/1', 'http://example.com/bugs/2']))
