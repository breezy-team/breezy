# Copyright (C) 2007-2011 Canonical Ltd
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

"""Multi-parent diff implementation for versioned files."""

import contextlib
import os
from io import BytesIO

from . import errors


def topo_iter_keys(vf, keys=None):
    """Iterate through keys in topological order."""
    if keys is None:
        keys = vf.keys()
    parents = vf.get_parent_map(keys)
    return _topo_iter(parents, keys)


def topo_iter(vf, versions=None):
    """Iterate through versions in topological order."""
    if versions is None:
        versions = vf.versions()
    parents = vf.get_parent_map(versions)
    return _topo_iter(parents, versions)


def _topo_iter(parents, versions):
    seen = set()
    descendants = {}

    def pending_parents(version):
        if parents[version] is None:
            return []
        return [v for v in parents[version] if v in versions and v not in seen]

    for version_id in versions:
        if parents[version_id] is None:
            # parentless
            continue
        for parent_id in parents[version_id]:
            descendants.setdefault(parent_id, []).append(version_id)
    cur = [v for v in versions if len(pending_parents(v)) == 0]
    while len(cur) > 0:
        next = []
        for version_id in cur:
            if version_id in seen:
                continue
            if len(pending_parents(version_id)) != 0:
                continue
            next.extend(descendants.get(version_id, []))
            yield version_id
            seen.add(version_id)
        cur = next


class MultiParent:
    """A multi-parent diff."""

    __slots__ = ["hunks"]

    def __init__(self, hunks=None):
        """Initialize a MultiParent diff."""
        if hunks is not None:
            self.hunks = hunks
        else:
            self.hunks = []

    def __repr__(self):
        """Return a string representation of this MultiParent."""
        return f"MultiParent({self.hunks!r})"

    def __eq__(self, other):
        """Check equality with another MultiParent."""
        if self.__class__ is not other.__class__:
            return False
        return self.hunks == other.hunks

    @staticmethod
    def from_lines(text, parents=(), left_blocks=None):
        """Produce a MultiParent from a list of lines and parents."""
        try:
            import patiencediff
        except ImportError as e:
            raise ImportError(
                "patiencediff module is required for multiparent operations"
            ) from e

        def compare(parent):
            matcher = patiencediff.PatienceSequenceMatcher(None, parent, text)
            return matcher.get_matching_blocks()

        if len(parents) > 0:
            if left_blocks is None:
                left_blocks = compare(parents[0])
            parent_comparisons = [left_blocks] + [compare(p) for p in parents[1:]]
        else:
            parent_comparisons = []
        cur_line = 0
        new_text = NewText([])
        block_iter = [iter(i) for i in parent_comparisons]
        diff = MultiParent([])

        def next_block(p):
            try:
                return next(block_iter[p])
            except StopIteration:
                return None

        cur_block = [next_block(p) for p, i in enumerate(block_iter)]
        while cur_line < len(text):
            best_match = None
            for p, block in enumerate(cur_block):
                if block is None:
                    continue
                i, j, n = block
                while j + n <= cur_line:
                    block = cur_block[p] = next_block(p)
                    if block is None:
                        break
                    i, j, n = block
                if block is None:
                    continue
                if j > cur_line:
                    continue
                offset = cur_line - j
                i += offset
                j = cur_line
                n -= offset
                if n == 0:
                    continue
                if best_match is None or n > best_match.num_lines:
                    best_match = ParentText(p, i, j, n)
            if best_match is None:
                new_text.lines.append(text[cur_line])
                cur_line += 1
            else:
                if len(new_text.lines) > 0:
                    diff.hunks.append(new_text)
                    new_text = NewText([])
                diff.hunks.append(best_match)
                cur_line += best_match.num_lines
        if len(new_text.lines) > 0:
            diff.hunks.append(new_text)
        return diff

    def get_matching_blocks(self, parent, parent_len):
        """Get matching blocks for a specific parent."""
        for hunk in self.hunks:
            if not isinstance(hunk, ParentText) or hunk.parent != parent:
                continue
            yield (hunk.parent_pos, hunk.child_pos, hunk.num_lines)
        yield parent_len, self.num_lines(), 0

    def to_lines(self, parents=()):
        """Contruct a fulltext from this diff and its parents."""
        mpvf = MultiMemoryVersionedFile()
        for num, parent in enumerate(parents):
            mpvf.add_version(BytesIO(parent).readlines(), num, [])
        mpvf.add_diff(self, "a", list(range(len(parents))))
        return mpvf.get_line_list(["a"])[0]

    @classmethod
    def from_texts(cls, text, parents=()):
        """Produce a MultiParent from a text and list of parent text."""
        return cls.from_lines(
            BytesIO(text).readlines(), [BytesIO(p).readlines() for p in parents]
        )

    def to_patch(self):
        """Yield text lines for a patch."""
        for hunk in self.hunks:
            yield from hunk.to_patch()

    def patch_len(self):
        """Return the length of the patch."""
        return len(b"".join(self.to_patch()))

    def zipped_patch_len(self):
        """Return the length of the gzipped patch."""
        return len(gzip_string(self.to_patch()))

    @classmethod
    def from_patch(cls, text):
        """Create a MultiParent from its string form."""
        return cls._from_patch(BytesIO(text))

    @staticmethod
    def _from_patch(lines):
        r"""This is private because it is essential to split lines on \n only."""
        line_iter = iter(lines)
        hunks = []
        cur_line = None
        while True:
            try:
                cur_line = next(line_iter)
            except StopIteration:
                break
            first_char = cur_line[0:1]
            if first_char == b"i":
                num_lines = int(cur_line.split(b" ")[1])
                hunk_lines = [next(line_iter) for _ in range(num_lines)]
                hunk_lines[-1] = hunk_lines[-1][:-1]
                hunks.append(NewText(hunk_lines))
            elif first_char == b"\n":
                hunks[-1].lines[-1] += b"\n"
            else:
                if not (first_char == b"c"):
                    raise AssertionError(first_char)
                parent, parent_pos, child_pos, num_lines = (
                    int(v) for v in cur_line.split(b" ")[1:]
                )
                hunks.append(ParentText(parent, parent_pos, child_pos, num_lines))
        return MultiParent(hunks)

    def range_iterator(self):
        """Iterate through the hunks, with range indicated.

        kind is "new" or "parent".
        for "new", data is a list of lines.
        for "parent", data is (parent, parent_start, parent_end)
        :return: a generator of (start, end, kind, data)
        """
        start = 0
        for hunk in self.hunks:
            if isinstance(hunk, NewText):
                kind = "new"
                end = start + len(hunk.lines)
                data = hunk.lines
            else:
                kind = "parent"
                start = hunk.child_pos
                end = start + hunk.num_lines
                data = (hunk.parent, hunk.parent_pos, hunk.parent_pos + hunk.num_lines)
            yield start, end, kind, data
            start = end

    def num_lines(self):
        """The number of lines in the output text."""
        extra_n = 0
        for hunk in reversed(self.hunks):
            if isinstance(hunk, ParentText):
                return hunk.child_pos + hunk.num_lines + extra_n
            extra_n += len(hunk.lines)
        return extra_n

    def is_snapshot(self):
        """Return true of this hunk is effectively a fulltext."""
        if len(self.hunks) != 1:
            return False
        return isinstance(self.hunks[0], NewText)


