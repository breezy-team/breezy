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
from bzrlib.tests import TestCaseWithMemoryTransport


# XXX - the bare minimum of text to help me think.
"""
Bug fix info is stored in revision properties: {bug_url: status}

But no one wants to type out bug URLs in full.

We want to map from <tag>:<bug_id> to <url>, where <tracker> refers to a
particular instance of a tracker.

For instance, twisted:123 -> http://twistedmatrix.com/trac/ticket/123

Of course, the mapping will be pretty much the same for all instances of any
given tracker software, so what we want to do is this:

- From <tag>, get a tracker type (like 'Trac', 'Bugzilla' or 'Launchpad')
- Give <tag> and <branch> to the tracker type
- The tracker type takes <tag> and <branch> and creates an instance of a
  tracker that knows how to take <bug_id> and turn it into a URL.
"""


class TestLaunchpadTracker(TestCaseWithMemoryTransport):
    def setUp(self):
        TestCaseWithMemoryTransport.setUp(self)
        self.branch = self.make_branch('some_branch')

    def test_get_with_unsupported_tag(self):
        self.assertEqual(
            None, bugtracker.LaunchpadTracker.get('twisted', self.branch))

    def test_get_with_supported_tag(self):
        tracker = bugtracker.LaunchpadTracker.get('lp', self.branch)
        self.assertEqual(bugtracker.LaunchpadTracker().get_bug_url('1234'),
                         tracker.get_bug_url('1234'))

    def test_get_url(self):
        self.assertEqual(
            'https://launchpad.net/bugs/1234',
            bugtracker.get_url('lp', self.branch, '1234'))

    def test_get_bug_url(self):
        tracker = bugtracker.LaunchpadTracker()
        self.assertEqual('https://launchpad.net/bugs/1234',
                         tracker.get_bug_url('1234'))


class TestTracTracker(TestCaseWithMemoryTransport):
    def setUp(self):
        TestCaseWithMemoryTransport.setUp(self)
        self.trac_url = 'http://twistedmatrix.com/trac'

    def test_get_url(self):
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('trac_twisted_url', self.trac_url)
        self.assertEqual('%s/ticket/1234' % self.trac_url,
                         bugtracker.get_url('twisted', branch, '1234'))

    def test_get_bug_url(self):
        tracker = bugtracker.TracTracker(self.trac_url)
        self.assertEqual(
            '%s/ticket/1234' % self.trac_url, tracker.get_bug_url('1234'))

    def test_get_with_unsupported_tag(self):
        branch = self.make_branch('some_branch')
        self.assertEqual(None, bugtracker.TracTracker.get('lp', branch))
        self.assertEqual(None, bugtracker.TracTracker.get('twisted', branch))

    def test_get_with_supported_tag(self):
        branch = self.make_branch('some_branch')
        config = branch.get_config()
        config.set_user_option('trac_twisted_url', self.trac_url)
        tracker = bugtracker.TracTracker.get('twisted', branch)
        self.assertEqual(
            bugtracker.TracTracker(self.trac_url).get_bug_url('1234'),
            tracker.get_bug_url('1234'))
