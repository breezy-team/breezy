# Copyright (C) 2021 Breezy Developers
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

"""Directory lookup that uses pypi."""

import json
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import urlopen

from ...errors import BzrError
from ...trace import note
from ...urlutils import InvalidURL


class PypiProjectWithoutRepositoryURL(InvalidURL):
    """Exception raised when a PyPI project has no repository URL configured.

    This error occurs when looking up a PyPI project that exists but doesn't
    have a repository URL set in its project metadata.
    """

    _fmt = "No repository URL set for pypi project %(name)s"

    def __init__(self, name, url=None):
        """Initialize the exception.

        Args:
            name: The name of the PyPI project.
            url: Optional URL that was being looked up.
        """
        BzrError.__init__(self, name=name, url=url)


class NoSuchPypiProject(InvalidURL):
    """Exception raised when a PyPI project with the given name doesn't exist.

    This error occurs when attempting to look up a PyPI project that
    is not found in the PyPI registry.
    """

    _fmt = "No pypi project with name %(name)s"

    def __init__(self, name, url=None):
        """Initialize the exception.

        Args:
            name: The name of the PyPI project that was not found.
            url: Optional URL that was being looked up.
        """
        BzrError.__init__(self, name=name, url=url)


def find_repo_url(data):
    """Find the repository URL from PyPI project data.

    Searches through the project URLs to find a repository URL, either by
    looking for an explicit "Repository" key or by identifying GitHub URLs.

    Args:
        data: PyPI project metadata dictionary containing project info.

    Returns:
        str or None: The repository URL if found, None otherwise.
    """
    for key, value in data["info"]["project_urls"].items():
        if key == "Repository":
            note("Found repository URL %s for pypi project %s", value, name)
            return value
        parsed_url = urlparse(value)
        if (
            parsed_url.hostname == "github.com"
            and parsed_url.path.strip("/").count("/") == 1
        ):
            return value


class PypiDirectory:
    """Directory service that looks up repository URLs for PyPI projects.

    This service allows looking up PyPI project names to find their
    corresponding repository URLs by querying the PyPI JSON API.
    """

    def look_up(self, name, url, purpose=None):
        """Look up a PyPI project and return its repository URL.

        Args:
            name: The name of the PyPI project to look up.
            url: The original URL being resolved (for error reporting).
            purpose: Optional purpose of the lookup (unused).

        Returns:
            str: The repository URL for the PyPI project.

        Raises:
            NoSuchPypiProject: If the project doesn't exist on PyPI.
            PypiProjectWithoutRepositoryURL: If the project exists but has
                no repository URL configured.
        """
        try:
            with urlopen(f"https://pypi.org/pypi/{name}/json") as f:
                data = json.load(f)
        except HTTPError as e:
            if e.status == 404:
                raise NoSuchPypiProject(name, url=url) from e
            raise
        url = find_repo_url(data)
        if url is None:
            raise PypiProjectWithoutRepositoryURL(name, url=url)
        return url