class NewText:
    """The contents of text that is introduced by this text."""

    __slots__ = ["lines"]

    def __init__(self, lines):
        """Initialize a NewText hunk."""
        self.lines = lines

    def __eq__(self, other):
        """Check equality with another NewText."""
        if self.__class__ is not other.__class__:
            return False
        return other.lines == self.lines

    def __repr__(self):
        """Return a string representation of this NewText."""
        return f"NewText({self.lines!r})"

    def to_patch(self):
        """Generate patch lines for this NewText."""
        yield b"i %d\n" % len(self.lines)
        yield from self.lines
        yield b"\n"


class ParentText:
    """A reference to text present in a parent text."""

    __slots__ = ["child_pos", "num_lines", "parent", "parent_pos"]

    def __init__(self, parent, parent_pos, child_pos, num_lines):
        """Initialize a ParentText hunk."""
        self.parent = parent
        self.parent_pos = parent_pos
        self.child_pos = child_pos
        self.num_lines = num_lines

    def _as_dict(self):
        return {
            b"parent": self.parent,
            b"parent_pos": self.parent_pos,
            b"child_pos": self.child_pos,
            b"num_lines": self.num_lines,
        }

    def __repr__(self):
        """Return a string representation of this ParentText."""
        return (
            "ParentText({parent!r}, {parent_pos!r}, {child_pos!r},"
            " {num_lines!r})".format(**self._as_dict())
        )

    def __eq__(self, other):
        """Check equality with another ParentText."""
        if self.__class__ is not other.__class__:
            return False
        return self._as_dict() == other._as_dict()

    def to_patch(self):
        """Generate patch lines for this ParentText."""
        yield (
            b"c %(parent)d %(parent_pos)d %(child_pos)d %(num_lines)d\n"
            % self._as_dict()
        )


