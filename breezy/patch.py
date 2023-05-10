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

"""Diff and patch functionality"""

from ._patch_rs import (PatchFailed, PatchInvokeError, diff3,  # noqa: F401
                        format_patch_date, iter_patched_from_hunks,
                        parse_patch_date, patch, run_patch)


def patch_tree(tree, patches, strip=0, reverse=False, dry_run=False,
               quiet=False, out=None):
    """Apply a patch to a tree.

    Args:
      tree: A MutableTree object
      patches: list of patches as bytes
      strip: Strip X segments of paths
      reverse: Apply reversal of patch
      dry_run: Dry run
    """
    return run_patch(tree.basedir, patches=patches, strip=strip,
                     reverse=reverse, dry_run=dry_run, quiet=quiet, out=out)
