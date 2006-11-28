# Copyright (C) 2006 Canonical Ltd

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

"""Tools for converting globs to regular expressions.

This module provides functions for converting shell-like globs to regular
expressions.
"""

import re

from bzrlib.trace import (
    mutter, 
    warning
    )


class Replacer(object):
    """Do a multiple-pattern substitution.

    The patterns and substitutions are combined into one, so the result of
    one replacement is never substituted again. Add the patterns and
    replacements via the add method and then call the object. The patterns
    must not contain capturing groups.
    """

    _expand = re.compile(ur'\\&')

    def __init__(self, source=None):
        self._pat = None
        if source:
            self._pats = list(source._pats)
            self._funs = list(source._funs)
        else:
            self._pats = []
            self._funs = []

    def add(self, pat, fun):
        r"""Add a pattern and replacement.

        The pattern must not contain capturing groups.
        The replacement might be either a string template in which \& will be
        replaced with the match, or a function that will get the matching text  
        as argument. It does not get match object, because capturing is 
        forbidden anyway.
        """
        self._pat = None
        self._pats.append(pat)
        self._funs.append(fun)

    def add_replacer(self, replacer):
        r"""Add all patterns from another replacer.

        All patterns and replacements from replacer are appended to the ones
        already defined.
        """
        self._pat = None
        self._pats.extend(replacer._pats)
        self._funs.extend(replacer._funs)

    def __call__(self, text):
        if not self._pat:
            self._pat = re.compile(
                    u'|'.join([u'(%s)' % p for p in self._pats]),
                    re.UNICODE)
        return self._pat.sub(self._do_sub, text)

    def _do_sub(self, m):
        fun = self._funs[m.lastindex - 1]
        if hasattr(fun, '__call__'):
            return fun(m.group(0))
        else:
            return self._expand.sub(m.group(0), fun)


_sub_named = Replacer()
_sub_named.add(ur'\[:digit:\]', ur'\d')
_sub_named.add(ur'\[:space:\]', ur'\s')
_sub_named.add(ur'\[:alnum:\]', ur'\w')
_sub_named.add(ur'\[:ascii:\]', ur'\0-\x7f')
_sub_named.add(ur'\[:blank:\]', ur' \t')
_sub_named.add(ur'\[:cntrl:\]', ur'\0-\x1f\x7f-\x9f')


def _sub_group(m):
    if m[1] in (u'!', u'^'):
        return u'[^' + _sub_named(m[2:-1]) + u']'
    return u'[' + _sub_named(m[1:-1]) + u']'


def _invalid_regex(repl):
    def _(m):
        warning(u"'%s' not allowed withing regexp. Replacing with '%s'" %
                (m, repl))
        return repl
    return _


_sub_re = Replacer()
_sub_re.add(u'^RE:', u'')
_sub_re.add(u'\((?!\?)', u'(?:')
_sub_re.add(u'\(\?P<.*>', _invalid_regex(u'(?:'))
_sub_re.add(u'\(\?P=[^)]*\)', _invalid_regex(u''))


_sub_fullpath = Replacer()
_sub_fullpath.add(ur'^RE:.*', _sub_re) # RE:<anything> is a regex
_sub_fullpath.add(ur'\[\^?\]?(?:[^][]|\[:[^]]+:\])+\]', _sub_group) # char group
_sub_fullpath.add(ur'(?:(?<=/)|^)(?:\.?/)+', u'') # canonicalize path
_sub_fullpath.add(ur'\\.', ur'\&') # keep anything backslashed
_sub_fullpath.add(ur'[(){}|^$+.]', ur'\\&') # escape specials
_sub_fullpath.add(ur'(?:(?<=/)|^)\*\*+/', ur'(?:.*/)?') # **/ after ^ or /
_sub_fullpath.add(ur'\*+', ur'[^/]*') # * elsewhere
_sub_fullpath.add(ur'\?', ur'[^/]') # ? everywhere


_sub_basename = Replacer()
_sub_basename.add(ur'\[\^?\]?(?:[^][]|\[:[^]]+:\])+\]', _sub_group) # char group
_sub_basename.add(ur'\\.', ur'\&') # keep anything backslashed
_sub_basename.add(ur'[(){}|^$+.]', ur'\\&') # escape specials
_sub_basename.add(ur'\*+', ur'.*') # * everywhere
_sub_basename.add(ur'\?', ur'.') # ? everywhere


def _sub_extension(pattern):
    return _sub_basename(pattern[2:])


class Globster(object):
    """A simple wrapper for a set of glob patterns.

    Provides the capability to search the patterns to find a match for
    a given filename (including the full path).

    Patterns are translated to regular expressions to expidite matching.

    The regular expressions for multiple patterns are aggregated into 
    a super-regex containing groups of up to 99 patterns.  
    The 99 limitation is due to the grouping limit of the Python re module.
    The resulting super-regex and associated patterns are stored as a list of
    (regex,[patterns]) in _regex_patterns.
    
    For performance reasons the patterns are categorised as extension patterns
    (those that match against a file extension), basename patterns
    (those that match against the basename of the filename),
    and fullpath patterns (those that match against the full path).
    The translations used for extensions and basenames are relatively simpler 
    and therefore faster to perform than the fullpath patterns.

    Also, the extension patterns are more likely to find a match and 
    so are matched first, then the basename patterns, then the fullpath
    patterns.
    """
    def __init__(self, patterns):
        self._regex_patterns = []
        path_patterns = []
        base_patterns = []
        ext_patterns = []
        for pat in patterns:
            if pat.startswith(u'RE:') or u'/' in pat:
                path_patterns.append(pat)
            elif pat.startswith(u'*.'):
                ext_patterns.append(pat)
            else:
                base_patterns.append(pat)
        self._add_patterns(ext_patterns,_sub_extension,
            prefix=r'(?:.*/)?(?!.*/)(?:.*\.)')
        self._add_patterns(base_patterns,_sub_basename, 
            prefix=r'(?:.*/)?(?!.*/)')
        self._add_patterns(path_patterns,_sub_fullpath) 

    def _add_patterns(self, patterns, translator, prefix=''):
        while patterns:
            grouped_rules = ['(%s)' % translator(pat) for pat in patterns[:99]]
            joined_rule = '%s(?:%s)$' % (prefix, '|'.join(grouped_rules))
            self._regex_patterns.append((re.compile(joined_rule, re.UNICODE), 
                patterns[:99]))
            patterns = patterns[99:]

    def match(self, filename):
        """Searches for a pattern that matches the given filename.
        
        :return A matching pattern or None if there is no matching pattern.
        """
        for regex, patterns in self._regex_patterns:
            match = regex.match(filename)
            if match:
                return patterns[match.lastindex -1]
        return None
        
