# Copyright (C) 2005, 2006 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""A version of inspect that includes what 'copy' needs.

Importing the python standard module 'copy' is far more expensive than it
needs to be, because copy imports 'inspect' which imports 'tokenize'.
And 'copy' only needs 2 small functions out of 'inspect', but has to
load all of 'tokenize', which makes it horribly slow.

This module is designed to use tricky hacks in import rules, to avoid this
overhead.
"""

from __future__ import absolute_import


####
# These are the only 2 functions that 'copy' needs from 'inspect'
# As you can see, they are quite trivial, and don't justify the
# 40ms spent to import 'inspect' because it is importing 'tokenize'
# These are copied verbatim from the python standard library.

# ----------------------------------------------------------- class helpers
def _searchbases(cls, accum):
    # Simulate the "classic class" search order.
    if cls in accum:
        return
    accum.append(cls)
    for base in cls.__bases__:
        _searchbases(base, accum)


def getmro(cls):
    "Return tuple of base classes (including cls) in method resolution order."
    if hasattr(cls, "__mro__"):
        return cls.__mro__
    else:
        result = []
        _searchbases(cls, result)
        return tuple(result)


def import_copy_with_hacked_inspect():
    """Import the 'copy' module with a hacked 'inspect' module"""
    # We don't actually care about 'getmro' but we need to pass
    # something in the list so that we get the direct module,
    # rather than getting the base module
    import sys

    # Don't hack around if 'inspect' already exists
    if 'inspect' in sys.modules:
        import copy
        return

    mod = __import__('bzrlib.inspect_for_copy',
                     globals(), locals(), ['getmro'])

    sys.modules['inspect'] = mod
    try:
        import copy
    finally:
        del sys.modules['inspect']
