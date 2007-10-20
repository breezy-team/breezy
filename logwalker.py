# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
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
import bzrlib.ui as ui
from copy import copy

from svn.core import SubversionException, Pool
from transport import SvnRaTransport
import svn.core

import base64

from cache import sqlite3

LOG_CHUNK_LIMIT = 1000

def _escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    if message is None:
        return None
    import re
    # FIXME: RBC 20060419 this should be done by the revision
    # serialiser not by commit. Then we can also add an unescaper
    # in the deserializer and start roundtripping revision messages
    # precisely. See repository_implementations/test_repository.py
    
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


class LogWalker(object):
    """Easy way to access the history of a Subversion repository."""
    def __init__(self, transport, cache_db=None, limit=None):
        """Create a new instance.

        :param transport:   SvnRaTransport to use to access the repository.
        :param cache_db:    Optional sql database connection to use. Doesn't 
                            cache if not set.
        """
        assert isinstance(transport, SvnRaTransport)

        self.url = transport.base
        self._transport = None

        if limit is not None:
            self._limit = limit
        else:
            self._limit = LOG_CHUNK_LIMIT

        if cache_db is None:
            self.db = sqlite3.connect(":memory:")
        else:
            self.db = cache_db

        self.db.executescript("""
          create table if not exists revision(revno integer unique, author text, message text, date text);
          create unique index if not exists revision_revno on revision (revno);
          create table if not exists changed_path(rev integer, action text, path text, copyfrom_path text, copyfrom_rev integer);
          create index if not exists path_rev on changed_path(rev);
          create unique index if not exists path_rev_path on changed_path(rev, path);
          create unique index if not exists path_rev_path_action on changed_path(rev, path, action);
        """)
        self.db.commit()
        self.saved_revnum = self.db.execute("SELECT MAX(revno) FROM revision").fetchone()[0]
        if self.saved_revnum is None:
            self.saved_revnum = 0

    def _get_transport(self):
        if self._transport is not None:
            return self._transport
        self._transport = SvnRaTransport(self.url)
        return self._transport

    def fetch_revisions(self, to_revnum=None):
        """Fetch information about all revisions in the remote repository
        until to_revnum.

        :param to_revnum: End of range to fetch information for
        """
        if to_revnum <= self.saved_revnum:
            return
        latest_revnum = self._get_transport().get_latest_revnum()
        to_revnum = max(latest_revnum, to_revnum)

        pb = ui.ui_factory.nested_progress_bar()

        def rcvr(orig_paths, rev, author, date, message, pool):
            pb.update('fetching svn revision info', rev, to_revnum)
            if orig_paths is None:
                orig_paths = {}
            for p in orig_paths:
                copyfrom_path = orig_paths[p].copyfrom_path
                if copyfrom_path is not None:
                    copyfrom_path = copyfrom_path.strip("/")

                self.db.execute(
                     "replace into changed_path (rev, path, action, copyfrom_path, copyfrom_rev) values (?, ?, ?, ?, ?)", 
                     (rev, p.strip("/"), orig_paths[p].action, copyfrom_path, orig_paths[p].copyfrom_rev))

            if message is not None:
                message = base64.b64encode(message)

            self.db.execute("replace into revision (revno, author, date, message) values (?,?,?,?)", (rev, author, date, message))

            self.saved_revnum = rev
            if self.saved_revnum % 1000 == 0:
                self.db.commit()

        try:
            try:
                while self.saved_revnum < to_revnum:
                    pool = Pool()
                    self._get_transport().get_log("/", self.saved_revnum, 
                                             to_revnum, self._limit, True, 
                                             True, rcvr, pool)
                    pool.destroy()
            finally:
                pb.finished()
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % to_revnum)
            raise
        self.db.commit()

    def follow_path(self, path, revnum):
        """Return iterator over all the revisions between revnum and 
        0 named path or inside path.

        :param path:   Branch path to start reporting (in revnum)
        :param revnum:        Start revision.

        :return: An iterators that yields tuples with (path, paths, revnum)
        where paths is a dictionary with all changes that happened in path 
        in revnum.
        """
        assert revnum >= 0

        if revnum == 0 and path == "":
            return

        recurse = (path != "")

        path = path.strip("/")

        while revnum >= 0:
            assert revnum > 0 or path == ""
            revpaths = self.get_revision_paths(revnum, path, recurse=recurse)

            if revpaths != {}:
                yield (path, copy(revpaths), revnum)

            if path == "":
                revnum -= 1
                continue

            if revpaths.has_key(path):
                if revpaths[path][1] is None:
                    if revpaths[path][0] in ('A', 'R'):
                        # this path didn't exist before this revision
                        return
                else:
                    # In this revision, this path was copied from 
                    # somewhere else
                    revnum = revpaths[path][2]
                    path = revpaths[path][1]
                    assert path == "" or revnum > 0
                    continue
            revnum -= 1
            for p in sorted(revpaths.keys()):
                if path.startswith(p+"/") and revpaths[p][0] in ('A', 'R'):
                    assert revpaths[p][1]
                    path = path.replace(p, revpaths[p][1])
                    revnum = revpaths[p][2]
                    break

    def get_revision_paths(self, revnum, path=None, recurse=False):
        """Obtain dictionary with all the changes in a particular revision.

        :param revnum: Subversion revision number
        :param path: optional path under which to return all entries
        :param recurse: Report changes to parents as well
        :returns: dictionary with paths as keys and 
                  (action, copyfrom_path, copyfrom_rev) as values.
        """

        if revnum == 0:
            assert path is None or path == ""
            return {'': ('A', None, -1)}
                
        self.fetch_revisions(revnum)

        query = "select path, action, copyfrom_path, copyfrom_rev from changed_path where rev="+str(revnum)
        if path is not None and path != "":
            query += " and (path='%s' or path like '%s/%%'" % (path, path)
            if recurse:
                query += " or ('%s' LIKE path || '/%%')" % path
            query += ")"

        paths = {}
        for p, act, cf, cr in self.db.execute(query):
            paths[p.encode("utf-8")] = (act, cf, cr)
        return paths

    def get_revision_info(self, revnum):
        """Obtain basic information for a specific revision.

        :param revnum: Revision number.
        :returns: Tuple with author, log message and date of the revision.
        """
        assert revnum >= 0
        if revnum == 0:
            return (None, None, None)
        self.fetch_revisions(revnum)
        (author, message, date) = self.db.execute("select author, message, date from revision where revno="+ str(revnum)).fetchone()
        if message is not None:
            message = _escape_commit_message(base64.b64decode(message))
        return (author, message, date)

    def find_latest_change(self, path, revnum, include_parents=False,
                           include_children=False):
        """Find latest revision that touched path.

        :param path: Path to check for changes
        :param revnum: First revision to check
        """
        assert isinstance(path, basestring)
        assert isinstance(revnum, int) and revnum >= 0
        self.fetch_revisions(revnum)

        extra = ""
        if include_children:
            if path == "":
                extra += " OR path LIKE '%'"
            else:
                extra += " OR path LIKE '%s/%%'" % path.strip("/")
        if include_parents:
            extra += " OR ('%s' LIKE (path || '/%%') AND (action = 'R' OR action = 'A'))" % path.strip("/")
        query = "SELECT rev FROM changed_path WHERE (path='%s'%s) AND rev <= %d ORDER BY rev DESC LIMIT 1" % (path.strip("/"), extra, revnum)

        row = self.db.execute(query).fetchone()
        if row is None and path == "":
            return 0

        if row is None:
            return None

        return row[0]

    def touches_path(self, path, revnum):
        """Check whether path was changed in specified revision.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        self.fetch_revisions(revnum)
        if revnum == 0:
            return (path == "")
        return (self.db.execute("select 1 from changed_path where path='%s' and rev=%d" % (path, revnum)).fetchone() is not None)

    def find_children(self, path, revnum):
        """Find all children of path in revnum."""
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
        edit, baton = svn.delta.make_editor(editor, pool)
        old_base = transport.base
        try:
            root_repos = transport.get_svn_repos_root()
            transport.reparent(urlutils.join(root_repos, path))
            reporter = transport.do_update(revnum,  True, edit, baton, pool)
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
        self.fetch_revisions(revnum)
        if revnum == 0:
            return (None, -1)
        row = self.db.execute("select action, copyfrom_path, copyfrom_rev from changed_path where path='%s' and rev=%d" % (path, revnum)).fetchone()
        if row[2] == -1:
            if row[0] == 'A':
                return (None, -1)
            return (path, revnum-1)
        return (row[1], row[2])
