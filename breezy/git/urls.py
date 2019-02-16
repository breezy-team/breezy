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

from dulwich.client import parse_rsync_url


KNOWN_GIT_SCHEMES = ['git+ssh', 'git', 'http', 'https', 'ftp']


def git_url_to_bzr_url(location):
    url = URL.from_string(location)
    if (url.scheme not in KNOWN_GIT_SCHEMES
            and not url.scheme.startswith('chroot-')):
        try:
            (username, host, path) = parse_rsync_url(location)
        except ValueError:
            return location
        else:
            url = URL(
                scheme='git+ssh',
                quoted_user=(quote(username) if username else None),
                quoted_password=None,
                quoted_host=quote(host),
                port=None,
                quoted_path=quote(path, safe="/~"))
        return str(url)
    else:
        return location
