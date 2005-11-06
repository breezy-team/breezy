from sets import Set as set
from copy import copy
from bisect import bisect

def unique_lcs(a, b):
    # set index[line in a] = position of line in a unless
    # unless a is a duplicate, in which case it's set to None
    index = {}
    for i in xrange(len(a)):
        line = a[i]
        if line in index:
            index[line] = None
        else:
            index[line]= i
    # make btoa[i] = position of line i in a, unless
    # that line doesn't occur exactly once in both, 
    # in which case it's set to None
    btoa = [None] * len(b)
    index2 = {}
    for pos, line in enumerate(b):
        next = index.get(line)
        if next is not None:
            if line in index2:
                # unset the previous mapping, which we now know to
                # be invalid because the line isn't unique
                btoa[index2[line]] = None
                del index[line]
            else:
                index2[line] = pos
                btoa[pos] = next
    # this is the Patience sorting algorithm
    # see http://en.wikipedia.org/wiki/Patience_sorting
    backpointers = [None] * len(b)
    stacks = []
    lasts = []
    k = 0
    for bpos, apos in enumerate(btoa):
        if apos is None:
            continue
        # as an optimization, check if the next line comes at the end,
        # because it usually does
        if stacks and stacks[-1] < apos:
            k = len(stacks)
        # as an optimization, check if the next line comes right after
        # the previous line, because usually it does
        elif stacks and stacks[k] < apos and (k == len(stacks) - 1 or stacks[k+1] > apos):
            k += 1
        else:
            k = bisect(stacks, apos)
        if k > 0:
            backpointers[bpos] = lasts[k-1]
        if k < len(stacks):
            stacks[k] = apos
            lasts[k] = bpos
        else:
            stacks.append(apos)
            lasts.append(bpos)
    if len(lasts) == 0:
        return []
    result = []
    k = lasts[-1]
    while k is not None:
        result.append((btoa[k], k))
        k = backpointers[k]
    result.reverse()
    return result

assert unique_lcs('', '') == []
assert unique_lcs('a', 'a') == [(0, 0)]
assert unique_lcs('a', 'b') == []
assert unique_lcs('ab', 'ab') == [(0, 0), (1, 1)]
assert unique_lcs('abcde', 'cdeab') == [(2, 0), (3, 1), (4, 2)]
assert unique_lcs('cdeab', 'abcde') == [(0, 2), (1, 3), (2, 4)]
assert unique_lcs('abXde', 'abYde') == [(0, 0), (1, 1), (3, 3), (4, 4)]
assert unique_lcs('acbac', 'abc') == [(2, 1)]

def recurse_matches(a, b, ahi, bhi, answer, maxrecursion):
    oldlen = len(answer)
    if maxrecursion < 0:
        # this will never happen normally, this check is to prevent DOS attacks
        return
    oldlength = len(answer)
    if len(answer) == 0:
        alo, blo = 0, 0
    else:
        alo, blo = answer[-1]
        alo += 1
        blo += 1
    if alo == ahi or blo == bhi:
        return
    for apos, bpos in unique_lcs(a[alo:ahi], b[blo:bhi]):
        # recurse between lines which are unique in each file and match
        apos += alo
        bpos += blo
        recurse_matches(a, b, apos, bpos, answer, maxrecursion - 1)
        answer.append((apos, bpos))
    if len(answer) > oldlength:
        # find matches between the last match and the end
        recurse_matches(a, b, ahi, bhi, answer, maxrecursion - 1)
    elif a[alo] == b[blo]:
        # find matching lines at the very beginning
        while alo < ahi and blo < bhi and a[alo] == b[blo]:
            answer.append((alo, blo))
            alo += 1
            blo += 1
        recurse_matches(a, b, ahi, bhi, answer, maxrecursion - 1)
    elif a[ahi - 1] == b[bhi - 1]:
        # find matching lines at the very end
        nahi = ahi - 1
        nbhi = bhi - 1
        while nahi > alo and nbhi > blo and a[nahi - 1] == b[nbhi - 1]:
            nahi -= 1
            nbhi -= 1
        recurse_matches(a, b, nahi, nbhi, answer, maxrecursion - 1)
        for i in xrange(ahi - nahi):
            answer.append((nahi + i, nbhi + i))

a1 = []
recurse_matches(['a', None, 'b', None, 'c'], ['a', 'a', 'b', 'c', 'c'], 5, 5, a1, 10)
assert a1 == [(0, 0), (2, 2), (4, 4)]
a2 = []
recurse_matches(['a', 'c', 'b', 'a', 'c'], ['a', 'b', 'c'], 5, 3, a2, 10)
assert  a2 == [(0, 0), (2, 1), (4, 2)]

