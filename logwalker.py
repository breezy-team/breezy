# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Cache of the Subversion history log."""

from bzrlib import urlutils
from bzrlib.errors import NoSuchRevision
from bzrlib.trace import mutter
import bzrlib.ui as ui

from bzrlib.plugins.svn import changes, core
from bzrlib.plugins.svn.cache import CacheTable
from bzrlib.plugins.svn.core import SubversionException
from bzrlib.plugins.svn.errors import ERR_FS_NO_SUCH_REVISION, ERR_FS_NOT_FOUND, ERR_FS_NOT_DIRECTORY
from bzrlib.plugins.svn.ra import DIRENT_KIND
from bzrlib.plugins.svn.transport import SvnRaTransport

class lazy_dict(object):
    def __init__(self, initial, create_fn, *args):
        self.initial = initial
        self.create_fn = create_fn
        self.args = args
        self.dict = None

    def _ensure_init(self):
        if self.dict is None:
            self.dict = self.create_fn(*self.args)
            self.create_fn = None

    def __len__(self):
        self._ensure_init()
        return len(self.dict)

    def __getitem__(self, key):
        if key in self.initial:
            return self.initial.__getitem__(key)
        self._ensure_init()
        return self.dict.__getitem__(key)

    def __setitem__(self, key, value):
        self._ensure_init()
        return self.dict.__setitem__(key, value)

    def __contains__(self, key):
        if key in self.initial:
            return True
        self._ensure_init()
        return self.dict.__contains__(key)

    def get(self, key, default=None):
        if key in self.initial:
            return self.initial[key]
        self._ensure_init()
        return self.dict.get(key, default)

    def has_key(self, key):
        if self.initial.has_key(key):
            return True
        self._ensure_init()
        return self.dict.has_key(key)

    def keys(self):
        self._ensure_init()
        return self.dict.keys()

    def values(self):
        self._ensure_init()
        return self.dict.values()

    def items(self):
        self._ensure_init()
        return self.dict.items()

    def __repr__(self):
        self._ensure_init()
        return repr(self.dict)

    def __eq__(self, other):
        self._ensure_init()
        return self.dict.__eq__(other)


