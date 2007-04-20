# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from bzrlib import bugtracker
from bzrlib.errors import MalformedBugIdentifier
from bzrlib.tests import TestCaseWithMemoryTransport


class TestGetBugURL(TestCaseWithMemoryTransport):
    """Tests for bugtracker.get_bug_url"""

    def test_get_launchpad_url(self):
        """No matter the branch, lp:1234 should map to a Launchpad URL."""
        branch = self.make_branch('some_branch')
        self.assertEqual(
            'https://launchpad.net/bugs/1234',
            bugtracker.get_bug_url('lp', branch, '1234'))

    def test_get_trac_url(self):
        trac_url = 'http://twistedmatrix.com/trac'
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('trac_twisted_url', trac_url)
        self.assertEqual('%s/ticket/1234' % trac_url,
                         bugtracker.get_bug_url('twisted', branch, '1234'))

    def test_unrecognized_abbreviation(self):
        """If the abbreviation is unrecognized, then raise a KeyError."""
        branch = self.make_branch('some_branch')
        self.assertRaises(KeyError,
                          bugtracker.get_bug_url, 'xxx', branch, '1234')


class TestUniqueBugTracker(TestCaseWithMemoryTransport):

    def test_check_bug_id_passes(self):
        """check_bug_id should always pass for the base UniqueBugTracker."""
        tracker = bugtracker.UniqueBugTracker('xxx', 'http://bugs.com')
        self.assertEqual(None, tracker.check_bug_id('12'))
        self.assertEqual(None, tracker.check_bug_id('orange'))

    def test_joins_id_to_base_url(self):
        """The URL of a bug is the base URL joined to the identifier."""
        tracker = bugtracker.UniqueBugTracker('xxx', 'http://bugs.com')
        self.assertEqual('http://bugs.com/1234', tracker.get_bug_url('1234'))
        self.assertEqual('http://bugs.com/red', tracker.get_bug_url('red'))

    def test_returns_tracker_if_abbreviation_matches(self):
        """The get() classmethod should return an instance of the tracker if
        the given abbreviation matches the tracker's abbreviated name.
        """
        tracker = bugtracker.UniqueBugTracker('xxx', 'http://bugs.com')
        branch = self.make_branch('some_branch')
        self.assertIs(tracker, tracker.get('xxx', branch))

    def test_returns_none_if_abbreviation_doesnt_match(self):
        """The get() classmethod should return None if the given abbreviated
        name doesn't match the tracker's abbreviation.
        """
        tracker = bugtracker.UniqueBugTracker('xxx', 'http://bugs.com')
        branch = self.make_branch('some_branch')
        self.assertEqual(None, tracker.get('yyy', branch))


class TestUniqueIntegerBugTracker(TestCaseWithMemoryTransport):

    def test_check_bug_id_only_accepts_integers(self):
        """An UniqueIntegerBugTracker only accepts integers as bug IDs."""
        tracker = bugtracker.UniqueIntegerBugTracker('xxx', 'http://bugs.com')
        self.assertEqual(None, tracker.check_bug_id('1234'))
        self.assertRaises(MalformedBugIdentifier, tracker.check_bug_id, 'red')


class TestTracTracker(TestCaseWithMemoryTransport):
    """Tests for TracTracker."""

    def setUp(self):
        TestCaseWithMemoryTransport.setUp(self)
        self.trac_url = 'http://twistedmatrix.com/trac'

    def test_get_bug_url(self):
        """A TracTracker should map a Trac bug to a URL for that instance."""
        tracker = bugtracker.TracTracker(self.trac_url)
        self.assertEqual(
            '%s/ticket/1234' % self.trac_url, tracker.get_bug_url('1234'))

    def test_get_with_unsupported_tag(self):
        """If asked for an unrecognized or unconfigured tag, return None."""
        branch = self.make_branch('some_branch')
        self.assertEqual(None, bugtracker.TracTracker.get('lp', branch))
        self.assertEqual(None, bugtracker.TracTracker.get('twisted', branch))

    def test_get_with_supported_tag(self):
        """If asked for a valid tag, return a matching TracTracker instance."""
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('trac_twisted_url', self.trac_url)
        tracker = bugtracker.TracTracker.get('twisted', branch)
        self.assertEqual(
            bugtracker.TracTracker(self.trac_url).get_bug_url('1234'),
            tracker.get_bug_url('1234'))

    def test_get_bug_url_for_bad_bag(self):
        """When given a bug identifier that is invalid for Launchpad,
        get_bug_url should raise an error.
        """
        tracker = bugtracker.TracTracker(self.trac_url)
        self.assertRaises(MalformedBugIdentifier, tracker.get_bug_url, 'bad')
