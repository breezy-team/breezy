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

import textwrap

from bzrlib import registry, help_topics
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
        raise errors.UnknownBugTrackerAbbreviation(abbreviated_bugtracker_name,
                                                   branch)

    def help_topic(self, topic):
        return textwrap.dedent("""\
        Bazaar provides the ability to store information about bugs being fixed
        as metadata on a revision.

        For each bug marked as fixed, an entry is included in the 'bugs'
        revision property stating '<url> <status>'.
        """)


tracker_registry = TrackerRegistry()
"""Registry of bug trackers."""


class BugTracker(object):
    """Base class for bug trackers."""

    def check_bug_id(self, bug_id):
        """Check that the bug_id is valid.

        The base implementation assumes that all bug_ids are valid.
        """

    def get_bug_url(self, bug_id):
        """Return the URL for bug_id. Raise an error if bug ID is malformed."""
        self.check_bug_id(bug_id)
        return self._get_bug_url(bug_id)

    def _get_bug_url(self, bug_id):
        """Given a validated bug_id, return the bug's web page's URL."""


class IntegerBugTracker(BugTracker):
    """A bug tracker that only allows integer bug IDs."""

    def check_bug_id(self, bug_id):
        try:
            int(bug_id)
        except ValueError:
            raise errors.MalformedBugIdentifier(bug_id, "Must be an integer")


class UniqueIntegerBugTracker(IntegerBugTracker):
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

    def _get_bug_url(self, bug_id):
        """Return the URL for bug_id."""
        return urlutils.join(self.base_url, bug_id)


tracker_registry.register(
    'launchpad', UniqueIntegerBugTracker('lp', 'https://launchpad.net/bugs/'))


tracker_registry.register(
    'debian', UniqueIntegerBugTracker('deb', 'http://bugs.debian.org/'))


class URLParametrizedIntegerBugTracker(IntegerBugTracker):
    """A type of bug tracker that can be found on a variety of different sites,
    and thus needs to have the base URL configured.

    Looks for a config setting in the form '<type_name>_<abbreviation>_url'.
    `type_name` is the name of the type of tracker (e.g. 'bugzilla' or 'trac')
    and `abbreviation` is a short name for the particular instance (e.g.
    'squid' or 'apache').
    """

    type_name = None

    @classmethod
    def get(klass, abbreviation, branch):
        config = branch.get_config()
        url = config.get_user_option(
            "%s_%s_url" % (klass.type_name, abbreviation))
        if url is None:
            return None
        return klass(url)

    def __init__(self, url):
        self._base_url = url


class TracTracker(URLParametrizedIntegerBugTracker):
    """A Trac instance."""

    type_name = 'trac'

    def _get_bug_url(self, bug_id):
        """Return a URL for a bug on this Trac instance."""
        return urlutils.join(self._base_url, 'ticket', bug_id)

tracker_registry.register('trac', TracTracker)


class BugzillaTracker(URLParametrizedIntegerBugTracker):
    """A Bugzilla instance."""

    type_name = 'bugzilla'

    def _get_bug_url(self, bug_id):
        """Return a URL for a bug on this Bugzilla instance."""
        return "%s/show_bug.cgi?id=%s" % (self._base_url, bug_id)

tracker_registry.register('bugzilla', BugzillaTracker)
