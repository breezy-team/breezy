from difflib import SequenceMatcher


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
            return SequenceMatcher(None, parent, text).get_matching_blocks()
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

    def __init__(self, snapshot_interval=25):
        self._diffs = {}
        self._lines = {}
        self._parents = {}
        self._snapshots = {}
        self.snapshot_interval = snapshot_interval

    def do_snapshot(self, version_id, parent_ids):
        if len(parent_ids) == 0:
            return False
        counter = 0
        while counter < self.snapshot_interval:
            if len(parent_ids) == 0:
                return False
            version_id = parent_ids[0]
            if self._snapshots[version_id]:
                return False
            counter += 1
            parent_ids = self._parents[version_id]
        return True

    def add_version(self, lines, version_id, parent_ids):
        if self.do_snapshot(version_id, parent_ids):
            self._snapshots[version_id] = True
            diff = MultiParent([NewText(lines)])
        else:
            self._snapshots[version_id] = False
            parent_lines = [self._lines[p] for p in parent_ids]
            diff = MultiParent.from_lines(lines, parent_lines)
        self.add_diff(diff, version_id, parent_ids)
        self._lines[version_id] = lines

    def add_diff(self, diff, version_id, parent_ids):
        self._diffs[version_id] = diff
        self._parents[version_id] = parent_ids

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
        reconstructor = _Reconstructor(self._diffs, self._lines, self._parents)
        reconstructor.reconstruct_version(lines, version_id)
        self._lines[version_id] = lines
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
        return self._reconstruct(lines, parent_id, parent_text.parent_pos, end)

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
