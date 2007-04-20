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


from bzrlib import registry
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import errors, urlutils
""")


"""Provides a shorthand for referring to bugs on a variety of bug trackers.

'commit --fixes' stores references to bugs as a <bug_url> -> <bug_status>
mapping in the properties for that revision.

However, it's inconvenient to type out full URLs for bugs on the command line,
particularly given that many users will be using only a single bug tracker per
branch.

Thus, this module provides a registry of types of bug tracker (e.g. Launchpad,
Trac). Given an abbreviated name (e.g. 'lp', 'twisted') and a branch with
configuration information, these tracker types can return an instance capable
of converting bug IDs into URLs.
"""


def get_bug_url(abbreviated_bugtracker_name, branch, bug_id):
    """Return a URL pointing to the canonical web page of the bug identified by
    'bug_id'.
    """
    tracker = tracker_registry.get_tracker(abbreviated_bugtracker_name, branch)
    return tracker.get_bug_url(bug_id)


class TrackerRegistry(registry.Registry):
    """Registry of bug tracker types."""

    def get_tracker(self, abbreviated_bugtracker_name, branch):
        """Return the first registered tracker that understands
        'abbreviated_bugtracker_name'.

        If no such tracker is found, raise KeyError.
        """
        for tracker_name in self.keys():
            tracker_type = self.get(tracker_name)
            tracker = tracker_type.get(abbreviated_bugtracker_name, branch)
            if tracker is not None:
                return tracker
        raise errors.UnknownBugTrackerAbbreviation(abbreviated_bugtracker_name)


tracker_registry = TrackerRegistry()
"""Registry of bug trackers."""


class UniqueBugTracker(object):
    """A style of bug tracker that exists in one place only, such as Launchpad.

    If you have one of these trackers then subclass this and add attributes
    named 'abbreviation' and 'base_url'. The former is the abbreviation that
    the user will use on the command line. The latter is the url that the bug
    ids will be appended to.

    If the bug_id must have a special form then override check_bug_id and
    raise an exception if the bug_id is not valid.
    """

    def __init__(self, abbreviated_bugtracker_name, base_url):
        self.abbreviation = abbreviated_bugtracker_name
        self.base_url = base_url

    def get(self, abbreviated_bugtracker_name, branch):
        """Returns the tracker if the abbreviation matches. Returns None
        otherwise."""
        if abbreviated_bugtracker_name != self.abbreviation:
            return None
        return self

    def get_bug_url(self, bug_id):
        """Return the URL for bug_id."""
        self.check_bug_id(bug_id)
        return urlutils.join(self.base_url, bug_id)

    def check_bug_id(self, bug_id):
        """Check that the bug_id is valid.

        The base implementation assumes that all bug_ids are valid.
        """


class UniqueIntegerBugTracker(UniqueBugTracker):
    """A SimpleBugtracker where the bug ids must be integers"""

    def check_bug_id(self, bug_id):
        try:
            int(bug_id)
        except ValueError:
            raise errors.MalformedBugIdentifier(bug_id, "Must be an integer")


tracker_registry.register(
    'launchpad', UniqueIntegerBugTracker('lp', 'https://launchpad.net/bugs/'))


tracker_registry.register(
    'debian', UniqueIntegerBugTracker('lp', 'https://launchpad.net/bugs/'))


class TracTracker(object):
    """A Trac instance."""

    @classmethod
    def get(klass, abbreviated_bugtracker_name, branch):
        """Return a TracTracker for the given abbreviation.

        Looks in the configuration of 'branch' for a 'trac_<abbreviation>_url'
        setting, which should refer to the base URL of a project's Trac
        instance. e.g.
            trac_twisted_url = http://twistedmatrix.com
        """
        config = branch.get_config()
        url = config.get_user_option(
            'trac_%s_url' % (abbreviated_bugtracker_name,))
        if url is None:
            return None
        return klass(url)

    def __init__(self, url):
        self._url = url

    def get_bug_url(self, bug_id):
        """Return a URL for a bug on this Trac instance."""
        try:
            int(bug_id)
        except ValueError:
            raise errors.MalformedBugIdentifier(bug_id, "Must be an integer")
        return urlutils.join(self._url, 'ticket', bug_id)

tracker_registry.register('trac', TracTracker)
