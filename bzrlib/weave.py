#! /usr/bin/python

# Copyright (C) 2005 Canonical Ltd

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

# Author: Martin Pool <mbp@canonical.com>


"""Weave - storage of related text file versions"""

# before intset (r923) 2000 versions in 41.5s
# with intset (r926) 2000 versions in 93s !!!
# better to just use plain sets.

# making _extract build and return a list, rather than being a generator
# takes 37.94s

# with python -O, r923 does 2000 versions in 36.87s

# with optimizations to avoid mutating lists - 35.75!  I guess copying
# all the elements every time costs more than the small manipulations.
# a surprisingly small change.

# r931, which avoids using a generator for extract, does 36.98s

# with memoized inclusions, takes 41.49s; not very good

# with slots, takes 37.35s; without takes 39.16, a bit surprising

# with the delta calculation mixed in with the add method, rather than
# separated, takes 36.78s

# with delta folded in and mutation of the list, 36.13s

# with all this and simplification of add code, 33s





# TODO: Perhaps have copy method for Weave instances?

# XXX: If we do weaves this way, will a merge still behave the same
# way if it's done in a different order?  That's a pretty desirable
# property.

# TODO: Nothing here so far assumes the lines are really \n newlines,
# rather than being split up in some other way.  We could accomodate
# binaries, perhaps by naively splitting on \n or perhaps using
# something like a rolling checksum.

# TODO: End marker for each version so we can stop reading?

# TODO: Check that no insertion occurs inside a deletion that was
# active in the version of the insertion.

# TODO: In addition to the SHA-1 check, perhaps have some code that
# checks structural constraints of the weave: ie that insertions are
# properly nested, that there is no text outside of an insertion, that
# insertions or deletions are not repeated, etc.

# TODO: Parallel-extract that passes back each line along with a
# description of which revisions include it.  Nice for checking all
# shas in parallel.

# TODO: Using a single _extract routine and then processing the output
# is probably inefficient.  It's simple enough that we can afford to
# have slight specializations for different ways its used: annotate,
# basis for add, get, etc.

# TODO: Perhaps the API should work only in names to hide the integer
# indexes from the user?



import sha



class WeaveError(Exception):
    """Exception in processing weave"""


class WeaveFormatError(WeaveError):
    """Weave invariant violated"""
    

