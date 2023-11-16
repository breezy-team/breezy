# Copyright (C) 2005 Canonical Ltd
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

# \subsection{\emph{rio} - simple text metaformat}
#
# \emph{r} stands for `restricted', `reproducible', or `rfc822-like'.
#
# The stored data consists of a series of \emph{stanzas}, each of which contains
# \emph{fields} identified by an ascii name, with Unicode or string contents.
# The field tag is constrained to alphanumeric characters.
# There may be more than one field in a stanza with the same name.
#
# The format itself does not deal with character encoding issues, though
# the result will normally be written in Unicode.
#
# The format is intended to be simple enough that there is exactly one character
# stream representation of an object and vice versa, and that this relation
# will continue to hold for future versions of bzr.

import re

from . import rio


def to_patch_lines(stanza, max_width=72):
    """Convert a stanza into RIO-Patch format lines.

    RIO-Patch is a RIO variant designed to be e-mailed as part of a patch.
    It resists common forms of damage such as newline conversion or the removal
    of trailing whitespace, yet is also reasonably easy to read.

    :param max_width: The maximum number of characters per physical line.
    :return: a list of lines
    """
    if max_width <= 6:
        raise ValueError(max_width)
    max_rio_width = max_width - 4
    lines = []
    for pline in stanza.to_lines():
        for line in pline.split(b"\n")[:-1]:
            line = re.sub(b"\\\\", b"\\\\\\\\", line)
            while len(line) > 0:
                partline = line[:max_rio_width]
                line = line[max_rio_width:]
                if len(line) > 0 and line[:1] != [b" "]:
                    break_index = -1
                    break_index = partline.rfind(b" ", -20)
                    if break_index < 3:
                        break_index = partline.rfind(b"-", -20)
                        break_index += 1
                    if break_index < 3:
                        break_index = partline.rfind(b"/", -20)
                    if break_index >= 3:
                        line = partline[break_index:] + line
                        partline = partline[:break_index]
                if len(line) > 0:
                    line = b"  " + line
                partline = re.sub(b"\r", b"\\\\r", partline)
                blank_line = False
                if len(line) > 0:
                    partline += b"\\"
                elif re.search(b" $", partline):
                    partline += b"\\"
                    blank_line = True
                lines.append(b"# " + partline + b"\n")
                if blank_line:
                    lines.append(b"#   \n")
    return lines


def _patch_stanza_iter(line_iter):
    map = {b"\\\\": b"\\", b"\\r": b"\r", b"\\\n": b""}

    def mapget(match):
        return map[match.group(0)]

    last_line = None
    for line in line_iter:
        if line.startswith(b"# "):
            line = line[2:]
        elif line.startswith(b"#"):
            line = line[1:]
        else:
            raise ValueError(f"bad line {line!r}")
        if last_line is not None and len(line) > 2:
            line = line[2:]
        line = re.sub(b"\r", b"", line)
        line = re.sub(b"\\\\(.|\n)", mapget, line)
        if last_line is None:
            last_line = line
        else:
            last_line += line
        if last_line[-1:] == b"\n":
            yield last_line
            last_line = None
    if last_line is not None:
        yield last_line


def read_patch_stanza(line_iter):
    """Convert an iterable of RIO-Patch format lines into a Stanza.

    RIO-Patch is a RIO variant designed to be e-mailed as part of a patch.
    It resists common forms of damage such as newline conversion or the removal
    of trailing whitespace, yet is also reasonably easy to read.

    :return: a Stanza
    """
    return rio.read_stanza(_patch_stanza_iter(line_iter))
