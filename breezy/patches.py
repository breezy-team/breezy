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
import re
from collections.abc import Iterator

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
        self.orig_line = orig_line.rstrip("\n")
        self.patch_line = patch_line.rstrip("\n")


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


from ._patch_rs import (  # noqa: F401
    BinaryFiles,
    MalformedPatchHeader,
    difference_index,
    get_patch_names,
    iter_lines_handle_nl,
    parse_range,
)


def hunk_from_header(line):
    """Parse a hunk header line and return a Hunk object.

    Args:
        line: The hunk header line to parse.

    Returns:
        A Hunk object created from the header.

    Raises:
        MalformedHunkHeader: If the header format is invalid.
    """
    import re

    matches = re.match(rb"\@\@ ([^@]*) \@\@( (.*))?\n", line)
    if matches is None:
        raise MalformedHunkHeader("Does not match format.", line)
    try:
        (orig, mod) = matches.group(1).split(b" ")
    except (ValueError, IndexError) as e:
        raise MalformedHunkHeader(str(e), line) from e
    if not orig.startswith(b"-") or not mod.startswith(b"+"):
        raise MalformedHunkHeader("Positions don't start with + or -.", line)
    try:
        (orig_pos, orig_range) = parse_range(orig[1:].decode("utf-8"))
        (mod_pos, mod_range) = parse_range(mod[1:].decode("utf-8"))
    except (ValueError, IndexError) as e:
        raise MalformedHunkHeader(str(e), line) from e
    if mod_range < 0 or orig_range < 0:
        raise MalformedHunkHeader("Hunk range is negative", line)
    tail = matches.group(3)
    return Hunk(orig_pos, orig_range, mod_pos, mod_range, tail)


