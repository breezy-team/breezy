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

"""Miscellaneous useful stuff."""


def single_plural(n, single, plural):
    """Return a single or plural form of a noun based on number."""
    if n == 1:
        return single
    else:
        return plural


def invert_dict(d):
    """Invert a dictionary with keys matching each value turned into a list."""
    # Based on recipe from ASPN
    result = {}
    for k, v in d.iteritems():
        keys = result.setdefault(v, [])
        keys.append(k)
    return result
