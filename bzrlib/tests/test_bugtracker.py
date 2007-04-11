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

    def test_unrecognized_tag(self):
        """If the tag is unrecognized, then raise a KeyError."""
        branch = self.make_branch('some_branch')
        self.assertRaises(KeyError,
                          bugtracker.get_bug_url, 'xxx', branch, '1234')



class TestLaunchpadTracker(TestCaseWithMemoryTransport):
    """Tests for LaunchpadTracker."""

    def setUp(self):
        TestCaseWithMemoryTransport.setUp(self)
        self.branch = self.make_branch('some_branch')

    def test_get_with_unsupported_tag(self):
        """If the given tag is unrecognized, return None."""
        self.assertEqual(
            None, bugtracker.LaunchpadTracker.get('twisted', self.branch))

    def test_get_with_supported_tag(self):
        """If given 'lp' as the bug tag, return a LaunchpadTracker instance."""
        tracker = bugtracker.LaunchpadTracker.get('lp', self.branch)
        self.assertEqual(bugtracker.LaunchpadTracker().get_bug_url('1234'),
                         tracker.get_bug_url('1234'))

    def test_get_bug_url(self):
        """A LaunchpadTracker should map a LP bug number to a LP bug URL."""
        tracker = bugtracker.LaunchpadTracker()
        self.assertEqual('https://launchpad.net/bugs/1234',
                         tracker.get_bug_url('1234'))

    def test_get_bug_url_for_bad_bag(self):
        """When given a bug identifier that is invalid for Launchpad,
        get_bug_url should raise an error.
        """
        tracker = bugtracker.LaunchpadTracker()
        self.assertRaises(MalformedBugIdentifier, tracker.get_bug_url, 'bad')


class TestTracTracker(TestCaseWithMemoryTransport):
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