class HunkLine:
    """Base class for a line in a patch hunk."""

    def __init__(self, contents):
        """Initialize a hunk line.

        Args:
            contents: The line contents as bytes.
        """
        self.contents = contents

    def get_str(self, leadchar):
        """Get string representation with a lead character.

        Args:
            leadchar: Character to prefix the line with.

        Returns:
            Formatted line as bytes.
        """
        if False:
            return b"\n"
        terminator = b"\n" + NO_NL if not self.contents.endswith(b"\n") else b""
        return leadchar + self.contents + terminator

    def as_bytes(self):
        """Return the line as bytes in patch format.

        Returns:
            The line formatted for a patch.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError


class ContextLine(HunkLine):
    """A context line in a patch hunk (unchanged)."""

    def __init__(self, contents):
        """Initialize a context line.

        Args:
            contents: The line contents as bytes.
        """
        HunkLine.__init__(self, contents)

    def as_bytes(self):
        """Return the context line as bytes in patch format.

        Returns:
            The line prefixed with a space character.
        """
        return self.get_str(b" ")


class InsertLine(HunkLine):
    """An insert line in a patch hunk (addition)."""

    def __init__(self, contents):
        """Initialize an insert line.

        Args:
            contents: The line contents as bytes.
        """
        HunkLine.__init__(self, contents)

    def as_bytes(self):
        """Return the insert line as bytes in patch format.

        Returns:
            The line prefixed with a plus character.
        """
        return self.get_str(b"+")


class RemoveLine(HunkLine):
    """A remove line in a patch hunk (deletion)."""

    def __init__(self, contents):
        """Initialize a remove line.

        Args:
            contents: The line contents as bytes.
        """
        HunkLine.__init__(self, contents)

    def as_bytes(self):
        """Return the remove line as bytes in patch format.

        Returns:
            The line prefixed with a minus character.
        """
        return self.get_str(b"-")


NO_NL = b"\\ No newline at end of file\n"
__pychecker__ = "no-returnvalues"


def parse_line(line):
    """Parse a single line from a patch hunk.

    Args:
        line: The line to parse as bytes.

    Returns:
        A HunkLine subclass instance representing the line.

    Raises:
        MalformedLine: If the line format is unknown.
    """
    if line.startswith(b"\n"):
        return ContextLine(line)
    elif line.startswith(b" "):
        return ContextLine(line[1:])
    elif line.startswith(b"+"):
        return InsertLine(line[1:])
    elif line.startswith(b"-"):
        return RemoveLine(line[1:])
    else:
        raise MalformedLine("Unknown line type", line)


__pychecker__ = ""


class Hunk:
    """A patch hunk containing a set of line changes."""

    def __init__(self, orig_pos, orig_range, mod_pos, mod_range, tail=None) -> None:
        """Initialize a patch hunk.

        Args:
            orig_pos: Starting position in original file.
            orig_range: Number of lines in original file.
            mod_pos: Starting position in modified file.
            mod_range: Number of lines in modified file.
            tail: Optional tail text from hunk header.
        """
        self.orig_pos = orig_pos
        self.orig_range = orig_range
        self.mod_pos = mod_pos
        self.mod_range = mod_range
        self.tail = tail
        self.lines: list[bytes] = []

    def get_header(self):
        """Get the header line for this hunk.

        Returns:
            The hunk header as bytes.
        """
        tail_str = b"" if self.tail is None else b" " + self.tail
        return b"@@ -%s +%s @@%s\n" % (
            self.range_str(self.orig_pos, self.orig_range),
            self.range_str(self.mod_pos, self.mod_range),
            tail_str,
        )

    def range_str(self, pos, range):
        """Return a file range, special-casing for 1-line files.

        :param pos: The position in the file
        :type pos: int
        :range: The range in the file
        :type range: int
        :return: a string in the format 1,4 except when range == pos == 1
        """
        if range == 1:
            return b"%i" % pos
        else:
            return b"%i,%i" % (pos, range)

    def as_bytes(self):
        """Return the complete hunk as bytes.

        Returns:
            The hunk header and all lines as bytes.
        """
        lines = [self.get_header()]
        for line in self.lines:
            lines.append(line.as_bytes())
        return b"".join(lines)

    __bytes__ = as_bytes

    def shift_to_mod(self, pos):
        """Shift a position from original to modified file coordinates.

        Args:
            pos: Position in the original file.

        Returns:
            Corresponding position shift in the modified file.
        """
        if pos < self.orig_pos - 1:
            return 0
        elif pos > self.orig_pos + self.orig_range:
            return self.mod_range - self.orig_range
        else:
            return self.shift_to_mod_lines(pos)

    def shift_to_mod_lines(self, pos):
        """Calculate position shift by examining individual hunk lines.

        Args:
            pos: Position in the original file.

        Returns:
            Position shift in the modified file, or None if position is removed.
        """
        position = self.orig_pos - 1
        shift = 0
        for line in self.lines:
            if isinstance(line, InsertLine):
                shift += 1
            elif isinstance(line, RemoveLine):
                if position == pos:
                    return None
                shift -= 1
                position += 1
            elif isinstance(line, ContextLine):
                position += 1
            if position > pos:
                break
        return shift


def iter_hunks(iter_lines, allow_dirty=False):
    """:arg iter_lines: iterable of lines to parse for hunks
    :kwarg allow_dirty: If True, when we encounter something that is not
        a hunk header when we're looking for one, assume the rest of the lines
        are not part of the patch (comments or other junk).  Default False.
    """
    hunk = None
    for line in iter_lines:
        if line == b"\n":
            if hunk is not None:
                yield hunk
                hunk = None
            continue
        if hunk is not None:
            yield hunk
        try:
            hunk = hunk_from_header(line)
        except MalformedHunkHeader:
            if allow_dirty:
                # If the line isn't a hunk header, then we've reached the end
                # of this patch and there's "junk" at the end.  Ignore the
                # rest of this patch.
                return
            raise
        orig_size = 0
        mod_size = 0
        while orig_size < hunk.orig_range or mod_size < hunk.mod_range:
            hunk_line = parse_line(next(iter_lines))
            hunk.lines.append(hunk_line)
            if isinstance(hunk_line, (RemoveLine, ContextLine)):
                orig_size += 1
            if isinstance(hunk_line, (InsertLine, ContextLine)):
                mod_size += 1
    if hunk is not None:
        yield hunk


class BinaryPatch:
    """A binary patch indicating files that differ but can't be shown."""

    def __init__(self, oldname, newname):
        """Initialize a binary patch.

        Args:
            oldname: Name of the original file.
            newname: Name of the new file.
        """
        self.oldname = oldname
        self.newname = newname

    def as_bytes(self):
        """Return the binary patch as bytes.

        Returns:
            A message indicating binary files differ.
        """
        return b"Binary files %s and %s differ\n" % (self.oldname, self.newname)


