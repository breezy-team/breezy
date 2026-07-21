# Copyright (C) 2009 Scott Chacon <schacon@gmail.com>
# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>

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

"""Compatibility for hg-git."""

import urllib.parse

RESERVED_EXTRA_KEYS = ("author", "committer", "encoding", "message", "branch", "hg-git")


def format_hg_metadata(renames, branch, extra):
    """Construct a tail with hg-git metadata.

    :param renames: List of (oldpath, newpath) tuples with file renames,
        as bytes
    :param branch: Branch name, as str
    :param extra: Dictionary mapping str keys to bytes values
    :return: Tail for commit message, as bytes
    """
    extra_message = b""
    if branch != "default":
        extra_message += b"branch : " + branch.encode("utf-8") + b"\n"

    for oldfile, newfile in renames:
        extra_message += b"rename : " + oldfile + b" => " + newfile + b"\n"

    for key, value in extra.items():
        if key in RESERVED_EXTRA_KEYS:
            continue
        quoted = urllib.parse.quote_from_bytes(value).encode("ascii")
        extra_message += b"extra : " + key.encode("utf-8") + b" : " + quoted + b"\n"

    if extra_message:
        return b"\n--HG--\n" + extra_message
    else:
        return b""


def extract_hg_metadata(message):
    """Extract Mercurial metadata from a commit message.

    :param message: Commit message to extract from, as bytes
    :return: Tuple with original commit message (bytes), renames
        (dict of bytes to bytes), branch (str or None) and extra data
        (dict of str to bytes).
    """
    split = message.split(b"\n--HG--\n", 1)
    renames = {}
    extra = {}
    branch = None
    if len(split) == 2:
        message, meta = split
        for line in meta.split(b"\n"):
            if line == b"":
                continue
            command, data = line.split(b" : ", 1)
            if command == b"rename":
                before, after = data.split(b" => ", 1)
                renames[after] = before
            elif command == b"branch":
                branch = data.decode("utf-8")
            elif command == b"extra":
                before, after = data.split(b" : ", 1)
                extra[before.decode("utf-8")] = urllib.parse.unquote_to_bytes(after)
            else:
                raise KeyError(f"unknown hg-git metadata command {command!r}")
    return (message, renames, branch, extra)
