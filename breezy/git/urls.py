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


from .. import urlutils
from .refs import (
    ref_to_branch_name,
    )

from dulwich.client import parse_rsync_url


KNOWN_GIT_SCHEMES = ['git+ssh', 'git', 'http', 'https', 'ftp', 'ssh']
SCHEME_REPLACEMENT = {
    'ssh': 'git+ssh',
    }


def git_url_to_bzr_url(location, branch=None, ref=None):
    if branch is not None and ref is not None:
        raise ValueError('only specify one of branch or ref')
    url = urlutils.URL.from_string(location)
    if (url.scheme not in KNOWN_GIT_SCHEMES and
            not url.scheme.startswith('chroot-')):
        try:
            (username, host, path) = parse_rsync_url(location)
        except ValueError:
            return location
        else:
            url = urlutils.URL(
                scheme='git+ssh',
                quoted_user=(urlutils.quote(username) if username else None),
                quoted_password=None,
                quoted_host=urlutils.quote(host),
                port=None,
                quoted_path=urlutils.quote(path, safe="/~"))
        location = str(url)
    elif url.scheme in SCHEME_REPLACEMENT:
        url.scheme = SCHEME_REPLACEMENT[url.scheme]
        location = str(url)
    if ref == b'HEAD':
        ref = branch = None
    if ref:
        try:
            branch = ref_to_branch_name(ref)
        except ValueError:
            branch = None
        else:
            ref = None
    if ref or branch:
        params = {}
        if ref:
            params['ref'] = urlutils.quote_from_bytes(ref, safe='')
        if branch:
            params['branch'] = urlutils.escape(branch, safe='')
        location = urlutils.join_segment_parameters(location, params)
    return location


def bzr_url_to_git_url(location):
    target_url, target_params = urlutils.split_segment_parameters(location)
    branch = target_params.get('branch')
    ref = target_params.get('ref')
    return target_url, branch, ref