class BaseVersionedFile:
    """Pseudo-VersionedFile skeleton for MultiParent."""

    def __init__(self, snapshot_interval=25, max_snapshots=None):
        """Initialize a BaseVersionedFile."""
        self._lines = {}
        self._parents = {}
        self._snapshots = set()
        self.snapshot_interval = snapshot_interval
        self.max_snapshots = max_snapshots

    def versions(self):
        """Return an iterator of version IDs."""
        return iter(self._parents)

    def has_version(self, version):
        """Check if a version exists."""
        return version in self._parents

    def do_snapshot(self, version_id, parent_ids):
        """Determine whether to perform a snapshot for this version."""
        if self.snapshot_interval is None:
            return False
        if (
            self.max_snapshots is not None
            and len(self._snapshots) == self.max_snapshots
        ):
            return False
        if len(parent_ids) == 0:
            return True
        for _ignored in range(self.snapshot_interval):
            if len(parent_ids) == 0:
                return False
            version_ids = parent_ids
            parent_ids = []
            for version_id in version_ids:
                if version_id not in self._snapshots:
                    parent_ids.extend(self._parents[version_id])
        else:
            return True

    def add_version(
        self, lines, version_id, parent_ids, force_snapshot=None, single_parent=False
    ):
        r"""Add a version to the versionedfile.

        :param lines: The list of lines to add.  Must be split on '\n'.
        :param version_id: The version_id of the version to add
        :param force_snapshot: If true, force this version to be added as a
            snapshot version.  If false, force this version to be added as a
            diff.  If none, determine this automatically.
        :param single_parent: If true, use a single parent, rather than
            multiple parents.
        """
        if force_snapshot is None:
            do_snapshot = self.do_snapshot(version_id, parent_ids)
        else:
            do_snapshot = force_snapshot
        if do_snapshot:
            self._snapshots.add(version_id)
            diff = MultiParent([NewText(lines)])
        else:
            if single_parent:
                parent_lines = self.get_line_list(parent_ids[:1])
            else:
                parent_lines = self.get_line_list(parent_ids)
            diff = MultiParent.from_lines(lines, parent_lines)
            if diff.is_snapshot():
                self._snapshots.add(version_id)
        self.add_diff(diff, version_id, parent_ids)
        self._lines[version_id] = lines

    def get_parents(self, version_id):
        """Get the parent IDs for a version."""
        return self._parents[version_id]

    def make_snapshot(self, version_id):
        """Create a snapshot for the given version."""
        snapdiff = MultiParent([NewText(self.cache_version(version_id))])
        self.add_diff(snapdiff, version_id, self._parents[version_id])
        self._snapshots.add(version_id)

    def import_versionedfile(
        self,
        vf,
        snapshots,
        no_cache=True,
        single_parent=False,
        verify=False,
        progress_callback=None,
    ):
        """Import all revisions of a versionedfile.

        :param vf: The versionedfile to import
        :param snapshots: If provided, the revisions to make snapshots of.
            Otherwise, this will be auto-determined
        :param no_cache: If true, clear the cache after every add.
        :param single_parent: If true, omit all but one parent text, (but
            retain parent metadata).
        :param progress_callback: Optional callback function that will be called
            with (current, total) to report progress.
        """
        if not (no_cache or not verify):
            raise ValueError()
        revisions = set(vf.versions())
        total = len(revisions)
        processed = 0
        while len(revisions) > 0:
            added = set()
            for revision in revisions:
                parents = vf.get_parents(revision)
                if [p for p in parents if p not in self._parents] != []:
                    continue
                lines = [a + b" " + l for a, l in vf.annotate(revision)]
                if snapshots is None:
                    force_snapshot = None
                else:
                    force_snapshot = revision in snapshots
                self.add_version(
                    lines, revision, parents, force_snapshot, single_parent
                )
                added.add(revision)
                if no_cache:
                    self.clear_cache()
                    vf.clear_cache()
                    if verify:
                        if not (lines == self.get_line_list([revision])[0]):
                            raise AssertionError()
                        self.clear_cache()
            processed += len(added)
            if progress_callback:
                progress_callback(processed, total)
            revisions = [r for r in revisions if r not in added]

    def select_snapshots(self, vf):
        """Determine which versions to add as snapshots."""
        build_ancestors = {}
        snapshots = set()
        for version_id in topo_iter(vf):
            potential_build_ancestors = set(vf.get_parents(version_id))
            parents = vf.get_parents(version_id)
            if len(parents) == 0:
                snapshots.add(version_id)
                build_ancestors[version_id] = set()
            else:
                for parent in vf.get_parents(version_id):
                    potential_build_ancestors.update(build_ancestors[parent])
                if len(potential_build_ancestors) > self.snapshot_interval:
                    snapshots.add(version_id)
                    build_ancestors[version_id] = set()
                else:
                    build_ancestors[version_id] = potential_build_ancestors
        return snapshots

    def select_by_size(self, num):
        """Select snapshots for minimum output size."""
        num -= len(self._snapshots)
        new_snapshots = self.get_size_ranking()[-num:]
        return [v for n, v in new_snapshots]

    def get_size_ranking(self):
        """Get versions ranked by size."""
        versions = []
        for version_id in self.versions():
            if version_id in self._snapshots:
                continue
            diff_len = self.get_diff(version_id).patch_len()
            snapshot_len = MultiParent(
                [NewText(self.cache_version(version_id))]
            ).patch_len()
            versions.append((snapshot_len - diff_len, version_id))
        versions.sort()
        return versions

    def import_diffs(self, vf):
        """Import the diffs from another pseudo-versionedfile."""
        for version_id in vf.versions():
            self.add_diff(vf.get_diff(version_id), version_id, vf._parents[version_id])

    def get_build_ranking(self):
        """Return revisions sorted by how much they reduce build complexity."""
        could_avoid = {}
        referenced_by = {}
        for version_id in topo_iter(self):
            could_avoid[version_id] = set()
            if version_id not in self._snapshots:
                for parent_id in self._parents[version_id]:
                    could_avoid[version_id].update(could_avoid[parent_id])
                could_avoid[version_id].update(self._parents)
                could_avoid[version_id].discard(version_id)
            for avoid_id in could_avoid[version_id]:
                referenced_by.setdefault(avoid_id, set()).add(version_id)
        available_versions = list(self.versions())
        ranking = []
        while len(available_versions) > 0:
            available_versions.sort(
                key=lambda x: len(could_avoid[x]) * len(referenced_by.get(x, []))
            )
            selected = available_versions.pop()
            ranking.append(selected)
            for version_id in referenced_by[selected]:
                could_avoid[version_id].difference_update(could_avoid[selected])
            for version_id in could_avoid[selected]:
                referenced_by[version_id].difference_update(referenced_by[selected])
        return ranking

    def clear_cache(self):
        """Clear the cached lines."""
        self._lines.clear()

    def get_line_list(self, version_ids):
        """Get a list of line lists for the given version IDs."""
        return [self.cache_version(v) for v in version_ids]

    def cache_version(self, version_id):
        """Get the lines for a version, caching if necessary."""
        try:
            return self._lines[version_id]
        except KeyError:
            pass
        self.get_diff(version_id)
        lines = []
        reconstructor = _Reconstructor(self, self._lines, self._parents)
        reconstructor.reconstruct_version(lines, version_id)
        self._lines[version_id] = lines
        return lines


