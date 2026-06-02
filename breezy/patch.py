# Copyright (C) 2005, 2006 Canonical Ltd
# Copyright (C) 2005, 2008 Aaron Bentley, 2006 Michael Ellerman
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

"""Diff and patch functionality."""

__all__ = [
    "PatchFailed",
    "PatchInvokeError",
    "diff3",
    "format_patch_date",
    "iter_patched_from_hunks",
    "parse_patch_date",
    "patch",
    "run_patch",
]

from ._patch_rs import (
    PatchFailed,
    PatchInvokeError,
    diff3,
    format_patch_date,
    iter_patched_from_hunks,
    parse_patch_date,
    patch,
    run_patch,
)
