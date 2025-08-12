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

"""Bug tracker integration and shorthand bug identifier support.

Provides a shorthand for referring to bugs on a variety of bug trackers.

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


class MalformedBugIdentifier(errors.BzrError):
    """Exception raised when a bug identifier cannot be parsed."""

    _fmt = (
        "Did not understand bug identifier %(bug_id)s: %(reason)s. "
        'See "brz help bugs" for more information on this feature.'
    )

    def __init__(self, bug_id, reason):
        """Initialize the exception.

        Args:
            bug_id: The malformed bug identifier.
            reason: Description of why the identifier is malformed.
        """
        self.bug_id = bug_id
        self.reason = reason


class InvalidBugTrackerURL(errors.BzrError):
    """Exception raised when a bug tracker URL template is invalid."""

    _fmt = 'The URL for bug tracker "%(abbreviation)s" doesn\'t contain {id}: %(url)s'

    def __init__(self, abbreviation, url):
        """Initialize the exception.

        Args:
            abbreviation: The bug tracker abbreviation.
            url: The invalid URL template.
        """
        self.abbreviation = abbreviation
        self.url = url


class UnknownBugTrackerAbbreviation(errors.BzrError):
    """Exception raised when a bug tracker abbreviation is not recognized."""

    _fmt = "Cannot find registered bug tracker called %(abbreviation)s on %(branch)s"

    def __init__(self, abbreviation, branch):
        """Initialize the exception.

        Args:
            abbreviation: The unrecognized bug tracker abbreviation.
            branch: The branch where the lookup was attempted.
        """
        self.abbreviation = abbreviation
        self.branch = branch


class InvalidLineInBugsProperty(errors.BzrError):
    """Exception raised when a line in the bugs property is malformed."""

    _fmt = "Invalid line in bugs property: '%(line)s'"

    def __init__(self, line):
        """Initialize the exception.

        Args:
            line: The invalid line from the bugs property.
        """
        self.line = line


class InvalidBugUrl(errors.BzrError):
    """Exception raised when a bug URL is malformed."""

    _fmt = "Invalid bug URL: %(url)s"

    def __init__(self, url):
        """Initialize the exception.

        Args:
            url: The invalid bug URL.
        """
        self.url = url


class InvalidBugStatus(errors.BzrError):
    """Exception raised when a bug status is not recognized."""

    _fmt = "Invalid bug status: '%(status)s'"

    def __init__(self, status):
        """Initialize the exception.

        Args:
            status: The invalid bug status.
        """
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
        raise UnknownBugTrackerAbbreviation(abbreviated_bugtracker_name, branch)

    def help_topic(self, topic):
        """Return help text for bug tracker topics.

        Args:
            topic: The help topic requested.

        Returns:
            Help text for the topic.
        """
        return _bugs_help


tracker_registry = TrackerRegistry()
"""Registry of bug trackers."""


class BugTracker:
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
        """Check that the bug_id is a valid integer.

        Args:
            bug_id: Bug identifier to validate.

        Raises:
            MalformedBugIdentifier: If the bug_id is not an integer.
        """
        try:
            int(bug_id)
        except ValueError as exc:
            raise MalformedBugIdentifier(bug_id, "Must be an integer") from exc


class UniqueIntegerBugTracker(IntegerBugTracker):
    """A style of bug tracker that exists in one place only, such as Launchpad.

    If you have one of these trackers then register an instance passing in an
    abbreviated name for the bug tracker and a base URL. The bug ids are
    appended directly to the URL.
    """

    def __init__(self, abbreviated_bugtracker_name, base_url):
        """Initialize the unique integer bug tracker.

        Args:
            abbreviated_bugtracker_name: Short name for this tracker.
            base_url: Base URL where bug IDs are appended.
        """
        self.abbreviation = abbreviated_bugtracker_name
        self.base_url = base_url

    def get(self, abbreviated_bugtracker_name, branch):
        """Returns the tracker if the abbreviation matches, otherwise ``None``."""
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
        """Initialize the project integer bug tracker.

        Args:
            abbreviated_bugtracker_name: Short name for this tracker.
            base_url: Base URL template with {project} and {id} placeholders.
        """
        self.abbreviation = abbreviated_bugtracker_name
        self._base_url = base_url

    def get(self, abbreviated_bugtracker_name, branch):
        """Returns the tracker if the abbreviation matches, otherwise ``None``."""
        if abbreviated_bugtracker_name != self.abbreviation:
            return None
        return self

    def check_bug_id(self, bug_id):
        """Check that the bug_id has valid project/id format.

        Args:
            bug_id: Bug identifier in project/id format.

        Raises:
            MalformedBugIdentifier: If the bug_id format is invalid.
        """
        try:
            (project, bug_id) = bug_id.rsplit("/", 1)
        except ValueError as exc:
            raise MalformedBugIdentifier(bug_id, "Expected format: project/id") from exc
        try:
            int(bug_id)
        except ValueError as exc:
            raise MalformedBugIdentifier(bug_id, "Bug id must be an integer") from exc

    def _get_bug_url(self, bug_id):
        (project, bug_id) = bug_id.rsplit("/", 1)
        """Return the URL for bug_id."""
        if "{id}" not in self._base_url:
            raise InvalidBugTrackerURL(self.abbreviation, self._base_url)
        if "{project}" not in self._base_url:
            raise InvalidBugTrackerURL(self.abbreviation, self._base_url)
        return self._base_url.replace("{project}", project).replace("{id}", str(bug_id))


tracker_registry.register(
    "launchpad", UniqueIntegerBugTracker("lp", "https://launchpad.net/bugs/")
)


tracker_registry.register(
    "debian", UniqueIntegerBugTracker("deb", "http://bugs.debian.org/")
)


tracker_registry.register(
    "gnome",
    UniqueIntegerBugTracker("gnome", "http://bugzilla.gnome.org/show_bug.cgi?id="),
)


tracker_registry.register(
    "github",
    ProjectIntegerBugTracker("github", "https://github.com/{project}/issues/{id}"),
)


class URLParametrizedBugTracker(BugTracker):
    """A type of bug tracker that can be found on a variety of different sites,
    and thus needs to have the base URL configured.

    Looks for a config setting in the form '<type_name>_<abbreviation>_url'.
    `type_name` is the name of the type of tracker and `abbreviation`
    is a short name for the particular instance.
    """

    def get(self, abbreviation, branch):
        """Get a bug tracker instance for the given abbreviation.

        Args:
            abbreviation: Bug tracker abbreviation to look up.
            branch: Branch to get configuration from.

        Returns:
            Bug tracker instance if found, None otherwise.
        """
        config = branch.get_config()
        url = config.get_user_option(
            f"{self.type_name}_{abbreviation}_url", expand=False
        )
        if url is None:
            return None
        self._base_url = url
        return self

    def __init__(self, type_name, bug_area):
        """Initialize the URL parametrized bug tracker.

        Args:
            type_name: Type name for configuration lookup.
            bug_area: Path component to append for bug URLs.
        """
        self.type_name = type_name
        self._bug_area = bug_area

    def _get_bug_url(self, bug_id):
        """Return a URL for a bug on this Trac instance."""
        return urlutils.join(self._base_url, self._bug_area) + str(bug_id)


class URLParametrizedIntegerBugTracker(IntegerBugTracker, URLParametrizedBugTracker):
    """A type of bug tracker that  only allows integer bug IDs.

    This can be found on a variety of different sites, and thus needs to have
    the base URL configured.

    Looks for a config setting in the form '<type_name>_<abbreviation>_url'.
    `type_name` is the name of the type of tracker (e.g. 'bugzilla' or 'trac')
    and `abbreviation` is a short name for the particular instance (e.g.
    'squid' or 'apache').
    """


tracker_registry.register("trac", URLParametrizedIntegerBugTracker("trac", "ticket/"))

tracker_registry.register(
    "bugzilla", URLParametrizedIntegerBugTracker("bugzilla", "show_bug.cgi?id=")
)


class GenericBugTracker(URLParametrizedBugTracker):
    """Generic bug tracker specified by an URL template."""

    def __init__(self):
        """Initialize the generic bug tracker."""
        super().__init__("bugtracker", None)

    def get(self, abbreviation, branch):
        """Get a generic bug tracker instance for the given abbreviation.

        Args:
            abbreviation: Bug tracker abbreviation to look up.
            branch: Branch to get configuration from.

        Returns:
            Bug tracker instance if configured, None otherwise.
        """
        self._abbreviation = abbreviation
        return super().get(abbreviation, branch)

    def _get_bug_url(self, bug_id):
        """Given a validated bug_id, return the bug's web page's URL."""
        if "{id}" not in self._base_url:
            raise InvalidBugTrackerURL(self._abbreviation, self._base_url)
        return self._base_url.replace("{id}", str(bug_id))


tracker_registry.register("generic", GenericBugTracker())


FIXED = "fixed"
RELATED = "related"

ALLOWED_BUG_STATUSES = {FIXED, RELATED}


def encode_fixes_bug_urls(bug_urls):
    """Get the revision property value for a commit that fixes bugs.

    :param bug_urls: An iterable of (escaped URL, tag) tuples. These normally
        come from `get_bug_url`.
    :return: A string that will be set as the 'bugs' property of a revision
        as part of a commit.
    """
    lines = []
    for url, tag in bug_urls:
        if " " in url:
            raise InvalidBugUrl(url)
        lines.append(f"{url} {tag}")
    return "\n".join(lines)


def decode_bug_urls(bug_lines):
    """Decode a bug property text.

    :param bug_lines: Contents of a bugs property
    :return: iterator over (url, status) tuples
    """
    for line in bug_lines:
        try:
            url, status = line.split(None, 2)
        except ValueError as exc:
            raise InvalidLineInBugsProperty(line) from exc
        if status not in ALLOWED_BUG_STATUSES:
            raise InvalidBugStatus(status)
        yield url, status
