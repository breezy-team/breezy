# Copyright (C) 2009, 2010 Canonical Ltd
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

"""End of Line Conversion filters.

See bzr help eol for details.
"""

import re
import sys

from ..errors import BzrError
from ..filters import ContentFilter

# Real Unix newline - \n without \r before it
_UNIX_NL_RE = re.compile(rb"(?<!\r)\n")


def _to_lf_converter(chunks, context=None):
    """A content file that converts crlf to lf."""
    content = b"".join(chunks)
    if b"\x00" in content:
        return [content]
    else:
        return [content.replace(b"\r\n", b"\n")]


def _to_crlf_converter(chunks, context=None):
    """A content file that converts lf to crlf."""
    content = b"".join(chunks)
    if b"\x00" in content:
        return [content]
    else:
        return [_UNIX_NL_RE.sub(b"\r\n", content)]


if sys.platform == "win32":
    _native_output = _to_crlf_converter
else:
    _native_output = _to_lf_converter
_eol_filter_stack_map = {
    "exact": [],
    "native": [ContentFilter(_to_lf_converter, _native_output)],
    "lf": [ContentFilter(_to_lf_converter, _to_lf_converter)],
    "crlf": [ContentFilter(_to_lf_converter, _to_crlf_converter)],
    "native-with-crlf-in-repo": [ContentFilter(_to_crlf_converter, _native_output)],
    "lf-with-crlf-in-repo": [ContentFilter(_to_crlf_converter, _to_lf_converter)],
    "crlf-with-crlf-in-repo": [ContentFilter(_to_crlf_converter, _to_crlf_converter)],
}


def eol_lookup(key):
    filter = _eol_filter_stack_map.get(key)
    if filter is None:
        raise BzrError("Unknown eol value '{}'".format(key))
    return filter
