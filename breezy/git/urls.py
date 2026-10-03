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

from dulwich.client import parse_rsync_url

from .. import urlutils
from .refs import ref_to_branch_name

KNOWN_GIT_SCHEMES = ["git+ssh", "git", "http", "https", "ftp", "ssh"]
SCHEME_REPLACEMENT = {
    "ssh": "git+ssh",
}


def git_url_to_bzr_url(location, branch=None, ref=None):
    if branch is not None and ref is not None:
        raise ValueError("only specify one of branch or ref")
    url = urlutils.URL.from_string(location)
    if url.scheme not in KNOWN_GIT_SCHEMES and not url.scheme.startswith("chroot-"):
        try:
            (username, host, path) = parse_rsync_url(location)
        except ValueError:
            return location
        else:
            url = urlutils.URL(
                scheme="git+ssh",
                quoted_user=(urlutils.quote(username) if username else None),
                quoted_password=None,
                quoted_host=urlutils.quote(host),
                port=None,
                quoted_path=urlutils.quote(path, safe="/~"),
            )
        location = str(url)
    elif url.scheme in SCHEME_REPLACEMENT:
        url.scheme = SCHEME_REPLACEMENT[url.scheme]
        location = str(url)
    if ref == b"HEAD":
        ref = branch = None
    if ref:
        try:
            branch = ref_to_branch_name(ref)
        except ValueError:
            branch = None
        else:
            ref = None
    if ref:
        location = join_ref_segment_parameter(location, ref)
    elif branch:
        location = urlutils.join_segment_parameters(location, {"branch": branch})
    return location


def join_ref_segment_parameter(url, ref):
    """Set the ref segment parameter of a URL.

    Args:
      url: A URL, as string
      ref: Ref, as bytes; it does not have to be valid UTF-8
    """
    base, subsegments = urlutils.split_segment_parameters_raw(url)
    subsegments = [s for s in subsegments if not s.startswith("ref=")]
    subsegments.append("ref=" + urlutils.quote_from_bytes(ref, safe=""))
    subsegments.sort(key=lambda s: s.partition("=")[0])
    return urlutils.join_segment_parameters_raw(base, *subsegments)


def ref_from_segment_parameters(url):
    """Return the ref segment parameter of a URL.

    Args:
      url: A URL, as string
    Returns: Ref as bytes, or None if the URL has no ref segment parameter
    """
    _base, subsegments = urlutils.split_segment_parameters_raw(url)
    for subsegment in subsegments:
        if subsegment.startswith("ref="):
            return urlutils.unquote_to_bytes(subsegment[len("ref=") :])
    return None


def bzr_url_to_git_url(location):
    target_url, target_params = urlutils.split_segment_parameters(location)
    branch = target_params.get("branch")
    ref = ref_from_segment_parameters(location)
    return target_url, branch, ref
