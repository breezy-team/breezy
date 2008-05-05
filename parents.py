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

from cache import CacheTable

class SqliteCachingParentsProvider(object):
    def __init__(self, actual, cachedb=None):
        self.cache = ParentsCache(cachedb)
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
            ret.update(self.actual.get_parent_map(todo))
        return ret


class ParentsCache(CacheTable):
    def _create_table(self):
        self.cachedb.executescript("""
        create table if not exists parent (revision text, parent text);
        create index if not exists parent_revision on parent (revision);
        """)

    def insert_parents(self, revid, parents):
        self.mutter('insert parents: %r -> %r' % (revid, parents))
        self.cachedb.execute("insert into parent (revision, parent) VALUES (?, ?)", (revid, parents))

    def lookup_parents(self, revid):
        self.mutter('lookup parents: %r' % (revid,))
        ret = []
        for row in self.cachedb.execute("select parent from parent where revision = ?", (revid,)).fetchall():
            ret.append(row[0])
        if ret == []:
            return None
        return tuple(ret)

