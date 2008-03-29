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


_bugs_help = \
"""When making a commit, metadata about bugs fixed by that change can be
recorded by using the --fixes option. For each bug marked as fixed, an
entry is included in the 'bugs' revision property stating '<url> <status>'.
(The only ``status`` value currently supported is ``fixed.``)
Support for Launchpad's central bug tracker is built in. For other bug
trackers, configuration is required in advance so that the correct URL
can be recorded.

In addition to Launchpad, Bazaar directly supports the generation of
URLs appropriate for Bugzilla and Trac. If your project uses a different
bug tracker, it is easy to add support for it.
If you use Bugzilla or Trac, then you only need to set a configuration
variable which contains the base URL of the bug tracker. These options
can go into ``bazaar.conf``, ``branch.conf`` or into a branch-specific
configuration section in ``locations.conf``.  You can set up these values
for each of the projects you work on.

Note: As you provide a short name for each tracker, you can specify one or
more bugs in one or more trackers at commit time if you wish.

bugzilla_<tracker_abbreviation>_url
-----------------------------------

If present, the location of the Bugzilla bug tracker referred to by
<tracker_abbreviation>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    bugzilla_squid_url = http://www.squid-cache.org/bugs

would allow ``bzr commit --fixes squid:1234`` to mark Squid's bug 1234 as
fixed.

trac_<tracker_abbrevation>_url
------------------------------

If present, the location of the Trac instance referred to by
<tracker_abbreviation>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    trac_twisted_url = http://www.twistedmatrix.com/trac

would allow ``bzr commit --fixes twisted:1234`` to mark Twisted's bug 1234 as
fixed.

bugtracker_<tracker_abbrevation>_url
------------------------------------

If present, the location of a generic bug tracker instance referred to by
<tracker_abbreviation>. The location must contain an ``{id}`` placeholder,
which will be replaced by a specific bug ID. This option can then be used
together with ``bzr commit --fixes`` to mark bugs in that tracker as being
fixed by that commit. For example::

    bugtracker_python_url = http://bugs.python.org/issue{id}

would allow ``bzr commit --fixes python:1234`` to mark bug 1234 in Python's
Roundup bug tracker as fixed, or::

    bugtracker_cpan_url = http://rt.cpan.org/Public/Bug/Display.html?id={id}

for CPAN's RT bug tracker.
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
        return _bugs_help


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

    If you have one of these trackers then register an instance passing in an
    abbreviated name for the bug tracker and a base URL. The bug ids are
    appended directly to the URL.
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
        return self.base_url + bug_id


tracker_registry.register(
    'launchpad', UniqueIntegerBugTracker('lp', 'https://launchpad.net/bugs/'))


tracker_registry.register(
    'debian', UniqueIntegerBugTracker('deb', 'http://bugs.debian.org/'))


tracker_registry.register('gnome',
    UniqueIntegerBugTracker('gnome', 'http://bugzilla.gnome.org/show_bug.cgi?id='))


class URLParametrizedIntegerBugTracker(IntegerBugTracker):
    """A type of bug tracker that can be found on a variety of different sites,
    and thus needs to have the base URL configured.

    Looks for a config setting in the form '<type_name>_<abbreviation>_url'.
    `type_name` is the name of the type of tracker (e.g. 'bugzilla' or 'trac')
    and `abbreviation` is a short name for the particular instance (e.g.
    'squid' or 'apache').
    """

    def get(self, abbreviation, branch):
        config = branch.get_config()
        url = config.get_user_option(
            "%s_%s_url" % (self.type_name, abbreviation))
        if url is None:
            return None
        self._base_url = url
        return self

    def __init__(self, type_name, bug_area):
        self.type_name = type_name
        self._bug_area = bug_area

    def _get_bug_url(self, bug_id):
        """Return a URL for a bug on this Trac instance."""
        return urlutils.join(self._base_url, self._bug_area) + str(bug_id)


tracker_registry.register(
    'trac', URLParametrizedIntegerBugTracker('trac', 'ticket/'))

tracker_registry.register(
    'bugzilla',
    URLParametrizedIntegerBugTracker('bugzilla', 'show_bug.cgi?id='))


class GenericBugTracker(URLParametrizedIntegerBugTracker):
    """Generic bug tracker specified by an URL template."""

    def __init__(self):
        super(GenericBugTracker, self).__init__('bugtracker', None)

    def get(self, abbreviation, branch):
        self._abbreviation = abbreviation
        return super(GenericBugTracker, self).get(abbreviation, branch)

    def _get_bug_url(self, bug_id):
        """Given a validated bug_id, return the bug's web page's URL."""
        if '{id}' not in self._base_url:
            raise errors.InvalidBugTrackerURL(self._abbreviation,
                                              self._base_url)
        return self._base_url.replace('{id}', str(bug_id))


tracker_registry.register('generic', GenericBugTracker())
