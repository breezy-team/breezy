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
    _fmt = "No repository URL set for pypi project %(name)s"

    def __init__(self, name, url=None):
        BzrError.__init__(self, name=name, url=url)


class NoSuchPypiProject(InvalidURL):
    _fmt = "No pypi project with name %(name)s"

    def __init__(self, name, url=None):
        BzrError.__init__(self, name=name, url=url)


def find_repo_url(data):
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
    def look_up(self, name, url, purpose=None):
        """See DirectoryService.look_up."""
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
