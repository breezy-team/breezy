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

from svn.core import SubversionException, Pool
from transport import SvnRaTransport
import svn.core

from cache import CacheTable
import changes

LOG_CHUNK_LIMIT = 0

class lazy_dict(object):
    def __init__(self, create_fn, *args):
        self.create_fn = create_fn
        self.args = args
        self.dict = None

    def _ensure_init(self):
        if self.dict is None:
            self.dict = self.create_fn(*self.args)

    def __len__(self):
        self._ensure_init()
        return len(self.dict)

    def __getitem__(self, key):
        self._ensure_init()
        return self.dict.__getitem__(key)

    def __setitem__(self, key, value):
        self._ensure_init()
        return self.dict.__setitem__(key, value)

    def __contains__(self, key):
        self._ensure_init()
        return self.dict.__contains__(key)

    def get(self, key, default=None):
        self._ensure_init()
        return self.dict.get(key, default)

    def has_key(self, key):
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





class CachingLogWalker(CacheTable):
    """Subversion log browser."""
    def __init__(self, actual, cache_db=None):
        CacheTable.__init__(self, cache_db)

        self.actual = actual
        self._get_transport = actual._get_transport
        self.find_children = actual.find_children

        self.saved_revnum = self.cachedb.execute("SELECT MAX(rev) FROM changed_path").fetchone()[0]
        if self.saved_revnum is None:
            self.saved_revnum = 0

    def _create_table(self):
        self.cachedb.executescript("""
          create table if not exists changed_path(rev integer, action text, path text, copyfrom_path text, copyfrom_rev integer);
          create index if not exists path_rev on changed_path(rev);
          create unique index if not exists path_rev_path on changed_path(rev, path);
          create unique index if not exists path_rev_path_action on changed_path(rev, path, action);
        """)

    def find_latest_change(self, path, revnum, include_parents=False,
                           include_children=False):
        """Find latest revision that touched path.

        :param path: Path to check for changes
        :param revnum: First revision to check
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int) and revnum >= 0
        self.fetch_revisions(revnum)

        self.mutter("latest change: %r:%r" % (path, revnum))

        extra = ""
        if include_children:
            if path == "":
                extra += " OR path LIKE '%'"
            else:
                extra += " OR path LIKE '%s/%%'" % path.strip("/")
        if include_parents:
            extra += " OR ('%s' LIKE (path || '/%%') AND (action = 'R' OR action = 'A'))" % path.strip("/")
        query = "SELECT rev FROM changed_path WHERE (path='%s'%s) AND rev <= %d ORDER BY rev DESC LIMIT 1" % (path.strip("/"), extra, revnum)

        row = self.cachedb.execute(query).fetchone()
        if row is None and path == "":
            return 0

        if row is None:
            return None

        return row[0]

    def iter_changes(self, path, revnum):
        """Return iterator over all the revisions between revnum and 0 named path or inside path.

        :param path:    Branch path to start reporting (in revnum)
        :param revnum:  Start revision.
        :return: An iterator that yields tuples with (path, paths, revnum, revprops)
            where paths is a dictionary with all changes that happened in path 
            in revnum.
        """
        assert revnum >= 0

        self.mutter("iter changes %r:%r" % (path, revnum))

        recurse = (path != "")

        path = path.strip("/")

        while revnum >= 0:
            assert revnum > 0 or path == ""
            revpaths = self.get_revision_paths(revnum)

            next = changes.find_prev_location(revpaths, path, revnum)

            revprops = lazy_dict(self._get_transport().revprop_list, revnum)

            if changes.changes_path(revpaths, path, True):
                yield (path, revpaths, revnum, revprops)

            if next is None:
                break

            (path, revnum) = next

    def get_previous(self, path, revnum):
        """Return path,revnum pair specified pair was derived from.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        assert revnum >= 0
        self.fetch_revisions(revnum)
        self.mutter("get previous %r:%r" % (path, revnum))
        if revnum == 0:
            return (None, -1)
        row = self.cachedb.execute("select action, copyfrom_path, copyfrom_rev from changed_path where path='%s' and rev=%d" % (path, revnum)).fetchone()
        if row is None:
            return (None, -1)
        if row[2] == -1:
            if row[0] == 'A':
                return (None, -1)
            return (path, revnum-1)
        return (row[1], row[2])

    def get_revision_paths(self, revnum):
        """Obtain dictionary with all the changes in a particular revision.

        :param revnum: Subversion revision number
        :returns: dictionary with paths as keys and 
                  (action, copyfrom_path, copyfrom_rev) as values.
        """

        if revnum == 0:
            return {'': ('A', None, -1)}

        self.mutter("revision paths: %r" % revnum)
                
        self.fetch_revisions(revnum)

        query = "select path, action, copyfrom_path, copyfrom_rev from changed_path where rev="+str(revnum)

        paths = {}
        for p, act, cf, cr in self.cachedb.execute(query):
            if cf is not None:
                cf = cf.encode("utf-8")
            paths[p.encode("utf-8")] = (act, cf, cr)
        return paths

    def fetch_revisions(self, to_revnum=None):
        """Fetch information about all revisions in the remote repository
        until to_revnum.

        :param to_revnum: End of range to fetch information for
        """
        if to_revnum <= self.saved_revnum:
            return
        latest_revnum = self.actual._get_transport().get_latest_revnum()
        to_revnum = max(latest_revnum, to_revnum)

        pb = ui.ui_factory.nested_progress_bar()

        def rcvr(log_entry, pool):
            pb.update('fetching svn revision info', log_entry.revision, to_revnum)
            orig_paths = log_entry.changed_paths
            if orig_paths is None:
                orig_paths = {}
            for p in orig_paths:
                copyfrom_path = orig_paths[p].copyfrom_path
                if copyfrom_path is not None:
                    copyfrom_path = copyfrom_path.strip("/")

                self.cachedb.execute(
                     "replace into changed_path (rev, path, action, copyfrom_path, copyfrom_rev) values (?, ?, ?, ?, ?)", 
                     (log_entry.revision, p.strip("/"), orig_paths[p].action, copyfrom_path, orig_paths[p].copyfrom_rev))
                # Work around nasty memory leak in Subversion
                orig_paths[p]._parent_pool.destroy()

            self.saved_revnum = log_entry.revision
            if self.saved_revnum % 1000 == 0:
                self.cachedb.commit()

        try:
            try:
                while self.saved_revnum < to_revnum:
                    pool = Pool()
                    self.actual._get_transport().get_log("", self.saved_revnum, 
                                             to_revnum, self.actual._limit, True, 
                                             True, [], rcvr, pool)
                    pool.destroy()
            finally:
                pb.finished()
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % to_revnum)
            raise
        self.cachedb.commit()


