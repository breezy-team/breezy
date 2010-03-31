# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Map from Git sha's to Bazaar objects."""

from dulwich.objects import (
    sha_to_hex,
    hex_to_sha,
    )
import os
import threading

import bzrlib
from bzrlib import (
    trace,
    )


def get_cache_dir():
    try:
        from xdg.BaseDirectory import xdg_cache_home
    except ImportError:
        from bzrlib.config import config_dir
        ret = os.path.join(config_dir(), "git")
    else:
        ret = os.path.join(xdg_cache_home, "bazaar", "git")
    if not os.path.isdir(ret):
        os.makedirs(ret)
    return ret


def check_pysqlite_version(sqlite3):
    """Check that sqlite library is compatible.

    """
    if (sqlite3.sqlite_version_info[0] < 3 or
            (sqlite3.sqlite_version_info[0] == 3 and
             sqlite3.sqlite_version_info[1] < 3)):
        trace.warning('Needs at least sqlite 3.3.x')
        raise bzrlib.errors.BzrError("incompatible sqlite library")

try:
    try:
        import sqlite3
        check_pysqlite_version(sqlite3)
    except (ImportError, bzrlib.errors.BzrError), e:
        from pysqlite2 import dbapi2 as sqlite3
        check_pysqlite_version(sqlite3)
except:
    trace.warning('Needs at least Python2.5 or Python2.4 with the pysqlite2 '
            'module')
    raise bzrlib.errors.BzrError("missing sqlite library")


_mapdbs = threading.local()
def mapdbs():
    """Get a cache for this thread's db connections."""
    try:
        return _mapdbs.cache
    except AttributeError:
        _mapdbs.cache = {}
        return _mapdbs.cache


class InventorySHAMap(object):
    """Maps inventory file ids to Git SHAs."""

    def lookup_blob(self, file_id, revision):
        """Retrieve a Git blob SHA by file id.

        :param file_id: File id of the file/symlink
        :param revision: revision in which the file was last changed.
        """
        raise NotImplementedError(self.lookup_blob)

    def lookup_tree(self, file_id):
        """Retrieve a Git tree SHA by file id.
        """
        raise NotImplementedError(self.lookup_tree)


class GitShaMap(object):
    """Git<->Bzr revision id mapping database."""

    def _add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        raise NotImplementedError(self._add_entry)

    def add_entries(self, revid, parent_revids, commit_sha, root_tree_sha, 
                    entries):
        """Add multiple new entries to the database.
        """
        for (fileid, kind, hexsha, revision) in entries:
            self._add_entry(hexsha, kind, (fileid, revision))
        self._add_entry(commit_sha, "commit", (revid, root_tree_sha))

    def get_inventory_sha_map(self, revid):
        """Return the inventory SHA map for a revision.

        :param revid: Revision to fetch the map for
        :return: A `InventorySHAMap`
        """
        raise NotImplementedError(self.get_inventory_sha_map)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.
        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        raise NotImplementedError(self.lookup_git_sha)

    def revids(self):
        """List the revision ids known."""
        raise NotImplementedError(self.revids)

    def missing_revisions(self, revids):
        """Return set of all the revisions that are not present."""
        present_revids = set(self.revids())
        if not isinstance(revids, set):
            revids = set(revids)
        return revids - present_revids

    def sha1s(self):
        """List the SHA1s."""
        raise NotImplementedError(self.sha1s)

    def start_write_group(self):
        """Start writing changes."""

    def commit_write_group(self):
        """Commit any pending changes."""

    def abort_write_group(self):
        """Abort any pending changes."""


class DictGitShaMap(GitShaMap):

    def __init__(self):
        self._by_sha = {}
        self._by_fileid = {}

    def _add_entry(self, sha, type, type_data):
        self._by_sha[sha] = (type, type_data)
        if type in ("blob", "tree"):
            self._by_fileid.setdefault(type_data[1], {})[type_data[0]] = sha

    def get_inventory_sha_map(self, revid):

        class DictInventorySHAMap(InventorySHAMap):

            def __init__(self, base, revid):
                self._base = base
                self.revid = revid

            def lookup_blob(self, fileid, revision):
                return self._base._by_fileid[revision][fileid]

            def lookup_tree(self, fileid):
                return self._base._by_fileid[self.revid][fileid]

        return DictInventorySHAMap(self, revid)

    def lookup_git_sha(self, sha):
        return self._by_sha[sha]

    def revids(self):
        for key, (type, type_data) in self._by_sha.iteritems():
            if type == "commit":
                yield type_data[0]

    def sha1s(self):
        return self._by_sha.iterkeys()


