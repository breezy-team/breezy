from difflib import SequenceMatcher
from StringIO import StringIO
import sys

from bzrlib import (
    patiencediff,
    trace,
    ui,
    )

from bzrlib.tuned_gzip import GzipFile

class MultiParent(object):

    def __init__(self, hunks=None):
        if hunks is not None:
            self.hunks = hunks
        else:
            self.hunks = []

    def __repr__(self):
        return "MultiParent(%r)" % self.hunks

    def __eq__(self, other):
        if self.__class__ is not other.__class__:
            return False
        return (self.hunks == other.hunks)

    @staticmethod
    def from_lines(text, parents=()):
        """Produce a MultiParent from a list of lines and parents"""
        def compare(parent):
            matcher = patiencediff.PatienceSequenceMatcher(None, parent,
                                                           text)
            return matcher.get_matching_blocks()
        parent_comparisons = [compare(p) for p in parents]
        cur_line = 0
        new_text = NewText([])
        parent_text = []
        block_iter = [iter(i) for i in parent_comparisons]
        diff = MultiParent([])
        def next_block(p):
            try:
                return block_iter[p].next()
            except StopIteration:
                return None
        cur_block = [next_block(p) for p, i in enumerate(block_iter)]
        while cur_line < len(text):
            best_match = None
            for p, block in enumerate(cur_block):
                if block is None:
                    continue
                i, j, n = block
                while j + n < cur_line:
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

    @classmethod
    def from_texts(cls, text, parents=()):
        """Produce a MultiParent from a text and list of parent text"""
        return cls.from_lines(text.splitlines(True),
                              [p.splitlines(True) for p in parents])

    def to_patch(self):
        """Yield text lines for a patch"""
        for hunk in self.hunks:
            for line in hunk.to_patch():
                yield line

    def patch_len(self):
        return len(''.join(self.to_patch()))

    def zipped_patch_len(self):
        return len(gzip_string(self.to_patch()))

    @staticmethod
    def from_patch(lines):
        """Produce a MultiParent from a sequence of lines"""
        line_iter = iter(lines)
        hunks = []
        cur_line = None
        while(True):
            try:
                cur_line = line_iter.next()
            except StopIteration:
                break
            if cur_line[0] == 'i':
                num_lines = int(cur_line.split(' ')[1])
                hunk_lines = [line_iter.next() for x in xrange(num_lines)]
                hunk_lines[-1] = hunk_lines[-1][:-1]
                hunks.append(NewText(hunk_lines))
            elif cur_line[0] == '\n':
                hunks[-1].lines[-1] += '\n'
            else:
                assert cur_line[0] == 'c', cur_line[0]
                parent, parent_pos, child_pos, num_lines =\
                    [int(v) for v in cur_line.split(' ')[1:]]
                hunks.append(ParentText(parent, parent_pos, child_pos,
                                        num_lines))
        return MultiParent(hunks)

    def range_iterator(self):
        """Iterate through the hunks, with range indicated

        kind is "new" or "parent".
        for "new", data is a list of lines.
        for "parent", data is (parent, parent_start, parent_end)
        :return: a generator of (start, end, kind, data)
        """
        start = 0
        for hunk in self.hunks:
            if isinstance(hunk, NewText):
                kind = 'new'
                end = start + len(hunk.lines)
                data = hunk.lines
            else:
                kind = 'parent'
                start = hunk.child_pos
                end = start + hunk.num_lines
                data = (hunk.parent, hunk.parent_pos, hunk.parent_pos +
                        hunk.num_lines)
            yield start, end, kind, data
            start = end

    def num_lines(self):
        extra_n = 0
        for hunk in reversed(self.hunks):
            if isinstance(hunk, ParentText):
               return hunk.child_pos + hunk.num_lines + extra_n
            extra_n += len(hunk.lines)
        return extra_n

    def is_snapshot(self):
        if len(self.hunks) != 1:
            return False
        return (isinstance(self.hunks[0], NewText))


