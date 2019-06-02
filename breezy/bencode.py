# Copyright (C) 2007, 2009 Canonical Ltd
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

"""Wrapper around the bencode pyrex and python implementation"""

from __future__ import absolute_import

from . import osutils

try:
    from ._bencode_pyx import bdecode, bdecode_as_tuple, bencode, Bencached
except ImportError as e:
    osutils.failed_to_load_extension(e)
    from .util._bencode_py import (  # noqa: F401
        bdecode,
        bdecode_as_tuple,
        bencode,
        Bencached,
        )
