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

from bzrlib import debug, errors
from bzrlib.knit import make_file_factory
from bzrlib.trace import mutter
from bzrlib.revision import NULL_REVISION
from bzrlib.versionedfile import ConstantMapper

class DiskCachingParentsProvider(object):
    def __init__(self, actual, cachetransport):
        self.cache = ParentsCache(cachetransport)
        self.actual = actual

    def get_parent_map(self, keys):
        ret = {}
        todo = set()
        for k in keys:
            parents = self.cache.lookup_parents(k)
            if parents is None:
                todo.add(k)
            else:
                ret[k] = parents
        if len(todo):
            newfound = self.actual.get_parent_map(todo)
            for revid, parents in newfound.items():
                if revid == NULL_REVISION:
                    continue
                self.cache.insert_parents(revid, parents)
            ret.update(newfound)
        return ret


PARENTMAP_VERSION = 1


class ParentsCache(object):

    def __init__(self, cache_transport):
        mapper = ConstantMapper("parentmap-v%d" % PARENTMAP_VERSION)
        self.parentmap_knit = make_file_factory(True, mapper)(cache_transport)

    def insert_parents(self, revid, parents):
        self.parentmap_knit.add_lines((revid,), [(r, ) for r in parents], [])

    def lookup_parents(self, revid):
        if "cache" in debug.debug_flags:
            mutter('lookup parents: %r', revid)
        try:
            return [r for (r,) in self.parentmap_knit.get_parent_map([(revid,)])[(revid,)]]
        except KeyError:
            return None