class Weave:
    def __init__(self):
        # [(lineid, line)]
        self.weave = []
        # {revid: [parent]}
        self.parents = {}
        # {revid: [(lineid, state)]}
        # states are integers
        # each line's state starts at 0, then goes to 1, 2, etc.
        # odd states are when the line is present, even are when it is not
        # the merge between two states is the greater of the two values
        self.newstates = {}

    def add_revision(self, revid, lines, parents):
        assert revid not in self.parents
        for p in parents:
            assert p in self.parents
        self.parents[revid] = copy(parents)
        matches = []
        # match against the weave
        lines2 = [line for (lineid, line) in self.weave]
        recurse_matches(lines, lines2, len(lines), len(lines2), matches, 10)
        s = set()
        for a, b in matches:
            s.add(self.weave[b][0])
        vs = [self._make_vals(p) for p in parents]
        # calculate which lines had their states changed in this revision
        newvals = []
        if len(vs) > 0:
            for lineid, line in self.weave:
                state = max([v.get(lineid, 0) for v in vs])
                if (state & 1 == 1) != (lineid in s):
                    newvals.append((lineid, state + 1))
        else:
            for lineid, line in self.weave:
                newvals.append((lineid, 1))
        # build a new weave
        newweave = []
        revpos = -1
        weavepos = -1
        matches.append((len(lines), len(lines2)))
        for a, b in matches:
            if b > weavepos + 1:
                # add current weave lines to the new weave
                newweave.extend(self.weave[weavepos + 1:b])
            if a > revpos + 1:
                # add lines which have never appeared before to the weave
                for i in xrange(revpos + 1, a):
                    lineid = (revid, i)
                    newweave.append((lineid, lines[i]))
                    newvals.append((lineid, 1))
            if b != len(lines2):
                newweave.append(self.weave[b])
            revpos = a
            weavepos = b
        self.newstates[revid] = newvals
        self.weave = newweave

    def _parents(self, revid):
        unused = [revid]
        result = set()
        while unused:
            next = unused.pop()
            if next not in result:
                unused.extend(self.parents[next])
                result.add(next)
        return result

    def _make_vals(self, revid):
        # return {lineid: state} for the given revision
        s = self._parents(revid)
        v = {}
        for n in s:
            for p, q in self.newstates[n]:
                v[p] = max(v.get(p, 0), q)
        return v

    def retrieve_revision(self, revid):
        # returns a list of strings
        v = self._make_vals(revid)
        return [line for (lineid, line) in self.weave if (v.get(lineid, 0) & 1)]

    def annotate(self, revid):
        # returns [(line, whether present, [perpetrator])]
        ps = self._parents(revid)
        # {lineid: [(parent, state)]}
        byline = {}
        for parent in ps:
            for lineid, state in self.newstates[parent]:
                byline.setdefault(lineid, []).append((parent, state))
        result = []
        for (lineid, line) in self.weave:
            maxstate = 0
            perps = []
            for (parent, state) in byline.get(lineid, []):
                if state > maxstate:
                    maxstate = state
                    perps = [parent]
                elif state == maxstate:
                    perps.append(parent)
            if maxstate > 0:
                result.append((line, (maxstate & 1) == 1, perps))
        return result

    def merge_revisions(self, reva, revb):
        # returns [line]
        # non-conflict lines are strings, conflict sections are
        # ([linesa], [linesb])
        va = self._make_vals(reva)
        vb = self._make_vals(revb)
        r = []
        awins, bwins = False, False
        alines, blines = [], []
        for lineid, line in self.weave:
            aval, bval = va.get(lineid, 0), vb.get(lineid, 0)
            if aval & 1 and bval & 1:
                # append a matched line and the section prior to it
                if awins and bwins:
                    # conflict case
                    r.append((alines, blines))
                elif awins:
                    r.extend(alines)
                elif bwins:
                    r.extend(blines)
                r.append(line)
                awins, bwins = False, False
                alines, blines = [], []
            elif aval & 1 or bval & 1:
                # extend either side of the potential conflict
                # section with a non-matching line
                if aval > bval:
                    awins = True
                else:
                    bwins = True
                if aval & 1:
                    alines.append(line)
                else:
                    blines.append(line)
        # add the potential conflict section at the end
        if awins and bwins:
            r.append((alines, blines))
        elif awins:
            r.extend(alines)
        elif bwins:
            r.extend(blines)
        return r

w = Weave()
w.add_revision(1, ['a', 'b'], [])
assert w.retrieve_revision(1) == ['a', 'b']
w.add_revision(2, ['a', 'x', 'b'], [1])
assert w.retrieve_revision(2) == ['a', 'x', 'b']
w.add_revision(3, ['a', 'y', 'b'], [1])
assert w.retrieve_revision(3) == ['a', 'y', 'b']
assert w.merge_revisions(2, 3) == ['a', (['x'], ['y']), 'b']
w.add_revision(4, ['a', 'x', 'b'], [1])
w.add_revision(5, ['a', 'z', 'b'], [4])
assert w.merge_revisions(2, 5) == ['a', 'z', 'b']
w = Weave()
w.add_revision('p', ['a', 'b'], [])
w.add_revision('q', ['a', 'c'], ['p'])
w.add_revision('r', ['a'], ['p'])
assert w.annotate('r') == [('a', True, ['p']), ('b', False, ['r'])]
