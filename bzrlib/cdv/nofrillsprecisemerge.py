from sets import Set as set
from copy import copy
from bisect import bisect

def unique_lcs(a, b):
    """Find the longest common subset for unique lines.

    :param a: An indexable object (such as string or list of strings)
    :param b: Another indexable object (such as string or list of strings)
    :return: A list of tuples, one for each line which is matched.
            [(line_in_a, line_in_b), ...]

    This only matches lines which are unique on both sides.
    This helps prevent common lines from over influencing match
    results.
    The longest common subset uses the Patience Sorting algorithm:
    http://en.wikipedia.org/wiki/Patience_sorting
    """
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
    """Find all of the matching text in the lines of a and b.

    :param a: A sequence
    :param b: Another sequence
    :param ahi: The maximum length of a to check, typically len(a)
    :param bhi: The maximum length of b to check, typically len(b)
    :param answer: The return array. Will be filled with tuples
                   indicating [(line_in_a), (line_in_b)]
    :param maxrecursion: The maximum depth to recurse.
                         Must be a positive integer.
    :return: None, the return value is in the parameter answer, which
             should be a list

    """
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

a3 = []
recurse_matches(['a', 'B', 'c', 'c', 'D', 'e'], ['a', 'b', 'c', 'c', 'd', 'e'], 6, 6, a3, 10)
# FIXME: recurse_matches won't match non-unique lines, surrounded by bogus text
# This is what it should be
#assert a2 == [(0,0), (2,2), (3,3), (5,5)]
# This is what it currently gives:
assert a3 == [(0,0), (5,5)]
