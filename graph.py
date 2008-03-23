# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib import graph
from bzrlib.revision import NULL_REVISION

class Graph(graph.Graph):
    def __init__(self, parents_provider):
        graph.Graph.__init__(self, parents_provider)
        if hasattr(parents_provider, "get_lhs_parent"):
            self.get_lhs_parent = parents_provider.get_lhs_parent

    def get_lhs_parent(self, revid):
        parents = self.get_parent_map([revid])[revid]
        if parents == () or parents == (NULL_REVISION,):
            return None
        return parents[0]

    def iter_lhs_ancestry(self, revid):
        while revid is not None:
            yield revid
            revid = self.get_lhs_parent(revid)
