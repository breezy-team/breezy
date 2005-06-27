#! /usr/bin/python

# Copyright (C) 2005 Canonical Ltd

# GNU GPL v2

# Author: Martin Pool <mbp@canonical.com>


"""knit - a weave-like structure"""


class VerInfo(object):
    included = frozenset()
    def __init__(self, included=None):
        if included:
            self.included = frozenset(included)

    def __repr__(self):
        s = self.__class__.__name__ + '('
        if self.included:
            s += 'included=%r' % (list(self.included))
        s += ')'
        return s


class Knit(object):
    """knit - versioned text file storage.
    
    A Knit manages versions of line-based text files, keeping track of the
    originating version for each line.

    Texts can be identified in either of two ways:

    * a nonnegative index number.

    * a version-id string.

    Typically the index number will be valid only inside this knit and
    the version-id is used to reference it in the larger world.

    _l
        List of edit instructions.

        Each line is stored as a tuple of (index-id, text).  The line
        is present in the version equal to index-id.

    _v
        List of versions, indexed by index number.

        For each version we store the tuple (included_versions), which
        lists the previous versions also considered active.
    """
    def __init__(self):
        self._l = []
        self._v = []

        
    def add(self, text, basis=None):
        """Add a single text on top of the weave.

        Returns the index number of the newly added version."""
        if not isinstance(text, list):
            raise ValueError("text should be a list, not %s" % type(text))

        idx = len(self._v)

        if basis:
            basis = frozenset(basis)
            delta = self._delta(basis, text)

            for i1, i2, newlines in delta:
                # TODO: handle lines being offset as we insert stuff
                if i1 != i2:
                    raise NotImplementedError("can't handle replacing weave lines %d-%d yet"
                                              % (i1, i2))

                # a pure insertion
                to_insert = []
                for line in newlines:
                    to_insert.append((idx, line))
                
                self._l[i1:i1] = to_insert

            self._v.append(VerInfo(basis))
        else:
            # special case; adding with no basis revision; can do this
            # more quickly by just appending unconditionally
            for line in text:
                self._l.append((idx, line))

            self._v.append(VerInfo())
            
        return idx

    
    def annotate(self, index):
        return list(self.annotate_iter(index))


    def annotate_iter(self, index):
        """Yield list of (index-id, line) pairs for the specified version.

        The index indicates when the line originated in the weave."""
        try:
            vi = self._v[index]
        except IndexError:
            raise IndexError('version index %d out of range' % index)
        included = set(vi.included)
        included.add(index)
        return iter(self._extract(included))


    def _extract(self, included):
        """Yield annotation of lines in included set.

        The set typically but not necessarily corresponds to a version.
        """
        for origin, line in self._l:
            if origin in included:
                yield origin, line
        


    def getiter(self, index):
        """Yield lines for the specified version."""
        for origin, line in self.annotate_iter(index):
            yield line


    def get(self, index):
        return list(self.getiter(index))


    def dump(self, to_file):
        from pprint import pprint
        print >>to_file, "Knit._l = ",
        pprint(self._l, to_file)
        print >>to_file, "Knit._v = ",
        pprint(self._v, to_file)


    def check(self):
        for vers_info in self._v:
            included = set()
            for vi in vers_info[0]:
                if vi < 0 or vi >= index:
                    raise ValueError("invalid included version %d for index %d"
                                     % (vi, index))
                if vi in included:
                    raise ValueError("repeated included version %d for index %d"
                                     % (vi, index))
                included.add(vi)



    def _delta(self, included, lines):
        """Return changes from basis to new revision.

        The old text for comparison is the union of included revisions.

        This is used in inserting a new text.

        Delta is returned as a sequence of (line1, line2, newlines),
        indicating that line1 through line2 of the old weave should be
        replaced by the sequence of lines in newlines.  Note that
        these line numbers are positions in the total weave and don't
        correspond to the lines in any extracted version, or even the
        extracted union of included versions.

        If line1=line2, this is a pure insert; if newlines=[] this is a
        pure delete.  (Similar to difflib.)
        """

        ##from pprint import pprint

        # first get basis for comparison
        # basis holds (lineno, origin, line)
        basis = []

        ##print 'my lines:'
        ##pprint(self._l)
        
        lineno = 0
        for origin, line in self._l:
            if origin in included:
                basis.append((lineno, line))
            lineno += 1

        assert lineno == len(self._l)

        # now make a parallel list with only the text, to pass to the differ
        basis_lines = [line for (lineno, line) in basis]

        # add a sentinal, because we can also match against the final line
        basis.append((len(self._l), None))

        # XXX: which line of the weave should we really consider matches the end of the file?
        # the current code says it's the last line of the weave?

        from difflib import SequenceMatcher
        s = SequenceMatcher(None, basis_lines, lines)

        ##print 'basis sequence:'
        ##pprint(basis)

        for tag, i1, i2, j1, j2 in s.get_opcodes():
            ##print tag, i1, i2, j1, j2

            if tag == 'equal':
                continue

            # i1,i2 are given in offsets within basis_lines; we need to map them
            # back to offsets within the entire weave
            real_i1 = basis[i1][0]
            real_i2 = basis[i2][0]

            # find the text identified by j:
            if j1 == j2:
                newlines = []
            else:
                assert 0 <= j1
                assert j1 <= j2
                assert j2 <= len(lines)
                newlines = lines[j1:j2]

            yield real_i1, real_i2, newlines


def update_knit(knit, new_vers, new_lines):
    """Return a new knit whose text matches new_lines.

    First of all the knit is diffed against the new lines, considering
    only the text of the lines from the knit.  This identifies lines
    unchanged from the knit, plus insertions and deletions.

    The deletions are marked as deleted.  The insertions are added
    with their new values.

    
    """
    if not isinstance(new_vers, int):
        raise TypeError('new version-id must be an int: %r' % new_vers)
    
    from difflib import SequenceMatcher
    knit_lines = knit2text(knit)
    m = SequenceMatcher(None, knit_lines, new_lines)

    for block in m.get_matching_blocks():
        print "a[%d] and b[%d] match for %d elements" % block
    
    new_knit = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        print ("%7s a[%d:%d] (%s) b[%d:%d] (%s)" %
               (tag, i1, i2, knit_lines[i1:i2], j1, j2, new_lines[j1:j2]))

        if tag == 'equal':
            new_knit.extend(knit[i1:i2])
        elif tag == 'delete':
            for i in range(i1, i2):
                kl = knit[i]
                new_knit.append((kl[0], kl[1], False))

    return new_knit
        

