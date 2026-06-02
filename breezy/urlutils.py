# Copyright (C) 2026 Breezy developers
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

"""Compatibility shim for urlutils module.

The canonical implementation lives in :mod:`dromedary.urlutils`; this
module re-exports its public surface so existing ``breezy.urlutils``
callers (and type checkers) keep working.

The re-exports are enumerated rather than star-imported so ``mypy``
can see them — ``from X import *`` doesn't propagate attribute
visibility through the type checker.
"""

from dromedary.urlutils import (
    MIN_ABS_FILEURL_LENGTH,
    URL,
    WIN32_MIN_ABS_FILEURL_LENGTH,
    InvalidRebaseURLs,
    InvalidURL,
    InvalidURLJoin,
    basename,
    combine_paths,
    derive_to_location,
    determine_relative_path,
    dirname,
    escape,
    file_relpath,
    is_url,
    join,
    join_segment_parameters,
    join_segment_parameters_raw,
    joinpath,
    local_path_from_url,
    local_path_to_url,
    normalize_url,
    parse_url,
    pathjoin,
    quote,
    quote_from_bytes,
    rebase_url,
    relative_url,
    split,
    split_segment_parameters,
    split_segment_parameters_raw,
    splitpath,
    strip_segment_parameters,
    strip_trailing_slash,
    unescape,
    unescape_for_display,
    unquote,
    unquote_to_bytes,
    urlparse,
)

__all__ = [
    "MIN_ABS_FILEURL_LENGTH",
    "URL",
    "WIN32_MIN_ABS_FILEURL_LENGTH",
    "InvalidRebaseURLs",
    "InvalidURL",
    "InvalidURLJoin",
    "basename",
    "combine_paths",
    "derive_to_location",
    "determine_relative_path",
    "dirname",
    "escape",
    "file_relpath",
    "is_url",
    "join",
    "join_segment_parameters",
    "join_segment_parameters_raw",
    "joinpath",
    "local_path_from_url",
    "local_path_to_url",
    "normalize_url",
    "parse_url",
    "pathjoin",
    "quote",
    "quote_from_bytes",
    "rebase_url",
    "relative_url",
    "split",
    "split_segment_parameters",
    "split_segment_parameters_raw",
    "splitpath",
    "strip_segment_parameters",
    "strip_trailing_slash",
    "unescape",
    "unescape_for_display",
    "unquote",
    "unquote_to_bytes",
    "urlparse",
]
