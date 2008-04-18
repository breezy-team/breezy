# Copyright (C) 2008 Canonical Ltd
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


"""RCS-style keyword expansion plugin."""

import re


_KW_RAW_RE = re.compile('\\$(\w+)\\$')
_KW_COOKED_RE = re.compile('\\$(\w+):')


def test_suite():
    from bzrlib.plugins.keywords import tests
    return tests.test_suite()


def expand_keywords(s, kw_dict):
    result = ''
    rest = s
    while (True):
        match = _KW_RAW_RE.search(rest)
        if not match:
            break
        result += rest[:match.start()]
        keyword = match.group(1)
        expansion = kw_dict.get(keyword)
        if expansion is None:
            # Unknown expansion - output a warning here?
            result += match.group(0)
        else:
            # Should we validate that the expansion is safe
            # to be collapsed? i.e. doesn't have ' $' embedded?
            result += '$%s: %s $' % (keyword, expansion)
        rest = rest[match.end():]
    return result + rest
