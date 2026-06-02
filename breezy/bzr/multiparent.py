# Copyright (C) 2007-2011 Canonical Ltd
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

"""Multi-parent diff format.

The implementation lives in bzrformats.multiparent; this module re-exports
it so that existing ``breezy.multiparent`` imports keep working.
"""

from bzrformats.multiparent import (  # noqa: F401
    BaseVersionedFile,
    MultiMemoryVersionedFile,
    MultiParent,
    MultiVersionedFile,
    NewText,
    ParentText,
    _Reconstructor,
    _topo_iter,
    gzip_string,
    topo_iter,
    topo_iter_keys,
)

__all__ = [
    "BaseVersionedFile",
    "MultiMemoryVersionedFile",
    "MultiParent",
    "MultiVersionedFile",
    "NewText",
    "ParentText",
    "gzip_string",
    "topo_iter",
    "topo_iter_keys",
]