class Weave(object):
    """weave - versioned text file storage.
    
    A Weave manages versions of line-based text files, keeping track
    of the originating version for each line.

    To clients the "lines" of the file are represented as a list of strings.
    These strings  will typically have terminal newline characters, but
    this is not required.  In particular files commonly do not have a newline
    at the end of the file.

    Texts can be identified in either of two ways:

    * a nonnegative index number.

    * a version-id string. (not implemented yet)

    Typically the index number will be valid only inside this weave and
    the version-id is used to reference it in the larger world.

    The weave is represented as a list mixing edit instructions and
    literal text.  Each entry in _weave can be either a string (or
    unicode), or a tuple.  If a string, it means that the given line
    should be output in the currently active revisions.

    If a tuple, it gives a processing instruction saying in which
    revisions the enclosed lines are active.  The tuple has the form
    (instruction, version).

    The instruction can be '{' or '}' for an insertion block, and '['
    and ']' for a deletion block respectively.  The version is the
    integer version index.  There is no replace operator, only deletes
    and inserts.  For '}', the end of an insertion, there is no
    version parameter because it always closes the most recently
    opened insertion.

    Constraints/notes:

    * A later version can delete lines that were introduced by any
      number of ancestor versions; this implies that deletion
      instructions can span insertion blocks without regard to the
      insertion block's nesting.

    * Similarly, deletions need not be properly nested with regard to
      each other, because they might have been generated by
      independent revisions.

    * Insertions are always made by inserting a new bracketed block
      into a single point in the previous weave.  This implies they
      can nest but not overlap, and the nesting must always have later
      insertions on the inside.

    * It doesn't seem very useful to have an active insertion
      inside an inactive insertion, but it might happen.
      
    * Therefore, all instructions are always"considered"; that
      is passed onto and off the stack.  An outer inactive block
      doesn't disable an inner block.

    * Lines are enabled if the most recent enclosing insertion is
      active and none of the enclosing deletions are active.

    * There is no point having a deletion directly inside its own
      insertion; you might as well just not write it.  And there
      should be no way to get an earlier version deleting a later
      version.

    _weave
        Text of the weave; list of control instruction tuples and strings.

    _parents
        List of parents, indexed by version number.
        It is only necessary to store the minimal set of parents for
        each version; the parent's parents are implied.

    _sha1s
        List of hex SHA-1 of each version.

    _names
        List of symbolic names for each version.  Each should be unique.

    _name_map
        For each name, the version number.
    """

    __slots__ = ['_weave', '_parents', '_sha1s', '_names', '_name_map']
    
    def __init__(self):
        self._weave = []
        self._parents = []
        self._sha1s = []
        self._names = []
        self._name_map = {}


    def __eq__(self, other):
        if not isinstance(other, Weave):
            return False
        return self._parents == other._parents \
               and self._weave == other._weave \
               and self._sha1s == other._sha1s 

    
    def __ne__(self, other):
        return not self.__eq__(other)


    def lookup(self, name):
        try:
            return self._name_map[name]
        except KeyError:
            raise WeaveError("name %s not present in weave" % name)

        
    def add(self, name, parents, text):
        """Add a single text on top of the weave.
  
        Returns the index number of the newly added version.

        name
            Symbolic name for this version.
            (Typically the revision-id of the revision that added it.)

        parents
            List or set of direct parent version numbers.
            
        text
            Sequence of lines to be added in the new version."""

        assert isinstance(name, basestring)
        if name in self._name_map:
            raise WeaveError("name %r already present in weave" % name)
        
        self._check_versions(parents)
        ## self._check_lines(text)
        new_version = len(self._parents)

        s = sha.new()
        map(s.update, text)
        sha1 = s.hexdigest()
        del s

        # if we abort after here the (in-memory) weave will be corrupt because only
        # some fields are updated
        self._parents.append(parents[:])
        self._sha1s.append(sha1)
        self._names.append(name)
        self._name_map[name] = new_version

            
        if not parents:
            # special case; adding with no parents revision; can do
            # this more quickly by just appending unconditionally.
            # even more specially, if we're adding an empty text we
            # need do nothing at all.
            if text:
                self._weave.append(('{', new_version))
                self._weave.extend(text)
                self._weave.append(('}', None))
        
            return new_version

        if len(parents) == 1:
            pv = list(parents)[0]
            if sha1 == self._sha1s[pv]:
                # special case: same as the single parent
                return new_version
            

        ancestors = self.inclusions(parents)

        l = self._weave

        # basis a list of (origin, lineno, line)
        basis_lineno = []
        basis_lines = []
        for origin, lineno, line in self._extract(ancestors):
            basis_lineno.append(lineno)
            basis_lines.append(line)

        # another small special case: a merge, producing the same text
        # as auto-merge
        if text == basis_lines:
            return new_version            

        # add a sentinal, because we can also match against the final line
        basis_lineno.append(len(self._weave))

        # XXX: which line of the weave should we really consider
        # matches the end of the file?  the current code says it's the
        # last line of the weave?

        #print 'basis_lines:', basis_lines
        #print 'new_lines:  ', lines

        from difflib import SequenceMatcher
        s = SequenceMatcher(None, basis_lines, text)

        # offset gives the number of lines that have been inserted
        # into the weave up to the current point; if the original edit instruction
        # says to change line A then we actually change (A+offset)
        offset = 0

        for tag, i1, i2, j1, j2 in s.get_opcodes():
            # i1,i2 are given in offsets within basis_lines; we need to map them
            # back to offsets within the entire weave
            #print 'raw match', tag, i1, i2, j1, j2
            if tag == 'equal':
                continue

            i1 = basis_lineno[i1]
            i2 = basis_lineno[i2]

            assert 0 <= j1 <= j2 <= len(text)

            #print tag, i1, i2, j1, j2

            # the deletion and insertion are handled separately.
            # first delete the region.
            if i1 != i2:
                self._weave.insert(i1+offset, ('[', new_version))
                self._weave.insert(i2+offset+1, (']', new_version))
                offset += 2

            if j1 != j2:
                # there may have been a deletion spanning up to
                # i2; we want to insert after this region to make sure
                # we don't destroy ourselves
                i = i2 + offset
                self._weave[i:i] = ([('{', new_version)] 
                                    + text[j1:j2] 
                                    + [('}', None)])
                offset += 2 + (j2 - j1)

        return new_version


    def inclusions(self, versions):
        """Return set of all ancestors of given version(s)."""
        i = set(versions)
        v = max(versions)
        try:
            while v >= 0:
                if v in i:
                    # include all its parents
                    i.update(self._parents[v])
                v -= 1
            return i
        except IndexError:
            raise ValueError("version %d not present in weave" % v)


    def minimal_parents(self, version):
        """Find the minimal set of parents for the version."""
        included = self._parents[version]
        if not included:
            return []
        
        li = list(included)
        li.sort(reverse=True)

        mininc = []
        gotit = set()

        for pv in li:
            if pv not in gotit:
                mininc.append(pv)
                gotit.update(self.inclusions(pv))

        assert mininc[0] >= 0
        assert mininc[-1] < version
        return mininc



    def _check_lines(self, text):
        if not isinstance(text, list):
            raise ValueError("text should be a list, not %s" % type(text))

        for l in text:
            if not isinstance(l, basestring):
                raise ValueError("text line should be a string or unicode, not %s"
                                 % type(l))
        


    def _check_versions(self, indexes):
        """Check everything in the sequence of indexes is valid"""
        for i in indexes:
            try:
                self._parents[i]
            except IndexError:
                raise IndexError("invalid version number %r" % i)

    
    def annotate(self, index):
        return list(self.annotate_iter(index))


    def annotate_iter(self, version):
        """Yield list of (index-id, line) pairs for the specified version.

        The index indicates when the line originated in the weave."""
        for origin, lineno, text in self._extract([version]):
            yield origin, text


    def _walk(self):
        """Walk the weave.

        Yields sequence of
        (lineno, insert, deletes, text)
        for each literal line.
        """
        
        istack = []
        dset = set()

        lineno = 0         # line of weave, 0-based

        for l in self._weave:
            if isinstance(l, tuple):
                c, v = l
                isactive = None
                if c == '{':
                    istack.append(v)
                elif c == '}':
                    istack.pop()
                elif c == '[':
                    assert v not in dset
                    dset.add(v)
                elif c == ']':
                    dset.remove(v)
                else:
                    raise WeaveFormatError('unexpected instruction %r'
                                           % v)
            else:
                assert isinstance(l, basestring)
                assert istack
                yield lineno, istack[-1], dset, l
            lineno += 1



    def _extract(self, versions):
        """Yield annotation of lines in included set.

        Yields a sequence of tuples (origin, lineno, text), where
        origin is the origin version, lineno the index in the weave,
        and text the text of the line.

        The set typically but not necessarily corresponds to a version.
        """
        included = self.inclusions(versions)

        istack = []
        dset = set()

        lineno = 0         # line of weave, 0-based

        isactive = None

        result = []

        WFE = WeaveFormatError

        for l in self._weave:
            if isinstance(l, tuple):
                c, v = l
                isactive = None
                if c == '{':
                    assert v not in istack
                    istack.append(v)
                elif c == '}':
                    istack.pop()
                elif c == '[':
                    if v in included:
                        assert v not in dset
                        dset.add(v)
                else:
                    assert c == ']'
                    if v in included:
                        assert v in dset
                        dset.remove(v)
            else:
                assert isinstance(l, basestring)
                if isactive is None:
                    isactive = (not dset) and istack and (istack[-1] in included)
                if isactive:
                    result.append((istack[-1], lineno, l))
            lineno += 1

        if istack:
            raise WFE("unclosed insertion blocks at end of weave",
                                   istack)
        if dset:
            raise WFE("unclosed deletion blocks at end of weave",
                                   dset)

        return result
    


    def get_iter(self, version):
        """Yield lines for the specified version."""
        for origin, lineno, line in self._extract([version]):
            yield line


    def get(self, index):
        return list(self.get_iter(index))


    def mash_iter(self, included):
        """Return composed version of multiple included versions."""
        for origin, lineno, text in self._extract(included):
            yield text


    def dump(self, to_file):
        from pprint import pprint
        print >>to_file, "Weave._weave = ",
        pprint(self._weave, to_file)
        print >>to_file, "Weave._parents = ",
        pprint(self._parents, to_file)



    def numversions(self):
        l = len(self._parents)
        assert l == len(self._sha1s)
        return l


    def __len__(self):
        return self.numversions()


    def check(self, progress_bar=None):
        # check no circular inclusions
        for version in range(self.numversions()):
            inclusions = list(self._parents[version])
            if inclusions:
                inclusions.sort()
                if inclusions[-1] >= version:
                    raise WeaveFormatError("invalid included version %d for index %d"
                                           % (inclusions[-1], version))

        # try extracting all versions; this is a bit slow and parallel
        # extraction could be used
        nv = self.numversions()
        for version in range(nv):
            if progress_bar:
                progress_bar.update('checking text', version, nv)
            s = sha.new()
            for l in self.get_iter(version):
                s.update(l)
            hd = s.hexdigest()
            expected = self._sha1s[version]
            if hd != expected:
                raise WeaveError("mismatched sha1 for version %d; "
                                 "got %s, expected %s"
                                 % (version, hd, expected))

        # TODO: check insertions are properly nested, that there are
        # no lines outside of insertion blocks, that deletions are
        # properly paired, etc.



    def merge(self, merge_versions):
        """Automerge and mark conflicts between versions.

        This returns a sequence, each entry describing alternatives
        for a chunk of the file.  Each of the alternatives is given as
        a list of lines.

        If there is a chunk of the file where there's no diagreement,
        only one alternative is given.
        """

        # approach: find the included versions common to all the
        # merged versions
        raise NotImplementedError()



    def _delta(self, included, lines):
        """Return changes from basis to new revision.

        The old text for comparison is the union of included revisions.

        This is used in inserting a new text.

        Delta is returned as a sequence of
        (weave1, weave2, newlines).

        This indicates that weave1:weave2 of the old weave should be
        replaced by the sequence of lines in newlines.  Note that
        these line numbers are positions in the total weave and don't
        correspond to the lines in any extracted version, or even the
        extracted union of included versions.

        If line1=line2, this is a pure insert; if newlines=[] this is a
        pure delete.  (Similar to difflib.)
        """


            
    def plan_merge(self, ver_a, ver_b):
        """Return pseudo-annotation indicating how the two versions merge.

        This is computed between versions a and b and their common
        base.

        Weave lines present in none of them are skipped entirely.
        """
        inc_a = self.inclusions([ver_a])
        inc_b = self.inclusions([ver_b])
        inc_c = inc_a & inc_b

        for lineno, insert, deleteset, line in self._walk():
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



    def weave_merge(self, plan):
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
                    yield '<<<<\n'
                    for l in lines_a: yield l
                    yield '====\n'
                    for l in lines_b: yield l
                    yield '>>>>\n'

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

                





