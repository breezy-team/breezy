"""Patch parsing and application functionality for Breezy.

This module provides classes and functions for parsing unified diffs,
applying patches to files, and handling patch-related operations.
It supports both text and binary patch formats.
"""
# Copyright (C) 2005-2010 Aaron Bentley, Canonical Ltd
# <aaron.bentley@utoronto.ca>
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

import os

from .errors import BzrError

binary_files_re = b"Binary files (.*) and (.*) differ\n"


class PatchSyntax(BzrError):
    """Base class for patch syntax errors."""


class MalformedLine(PatchSyntax):
    """Error raised when a patch contains a malformed line."""

    _fmt = "Malformed line.  %(desc)s\n%(line)r"

    def __init__(self, desc, line):
        """Initialize MalformedLine error.

        Args:
            desc: Description of the malformed line.
            line: The malformed line content.
        """
        self.desc = desc
        self.line = line


class PatchConflict(BzrError):
    """Error raised when patch application encounters a conflict."""

    _fmt = (
        "Text contents mismatch at line %(line_no)d.  Original has "
        '"%(orig_line)s", but patch says it should be "%(patch_line)s"'
    )

    def __init__(self, line_no, orig_line, patch_line):
        """Initialize PatchConflict error.

        Args:
            line_no: Line number where conflict occurred.
            orig_line: Original line content.
            patch_line: Expected line content from patch.
        """
        self.line_no = line_no
        self.orig_line = orig_line.rstrip(b"\n")
        self.patch_line = patch_line.rstrip(b"\n")


class MalformedHunkHeader(PatchSyntax):
    """Error raised when a patch hunk header is malformed."""

    _fmt = "Malformed hunk header.  %(desc)s\n%(line)r"

    def __init__(self, desc, line):
        """Initialize MalformedHunkHeader error.

        Args:
            desc: Description of the malformed header.
            line: The malformed header line content.
        """
        self.desc = desc
        self.line = line


# Imported after the exception classes above: the Rust extension resolves them
# out of this module when it raises.
from ._patch_rs import (  # noqa: F401
    NO_NL,
    BinaryFiles,
    BinaryPatch,
    ContextLine,
    Hunk,
    HunkLine,
    InsertLine,
    MalformedPatchHeader,
    Patch,
    RemoveLine,
    difference_index,
    get_patch_names,
    hunk_from_header,
    iter_hunks,
    iter_lines_handle_nl,
    iter_patched_from_hunks,
    parse_line,
    parse_patch,
    parse_patches,
    parse_range,
)


def iter_patched(orig_lines, patch_lines):
    """Iterate through a series of lines with a patch applied.
    This handles a single file, and does exact, not fuzzy patching.
    """
    patch_lines = iter_lines_handle_nl(iter(patch_lines))
    get_patch_names(patch_lines)
    return iter_patched_from_hunks(orig_lines, iter_hunks(patch_lines))


def apply_patches(tt, patches, prefix=1):
    """Apply patches to a TreeTransform.

    :param tt: TreeTransform instance
    :param patches: List of patches
    :param prefix: Number leading path segments to strip
    """

    def strip_prefix(p):
        return "/".join(p.split("/")[1:])

    from bzrformats.generate_ids import gen_file_id

    # TODO(jelmer): Extract and set mode
    for patch in patches:
        if patch.oldname == b"/dev/null":
            trans_id = None
            orig_contents = b""
        else:
            oldname = strip_prefix(patch.oldname.decode())
            trans_id = tt.trans_id_tree_path(oldname)
            orig_contents = tt._tree.get_file_text(oldname)
            tt.delete_contents(trans_id)

        if patch.newname != b"/dev/null":
            newname = strip_prefix(patch.newname.decode())
            new_contents = iter_patched_from_hunks(
                orig_contents.splitlines(True), patch.hunks
            )
            if trans_id is None:
                parts = os.path.split(newname)
                trans_id = tt.root
                for part in parts[1:-1]:
                    trans_id = tt.new_directory(part, trans_id)
                tt.new_file(
                    parts[-1], trans_id, new_contents, file_id=gen_file_id(newname)
                )
            else:
                tt.create_file(new_contents, trans_id)


class AppliedPatches:
    """Context that provides access to a tree with patches applied."""

    def __init__(self, tree, patches, prefix=1):
        """Initialize an AppliedPatches context.

        Args:
            tree: The tree to apply patches to.
            patches: List of patches to apply.
            prefix: Number of path segments to strip from patch paths.
        """
        self.tree = tree
        self.patches = patches
        self.prefix = prefix

    def __enter__(self):
        """Enter the context and return a tree with patches applied.

        Returns:
            A preview tree with the patches applied.
        """
        self._tt = self.tree.preview_transform()
        apply_patches(self._tt, self.patches, prefix=self.prefix)
        return self._tt.get_preview_tree()

    def __exit__(self, exc_type, exc_value, exc_tb):
        """Exit the context and clean up resources.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_value: Exception value if an exception occurred.
            exc_tb: Exception traceback if an exception occurred.

        Returns:
            False to allow exceptions to propagate.
        """
        self._tt.finalize()
        return False
