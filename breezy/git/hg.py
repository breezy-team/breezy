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


def format_hg_metadata(renames, branch, extra):
    """Construct a tail with hg-git metadata.

    :param renames: List of (oldpath, newpath) tuples with file renames
    :param branch: Branch name
    :param extra: Dictionary with extra data
    :return: Tail for commit message
    """
    extra_message = ""
    if branch != "default":
        extra_message += "branch : " + branch + "\n"

    if renames:
        for oldfile, newfile in renames:
            extra_message += "rename : " + oldfile + " => " + newfile + "\n"

    for key, value in extra.iteritems():
        if key in ("author", "committer", "encoding", "message", "branch", "hg-git"):
            continue
        else:
            extra_message += "extra : " + key + " : " + urllib.parse.quote(value) + "\n"

    if extra_message:
        return "\n--HG--\n" + extra_message
    else:
        return ""


def extract_hg_metadata(message):
    """Extract Mercurial metadata from a commit message.

    :param message: Commit message to extract from
    :return: Tuple with original commit message, renames, branch and
        extra data.
    """
    split = message.split("\n--HG--\n", 1)
    renames = {}
    extra = {}
    branch = None
    if len(split) == 2:
        message, meta = split
        lines = meta.split("\n")
        for line in lines:
            if line == "":
                continue
            command, data = line.split(" : ", 1)
            if command == "rename":
                before, after = data.split(" => ", 1)
                renames[after] = before
            elif command == "branch":
                branch = data
            elif command == "extra":
                before, after = data.split(" : ", 1)
                extra[before] = urllib.parse.unquote(after)
            else:
                raise KeyError(f"unknown hg-git metadata command {command}")
    return (message, renames, branch, extra)