def weave_toc(w):
    """Show the weave's table-of-contents"""
    print '%6s %50s %10s %10s' % ('ver', 'name', 'sha1', 'parents')
    for i in (6, 50, 10, 10):
        print '-' * i,
    print
    for i in range(w.numversions()):
        sha1 = w._sha1s[i]
        name = w._names[i]
        parent_str = ' '.join(map(str, w._parents[i]))
        print '%6d %-50.50s %10.10s %s' % (i, name, sha1, parent_str)



def weave_stats(weave_file):
    from bzrlib.progress import ProgressBar
    from bzrlib.weavefile import read_weave

    pb = ProgressBar()

    wf = file(weave_file, 'rb')
    w = read_weave(wf)
    # FIXME: doesn't work on pipes
    weave_size = wf.tell()

    total = 0
    vers = len(w)
    for i in range(vers):
        pb.update('checking sizes', i, vers)
        for line in w.get_iter(i):
            total += len(line)

    pb.clear()

    print 'versions          %9d' % vers
    print 'weave file        %9d bytes' % weave_size
    print 'total contents    %9d bytes' % total
    print 'compression ratio %9.2fx' % (float(total) / float(weave_size))
    if vers:
        avg = total/vers
        print 'average size      %9d bytes' % avg
        print 'relative size     %9.2fx' % (float(weave_size) / float(avg))