class SqliteGitShaMap(GitShaMap):

    def __init__(self, path=None):
        self.path = path
        if path is None:
            self.db = sqlite3.connect(":memory:")
        else:
            if not mapdbs().has_key(path):
                mapdbs()[path] = sqlite3.connect(path)
            self.db = mapdbs()[path]
        self.db.text_factory = str
        self.db.executescript("""
        create table if not exists commits(
            sha1 text not null check(length(sha1) == 40),
            revid text not null,
            tree_sha text not null check(length(tree_sha) == 40)
        );
        create index if not exists commit_sha1 on commits(sha1);
        create unique index if not exists commit_revid on commits(revid);
        create table if not exists blobs(
            sha1 text not null check(length(sha1) == 40),
            fileid text not null,
            revid text not null
        );
        create index if not exists blobs_sha1 on blobs(sha1);
        create unique index if not exists blobs_fileid_revid on blobs(fileid, revid);
        create table if not exists trees(
            sha1 text unique not null check(length(sha1) == 40),
            fileid text not null,
            revid text not null
        );
        create unique index if not exists trees_sha1 on trees(sha1);
        create unique index if not exists trees_fileid_revid on trees(fileid, revid);
""")

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.path)
    
    @classmethod
    def from_repository(cls, repository):
        try:
            transport = getattr(repository, "_transport", None)
            if transport is not None:
                return cls(os.path.join(transport.local_abspath("."), "git.db"))
        except bzrlib.errors.NotLocalUrl:
            pass
        return cls(os.path.join(get_cache_dir(), "remote.db"))

    def lookup_commit(self, revid):
        row = self.db.execute("select sha1 from commits where revid = ?", (revid,)).fetchone()
        if row is not None:
            return row[0]
        raise KeyError

    def commit_write_group(self):
        self.db.commit()

    def add_entries(self, revid, parent_revids, commit_sha, root_tree_sha,
                    entries):
        trees = []
        blobs = []
        for (fileid, kind, hexsha, revision) in entries:
            if kind is None:
                continue
            if kind == "tree":
                trees.append((hexsha, fileid, revid))
            elif kind == "blob":
                blobs.append((hexsha, fileid, revision))
            else:
                raise AssertionError
        if trees:
            self.db.executemany("replace into trees (sha1, fileid, revid) values (?, ?, ?)", trees)
        if blobs:
            self.db.executemany("replace into blobs (sha1, fileid, revid) values (?, ?, ?)", blobs)
        self._add_entry(commit_sha, "commit", (revid, root_tree_sha))

    def _add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        assert isinstance(type_data, tuple)
        if sha is None:
            return
        assert isinstance(sha, str), "type was %r" % sha
        if type == "commit":
            self.db.execute("replace into commits (sha1, revid, tree_sha) values (?, ?, ?)", (sha, type_data[0], type_data[1]))
        elif type in ("blob", "tree"):
            self.db.execute("replace into %ss (sha1, fileid, revid) values (?, ?, ?)" % type, (sha, type_data[0], type_data[1]))
        else:
            raise AssertionError("Unknown type %s" % type)

    def get_inventory_sha_map(self, revid):
        class SqliteInventorySHAMap(InventorySHAMap):

            def __init__(self, db, revid):
                self.db = db
                self.revid = revid

            def lookup_blob(self, fileid, revision):
                row = self.db.execute("select sha1 from blobs where fileid = ? and revid = ?", (fileid, revision)).fetchone()
                if row is not None:
                    return row[0]
                raise KeyError(fileid)

            def lookup_tree(self, fileid):
                row = self.db.execute("select sha1 from trees where fileid = ? and revid = ?", (fileid, self.revid)).fetchone()
                if row is not None:
                    return row[0]
                raise KeyError(fileid)

        return SqliteInventorySHAMap(self.db, revid)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        def format(type, row):
            return (type, (row[0], row[1]))
        row = self.db.execute("select revid, tree_sha from commits where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return format("commit", row)
        row = self.db.execute("select fileid, revid from blobs where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return format("blob", row)
        row = self.db.execute("select fileid, revid from trees where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return format("tree", row)
        raise KeyError(sha)

    def revids(self):
        """List the revision ids known."""
        return (row for (row,) in self.db.execute("select revid from commits"))

    def sha1s(self):
        """List the SHA1s."""
        for table in ("blobs", "commits", "trees"):
            trace.note(table)
            for (row,) in self.db.execute("select sha1 from %s" % table):
                yield row


TDB_MAP_VERSION = 3
TDB_HASH_SIZE = 50000


class TdbGitShaMap(GitShaMap):
    """SHA Map that uses a TDB database.

    Entries:

    "git <sha1>" -> "<type> <type-data1> <type-data2>"
    "commit revid" -> "<sha1> <tree-id>"
    "tree fileid revid" -> "<sha1>"
    "blob fileid revid" -> "<sha1>"
    """

    def __init__(self, path=None):
        import tdb
        self.path = path
        if path is None:
            self.db = {}
        else:
            if not mapdbs().has_key(path):
                mapdbs()[path] = tdb.Tdb(path, TDB_HASH_SIZE, tdb.DEFAULT,
                                          os.O_RDWR|os.O_CREAT)
            self.db = mapdbs()[path]
        try:
            if int(self.db["version"]) not in (2, 3):
                trace.warning("SHA Map is incompatible (%s -> %d), rebuilding database.",
                              self.db["version"], TDB_MAP_VERSION)
                self.db.clear()
        except KeyError:
            pass
        self.db["version"] = str(TDB_MAP_VERSION)

    def add_entries(self, revid, parent_revids, commit_sha, root_tree_sha, 
                    entries):
        """Add multiple new entries to the database.
        """
        self.db.transaction_start()
        try:
            self._add_entry(commit_sha, "commit", (revid, root_tree_sha))
            for (fileid, kind, hexsha, revision) in entries:
                self._add_entry(hexsha, kind, (fileid, revision))
        except:
            self.db.transaction_cancel()
            raise
        else:
            self.db.transaction_commit()

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.path)

    @classmethod
    def from_repository(cls, repository):
        try:
            transport = getattr(repository, "_transport", None)
            if transport is not None:
                return cls(os.path.join(transport.local_abspath("."), "git.tdb"))
        except bzrlib.errors.NotLocalUrl:
            pass
        return cls(os.path.join(get_cache_dir(), "remote.tdb"))

    def lookup_commit(self, revid):
        return sha_to_hex(self.db["commit\0" + revid][:20])

    def _add_entry(self, hexsha, type, type_data):
        """Add a new entry to the database.
        """
        if hexsha is None:
            sha = ""
        else:
            sha = hex_to_sha(hexsha)
            self.db["git\0" + sha] = "\0".join((type, type_data[0], type_data[1]))
        if type == "commit":
            self.db["commit\0" + type_data[0]] = "\0".join((sha, type_data[1]))
        elif type == "blob":
            self.db["\0".join(("blob", type_data[0], type_data[1]))] = sha

    def get_inventory_sha_map(self, revid):

        class TdbInventorySHAMap(InventorySHAMap):

            def __init__(self, db, revid):
                self.db = db
                self.revid = revid

            def lookup_blob(self, fileid, revision):
                return sha_to_hex(self.db["\0".join(("blob", fileid, revision))])
                
        return TdbInventorySHAMap(self.db, revid)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        if len(sha) == 40:
            sha = hex_to_sha(sha)
        data = self.db["git\0" + sha].split("\0")
        return (data[0], (data[1], data[2]))

    def missing_revisions(self, revids):
        ret = set()
        for revid in revids:
            if self.db.get("commit\0" + revid) is None:
                ret.add(revid)
        return ret

    def revids(self):
        """List the revision ids known."""
        for key in self.db.iterkeys():
            if key.startswith("commit\0"):
                yield key[7:]

    def sha1s(self):
        """List the SHA1s."""
        for key in self.db.iterkeys():
            if key.startswith("git\0"):
                yield sha_to_hex(key[4:])


def from_repository(repository):
    try:
        return TdbGitShaMap.from_repository(repository)
    except ImportError:
        return SqliteGitShaMap.from_repository(repository)