class MultiMemoryVersionedFile(BaseVersionedFile):
    """Memory-backed pseudo-versionedfile."""

    def __init__(self, snapshot_interval=25, max_snapshots=None):
        """Initialize a MultiMemoryVersionedFile."""
        BaseVersionedFile.__init__(self, snapshot_interval, max_snapshots)
        self._diffs = {}

    def add_diff(self, diff, version_id, parent_ids):
        """Add a diff to the versioned file."""
        self._diffs[version_id] = diff
        self._parents[version_id] = parent_ids

    def get_diff(self, version_id):
        """Get the diff for a version."""
        try:
            return self._diffs[version_id]
        except KeyError as e:
            raise errors.RevisionNotPresent(version_id, self) from e

    def destroy(self):
        """Clear all diffs."""
        self._diffs = {}


class MultiVersionedFile(BaseVersionedFile):
    """Disk-backed pseudo-versionedfile."""

    def __init__(self, filename, snapshot_interval=25, max_snapshots=None):
        """Initialize a MultiVersionedFile."""
        BaseVersionedFile.__init__(self, snapshot_interval, max_snapshots)
        self._filename = filename
        self._diff_offset = {}

    def get_diff(self, version_id):
        """Get the diff for a version from disk."""
        import gzip

        start, count = self._diff_offset[version_id]
        with open(self._filename + ".mpknit", "rb") as infile:
            infile.seek(start)
            sio = BytesIO(infile.read(count))
        with gzip.GzipFile(None, mode="rb", fileobj=sio) as zip_file:
            zip_file.readline()
            content = zip_file.read()
            return MultiParent.from_patch(content)

    def add_diff(self, diff, version_id, parent_ids):
        """Add a diff to the versioned file on disk."""
        import gzip
        import itertools

        with open(self._filename + ".mpknit", "ab") as outfile:
            outfile.seek(0, 2)  # workaround for windows bug:
            # .tell() for files opened in 'ab' mode
            # before any write returns 0
            start = outfile.tell()
            with gzip.GzipFile(None, mode="ab", fileobj=outfile) as zipfile:
                zipfile.writelines(
                    itertools.chain([b"version %s\n" % version_id], diff.to_patch())
                )
            end = outfile.tell()
        self._diff_offset[version_id] = (start, end - start)
        self._parents[version_id] = parent_ids

    def destroy(self):
        """Remove the files from disk."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._filename + ".mpknit")
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._filename + ".mpidx")

    def save(self):
        """Save the index to disk."""
        import fastbencode as bencode

        with open(self._filename + ".mpidx", "wb") as f:
            f.write(
                bencode.bencode(
                    (self._parents, list(self._snapshots), self._diff_offset)
                )
            )

    def load(self):
        """Load the index from disk."""
        import fastbencode as bencode

        with open(self._filename + ".mpidx", "rb") as f:
            self._parents, snapshots, self._diff_offset = bencode.bdecode(f.read())
        self._snapshots = set(snapshots)


class _Reconstructor:
    """Build a text from the diffs, ancestry graph and cached lines."""

    def __init__(self, diffs, lines, parents):
        self.diffs = diffs
        self.lines = lines
        self.parents = parents
        self.cursor = {}

    def reconstruct(self, lines, parent_text, version_id):
        """Append the lines referred to by a ParentText to lines."""
        parent_id = self.parents[version_id][parent_text.parent]
        end = parent_text.parent_pos + parent_text.num_lines
        return self._reconstruct(lines, parent_id, parent_text.parent_pos, end)

    def _reconstruct(self, lines, req_version_id, req_start, req_end):
        """Append lines for the requested version_id range."""
        # stack of pending range requests
        if req_start == req_end:
            return
        pending_reqs = [(req_version_id, req_start, req_end)]
        while len(pending_reqs) > 0:
            req_version_id, req_start, req_end = pending_reqs.pop()
            # lazily allocate cursors for versions
            if req_version_id in self.lines:
                lines.extend(self.lines[req_version_id][req_start:req_end])
                continue
            try:
                start, end, kind, data, iterator = self.cursor[req_version_id]
            except KeyError:
                iterator = self.diffs.get_diff(req_version_id).range_iterator()
                start, end, kind, data = next(iterator)
            if start > req_start:
                iterator = self.diffs.get_diff(req_version_id).range_iterator()
                start, end, kind, data = next(iterator)

            # find the first hunk relevant to the request
            while end <= req_start:
                start, end, kind, data = next(iterator)
            self.cursor[req_version_id] = start, end, kind, data, iterator
            # if the hunk can't satisfy the whole request, split it in two,
            # and leave the second half for later.
            if req_end > end:
                pending_reqs.append((req_version_id, end, req_end))
                req_end = end
            if kind == "new":
                lines.extend(data[req_start - start : (req_end - start)])
            else:
                # If the hunk is a ParentText, rewrite it as a range request
                # for the parent, and make it the next pending request.
                parent, parent_start, parent_end = data
                new_version_id = self.parents[req_version_id][parent]
                new_start = parent_start + req_start - start
                new_end = parent_end + req_end - end
                pending_reqs.append((new_version_id, new_start, new_end))

    def reconstruct_version(self, lines, version_id):
        length = self.diffs.get_diff(version_id).num_lines()
        return self._reconstruct(lines, version_id, 0, length)


def gzip_string(lines):
    """Compress lines using gzip."""
    import gzip

    sio = BytesIO()
    with gzip.GzipFile(None, mode="wb", fileobj=sio) as data_file:
        data_file.writelines(lines)
    return sio.getvalue()
