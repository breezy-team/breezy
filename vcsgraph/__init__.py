# Copyright (C) 2005-2010 Canonical Ltd
# Copyright (C) 2018-2025 Breezy Developers
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

"""Graph algorithms for version control systems.

This package contains graph-related algorithms that are useful for
version control systems, including:

- Topological sorting (tsort)
- Graph operations (graph)
- Multi-parent handling (multiparent)
"""

__all__ = [
    'BaseVersionedFile',
    'DictParentsProvider',
    'FrozenHeadsCache',
    'Graph',
    'KnownGraph',
    'MultiMemoryVersionedFile',
    'MultiParent',
    'MultiVersionedFile',
    'invert_parent_map',
    'topo_sort',
]

# Re-export commonly used functions and classes
from .graph import (
    DictParentsProvider,
    FrozenHeadsCache,
    Graph,
    invert_parent_map,
)
from ._known_graph_py import KnownGraph
from .multiparent import (
    BaseVersionedFile,
    MultiMemoryVersionedFile,
    MultiParent,
    MultiVersionedFile,
)
from .tsort import topo_sort
