# Copyright (C) 2005 by Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# Remaing to do is to figure out if get_graph should return a simple
# map, or a graph object of some kind.


"""Versioned text file storage api."""


class VersionedFile(object):
    """Versioned text file storage.
    
    A versioned file manages versions of line-based text files,
    keeping track of the originating version for each line.

    To clients the "lines" of the file are represented as a list of
    strings. These strings will typically have terminal newline
    characters, but this is not required.  In particular files commonly
    do not have a newline at the end of the file.

    Texts are identified by a version-id string.
    """

    def versions(self):
        """Return a unsorted list of versions."""
        raise NotImplementedError(self.versions)

    def has_version(self, version_id):
        """Returns whether version is present."""
        raise NotImplementedError(self.has_version)

    def add_lines(self, version_id, parents, lines):
        """Add a single text on top of the versioned file.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history.

        Must raise RevisionNotPresent if any of the given parents are
        not present in file history."""
        raise NotImplementedError(self.add_text)

    def clone_text(self, new_version_id, old_version_id, parents,
                   transaction):
        """Add an identical text to old_version_id as new_version_id.

        Must raise RevisionNotPresent if the old version or any of the
        parents are not present in file history.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history."""
        raise NotImplementedError(self.clone_text)

    def get_text(self, version_id):
        """Return version contents as a text string.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return ''.join(self.get_lines(version_id))
    get_string = get_text

    def get_lines(self, version_id):
        """Return version contents as a sequence of lines.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_lines)

    def get_ancestry(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history."""
        if isinstance(version_ids, basestring):
            version_ids = [version_ids]
        raise NotImplementedError(self.get_ancestry)
        
    def get_graph(self, version_id):
        """Return a graph.

        Must raise RevisionNotPresent if version is not present in
        file history."""
        raise NotImplementedError(self.get_graph)

    def get_parents(self, version_id):
        """Return version names for parents of a version.

        Must raise RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_parents)

    def annotate_iter(self, version_id):
        """Yield list of (version-id, line) pairs for the specified
        version.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        """
        raise NotImplementedError(self.annotate_iter)

    def annotate(self, version_id):
        return list(self.annotate_iter(version_id))

    def join(self, other, version_ids, transaction, pb=None):
        """Integrate versions from other into this versioned file.

        If version_ids is None all versions from other should be
        incorporated into this versioned file.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the other files history."""
        raise NotImplementedError(self.join)

    def walk(self, version_ids=None):
        """Walk the versioned file as a weave-like structure, for
        versions relative to version_ids.  Yields sequence of (lineno,
        insert, deletes, text) for each relevant line.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the file history.

        :param version_ids: the version_ids to walk with respect to. If not
                            supplied the entire weave-like structure is walked.
        """
        raise NotImplementedError(self.walk)

    def plan_merge(self, ver_a, ver_b):
        """Return pseudo-annotation indicating how the two versions merge.

        This is computed between versions a and b and their common
        base.

        Weave lines present in none of them are skipped entirely.
        """
        inc_a = set(self.inclusions([ver_a]))
        inc_b = set(self.inclusions([ver_b]))
        inc_c = inc_a & inc_b

        for lineno, insert, deleteset, line in self.walk():
            if deleteset & inc_c:
                # killed in parent; can't be in either a or b
                # not relevant to our work
                yield 'killed-base', line
            elif insert in inc_c:
                # was inserted in base
                killed_a = bool(deleteset & inc_a)
                killed_b = bool(deleteset & inc_b)
                if killed_a and killed_b:
                    yield 'killed-both', line
                elif killed_a:
                    yield 'killed-a', line
                elif killed_b:
                    yield 'killed-b', line
                else:
                    yield 'unchanged', line
            elif insert in inc_a:
                if deleteset & inc_a:
                    yield 'ghost-a', line
                else:
                    # new in A; not in B
                    yield 'new-a', line
            elif insert in inc_b:
                if deleteset & inc_b:
                    yield 'ghost-b', line
                else:
                    yield 'new-b', line
            else:
                # not in either revision
                yield 'irrelevant', line

        yield 'unchanged', ''           # terminator

    def weave_merge(self, plan, a_marker='<<<<<<< \n', b_marker='>>>>>>> \n'):
        lines_a = []
        lines_b = []
        ch_a = ch_b = False
        # TODO: Return a structured form of the conflicts (e.g. 2-tuples for
        # conflicted regions), rather than just inserting the markers.
        # 
        # TODO: Show some version information (e.g. author, date) on 
        # conflicted regions.
        for state, line in plan:
            if state == 'unchanged' or state == 'killed-both':
                # resync and flush queued conflicts changes if any
                if not lines_a and not lines_b:
                    pass
                elif ch_a and not ch_b:
                    # one-sided change:                    
                    for l in lines_a: yield l
                elif ch_b and not ch_a:
                    for l in lines_b: yield l
                elif lines_a == lines_b:
                    for l in lines_a: yield l
                else:
                    yield a_marker
                    for l in lines_a: yield l
                    yield '=======\n'
                    for l in lines_b: yield l
                    yield b_marker

                del lines_a[:]
                del lines_b[:]
                ch_a = ch_b = False
                
            if state == 'unchanged':
                if line:
                    yield line
            elif state == 'killed-a':
                ch_a = True
                lines_b.append(line)
            elif state == 'killed-b':
                ch_b = True
                lines_a.append(line)
            elif state == 'new-a':
                ch_a = True
                lines_a.append(line)
            elif state == 'new-b':
                ch_b = True
                lines_b.append(line)
            else:
                assert state in ('irrelevant', 'ghost-a', 'ghost-b', 'killed-base',
                                 'killed-both'), \
                       state


