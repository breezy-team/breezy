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

# TODO: When extracting a single version it'd be enough to just pass
# an iterator returning the weave lines...  We don't really need to
# deserialize it into memory.

FORMAT_1 = b"# bzr weave file v5\n"


def write_weave(weave, f, format=None):
    if format is None or format == 1:
        return write_weave_v5(weave, f)
    else:
        raise ValueError("unknown weave format {!r}".format(format))


def write_weave_v5(weave, f):
    """Write weave to file f."""
    f.write(FORMAT_1)

    for version, included in enumerate(weave._parents):
        if included:
            # mininc = weave.minimal_parents(version)
            mininc = included
            f.write(b"i ")
            f.write(b" ".join(b"%d" % i for i in mininc))
            f.write(b"\n")
        else:
            f.write(b"i\n")
        f.write(b"1 " + weave._sha1s[version] + b"\n")
        f.write(b"n " + weave._names[version] + b"\n")
        f.write(b"\n")

    f.write(b"w\n")

    for l in weave._weave:
        if isinstance(l, tuple):
            if l[0] == b"}":
                f.write(b"}\n")
            else:
                f.write(l[0] + b" %d\n" % l[1])
        else:  # text line
            if not l:
                f.write(b", \n")
            elif l.endswith(b"\n"):
                f.write(b". " + l)
            else:
                f.write(b", " + l + b"\n")

    f.write(b"W\n")


def read_weave(f):
    # FIXME: detect the weave type and dispatch
    from .weave import Weave

    w = Weave(getattr(f, "name", None))
    _read_weave_v5(f, w)
    return w


def _read_weave_v5(f, w):
    """Private helper routine to read a weave format 5 file into memory.

    This is only to be used by read_weave and WeaveFile.__init__.
    """
    #  200   0   2075.5080   1084.0360   breezy.weavefile:104(_read_weave_v5)
    # +60412 0    366.5900    366.5900   +<method 'readline' of 'file' objects>
    # +59982 0    320.5280    320.5280   +<method 'startswith' of 'str' objects>
    # +59363 0    297.8080    297.8080   +<method 'append' of 'list' objects>
    # replace readline call with iter over all lines ->
    # safe because we already suck on memory.
    #  200   0   1492.7170    802.6220   breezy.weavefile:104(_read_weave_v5)
    # +59982 0    329.9100    329.9100   +<method 'startswith' of 'str' objects>
    # +59363 0    320.2980    320.2980   +<method 'append' of 'list' objects>
    # replaced startswith with slice lookups:
    #  200   0    851.7250    501.1120   breezy.weavefile:104(_read_weave_v5)
    # +59363 0    311.8780    311.8780   +<method 'append' of 'list' objects>
    # +200   0     30.2500     30.2500   +<method 'readlines' of 'file' objects>

    from .weave import WeaveFormatError

    try:
        lines = iter(f.readlines())
    finally:
        f.close()

    try:
        l = next(lines)
    except StopIteration as err:
        raise WeaveFormatError("invalid weave file: no header") from err

    if l != FORMAT_1:
        raise WeaveFormatError("invalid weave file header: {!r}".format(l))

    ver = 0
    # read weave header.
    while True:
        l = next(lines)
        if l[0:1] == b"i":
            if len(l) > 2:
                w._parents.append(list(map(int, l[2:].split(b" "))))
            else:
                w._parents.append([])
            l = next(lines)[:-1]
            w._sha1s.append(l[2:])
            l = next(lines)
            name = l[2:-1]
            w._names.append(name)
            w._name_map[name] = ver
            l = next(lines)
            ver += 1
        elif l == b"w\n":
            break
        else:
            raise WeaveFormatError("unexpected line {!r}".format(l))

    # read weave body
    while True:
        l = next(lines)
        if l == b"W\n":
            break
        elif l[0:2] == b". ":
            w._weave.append(l[2:])  # include newline
        elif l[0:2] == b", ":
            w._weave.append(l[2:-1])  # exclude newline
        elif l == b"}\n":
            w._weave.append((b"}", None))
        else:
            w._weave.append((l[0:1], int(l[2:].decode("ascii"))))
    return w