class Patch(BinaryPatch):
    """A text patch containing hunks showing file differences."""

    def __init__(self, oldname, newname, oldts=None, newts=None) -> None:
        """Initialize a text patch.

        Args:
            oldname: Name of the original file.
            newname: Name of the new file.
            oldts: Timestamp of the original file.
            newts: Timestamp of the new file.
        """
        BinaryPatch.__init__(self, oldname, newname)
        self.oldts = oldts
        self.newts = newts
        self.hunks: list[Hunk] = []

    def as_bytes(self):
        """Return the complete patch as bytes.

        Returns:
            The patch header and all hunks as bytes.
        """
        ret = self.get_header()
        ret += b"".join([h.as_bytes() for h in self.hunks])
        return ret

    @classmethod
    def _headerline(cls, start, name, ts):
        l = start + b" " + name
        if ts is not None:
            l += b"\t%s" % ts
        l += b"\n"
        return l

    def get_header(self):
        """Get the patch header lines.

        Returns:
            Header lines showing old and new file names and timestamps.
        """
        return self._headerline(b"---", self.oldname, self.oldts) + self._headerline(
            b"+++", self.newname, self.newts
        )

    def stats_values(self):
        """Calculate the number of inserts and removes."""
        removes = 0
        inserts = 0
        for hunk in self.hunks:
            for line in hunk.lines:
                if isinstance(line, InsertLine):
                    inserts += 1
                elif isinstance(line, RemoveLine):
                    removes += 1
        return (inserts, removes, len(self.hunks))

    def stats_str(self):
        """Return a string of patch statistics."""
        return "%i inserts, %i removes in %i hunks" % self.stats_values()

    def pos_in_mod(self, position):
        """Calculate position in modified file from original position.

        Args:
            position: Position in the original file.

        Returns:
            Corresponding position in the modified file, or None if removed.
        """
        newpos = position
        for hunk in self.hunks:
            shift = hunk.shift_to_mod(position)
            if shift is None:
                return None
            newpos += shift
        return newpos

    def iter_inserted(self):
        """Iteraties through inserted lines.

        :return: Pair of line number, line
        :rtype: iterator of (int, InsertLine)
        """
        for hunk in self.hunks:
            pos = hunk.mod_pos - 1
            for line in hunk.lines:
                if isinstance(line, InsertLine):
                    yield (pos, line)
                    pos += 1
                if isinstance(line, ContextLine):
                    pos += 1


def parse_patch(iter_lines, allow_dirty=False):
    """:arg iter_lines: iterable of lines to parse
    :kwarg allow_dirty: If True, allow the patch to have trailing junk.
        Default False.
    """
    iter_lines = iter_lines_handle_nl(iter_lines)
    try:
        ((orig_name, orig_ts), (mod_name, mod_ts)) = get_patch_names(iter_lines)
    except BinaryFiles as e:
        return BinaryPatch(e.args[0].encode("utf-8"), e.args[1].encode("utf-8"))
    else:
        patch = Patch(orig_name, mod_name, orig_ts, mod_ts)
        for hunk in iter_hunks(iter_lines, allow_dirty):
            patch.hunks.append(hunk)
        return patch