class LogWalker(object):
    """Easy way to access the history of a Subversion repository."""
    def __init__(self, transport, limit=None):
        """Create a new instance.

        :param transport:   SvnRaTransport to use to access the repository.
        """
        assert isinstance(transport, SvnRaTransport)

        self.url = transport.base
        self._transport = None

        if limit is not None:
            self._limit = limit
        else:
            self._limit = LOG_CHUNK_LIMIT

    def _get_transport(self):
        if self._transport is not None:
            return self._transport
        self._transport = SvnRaTransport(self.url)
        return self._transport

    def find_latest_change(self, path, revnum, include_parents=False,
                           include_children=False):
        """Find latest revision that touched path.

        :param path: Path to check for changes
        :param revnum: First revision to check
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int) and revnum >= 0
        raise NotImplementedError

    def iter_changes(self, path, revnum):
        """Return iterator over all the revisions between revnum and 0 named path or inside path.

        :param path:    Branch path to start reporting (in revnum)
        :param revnum:  Start revision.
        :return: An iterator that yields tuples with (path, paths, revnum, revprops)
            where paths is a dictionary with all changes that happened in path 
            in revnum.
        """
        assert revnum >= 0

        raise NotImplementedError

    def get_revision_paths(self, revnum):
        """Obtain dictionary with all the changes in a particular revision.

        :param revnum: Subversion revision number
        :returns: dictionary with paths as keys and 
                  (action, copyfrom_path, copyfrom_rev) as values.
        """
        raise NotImplementedError
        
    def find_children(self, path, revnum):
        """Find all children of path in revnum.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        path = path.strip("/")
        transport = self._get_transport()
        ft = transport.check_path(path, revnum)
        if ft == svn.core.svn_node_file:
            return []
        assert ft == svn.core.svn_node_dir

        class TreeLister(svn.delta.Editor):
            def __init__(self, base):
                self.files = []
                self.base = base

            def set_target_revision(self, revnum):
                """See Editor.set_target_revision()."""
                pass

            def open_root(self, revnum, baton):
                """See Editor.open_root()."""
                return path

            def add_directory(self, path, parent_baton, copyfrom_path, copyfrom_revnum, pool):
                """See Editor.add_directory()."""
                self.files.append(urlutils.join(self.base, path))
                return path

            def change_dir_prop(self, id, name, value, pool):
                pass

            def change_file_prop(self, id, name, value, pool):
                pass

            def add_file(self, path, parent_id, copyfrom_path, copyfrom_revnum, baton):
                self.files.append(urlutils.join(self.base, path))
                return path

            def close_dir(self, id):
                pass

            def close_file(self, path, checksum):
                pass

            def close_edit(self):
                pass

            def abort_edit(self):
                pass

            def apply_textdelta(self, file_id, base_checksum):
                pass
        pool = Pool()
        editor = TreeLister(path)
        old_base = transport.base
        try:
            root_repos = transport.get_svn_repos_root()
            transport.reparent(urlutils.join(root_repos, path))
            reporter = transport.do_update(revnum, True, editor, pool)
            reporter.set_path("", revnum, True, None, pool)
            reporter.finish_report(pool)
        finally:
            transport.reparent(old_base)
        return editor.files

    def get_previous(self, path, revnum):
        """Return path,revnum pair specified pair was derived from.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        assert revnum >= 0
        raise NotImplementedError
