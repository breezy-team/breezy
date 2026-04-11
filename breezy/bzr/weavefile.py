# Copyright (C) 2005-2010 Canonical Ltd
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
#
# Author: Martin Pool <mbp@canonical.com>

"""Store and retrieve weaves in files.

There is one format marker followed by a blank line, followed by a
series of version headers, followed by the weave itself.

Each version marker has

 'i'   parent version indexes
 '1'   SHA-1 of text
 'n'   name

The inclusions do not need to list versions included by a parent.

The weave is bracketed by 'w' and 'W' lines, and includes the '{}[]'
processing instructions.  Lines of text are prefixed by '.' if the
line contains a newline, or ',' if not.
"""

from bzrformats.weavefile import (  # noqa: F401
    _read_weave_v5,
    write_weave,
    write_weave_v5,
)


def read_weave(f):
    """Read a weave from a file.

    Args:
        f: File-like object to read from.

    Returns:
        A Weave object containing the data read from the file.
    """
    # FIXME: detect the weave type and dispatch
    from .weave import Weave

    w = Weave(getattr(f, "name", None))
    _read_weave_v5(f, w)
    return w
