# Copyright (C) 2007-2011 Canonical Ltd
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

"""Directory lookup that uses Launchpad."""

from urllib.parse import urlsplit

from ... import debug, errors, trace, transport
from ...urlutils import InvalidURL, join, split
from .account import get_lp_login
from .uris import LPNET_SERVICE_ROOT

# As breezy.transport.remote may not be loaded yet, make sure bzr+ssh
# is counted as a netloc protocol.
transport.register_urlparse_netloc_protocol("bzr+ssh")
transport.register_urlparse_netloc_protocol("lp")
transport.register_urlparse_netloc_protocol("lp+bzr")


def _requires_launchpad_login(scheme, netloc, path, query, fragment):
    """Does the URL require a Launchpad login in order to be reached?

    The URL is specified by its parsed components, as returned from
    urlsplit.
    """
    return scheme in ("bzr+ssh", "sftp", "git+ssh") and (
        netloc.endswith("launchpad.net") or netloc.endswith("launchpad.test")
    )


def _expand_user(path, url, lp_login):
    if path.startswith("~/"):
        if lp_login is None:
            raise InvalidURL(
                path=url,
                extra='Cannot resolve "~" to your username.'
                ' See "bzr help launchpad-login"',
            )
        path = "~" + lp_login + path[1:]
    return path


def _update_url_scheme(url):
    scheme, netloc, path, query, fragment = urlsplit(url)
    if scheme == "lp+bzr":
        scheme = "lp"
    return url, path


def _resolve_via_api(path, url, api_base_url=LPNET_SERVICE_ROOT):
    from .lp_api import connect_launchpad

    lp = connect_launchpad(api_base_url, version="devel")
    subpaths = []
    lp_branch = None
    git_repo = None
    while path:
        lp_branch = lp.branches.getByPath(path=path)
        git_repo = lp.git_repositories.getByPath(path=path)
        if lp_branch and git_repo:
            target = git_repo.target
            vcs = target.vcs
            trace.warning(
                "Found both a Bazaar branch and a git repository at lp:%s. Using "
                "%s, since that is the projects' default vcs",
                path,
                vcs,
            )
            if vcs == "Git":
                lp_branch = None
            elif vcs == "Bazaar":
                git_repo = None
            else:
                raise errors.BzrError("Unknown default vcs {} for {}".format(vcs, target))
        if lp_branch or git_repo:
            break
        path, subpath = split(path)
        subpaths.insert(0, subpath)
    if lp_branch:
        return {
            "urls": [
                join(lp_branch.composePublicURL(scheme="bzr+ssh"), *subpaths),
                join(lp_branch.composePublicURL(scheme="http"), *subpaths),
            ]
        }
    elif git_repo:
        return {
            "urls": [
                join(git_repo.git_ssh_url, *subpaths),
                join(git_repo.git_https_url, *subpaths),
            ]
        }
    else:
        raise InvalidURL(f"Unknown Launchpad path: {url}")


def _resolve(url, _lp_login=None):
    """Resolve the base URL for this transport."""
    url, path = _update_url_scheme(url)
    if _lp_login is None:
        _lp_login = get_lp_login()
    path = path.strip("/")
    path = _expand_user(path, url, _lp_login)
    result = _resolve_via_api(path, url)

    if "launchpad" in debug.debug_flags:
        trace.mutter("resolve_lp_path(%r) == %r", url, result)

    _warned_login = False
    for url in result["urls"]:
        scheme, netloc, path, query, fragment = urlsplit(url)
        if _requires_launchpad_login(scheme, netloc, path, query, fragment):
            # Only accept launchpad.net bzr+ssh URLs if we know
            # the user's Launchpad login:
            if _lp_login is not None:
                break
            if _lp_login is None:
                if not _warned_login:
                    trace.warning(
                        "You have not informed bzr of your Launchpad ID, and you must do this to\n"
                        'write to Launchpad or access private data.  See "bzr help launchpad-login".'
                    )
                    _warned_login = True
        else:
            break
    else:
        raise InvalidURL(path=url, extra="no supported schemes")
    return url


class LaunchpadDirectory:
    def look_up(self, name, url, purpose=None):
        """See DirectoryService.look_up."""
        return _resolve(url)


def get_test_permutations():
    # Since this transport doesn't do anything once opened, it's not subjected
    # to the usual transport tests.
    return []
