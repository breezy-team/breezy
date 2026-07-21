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

from .._git_rs import extract_hg_metadata  # noqa: F401
from .._git_rs import format_hg_metadata as _format_hg_metadata


def format_hg_metadata(renames, branch, extra):
    """Construct a tail with hg-git metadata.

    :param renames: List of (oldpath, newpath) tuples with file renames,
        as bytes
    :param branch: Branch name, as str
    :param extra: Dictionary mapping str keys to bytes values
    :return: Tail for commit message, as bytes
    """
    renames = [(oldfile, newfile) for (oldfile, newfile) in renames]
    return _format_hg_metadata(renames, branch, list(extra.items()))