def usage():
    print """bzr weave tool

Experimental tool for weave algorithm.

usage:
    weave init WEAVEFILE
        Create an empty weave file
    weave get WEAVEFILE VERSION
        Write out specified version.
    weave check WEAVEFILE
        Check consistency of all versions.
    weave toc WEAVEFILE
        Display table of contents.
    weave add WEAVEFILE NAME [BASE...] < NEWTEXT
        Add NEWTEXT, with specified parent versions.
    weave annotate WEAVEFILE VERSION
        Display origin of each line.
    weave mash WEAVEFILE VERSION...
        Display composite of all selected versions.
    weave merge WEAVEFILE VERSION1 VERSION2 > OUT
        Auto-merge two versions and display conflicts.

example:

    % weave init foo.weave
    % vi foo.txt
    % weave add foo.weave ver0 < foo.txt
    added version 0

    (create updated version)
    % vi foo.txt
    % weave get foo.weave 0 | diff -u - foo.txt
    % weave add foo.weave ver1 0 < foo.txt
    added version 1

    % weave get foo.weave 0 > foo.txt       (create forked version)
    % vi foo.txt
    % weave add foo.weave ver2 0 < foo.txt
    added version 2

    % weave merge foo.weave 1 2 > foo.txt   (merge them)
    % vi foo.txt                            (resolve conflicts)
    % weave add foo.weave merged 1 2 < foo.txt     (commit merged version)     
    
"""
    


