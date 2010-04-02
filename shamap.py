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
    btree_index as _mod_btree_index,
    index as _mod_index,
    knit,
    osutils,
    trace,
    versionedfile,
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

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.
        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        raise NotImplementedError(self.lookup_git_sha)

    def lookup_blob_id(self, file_id, revision):
        """Retrieve a Git blob SHA by file id.

        :param file_id: File id of the file/symlink
        :param revision: revision in which the file was last changed.
        """
        raise NotImplementedError(self.lookup_blob_id)

    def lookup_tree_id(self, file_id, revision):
        """Retrieve a Git tree SHA by file id.
        """
        raise NotImplementedError(self.lookup_tree_id)

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

    def lookup_blob_id(self, fileid, revision):
        return self._by_fileid[revision][fileid]

    def lookup_git_sha(self, sha):
        return self._by_sha[sha]

    def lookup_tree_id(self, fileid, revision):
        return self._base._by_fileid[revision][fileid]

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
                pass # removal
            elif kind == "tree":
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

    def lookup_blob_id(self, fileid, revision):
        row = self.db.execute("select sha1 from blobs where fileid = ? and revid = ?", (fileid, revision)).fetchone()
        if row is not None:
            return row[0]
        raise KeyError(fileid)

    def lookup_tree_id(self, fileid, revision):
        row = self.db.execute("select sha1 from trees where fileid = ? and revid = ?", (fileid, self.revid)).fetchone()
        if row is not None:
            return row[0]
        raise KeyError(fileid)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        row = self.db.execute("select revid, tree_sha from commits where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return ("commit", row)
        row = self.db.execute("select fileid, revid from blobs where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return ("blob", row)
        row = self.db.execute("select fileid, revid from trees where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return ("tree", row)
        raise KeyError(sha)

    def revids(self):
        """List the revision ids known."""
        return (row for (row,) in self.db.execute("select revid from commits"))

    def sha1s(self):
        """List the SHA1s."""
        for table in ("blobs", "commits", "trees"):
            for (sha,) in self.db.execute("select sha1 from %s" % table):
                yield sha


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

    def start_write_group(self):
        """Start writing changes."""
        self.db.transaction_start()

    def commit_write_group(self):
        """Commit any pending changes."""
        self.db.transaction_commit()

    def abort_write_group(self):
        """Abort any pending changes."""
        self.db.transaction_cancel()

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

    def lookup_blob_id(self, fileid, revision):
        return sha_to_hex(self.db["\0".join(("blob", fileid, revision))])
                
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

INDEX_FORMAT = 'bzr-git sha map version 1'


class IndexGitShaMap(GitShaMap):
    """SHA Map that uses the Bazaar APIs to store a cache.

    BTree Index file with the following contents:

    ("git", <sha1>) -> "<type> <type-data1> <type-data2>"
    ("commit", <revid>) -> "<sha1> <tree-id>"
    ("blob", <fileid>, <revid>) -> <sha1>

    """

    def __init__(self, transport=None):
        self._transport = transport
        if transport is None:
            self._index_transport = None
            self._index = _mod_index.InMemoryGraphIndex(0, key_elements=3)
            self._builder = self._index
        else:
            self._builder = None
            try:
                transport.mkdir('index')
            except bzrlib.errors.FileExists:
                pass
            self._index_transport = transport.clone('index')
            try:
                format = self._index_transport.get_bytes('format')
            except bzrlib.errors.NoSuchFile:
                self._index_transport.put_bytes('format', INDEX_FORMAT)
            else:
                if format != INDEX_FORMAT:
                    trace.warning("SHA Map is incompatible (%s -> %s), rebuilding database.",
                                  format, INDEX_FORMAT)
                    raise KeyError
            self._index = _mod_index.CombinedGraphIndex([])
            for name in self._index_transport.list_dir("."):
                if not name.endswith(".rix"):
                    continue
                x = _mod_btree_index.BTreeGraphIndex(self._index_transport, name, self._index_transport.stat(name).st_size)
                self._index.insert_index(0, x)
            mapper = versionedfile.ConstantMapper("trees1")
            self._trees_store = knit.make_file_factory(True, mapper)(transport)

    @classmethod
    def from_repository(cls, repository):
        transport = getattr(repository, "_transport", None)
        if transport is not None:
            try:
                transport.mkdir('git')
            except bzrlib.errors.FileExists:
                pass
            return cls(transport.clone('git'))
        from bzrlib.transport import get_transport
        return cls(get_transport(get_cache_dir()))

    def __repr__(self):
        if self._transport is not None:
            return "%s(%r)" % (self.__class__.__name__, self._transport.base)
        else:
            return "%s()" % (self.__class__.__name__)

    def repack(self):
        assert self._builder is None
        self.start_write_group()
        for _, key, value in self._index.iter_all_entries():
            self._builder.add_node(key, value)
        to_remove = []
        for name in self._index_transport.list_dir('.'):
            if name.endswith('.rix'):
                to_remove.append(name)
        self.commit_write_group()
        del self._index.indices[1:]
        for name in to_remove:
            self._index_transport.rename(name, name + '.old')

    def start_write_group(self):
        assert self._builder is None
        self._builder = _mod_btree_index.BTreeBuilder(0, key_elements=3)
        self._name = osutils.sha()

    def commit_write_group(self):
        assert self._builder is not None
        stream = self._builder.finish()
        name = self._name.hexdigest() + ".rix"
        size = self._index_transport.put_file(name, stream)
        index = _mod_btree_index.BTreeGraphIndex(self._index_transport, name, size)
        self._index.insert_index(0, index)
        self._builder = None
        self._name = None

    def abort_write_group(self):
        assert self._builder is not None
        self._builder = None
        self._name = None

    def _add_node(self, key, value):
        try:
            self._builder.add_node(key, value)
        except bzrlib.errors.BadIndexDuplicateKey:
            # Multiple bzr objects can have the same contents
            return True
        else:
            return False

    def _get_entry(self, key):
        entries = self._index.iter_entries([key])
        try:
            return entries.next()[2]
        except StopIteration:
            if self._builder is None:
                raise KeyError
            entries = self._builder.iter_entries([key])
            try:
                return entries.next()[2]
            except StopIteration:
                raise KeyError

    def _iter_keys_prefix(self, prefix):
        for entry in self._index.iter_entries_prefix([prefix]):
            yield entry[1]
        if self._builder is not None:
            for entry in self._builder.iter_entries_prefix([prefix]):
                yield entry[1]

    def lookup_commit(self, revid):
        return self._get_entry(("commit", revid, "X"))[:40]

    def _add_git_sha(self, hexsha, type, type_data):
        if hexsha is not None:
            self._name.update(hexsha)
            self._add_node(("git", hexsha, "X"),
                " ".join((type, type_data[0], type_data[1])))
        else:
            # This object is not represented in Git - perhaps an empty
            # directory?
            self._name.update(type + " ".join(type_data))

    def add_entries(self, revid, parent_revids, commit_sha, root_tree_sha,
                    entries):
        self._add_git_sha(commit_sha, "commit", (revid, root_tree_sha))
        self._add_node(("commit", revid, "X"), " ".join((commit_sha, root_tree_sha)))
        for (fileid, kind, hexsha, revision) in entries:
            if kind is None:
                pass # Removal
            elif kind == "blob":
                self._add_git_sha(hexsha, "blob", (fileid, revision))
                self._add_node(("blob", fileid, revision), hexsha)
            elif kind == "tree":
                self._add_git_sha(hexsha, "tree", (fileid, revid))
            else:
                raise AssertionError

    def lookup_blob_id(self, fileid, revision):
        return self._get_entry(("blob", fileid, revision))

    def lookup_git_sha(self, sha):
        if len(sha) == 20:
            sha = sha_to_hex(sha)
        data = self._get_entry(("git", sha, "X")).split(" ", 2)
        return (data[0], (data[1], data[2]))

    def revids(self):
        """List the revision ids known."""
        for key in self._iter_keys_prefix(("commit", None, None)):
            yield key[1]

    def missing_revisions(self, revids):
        """Return set of all the revisions that are not present."""
        missing_revids = set(revids)
        for _, key, value in self._index.iter_entries((
            ("commit", revid, "X") for revid in revids)):
            missing_revids.remove(key[1])
        return missing_revids

    def sha1s(self):
        """List the SHA1s."""
        for key in self._iter_keys_prefix(("git", None, None)):
            yield key[1]


def from_repository(repository):
    return IndexGitShaMap.from_repository(repository)
    try:
        return TdbGitShaMap.from_repository(repository)
    except ImportError:
        return SqliteGitShaMap.from_repository(repository)