class LogCache(CacheTable):
    """Log browser cache table manager. The methods of this class
    encapsulate the SQL commands used by CachingLogWalker to access
    the log cache tables."""
    
    def __init__(self, cache_db=None):
        CacheTable.__init__(self, cache_db)

    def _create_table(self):
        self.cachedb.executescript("""
            create table if not exists changed_path(rev integer, action text, path text, copyfrom_path text, copyfrom_rev integer);
            create index if not exists path_rev on changed_path(rev);
            create unique index if not exists path_rev_path on changed_path(rev, path);
            create unique index if not exists path_rev_path_action on changed_path(rev, path, action);

            create table if not exists revprop(rev integer, name text, value text);
            create table if not exists revinfo(rev integer, all_revprops int);
            create index if not exists revprop_rev on revprop(rev);
            create unique index if not exists revprop_rev_name on revprop(rev, name);
            create unique index if not exists revinfo_rev on revinfo(rev);
        """)
        self._commit_interval = 1000
    
    def find_latest_change(self, path, revnum):
        if path == "":
            return self.cachedb.execute("select max(rev) from changed_path where rev <= ?", (revnum,)).fetchone()[0]
        return self.cachedb.execute("""
            select max(rev) from changed_path
            where rev <= ?
            and (path=?
                 or path glob ?
                 or (? glob (path || '/*')
                     and action in ('A', 'R')))
        """, (revnum, path, path + "/*", path)).fetchone()[0]

    def path_added(self, path, from_revnum, to_revnum):
        """Determine whether a path was recently added. 
        
        It returns the latest revision number before to_revnum in which the 
        path was added or replaced, or None if the path was neither added nor
        replaced after from_revnum but before to_revnum.
        """
        assert from_revnum < to_revnum
        return self.cachedb.execute("""
            select max(rev) from changed_path
            where rev > ? and rev <= ?
            and (?=path or ? glob (path || '/*'))
            and action in ('A', 'R')
        """, (from_revnum, to_revnum, path, path)).fetchone()[0]
    
    def get_change(self, path, revnum):
        return self.cachedb.execute("""
            select action, copyfrom_path, copyfrom_rev
            from changed_path
            where path=? and rev=?
        """, (path, revnum)).fetchone()

    def get_previous(self, path, revnum):
        """Determine the change that created the given path or its
        nearest ancestor, in order to determine where it came from."""
        return self.cachedb.execute("""
            select path, action, copyfrom_path, copyfrom_rev
            from changed_path
            where rev=? and action in ('A', 'R')
            and (path=? or path='' or ? glob (path || '/*'))
            order by path desc
            limit 1
        """, (revnum, path, path)).fetchone()

    def get_revision_paths(self, revnum):
        """Return all history information for a given revision number.
        
        :param revnum: Revision number of revision.
        """
        result = self.cachedb.execute("select path, action, copyfrom_path, copyfrom_rev from changed_path where rev=?", (revnum,))
        paths = {}
        for p, act, cf, cr in result:
            if cf is not None:
                cf = cf.encode("utf-8")
            paths[p.encode("utf-8")] = (act, cf, cr)
        return paths
    
    def changes_path(self, path, revnum):
        """Check whether a path was changed in a particular revision:

        :param path: path to check for
        :param revnum: revision number to fetch
        """
        if path == '':
            return self.cachedb.execute("select count(*) from changed_path where rev=?", (revnum,)).fetchone()[0] > 0
        return self.cachedb.execute("select count(*) from changed_path where rev=? and (path=? or path glob (? || '/*'))", (revnum, path, path)).fetchone()[0] > 0

    def insert_path(self, rev, path, action, copyfrom_path=None, copyfrom_rev=-1):
        """Insert new history information into the cache.
        
        :param rev: Revision number of the revision
        :param path: Path that was changed
        :param action: Action on path (single-character)
        :param copyfrom_path: Optional original path this path was copied from.
        :param copyfrom_rev: Optional original rev this path was copied from.
        """
        assert action in ("A", "R", "D", "M")
        assert not path.startswith("/")
        self.cachedb.execute("replace into changed_path (rev, path, action, copyfrom_path, copyfrom_rev) values (?, ?, ?, ?, ?)", (rev, path, action, copyfrom_path, copyfrom_rev))

    def get_revprops(self, revnum):
        """Retrieve all the cached revision properties.

        :param revnum: Revision number of revision to retrieve revprops for.
        """
        result = self.cachedb.execute("select name, value from revprop where rev = ?", (revnum,))
        revprops = {}
        for k,v in result:
            revprops[k.encode("utf-8")] = v.encode("utf-8")
        return revprops

    def insert_revprop(self, rev, name, value):
        """Add a revision property.

        :param rev: Revision number of the revision.
        :param name: Name of the revision property.
        :param value: Contents of the revision property.
        """
        self.cachedb.execute("replace into revprop (rev, name, value) values (?, ?, ?)", (rev, name, value))
    
    def insert_revprops(self, revision, revprops):
        for k,v in revprops.items():
            self.insert_revprop(revision, k, v)

    def has_all_revprops(self, revnum):
        """Check whether all revprops for a revision have been cached.

        :param revnum: Revision number of the revision.
        """
        return self.cachedb.execute("select all_revprops from revinfo where rev = ?", (revnum,)).fetchone()[0]

    def insert_revinfo(self, rev, all_revprops):
        """Insert metadata for a revision.

        :param rev: Revision number of the revision.
        :param all_revprops: Whether or not the full revprops have been stored.
        """
        self.cachedb.execute("""
            replace into revinfo (rev, all_revprops) values (?, ?)
        """, (rev, all_revprops))

    def last_revnum(self):
        saved_revnum = self.cachedb.execute("SELECT MAX(rev) FROM revinfo").fetchone()[0]
        if saved_revnum is None:
            return 0
        return saved_revnum


