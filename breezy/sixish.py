# Copyright (C) 2017 Bazaar hackers
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

"""
Module to aid writing a Python dialect compatible with 2.7 and 3.4+.

Initially pretty much just a subset of six while things get worked out.
"""

from __future__ import absolute_import

from six import (
    binary_type,
    get_unbound_function,
    indexbytes,
    int2byte,
    PY3,
    reraise,
    string_types,
    text_type,
    unichr,
    viewitems,
    viewkeys,
    viewvalues,
    )  # noqa: F401


# The io module exists in Python 2.7 but lacks optimisation. Most uses are not
# performance critical, but want to measure before switching from cStringIO.
if PY3:
    import io as _io
    BytesIO = _io.BytesIO
    StringIO = _io.StringIO
    from builtins import range, map, zip
else:
    from cStringIO import StringIO as BytesIO  # noqa: F401
    from StringIO import StringIO  # noqa: F401
    from future_builtins import zip, map  # noqa: F401
    range = xrange  # noqa: F821


# GZ 2017-06-10: Work out if interning bits of inventory is behaviour we want
# to retain outside of StaticTuple, if so need to implement for Python 3.
if PY3:
    def bytesintern(b):
        """Dummy intern() function."""
        return b
else:
    bytesintern = intern
