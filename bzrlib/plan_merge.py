# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib import errors, patiencediff, revision


class PlanMerge(object):
    """Plan an annotate merge using on-the-fly annotation"""

    def __init__(self, a_rev, b_rev, vf):
        """Contructor.

        :param a_rev: Revision-id of one revision to merge
        :param b_rev: Revision-id of the other revision to merge
        :param vf: A versionedfile containing both revisions
        """
        self.a_rev = a_rev
        self.b_rev = b_rev
        self.lines_a = vf.get_lines(a_rev)
        self.lines_b = vf.get_lines(b_rev)
        self.vf = vf
        a_ancestry = set(vf.get_ancestry(a_rev))
        b_ancestry = set(vf.get_ancestry(b_rev))
        self.uncommon = a_ancestry.symmetric_difference(b_ancestry)

    def plan_merge(self):
        """Generate a 'plan' for merging the two revisions.

        This involves comparing their texts and determining the cause of
        differences.  If text A has a line and text B does not, then either the
        line was added to text A, or it was deleted from B.  Once the causes
        are combined, they are written out in the format described in
        VersionedFile.plan_merge
        """
        blocks = self._get_matching_blocks(self.a_rev, self.b_rev)
        new_a = self._find_new(self.a_rev)
        new_b = self._find_new(self.b_rev)
        last_i = 0
        last_j = 0
        a_lines = self.vf.get_lines(self.a_rev)
        b_lines = self.vf.get_lines(self.b_rev)
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
        """Return a description of which sections of two revisions match.

        See SequenceMatcher.get_matching_blocks
        """
        left_lines = self.vf.get_lines(left_revision)
        right_lines = self.vf.get_lines(right_revision)
        matcher = patiencediff.PatienceSequenceMatcher(None, left_lines,
                                                       right_lines)
        return matcher.get_matching_blocks()

    def _unique_lines(self, matching_blocks):
        """Analyse matching_blocks to determine which lines are unique

        :return: a tuple of (unique_left, unique_right), where the values are
            sets of line numbers of unique lines.
        """
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


class _PlanMergeVersionedFile(object):
    """A VersionedFile for uncommitted and committed texts.

    It is intended to allow merges to be planned with working tree texts.
    It implements only the small part of the VersionedFile interface used by
    PlanMerge.  It falls back to multiple versionedfiles for data not stored in
    _PlanMergeVersionedFile itself.
    """

    def __init__(self, file_id, fallback_versionedfiles=None):
        """Constuctor

        :param file_id: Used when raising exceptions.
        :param fallback_versionedfiles: If supplied, the set of fallbacks to
            use.  Otherwise, _PlanMergeVersionedFile.fallback_versionedfiles
            can be appended to later.
        """
        self._file_id = file_id
        if fallback_versionedfiles is None:
            self.fallback_versionedfiles = []
        else:
            self.fallback_versionedfiles = fallback_versionedfiles
        self._parents = {}
        self._lines = {}

    def add_lines(self, version_id, parents, lines):
        """See VersionedFile.add_lines

        Lines are added locally, not fallback versionedfiles.  Also, ghosts are
        permitted.  Only reserved ids are permitted.
        """
        if not revision.is_reserved_id(version_id):
            raise ValueError('Only reserved ids may be used')
        if parents is None:
            raise ValueError('Parents may not be None')
        if lines is None:
            raise ValueError('Lines may not be None')
        self._parents[version_id] = parents
        self._lines[version_id] = lines

    def get_lines(self, version_id):
        """See VersionedFile.get_ancestry"""
        lines = self._lines.get(version_id)
        if lines is not None:
            return lines
        for versionedfile in self.fallback_versionedfiles:
            try:
                return versionedfile.get_lines(version_id)
            except errors.RevisionNotPresent:
                continue
        else:
            raise errors.RevisionNotPresent(version_id, self._file_id)

    def get_ancestry(self, version_id):
        """See VersionedFile.get_ancestry.

        Note that this implementation assumes that if a VersionedFile can
        answer get_ancestry at all, it can give an authoritative answer.  In
        fact, ghosts can invalidate this assumption.  But it's good enough
        99% of the time, and far cheaper/simpler.

        Also note that the results of this version are never topologically
        sorted, and are a set.
        """
        parents = self._parents.get(version_id)
        if parents is None:
            for vf in self.fallback_versionedfiles:
                try:
                    return vf.get_ancestry(version_id)
                except errors.RevisionNotPresent:
                    continue
            else:
                raise errors.RevisionNotPresent(version_id, self._file_id)
        ancestry = set([version_id])
        for parent in parents:
            ancestry.update(self.get_ancestry(parent))
        return ancestry

    def get_parents(self, version_id):
        """See VersionedFile.get_parents"""
        parents = self._parents.get(version_id)
        if parents is not None:
            return parents
        for versionedfile in self.fallback_versionedfiles:
            try:
                return versionedfile.get_parents(version_id)
            except errors.RevisionNotPresent:
                continue
        else:
            raise errors.RevisionNotPresent(version_id, self._file_id)