class NewText(object):
    """The contents of text that is introduced by this text"""

    def __init__(self, lines):
        self.lines = lines

    def __eq__(self, other):
        if self.__class__ is not other.__class__:
            return False
        return (other.lines == self.lines)

    def __repr__(self):
        return 'NewText(%r)' % self.lines

    def to_patch(self):
        yield 'i %d\n' % len(self.lines)
        for line in self.lines:
            yield line
        yield '\n'


class ParentText(object):
    """A reference to text present in a parent text"""

    def __init__(self, parent, parent_pos, child_pos, num_lines):
        self.parent = parent
        self.parent_pos = parent_pos
        self.child_pos = child_pos
        self.num_lines = num_lines

    def __repr__(self):
        return 'ParentText(%(parent)r, %(parent_pos)r, %(child_pos)r,'\
            ' %(num_lines)r)' % self.__dict__

    def __eq__(self, other):
        if self.__class__ != other.__class__:
            return False
        return (self.__dict__ == other.__dict__)

    def to_patch(self):
        yield 'c %(parent)d %(parent_pos)d %(child_pos)d %(num_lines)d\n'\
            % self.__dict__


class MultiVersionedFile(object):
    """VersionedFile skeleton for MultiParent"""

    def __init__(self, snapshot_interval=25, max_snapshots=None):
        self._diffs = {}
        self._lines = {}
        self._parents = {}
        self._snapshots = set()
        self.snapshot_interval = snapshot_interval
        self.max_snapshots = max_snapshots

    def do_snapshot(self, version_id, parent_ids):
        if self.snapshot_interval is None:
            return False
        if self.max_snapshots is not None and\
            len(self._snapshots) == self.max_snapshots:
            return False
        if len(parent_ids) == 0:
            return True
        for ignored in xrange(self.snapshot_interval):
            if len(parent_ids) == 0:
                return False
            version_ids = parent_ids
            parent_ids = []
            for version_id in version_ids:
                if version_id not in self._snapshots:
                    parent_ids.extend(self._parents[version_id])
        else:
            return True

    def add_version(self, lines, version_id, parent_ids,
                    force_snapshot=None, single_parent=False):
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
            snapdiff = MultiParent([NewText(lines)])
            if diff.is_snapshot():
                self._snapshots.add(version_id)
            elif diff.patch_len() >= snapdiff.patch_len():
                trace.note("Forcing snapshot")
                self._snapshots.add(version_id)
        self.add_diff(diff, version_id, parent_ids)
        self._lines[version_id] = lines

    def add_diff(self, diff, version_id, parent_ids):
        self._diffs[version_id] = diff
        self._parents[version_id] = parent_ids

    def import_versionedfile(self, vf, snapshots, no_cache=True,
                             single_parent=False, verify=False):
        """Import all revisions of a versionedfile

        :param vf: The versionedfile to import
        :param snapshots: If provided, the revisions to make snapshots of.
            Otherwise, this will be auto-determined
        :param no_cache: If true, clear the cache after every add.
        :param single_parent: If true, omit all but one parent text, (but
            retain parent metadata).
        """
        assert no_cache or not verify
        revisions = set(vf.versions())
        total = len(revisions)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            while len(revisions) > 0:
                added = set()
                for revision in revisions:
                    parents = vf.get_parents(revision)
                    if [p for p in parents if p not in self._diffs] != []:
                        continue
                    lines = [a + ' ' + l for a, l in
                             vf.annotate_iter(revision)]
                    if snapshots is None:
                        force_snapshot = None
                    else:
                        force_snapshot = (revision in snapshots)
                    self.add_version(lines, revision, parents, force_snapshot,
                                     single_parent)
                    added.add(revision)
                    if no_cache:
                        self.clear_cache()
                        vf.clear_cache()
                        if verify:
                            assert lines == self.get_line_list([revision])[0]
                            self.clear_cache()
                    pb.update('Importing revisions',
                              (total - len(revisions)) + len(added), total)
                revisions = [r for r in revisions if r not in added]
        finally:
            pb.finished()

    def select_snapshots(self, vf):
        distances = {}
        descendants = {}
        snapshots = set()
        for version_id in vf.versions():
            for parent_id in vf.get_parents(version_id):
                descendants.setdefault(parent_id, []).append(version_id)
        cur = [v for v in vf.versions() if len(vf.get_parents(v)) == 0]
        while len(cur) > 0:
            next = []
            for version_id in cur:
                if version_id in distances:
                    continue
                parents = vf.get_parents(version_id)
                p_distances = [distances.get(p) for p in parents]
                if None in p_distances:
                    continue
                next.extend(descendants.get(version_id, []))
                if len(p_distances) == 0:
                    snapshots.add(version_id)
                    distances[version_id] = 0
                else:
                    max_distance = max(p_distances)
                    if max_distance + 1 > self.snapshot_interval:
                        snapshots.add(version_id)
                        distances[version_id] = 0
                    elif len(descendants) > 1 and max_distance > \
                        self.snapshot_interval -4 and False:
                        snapshots.add(version_id)
                        distances[version_id] = 0
                    else:
                        distances[version_id] = max_distance + 1
            cur = next
        return snapshots


    def clear_cache(self):
        self._lines.clear()

    def get_line_list(self, version_ids):
        return [self.cache_version(v) for v in version_ids]

    def cache_version(self, version_id):
        try:
            return self._lines[version_id]
        except KeyError:
            pass
        diff = self._diffs[version_id]
        lines = []
        reconstructor = _Reconstructor(self._diffs, self._lines,
                                       self._parents)
        reconstructor.reconstruct_version(lines, version_id)
        #self._lines[version_id] = lines
        return lines


