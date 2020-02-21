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

from . import (
    errors,
    registry,
    )
from .lazy_import import lazy_import
lazy_import(globals(), """
from breezy import urlutils
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


_bugs_help = """\
When making a commit, metadata about bugs fixed by that change can be
recorded by using the ``--fixes`` option. For each bug marked as fixed, an
entry is included in the 'bugs' revision property stating '<url> <status>'.
(The only ``status`` value currently supported is ``fixed.``)

The ``--fixes`` option allows you to specify a bug tracker and a bug identifier
rather than a full URL. This looks like::

    bzr commit --fixes <tracker>:<id>

or::

    bzr commit --fixes <id>

where "<tracker>" is an identifier for the bug tracker, and "<id>" is the
identifier for that bug within the bugtracker, usually the bug number.
If "<tracker>" is not specified the ``bugtracker`` set in the branch
or global configuration is used.

Bazaar knows about a few bug trackers that have many users. If
you use one of these bug trackers then there is no setup required to
use this feature, you just need to know the tracker identifier to use.
These are the bugtrackers that are built in:

  ============================ ============ ============
  URL                          Abbreviation Example
  ============================ ============ ============
  https://bugs.launchpad.net/  lp           lp:12345
  http://bugs.debian.org/      deb          deb:12345
  http://bugzilla.gnome.org/   gnome        gnome:12345
  ============================ ============ ============

For the bug trackers not listed above configuration is required.
Support for generating the URLs for any project using Bugzilla or Trac
is built in, along with a template mechanism for other bugtrackers with
simple URL schemes. If your bug tracker can't be described by one
of the schemes described below then you can write a plugin to support
it.

If you use Bugzilla or Trac, then you only need to set a configuration
variable which contains the base URL of the bug tracker. These options
can go into ``breezy.conf``, ``branch.conf`` or into a branch-specific
configuration section in ``locations.conf``.  You can set up these values
for each of the projects you work on.

Note: As you provide a short name for each tracker, you can specify one or
more bugs in one or more trackers at commit time if you wish.

Launchpad
---------

Use ``bzr commit --fixes lp:2`` to record that this commit fixes bug 2.

bugzilla_<tracker>_url
----------------------

If present, the location of the Bugzilla bug tracker referred to by
<tracker>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    bugzilla_squid_url = http://bugs.squid-cache.org

would allow ``bzr commit --fixes squid:1234`` to mark Squid's bug 1234 as
fixed.

trac_<tracker>_url
------------------

If present, the location of the Trac instance referred to by
<tracker>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    trac_twisted_url = http://www.twistedmatrix.com/trac

would allow ``bzr commit --fixes twisted:1234`` to mark Twisted's bug 1234 as
fixed.

bugtracker_<tracker>_url
------------------------

If present, the location of a generic bug tracker instance referred to by
<tracker>. The location must contain an ``{id}`` placeholder,
which will be replaced by a specific bug ID. This option can then be used
together with ``bzr commit --fixes`` to mark bugs in that tracker as being
fixed by that commit. For example::

    bugtracker_python_url = http://bugs.python.org/issue{id}

would allow ``bzr commit --fixes python:1234`` to mark bug 1234 in Python's
Roundup bug tracker as fixed, or::

    bugtracker_cpan_url = http://rt.cpan.org/Public/Bug/Display.html?id={id}

would allow ``bzr commit --fixes cpan:1234`` to mark bug 1234 in CPAN's
RT bug tracker as fixed, or::

    bugtracker_hudson_url = http://issues.hudson-ci.org/browse/{id}

would allow ``bzr commit --fixes hudson:HUDSON-1234`` to mark bug HUDSON-1234
in Hudson's JIRA bug tracker as fixed.
"""


class MalformedBugIdentifier(errors.BzrError):

    _fmt = ('Did not understand bug identifier %(bug_id)s: %(reason)s. '
            'See "brz help bugs" for more information on this feature.')

    def __init__(self, bug_id, reason):
        self.bug_id = bug_id
        self.reason = reason


class InvalidBugTrackerURL(errors.BzrError):

    _fmt = ("The URL for bug tracker \"%(abbreviation)s\" doesn't "
            "contain {id}: %(url)s")

    def __init__(self, abbreviation, url):
        self.abbreviation = abbreviation
        self.url = url


class UnknownBugTrackerAbbreviation(errors.BzrError):

    _fmt = ("Cannot find registered bug tracker called %(abbreviation)s "
            "on %(branch)s")

    def __init__(self, abbreviation, branch):
        self.abbreviation = abbreviation
        self.branch = branch


class InvalidLineInBugsProperty(errors.BzrError):

    _fmt = ("Invalid line in bugs property: '%(line)s'")

    def __init__(self, line):
        self.line = line


class InvalidBugUrl(errors.BzrError):

    _fmt = "Invalid bug URL: %(url)s"

    def __init__(self, url):
        self.url = url


class InvalidBugStatus(errors.BzrError):

    _fmt = ("Invalid bug status: '%(status)s'")

    def __init__(self, status):
        self.status = status


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
        raise UnknownBugTrackerAbbreviation(
            abbreviated_bugtracker_name, branch)

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
            raise MalformedBugIdentifier(bug_id, "Must be an integer")


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
        """Returns the tracker if the abbreviation matches, otherwise ``None``.
        """
        if abbreviated_bugtracker_name != self.abbreviation:
            return None
        return self

    def _get_bug_url(self, bug_id):
        """Return the URL for bug_id."""
        return self.base_url + str(bug_id)


class ProjectIntegerBugTracker(IntegerBugTracker):
    """A bug tracker that exists in one place only with per-project ids.

    If you have one of these trackers then register an instance passing in an
    abbreviated name for the bug tracker and a base URL. The bug ids are
    appended directly to the URL.
    """

    def __init__(self, abbreviated_bugtracker_name, base_url):
        self.abbreviation = abbreviated_bugtracker_name
        self._base_url = base_url

    def get(self, abbreviated_bugtracker_name, branch):
        """Returns the tracker if the abbreviation matches, otherwise ``None``.
        """
        if abbreviated_bugtracker_name != self.abbreviation:
            return None
        return self

    def check_bug_id(self, bug_id):
        try:
            (project, bug_id) = bug_id.rsplit('/', 1)
        except ValueError:
            raise MalformedBugIdentifier(bug_id, "Expected format: project/id")
        try:
            int(bug_id)
        except ValueError:
            raise MalformedBugIdentifier(bug_id, "Bug id must be an integer")

    def _get_bug_url(self, bug_id):
        (project, bug_id) = bug_id.rsplit('/', 1)
        """Return the URL for bug_id."""
        if '{id}' not in self._base_url:
            raise InvalidBugTrackerURL(self._abbreviation, self._base_url)
        if '{project}' not in self._base_url:
            raise InvalidBugTrackerURL(self._abbreviation, self._base_url)
        return self._base_url.replace(
            '{project}', project).replace('{id}', str(bug_id))


tracker_registry.register(
    'launchpad', UniqueIntegerBugTracker('lp', 'https://launchpad.net/bugs/'))


tracker_registry.register(
    'debian', UniqueIntegerBugTracker('deb', 'http://bugs.debian.org/'))


tracker_registry.register(
    'gnome', UniqueIntegerBugTracker(
        'gnome', 'http://bugzilla.gnome.org/show_bug.cgi?id='))


tracker_registry.register(
    'github', ProjectIntegerBugTracker(
        'github', 'https://github.com/{project}/issues/{id}'))


class URLParametrizedBugTracker(BugTracker):
    """A type of bug tracker that can be found on a variety of different sites,
    and thus needs to have the base URL configured.

    Looks for a config setting in the form '<type_name>_<abbreviation>_url'.
    `type_name` is the name of the type of tracker and `abbreviation`
    is a short name for the particular instance.
    """

    def get(self, abbreviation, branch):
        config = branch.get_config()
        url = config.get_user_option(
            "%s_%s_url" % (self.type_name, abbreviation), expand=False)
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


class URLParametrizedIntegerBugTracker(IntegerBugTracker,
                                       URLParametrizedBugTracker):
    """A type of bug tracker that  only allows integer bug IDs.

    This can be found on a variety of different sites, and thus needs to have
    the base URL configured.

    Looks for a config setting in the form '<type_name>_<abbreviation>_url'.
    `type_name` is the name of the type of tracker (e.g. 'bugzilla' or 'trac')
    and `abbreviation` is a short name for the particular instance (e.g.
    'squid' or 'apache').
    """


tracker_registry.register(
    'trac', URLParametrizedIntegerBugTracker('trac', 'ticket/'))

tracker_registry.register(
    'bugzilla',
    URLParametrizedIntegerBugTracker('bugzilla', 'show_bug.cgi?id='))


class GenericBugTracker(URLParametrizedBugTracker):
    """Generic bug tracker specified by an URL template."""

    def __init__(self):
        super(GenericBugTracker, self).__init__('bugtracker', None)

    def get(self, abbreviation, branch):
        self._abbreviation = abbreviation
        return super(GenericBugTracker, self).get(abbreviation, branch)

    def _get_bug_url(self, bug_id):
        """Given a validated bug_id, return the bug's web page's URL."""
        if '{id}' not in self._base_url:
            raise InvalidBugTrackerURL(self._abbreviation, self._base_url)
        return self._base_url.replace('{id}', str(bug_id))


tracker_registry.register('generic', GenericBugTracker())


FIXED = 'fixed'
RELATED = 'related'

ALLOWED_BUG_STATUSES = {FIXED, RELATED}


def encode_fixes_bug_urls(bug_urls):
    """Get the revision property value for a commit that fixes bugs.

    :param bug_urls: An iterable of (escaped URL, tag) tuples. These normally
        come from `get_bug_url`.
    :return: A string that will be set as the 'bugs' property of a revision
        as part of a commit.
    """
    lines = []
    for (url, tag) in bug_urls:
        if ' ' in url:
            raise InvalidBugUrl(url)
        lines.append('%s %s' % (url, tag))
    return '\n'.join(lines)


def decode_bug_urls(bug_text):
    """Decode a bug property text.

    :param bug_text: Contents of a bugs property
    :return: iterator over (url, status) tuples
    """
    for line in bug_text.splitlines():
        try:
            url, status = line.split(None, 2)
        except ValueError:
            raise InvalidLineInBugsProperty(line)
        if status not in ALLOWED_BUG_STATUSES:
            raise InvalidBugStatus(status)
        yield url, status