def main(argv):
    import sys
    import os
    from weavefile import write_weave, read_weave
    from bzrlib.progress import ProgressBar

    try:
        import psyco
        psyco.full()
    except ImportError:
        pass

    if len(argv) < 2:
        usage()
        return 0

    cmd = argv[1]

    def readit():
        return read_weave(file(argv[2], 'rb'))
    
    if cmd == 'help':
        usage()
    elif cmd == 'add':
        w = readit()
        # at the moment, based on everything in the file
        name = argv[3]
        parents = map(int, argv[4:])
        lines = sys.stdin.readlines()
        ver = w.add(name, parents, lines)
        write_weave(w, file(argv[2], 'wb'))
        print 'added version %r %d' % (name, ver)
    elif cmd == 'init':
        fn = argv[2]
        if os.path.exists(fn):
            raise IOError("file exists")
        w = Weave()
        write_weave(w, file(fn, 'wb'))
    elif cmd == 'get': # get one version
        w = readit()
        sys.stdout.writelines(w.get_iter(int(argv[3])))
        
    elif cmd == 'mash': # get composite
        w = readit()
        sys.stdout.writelines(w.mash_iter(map(int, argv[3:])))

    elif cmd == 'annotate':
        w = readit()
        # newline is added to all lines regardless; too hard to get
        # reasonable formatting otherwise
        lasto = None
        for origin, text in w.annotate(int(argv[3])):
            text = text.rstrip('\r\n')
            if origin == lasto:
                print '      | %s' % (text)
            else:
                print '%5d | %s' % (origin, text)
                lasto = origin
                
    elif cmd == 'toc':
        weave_toc(readit())

    elif cmd == 'stats':
        weave_stats(argv[2])
        
    elif cmd == 'check':
        w = readit()
        pb = ProgressBar()
        w.check(pb)
        pb.clear()
        print '%d versions ok' % w.numversions()

    elif cmd == 'inclusions':
        w = readit()
        print ' '.join(map(str, w.inclusions([int(argv[3])])))

    elif cmd == 'parents':
        w = readit()
        print ' '.join(map(str, w._parents[int(argv[3])]))

    elif cmd == 'plan-merge':
        w = readit()
        for state, line in w.plan_merge(int(argv[3]), int(argv[4])):
            if line:
                print '%14s | %s' % (state, line),

    elif cmd == 'merge':
        w = readit()
        p = w.plan_merge(int(argv[3]), int(argv[4]))
        sys.stdout.writelines(w.weave_merge(p))
            
    elif cmd == 'mash-merge':
        if len(argv) != 5:
            usage()
            return 1

        w = readit()
        v1, v2 = map(int, argv[3:5])

        basis = w.inclusions([v1]).intersection(w.inclusions([v2]))

        base_lines = list(w.mash_iter(basis))
        a_lines = list(w.get(v1))
        b_lines = list(w.get(v2))

        from bzrlib.merge3 import Merge3
        m3 = Merge3(base_lines, a_lines, b_lines)

        name_a = 'version %d' % v1
        name_b = 'version %d' % v2
        sys.stdout.writelines(m3.merge_lines(name_a=name_a, name_b=name_b))
    else:
        raise ValueError('unknown command %r' % cmd)
    


def profile_main(argv): 
    import tempfile, hotshot, hotshot.stats

    prof_f = tempfile.NamedTemporaryFile()

    prof = hotshot.Profile(prof_f.name)

    ret = prof.runcall(main, argv)
    prof.close()

    stats = hotshot.stats.load(prof_f.name)
    #stats.strip_dirs()
    stats.sort_stats('cumulative')
    ## XXX: Might like to write to stderr or the trace file instead but
    ## print_stats seems hardcoded to stdout
    stats.print_stats(20)
            
    return ret


if __name__ == '__main__':
    import sys
    if '--profile' in sys.argv:
        args = sys.argv[:]
        args.remove('--profile')
        sys.exit(profile_main(args))
    else:
        sys.exit(main(sys.argv))