class _Reconstructor(object):
    """Build a text from the diffs, ancestry graph and cached lines"""

    def __init__(self, diffs, lines, parents):
        self.diffs = diffs
        self.lines = lines
        self.parents = parents
        self.cursor = {}

    def reconstruct(self, lines, parent_text, version_id):
        """Append the lines referred to by a ParentText to lines"""
        parent_id = self.parents[version_id][parent_text.parent]
        end = parent_text.parent_pos + parent_text.num_lines
        return self._reconstruct(lines, parent_id, parent_text.parent_pos,
                                 end)

    def _reconstruct(self, lines, req_version_id, req_start, req_end):
        """Append lines for the requested version_id range"""
        # stack of pending range requests
        pending_reqs = [(req_version_id, req_start, req_end)]
        while len(pending_reqs) > 0:
            req_version_id, req_start, req_end = pending_reqs.pop()
            # lazily allocate cursors for versions
            try:
                start, end, kind, data, iterator = self.cursor[req_version_id]
            except KeyError:
                iterator = self.diffs[req_version_id].range_iterator()
                start, end, kind, data = iterator.next()
            if start > req_start:
                iterator = self.diffs[req_version_id].range_iterator()
                start, end, kind, data = iterator.next()

            # find the first hunk relevant to the request
            while end <= req_start:
                start, end, kind, data = iterator.next()
            self.cursor[req_version_id] = start, end, kind, data, iterator
            # if the hunk can't satisfy the whole request, split it in two,
            # and leave the second half for later.
            if req_end > end:
                pending_reqs.append((req_version_id, end, req_end))
                req_end = end
            if kind == 'new':
                lines.extend(data[req_start - start: (req_end - start)])
            else:
                # If the hunk is a ParentText, rewrite it as a range request
                # for the parent, and make it the next pending request.
                parent, parent_start, parent_end = data
                new_version_id = self.parents[req_version_id][parent]
                new_start = parent_start + req_start - start
                new_end = parent_end + req_end - end
                pending_reqs.append((new_version_id, new_start, new_end))

    def reconstruct_version(self, lines, version_id):
        length = self.diffs[version_id].num_lines()
        return self._reconstruct(lines, version_id, 0, length)

def gzip_string(lines):
    sio = StringIO()
    data_file = GzipFile(None, mode='wb', fileobj=sio)
    data_file.writelines(lines)
    data_file.close()
    return sio.getvalue()