class CachingLogWalker(CacheTable):
    """Subversion log browser."""
    def __init__(self, actual, cache_db=None):
        self.cache = LogCache(cache_db)
        self.actual = actual
        self._transport = actual._transport
        self.find_children = actual.find_children

        self.saved_revnum = self.cache.last_revnum()

    def find_latest_change(self, path, revnum):
        """Find latest revision that touched path.

        :param path: Path to check for changes
        :param revnum: First revision to check
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int) and revnum >= 0
        self.fetch_revisions(revnum)

        self.mutter("latest change: %r:%r", path, revnum)
        revnum = self.cache.find_latest_change(path.strip("/"), revnum)
        if revnum is None and path == "":
            return 0
        
        return revnum

    def iter_changes(self, paths, from_revnum, to_revnum=0, limit=0, pb=None):
        """Return iterator over all the revisions between from_revnum and to_revnum named path or inside path.

        :param paths:    Paths to report about.
        :param from_revnum:  Start revision.
        :param to_revnum: End revision.
        :return: An iterator that yields tuples with (paths, revnum, revprops)
            where paths is a dictionary with all changes that happened 
            in revnum.
        """
        assert from_revnum >= 0 and to_revnum >= 0

        ascending = (to_revnum > from_revnum)

        revnum = from_revnum

        self.mutter("iter changes %r->%r (%r)", from_revnum, to_revnum, paths)

        if paths is None:
            path = ""
        else:
            assert len(paths) == 1
            path = paths[0].strip("/")

        assert from_revnum >= to_revnum or path == ""

        self.fetch_revisions(max(from_revnum, to_revnum), pb=pb)
        i = 0

        while ((not ascending and revnum >= to_revnum) or
               (ascending and revnum <= to_revnum)):
            if pb is not None:
                pb.update("determining changes", from_revnum-revnum, from_revnum)
            assert revnum > 0 or path == "", "Inconsistent path,revnum: %r,%r" % (revnum, path)
            revpaths = self.get_revision_paths(revnum)

            if ascending:
                next = (path, revnum+1)
            else:
                next = changes.find_prev_location(revpaths, path, revnum)

            revprops = lazy_dict({}, self.revprop_list, revnum)

            if changes.changes_path(revpaths, path, True):
                assert isinstance(revnum, int)
                yield (revpaths, revnum, revprops)
                i += 1
                if limit != 0 and i == limit:
                    break

            if next is None:
                break

            assert (ascending and next[1] > revnum) or \
                   (not ascending and next[1] < revnum)
            (path, revnum) = next
            assert isinstance(path, str)
            assert isinstance(revnum, int)

    def get_previous(self, path, revnum):
        """Return path,revnum pair specified pair was derived from.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        assert revnum >= 0
        self.fetch_revisions(revnum)
        self.mutter("get previous %r:%r", path, revnum)
        if path == "":
            if revnum == 0:
                return (None, -1)
            return (path, revnum - 1)
        row = self.cache.get_previous(path, revnum)
        if row is None:
            return (path, revnum-1)
        (branch_path, action, copyfrom_path, copyfrom_rev) = row
        branch_path = branch_path.encode('utf-8')
        if copyfrom_path is not None:
            copyfrom_path = copyfrom_path.encode('utf-8')
        assert path == branch_path or path.startswith(branch_path + "/")
        if copyfrom_rev == -1:
            assert path == branch_path
            return (None, -1) # newly added
        return (copyfrom_path + path[len(branch_path):], copyfrom_rev)

    def get_revision_paths(self, revnum):
        if revnum == 0:
            return {'': ('A', None, -1)}
        self.fetch_revisions(revnum)

        return self.cache.get_revision_paths(revnum)

    def get_change(self, path, revnum):
        """Return action,copyfrom_path,copyfrom_revnum tuple for given
        path, or None if no modification occurred in given revision.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        assert revnum >= 0
        self.fetch_revisions(path, revnum)
        
        self.mutter("get previous %r:%r", path, revnum)
        if revnum == 0:
            if path == "":
                return ('A', None, -1)
            return None
        return self.cache.get_change(path, revnum)

    def revprop_list(self, revnum):
        self.mutter("revprop list: %r", revnum)

        self.fetch_revisions(revnum)

        if revnum > 0:
            has_all_revprops = self.cache.has_all_revprops(revnum)
            known_revprops = self.cache.get_revprops(revnum)
        else:
            has_all_revprops = False
            known_revprops = {}

        if has_all_revprops:
            return known_revprops

        return lazy_dict(known_revprops, self._caching_revprop_list, revnum)

    def _caching_revprop_list(self, revnum):
        revprops = self._transport.revprop_list(revnum)
        self.cache.insert_revprops(revnum, revprops)
        self.cache.insert_revinfo(revnum, True)
        self.cache.commit()
        return revprops

    def changes_path(self, path, revnum):
        self.fetch_revisions(revnum)
        return self.cache.changes_path(path, revnum)

    def fetch_revisions(self, to_revnum=None, pb=None):
        """Fetch information about all revisions in the remote repository
        until to_revnum.

        :param to_revnum: End of range to fetch information for
        """
        assert isinstance(self.saved_revnum, int)
        if to_revnum <= self.saved_revnum:
            return
        latest_revnum = self.actual._transport.get_latest_revnum()
        assert isinstance(latest_revnum, int)
        to_revnum = max(latest_revnum, to_revnum)

        # Subversion 1.4 clients and servers can only deliver a limited set of revprops
        if self._transport.has_capability("log-revprops"):
            todo_revprops = None
        else:
            todo_revprops = ["svn:author", "svn:log", "svn:date"]

        def rcvr(orig_paths, revision, revprops, has_children):
            nested_pb.update('fetching svn revision info', revision, to_revnum)
            if orig_paths is None:
                orig_paths = {}
            for p in orig_paths:
                copyfrom_path = orig_paths[p][1]
                if copyfrom_path is not None:
                    copyfrom_path = copyfrom_path.strip("/")

                self.cache.insert_path(revision, p.strip("/"), orig_paths[p][0], copyfrom_path, orig_paths[p][2])
            self.cache.insert_revprops(revision, revprops)
            self.cache.insert_revinfo(revision, todo_revprops is None)
            self.saved_revnum = revision
            self.cache.commit_conditionally()

        self.mutter("get_log %d->%d", self.saved_revnum, to_revnum)

        if pb is None:
            nested_pb = ui.ui_factory.nested_progress_bar()
        else:
            nested_pb = pb

        try:
            nested_pb.update('fetching svn revision info', 0, to_revnum)
            try:
                self.actual._transport.get_log(rcvr, [""], self.saved_revnum, to_revnum, 0, True, True, False, todo_revprops)
            except SubversionException, (_, num):
                if num == ERR_FS_NO_SUCH_REVISION:
                    raise NoSuchRevision(branch=self, 
                        revision="Revision number %d" % to_revnum)
                raise
        finally:
            if pb is None:
                nested_pb.finished()
        self.cache.commit()


def struct_revpaths_to_tuples(changed_paths):
    assert isinstance(changed_paths, dict)
    revpaths = {}
    for k,(action, copyfrom_path, copyfrom_rev) in changed_paths.items():
        if copyfrom_path is None:
            copyfrom_path = None
        else:
            copyfrom_path = copyfrom_path.strip("/")
        revpaths[k.strip("/")] = (action, copyfrom_path, copyfrom_rev)
    return revpaths


class LogWalker(object):
    """Easy way to access the history of a Subversion repository."""
    def __init__(self, transport, limit=None):
        """Create a new instance.

        :param transport:   SvnRaTransport to use to access the repository.
        """
        assert isinstance(transport, SvnRaTransport)

        self._transport = transport

    def find_latest_change(self, path, revnum):
        """Find latest revision that touched path.

        :param path: Path to check for changes
        :param revnum: First revision to check
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int) and revnum >= 0

        try:
            return self._transport.iter_log([path], revnum, 0, 2, True, False, False, []).next()[1]
        except SubversionException, (_, num):
            if num == ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % revnum)
            if num == ERR_FS_NOT_FOUND:
                return None
            raise

    def revprop_list(self, revnum):
        return lazy_dict({}, self._transport.revprop_list, revnum)

    def iter_changes(self, paths, from_revnum, to_revnum=0, limit=0, pb=None):
        """Return iterator over all the revisions between revnum and 0 named path or inside path.

        :param paths:    Paths report about (in revnum)
        :param from_revnum:  Start revision.
        :param to_revnum: End revision.
        :return: An iterator that yields tuples with (paths, revnum, revprops)
            where paths is a dictionary with all changes that happened in revnum.
        """
        assert from_revnum >= 0 and to_revnum >= 0

        try:
            # Subversion 1.4 clients and servers can only deliver a limited set of revprops
            if self._transport.has_capability("log-revprops"):
                todo_revprops = None
            else:
                todo_revprops = ["svn:author", "svn:log", "svn:date"]

            iterator = self._transport.iter_log(paths, from_revnum, to_revnum, limit, 
                                                    True, False, False, revprops=todo_revprops)

            for (changed_paths, revnum, known_revprops, has_children) in iterator:
                if pb is not None:
                    pb.update("determining changes", from_revnum-revnum, from_revnum)
                if revnum == 0 and changed_paths is None:
                    revpaths = {"": ('A', None, -1)}
                else:
                    assert isinstance(changed_paths, dict), "invalid paths %r in %r" % (changed_paths, revnum)
                    revpaths = struct_revpaths_to_tuples(changed_paths)
                if todo_revprops is None:
                    revprops = known_revprops
                else:
                    revprops = lazy_dict(known_revprops, self.revprop_list, revnum)
                yield (revpaths, revnum, revprops)
        except SubversionException, (_, num):
            if num == ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % from_revnum)
            raise

    def get_revision_paths(self, revnum):
        """Obtain dictionary with all the changes in a particular revision.

        :param revnum: Subversion revision number
        :returns: dictionary with paths as keys and 
                  (action, copyfrom_path, copyfrom_rev) as values.
        """
        # To make the existing code happy:
        if revnum == 0:
            return {'': ('A', None, -1)}

        try:
            return struct_revpaths_to_tuples(
                self._transport.iter_log([""], revnum, revnum, 1, True, True, False, []).next()[0])
        except SubversionException, (_, num):
            if num == ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % revnum)
            raise

    def changes_path(self, path, revnum):
        return self.get_revision_paths(revnum).has_key(path)
        
    def find_children(self, path, revnum):
        """Find all children of path in revnum.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        assert isinstance(path, str), "invalid path"
        path = path.strip("/")
        conn = self._transport.connections.get(self._transport.get_svn_repos_root())
        results = []
        unchecked_dirs = set([path])
        try:
            while len(unchecked_dirs) > 0:
                nextp = unchecked_dirs.pop()
                try:
                    dirents = conn.get_dir(nextp, revnum, DIRENT_KIND)[0]
                except SubversionException, (_, num):
                    if num == ERR_FS_NOT_DIRECTORY:
                        continue
                    raise
                for k,v in dirents.items():
                    childp = urlutils.join(nextp, k)
                    if v['kind'] == core.NODE_DIR:
                        unchecked_dirs.add(childp)
                    results.append(childp)
        finally:
            self._transport.connections.add(conn)
        return results

    def get_previous(self, path, revnum):
        """Return path,revnum pair specified pair was derived from.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        assert revnum >= 0
        if revnum == 0:
            return (None, -1)

        try:
            paths = struct_revpaths_to_tuples(self._transport.iter_log([path], revnum, revnum, 1, True, False, False, []).next()[0])
        except SubversionException, (_, num):
            if num == ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % revnum)
            raise

        if not path in paths:
            return (None, -1)

        if paths[path][2] == -1:
            if paths[path][0] in ('A', 'R'):
                return (None, -1)
            return (path, revnum-1)

        return (paths[path][1], paths[path][2])

