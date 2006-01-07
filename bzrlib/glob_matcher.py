# Copyright (C) 2006 Canonical Ltd

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

import re


def glob_to_re(pat):
    """Convert a glob pattern into a regular expression.

    We handle the following patterns:
        **      Match a string of characters (including dir separators)
        *       Match a string of characters (not directory separator)
        ?       Match a single character (not directory separator)
        [seq]   Matches a single character, but any of 'seq'
        [!seq]  Match any single character not in 'seq'

    This was adapted from fnmatch.translate()

    :param pat: The pattern to transform
    :return: A regular expression
    """

    i, n = 0, len(pat)
    res = ''
    while i < n:
        c = pat[i]
        i += 1
        if c == '*':
            if pat[i:i+1] == '*': # pattern '**'
                res = res + '.*'
                i += 1
            else: # pattern '*'
                res = res + r'[^/\\]*'
        elif c == '?':
            res = res + r'[^/\\]'
        elif c == '[':
            j = i
            if j < n and pat[j] == '!':
                j = j+1
            if j < n and pat[j] == ']':
                j = j+1
            while j < n and pat[j] != ']':
                j = j+1
            if j >= n:
                res = res + '\\['
            else:
                stuff = pat[i:j].replace('\\','\\\\')
                i = j+1
                if stuff[0] == '!':
                    stuff = '^' + stuff[1:] + r'/\\'
                elif stuff[0] == '^':
                    stuff = '\\' + stuff
                res = '%s[%s]' % (res, stuff)
        else:
            res = res + re.escape(c)
    # Without a final $, re.match() will match if just the beginning
    # matches. I did not expect that. I thought re.match() had to match
    # the entire string.
    return res + "$"


class _GlobMatcher(object):
    """A class which handles matching filenames to glob expressions"""
    
    def __init__(self, glob_re):
        """Create a matcher from a regular expression."""
        self._compiled_re = re.compile(glob_re, re.UNICODE)

    def __call__(self, fname):
        """See if fname matches the internal glob.

        :param fname: A filename to check.
        :return: Boolean, does/doesn't match
        """
        return self._compiled_re.match(fname) is not None


def glob_to_matcher(glob):
    """Return a callable which will match filenames versus the glob."""
    return _GlobMatcher(glob_to_re(glob))


def globs_to_re(patterns):
    """Convert a set of patterns into a single regular expression.

    :param patterns: A list of patterns to transform
    :return: A regular expression combining all patterns
    """
    final_re = []
    for pat in patterns:
        pat_re = glob_to_re(pat)
        assert pat_re[-1] == '$'
        # TODO: jam 20060107 It seems to be enough to do:
        #       (pat1|pat2|pat3|pat4)$
        #       Is there a circumstance where we need to do
        #       ((pat1)|(pat2)|(pat3))$
        
        # TODO: jam 20060107 Is it more efficient to do:
        #       (pat1|pat2|pat3)$
        #       Or to do:
        #       (pat1$)|(pat2$)|(pat3$)
        # I thought it would be more efficent to only have to
        # match the end of the pattern once

        #final_re.append('(' + pat_re[:-1] + ')')
        final_re.append(pat_re[:-1])
    # All patterns end in $, we don't need to specify it
    # for every pattern.
    # Just put one at the end
    return '(' + '|'.join(final_re) + ')$'


def globs_to_matcher(patterns):
    """Return a callable which will match filenames versus the globs."""
    return _GlobMatcher(globs_to_re(patterns))


