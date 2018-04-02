# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""URL Conversion."""

from __future__ import absolute_import

from breezy.urlutils import URL, quote


KNOWN_GIT_SCHEMES = ['git+ssh', 'git', 'http', 'https', 'ftp']


def parse_git_url(location):
    """Parse a rsync-style URL."""
    if ':' in location and '@' not in location:
        # SSH with no user@, zero or one leading slash.
        (host, path) = location.split(':', 1)
        user = None
    elif ':' in location:
        # SSH with user@host:foo.
        user_host, path = location.split(':', 1)
        if '@' in user_host:
            user, host = user_host.rsplit('@', 1)
        else:
            user = None
            host = user_host
    return (user, host, path)


def git_url_to_bzr_url(location):
    (username, host, path) = parse_git_url(location)
    url = URL.from_string(location)
    if url.scheme not in KNOWN_GIT_SCHEMES:
        url = URL(
                scheme='git+ssh',
                quoted_user=(quote(username) if username else None),
                quoted_password=None,
                quoted_host=quote(host),
                port=None,
                quoted_path=quote(path, safe="/~"))
    return str(url)
