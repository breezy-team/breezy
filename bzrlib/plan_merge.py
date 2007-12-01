from bzrlib import patiencediff

class PlanMerge(object):
    """Plan an annotate merge using on-the-fly annotation"""

    def __init__(self, a_rev, b_rev, vf):
        self.a_rev = a_rev
        self.b_rev = b_rev
        self.lines_a = vf.get_lines(a_rev)
        self.lines_b = vf.get_lines(b_rev)
        self.vf = vf
        self.uncommon =\
        set(vf.get_ancestry(a_rev)).symmetric_difference(vf.get_ancestry(b_rev))

    def plan_merge(self):
        blocks = self._get_matching_blocks(self.a_rev, self.b_rev)
        new_a = self._find_new(self.a_rev)
        new_b = self._find_new(self.b_rev)
        last_i = 0
        last_j = 0
        a_lines, b_lines = self.vf.get_line_list((self.a_rev, self.b_rev))
        for i, j, n in blocks:
            # determine why lines aren't common
            for a_index in range(last_i, i):
                if a_index in new_a:
                    cause = 'new-a'
                else:
                    cause = 'killed-b'
                yield cause, a_lines[a_index]
            for b_index in range(last_j, j):
                if b_index in new_b:
                    cause = 'new-b'
                else:
                    cause = 'killed-a'
                yield cause, b_lines[b_index]
            # handle common lines
            for a_index in range(i, i+n):
                yield 'unchanged', a_lines[a_index]
            last_i = i+n
            last_j = j+n

    def _get_matching_blocks(self, left_revision, right_revision):
        left_lines = self.vf.get_lines(left_revision)
        right_lines = self.vf.get_lines(right_revision)
        matcher = patiencediff.PatienceSequenceMatcher(None, left_lines,
                                                       right_lines)
        return matcher.get_matching_blocks()

    def _unique_lines(self, matching_blocks):
        last_i = 0
        last_j = 0
        unique_left = []
        unique_right = []
        for i, j, n in matching_blocks:
            unique_left.extend(range(last_i, i))
            unique_right.extend(range(last_j, j))
            last_i = i + n
            last_j = j + n
        return unique_left, unique_right

    def _find_new(self, version_id):
        """Determine which lines are new in the ancestry of this version.
        
        If a lines is present in this version, and not present in any
        common ancestor, it is considered new.
        """
        if version_id not in self.uncommon:
            return set()
        parents = self.vf.get_parents(version_id)
        if len(parents) == 0:
            return set(range(len(self.vf.get_lines(version_id))))
        new = None
        for parent in parents:
            blocks = self._get_matching_blocks(version_id, parent)
            result, unused = self._unique_lines(blocks)
            parent_new = self._find_new(parent)
            for i, j, n in blocks:
                for ii, jj in [(i+r, j+r) for r in range(n)]:
                    if jj in parent_new:
                        result.append(ii)
            if new is None:
                new = set(result)
            else:
                new.intersection_update(result)
        return new