def plan_merge(file, version_a, version_b):
    """Return pseudo-annotation indicating how the two versions merge.
    
    This is computed between versions a and b and their common
    base.

    Weave lines present in none of them are skipped entirely.
    """
    inc_a = set(file.get_ancestry([version_a]))
    inc_b = set(file.get_ancestry([version_b]))
    inc_c = inc_a & inc_b

    for lineno, insert, deleteset, line in file.walk([version_a, version_b]):
        if deleteset & inc_c:
            # killed in parent; can't be in either a or b
            # not relevant to our work
            yield 'killed-base', line
        elif insert in inc_c:
            # was inserted in base
            killed_a = bool(deleteset & inc_a)
            killed_b = bool(deleteset & inc_b)
            if killed_a and killed_b:
                yield 'killed-both', line
            elif killed_a:
                yield 'killed-a', line
            elif killed_b:
                yield 'killed-b', line
            else:
                yield 'unchanged', line
        elif insert in inc_a:
            if deleteset & inc_a:
                yield 'ghost-a', line
            else:
                # new in A; not in B
                yield 'new-a', line
        elif insert in inc_b:
            if deleteset & inc_b:
                yield 'ghost-b', line
            else:
                yield 'new-b', line
        else:
            # not in either revision
            yield 'irrelevant', line

    yield 'unchanged', ''           # terminator


def weave_merge(plan):
    """Yield merged sequence of lines based on merge plan."""

    lines_a = []
    lines_b = []
    ch_a = ch_b = False

    for state, line in plan:
        if state == 'unchanged' or state == 'killed-both':
            # resync and flush queued conflicts changes if any
            if not lines_a and not lines_b:
                pass
            elif ch_a and not ch_b:
                # one-sided change:                    
                for l in lines_a: yield l
            elif ch_b and not ch_a:
                for l in lines_b: yield l
            elif lines_a == lines_b:
                for l in lines_a: yield l
            else:
                yield '<<<<<<<\n'
                for l in lines_a: yield l
                yield '=======\n'
                for l in lines_b: yield l
                yield '>>>>>>>\n'

            del lines_a[:]
            del lines_b[:]
            ch_a = ch_b = False
                
        if state == 'unchanged':
            if line:
                yield line
        elif state == 'killed-a':
            ch_a = True
            lines_b.append(line)
        elif state == 'killed-b':
            ch_b = True
            lines_a.append(line)
        elif state == 'new-a':
            ch_a = True
            lines_a.append(line)
        elif state == 'new-b':
            ch_b = True
            lines_b.append(line)
        else:
            assert state in ('irrelevant', 'ghost-a', 'ghost-b', 'killed-base',
                             'killed-both'), state