def iter_file_patch(
    iter_lines: Iterator[bytes], allow_dirty: bool = False, keep_dirty: bool = False
):
    """:arg iter_lines: iterable of lines to parse for patches
    :kwarg allow_dirty: If True, allow comments and other non-patch text
        before the first patch.  Note that the algorithm here can only find
        such text before any patches have been found.  Comments after the
        first patch are stripped away in iter_hunks() if it is also passed
        allow_dirty=True.  Default False.
    """
    # FIXME: Docstring is not quite true.  We allow certain comments no
    # matter what, If they startwith '===', '***', or '#' Someone should
    # reexamine this logic and decide if we should include those in
    # allow_dirty or restrict those to only being before the patch is found
    # (as allow_dirty does).
    regex = re.compile(binary_files_re)
    saved_lines: list[bytes] = []
    dirty_head: list[bytes] = []
    orig_range = 0
    beginning = True

    for line in iter_lines:
        if line.startswith(b"=== "):
            if allow_dirty and beginning:
                # Patches can have "junk" at the beginning
                # Stripping junk from the end of patches is handled when we
                # parse the patch
                pass
            elif len(saved_lines) > 0:
                if keep_dirty and len(dirty_head) > 0:
                    yield {"saved_lines": saved_lines, "dirty_head": dirty_head}
                    dirty_head = []
                else:
                    yield saved_lines
                saved_lines = []
            dirty_head.append(line)
            continue
        if line.startswith(b"*** "):
            continue
        if line.startswith(b"#"):
            continue
        elif orig_range > 0:
            if line.startswith(b"-") or line.startswith(b" "):
                orig_range -= 1
        elif line.startswith(b"--- ") or regex.match(line):
            if allow_dirty and beginning:
                # Patches can have "junk" at the beginning
                # Stripping junk from the end of patches is handled when we
                # parse the patch
                beginning = False
            elif len(saved_lines) > 0:
                if keep_dirty and len(dirty_head) > 0:
                    yield {"saved_lines": saved_lines, "dirty_head": dirty_head}
                    dirty_head = []
                else:
                    yield saved_lines
            saved_lines = []
        elif line.startswith(b"@@"):
            hunk = hunk_from_header(line)
            orig_range = hunk.orig_range
        saved_lines.append(line)
    if len(saved_lines) > 0:
        if keep_dirty and len(dirty_head) > 0:
            yield {"saved_lines": saved_lines, "dirty_head": dirty_head}
        else:
            yield saved_lines


def parse_patches(iter_lines, allow_dirty=False, keep_dirty=False):
    """:arg iter_lines: iterable of lines to parse for patches
    :kwarg allow_dirty: If True, allow text that's not part of the patch at
        selected places.  This includes comments before and after a patch
        for instance.  Default False.
    :kwarg keep_dirty: If True, returns a dict of patches with dirty headers.
        Default False.
    """
    for patch_lines in iter_file_patch(iter_lines, allow_dirty, keep_dirty):
        if "dirty_head" in patch_lines:
            yield (
                {
                    "patch": parse_patch(patch_lines["saved_lines"], allow_dirty),
                    "dirty_head": patch_lines["dirty_head"],
                }
            )
        else:
            yield parse_patch(patch_lines, allow_dirty)


def iter_patched(orig_lines, patch_lines):
    """Iterate through a series of lines with a patch applied.
    This handles a single file, and does exact, not fuzzy patching.
    """
    patch_lines = iter_lines_handle_nl(iter(patch_lines))
    get_patch_names(patch_lines)
    return iter_patched_from_hunks(orig_lines, iter_hunks(patch_lines))


def iter_patched_from_hunks(orig_lines, hunks):
    """Iterate through a series of lines with a patch applied.
    This handles a single file, and does exact, not fuzzy patching.

    :param orig_lines: The unpatched lines.
    :param hunks: An iterable of Hunk instances.
    """
    seen_patch = []
    line_no = 1
    if orig_lines is not None:
        orig_lines = iter(orig_lines)
    for hunk in hunks:
        while line_no < hunk.orig_pos:
            orig_line = next(orig_lines)
            yield orig_line
            line_no += 1
        for hunk_line in hunk.lines:
            seen_patch.append(hunk_line.contents)
            if isinstance(hunk_line, InsertLine):
                yield hunk_line.contents
            elif isinstance(hunk_line, (ContextLine, RemoveLine)):
                orig_line = next(orig_lines)
                if orig_line != hunk_line.contents:
                    raise PatchConflict(line_no, orig_line, b"".join(seen_patch))
                if isinstance(hunk_line, ContextLine):
                    yield orig_line
                else:
                    if not isinstance(hunk_line, RemoveLine):
                        raise AssertionError(hunk_line)
                line_no += 1
    if orig_lines is not None:
        yield from orig_lines


def apply_patches(tt, patches, prefix=1):
    """Apply patches to a TreeTransform.

    :param tt: TreeTransform instance
    :param patches: List of patches
    :param prefix: Number leading path segments to strip
    """

    def strip_prefix(p):
        return "/".join(p.split("/")[1:])

    from .bzr.generate_ids import gen_file_id

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
