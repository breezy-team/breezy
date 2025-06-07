# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Map from Git sha's to Bazaar objects."""

import contextlib
import hashlib
import os
import threading

from dulwich.objects import ShaFile, hex_to_sha, sha_to_hex

from bzrformats import btree_index as _mod_btree_index
from bzrformats import index as _mod_index
from bzrformats import versionedfile

from .. import errors as bzr_errors
from .. import registry, trace
from .._git_rs import get_cache_dir
from ..transport import FileExists, NoSuchFile, get_transport_from_path


def get_remote_cache_transport(repository):
    """Retrieve the transport to use when accessing (unwritable) remote
    repositories.
    """
    uuid = getattr(repository, "uuid", None)
    if uuid is None:
        path = get_cache_dir()
    else:
        path = os.path.join(get_cache_dir(), uuid)
        if not os.path.isdir(path):
            os.mkdir(path)
    return get_transport_from_path(path)


_mapdbs = threading.local()


def mapdbs():
    """Get a cache for this thread's db connections."""
    try:
        return _mapdbs.cache
    except AttributeError:
        _mapdbs.cache = {}
        return _mapdbs.cache


class GitShaMap:
    """Git<->Bzr revision id mapping database."""

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.
        :param sha: Git object sha
        :return: list with (type, type_data) tuples with type_data:
            commit: revid, tree_sha, verifiers
            blob: fileid, revid
            tree: fileid, revid.
        """
        raise NotImplementedError(self.lookup_git_sha)

    def lookup_blob_id(self, file_id, revision):
        """Retrieve a Git blob SHA by file id.

        :param file_id: File id of the file/symlink
        :param revision: revision in which the file was last changed.
        """
        raise NotImplementedError(self.lookup_blob_id)

    def lookup_tree_id(self, file_id, revision):
        """Retrieve a Git tree SHA by file id."""
        raise NotImplementedError(self.lookup_tree_id)

    def lookup_commit(self, revid):
        """Retrieve a Git commit SHA by Bazaar revision id."""
        raise NotImplementedError(self.lookup_commit)

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


class ContentCache:
    """Object that can cache Git objects."""

    def add(self, object):
        """Add an object."""
        raise NotImplementedError(self.add)

    def add_multi(self, objects):
        """Add multiple objects."""
        for obj in objects:
            self.add(obj)

    def __getitem__(self, sha):
        """Retrieve an item, by SHA."""
        raise NotImplementedError(self.__getitem__)


class BzrGitCacheFormat:
    """Bazaar-Git Cache Format."""

    def get_format_string(self):
        """Return a single-line unique format string for this cache format."""
        raise NotImplementedError(self.get_format_string)

    def open(self, transport):
        """Open this format on a transport."""
        raise NotImplementedError(self.open)

    def initialize(self, transport):
        """Create a new instance of this cache format at transport."""
        transport.put_bytes("format", self.get_format_string())

    @classmethod
    def from_transport(self, transport):
        """Open a cache file present on a transport, or initialize one.

        :param transport: Transport to use
        :return: A BzrGitCache instance
        """
        try:
            format_name = transport.get_bytes("format")
            format = formats.get(format_name)
        except NoSuchFile:
            format = formats.get("default")
            format.initialize(transport)
        return format.open(transport)

    @classmethod
    def from_repository(cls, repository):
        """Open a cache file for a repository.

        This will use the repository's transport to store the cache file, or
        use the users global cache directory if the repository has no
        transport associated with it.

        :param repository: Repository to open the cache for
        :return: A `BzrGitCache`
        """
        from ..transport.local import LocalTransport

        repo_transport = getattr(repository, "_transport", None)
        if repo_transport is not None and isinstance(repo_transport, LocalTransport):
            # Even if we don't write to this repo, we should be able
            # to update its cache.
            try:
                repo_transport = remove_readonly_transport_decorator(repo_transport)
            except bzr_errors.ReadOnlyError:
                transport = None
            else:
                with contextlib.suppress(FileExists):
                    repo_transport.mkdir("git")
                transport = repo_transport.clone("git")
        else:
            transport = None
        if transport is None:
            transport = get_remote_cache_transport(repository)
        return cls.from_transport(transport)


class CacheUpdater:
    """Base class for objects that can update a bzr-git cache."""

    def add_object(self, obj, bzr_key_data, path):
        """Add an object.

        :param obj: Object type ("commit", "blob" or "tree")
        :param bzr_key_data: bzr key store data or testament_sha in case
            of commit
        :param path: Path of the object (optional)
        """
        raise NotImplementedError(self.add_object)

    def finish(self):
        raise NotImplementedError(self.finish)


class BzrGitCache:
    """Caching backend."""

    def __init__(self, idmap, cache_updater_klass):
        self.idmap = idmap
        self._cache_updater_klass = cache_updater_klass

    def get_updater(self, rev):
        """Update an object that implements the CacheUpdater interface for
        updating this cache.
        """
        return self._cache_updater_klass(self, rev)


def DictBzrGitCache():
    return BzrGitCache(DictGitShaMap(), DictCacheUpdater)


class DictCacheUpdater(CacheUpdater):
    """Cache updater for dict-based caches."""

    def __init__(self, cache, rev):
        self.cache = cache
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, bzr_key_data, path):
        if isinstance(obj, tuple):
            (type_name, hexsha) = obj
        else:
            type_name = obj.type_name.decode("ascii")
            hexsha = obj.id
        if not isinstance(hexsha, bytes):
            raise TypeError(hexsha)
        if type_name == "commit":
            self._commit = obj
            if not isinstance(bzr_key_data, dict):
                raise TypeError(bzr_key_data)
            key = self.revid
            type_data = (self.revid, self._commit.tree, bzr_key_data)
            self.cache.idmap._by_revid[self.revid] = hexsha
        elif type_name in ("blob", "tree"):
            if bzr_key_data is not None:
                key = type_data = bzr_key_data
                self.cache.idmap._by_fileid.setdefault(type_data[1], {})[
                    type_data[0]
                ] = hexsha
        else:
            raise AssertionError
        entry = (type_name, type_data)
        self.cache.idmap._by_sha.setdefault(hexsha, {})[key] = entry

    def finish(self):
        if self._commit is None:
            raise AssertionError("No commit object added")
        return self._commit


class DictGitShaMap(GitShaMap):
    """Git SHA map that uses a dictionary."""

    def __init__(self):
        self._by_sha = {}
        self._by_fileid = {}
        self._by_revid = {}

    def lookup_blob_id(self, fileid, revision):
        return self._by_fileid[revision][fileid]

    def lookup_git_sha(self, sha):
        if not isinstance(sha, bytes):
            raise TypeError(sha)
        yield from self._by_sha[sha].values()

    def lookup_tree_id(self, fileid, revision):
        return self._by_fileid[revision][fileid]

    def lookup_commit(self, revid):
        return self._by_revid[revid]

    def revids(self):
        for _key, entries in self._by_sha.items():
            for type, type_data in entries.values():
                if type == "commit":
                    yield type_data[0]

    def sha1s(self):
        return self._by_sha.keys()


class SqliteCacheUpdater(CacheUpdater):
    def __init__(self, cache, rev):
        self.cache = cache
        self.db = self.cache.idmap.db
        self.revid = rev.revision_id
        self._commit = None
        self._trees = []
        self._blobs = []

    def add_object(self, obj, bzr_key_data, path):
        if isinstance(obj, tuple):
            (type_name, hexsha) = obj
        else:
            type_name = obj.type_name.decode("ascii")
            hexsha = obj.id
        if not isinstance(hexsha, bytes):
            raise TypeError(hexsha)
        if type_name == "commit":
            self._commit = obj
            if not isinstance(bzr_key_data, dict):
                raise TypeError(bzr_key_data)
            self._testament3_sha1 = bzr_key_data.get("testament3-sha1")
        elif type_name == "tree":
            if bzr_key_data is not None:
                self._trees.append((hexsha, bzr_key_data[0], bzr_key_data[1]))
        elif type_name == "blob":
            if bzr_key_data is not None:
                self._blobs.append((hexsha, bzr_key_data[0], bzr_key_data[1]))
        else:
            raise AssertionError

    def finish(self):
        if self._commit is None:
            raise AssertionError("No commit object added")
        self.db.executemany(
            "replace into trees (sha1, fileid, revid) values (?, ?, ?)", self._trees
        )
        self.db.executemany(
            "replace into blobs (sha1, fileid, revid) values (?, ?, ?)", self._blobs
        )
        self.db.execute(
            "replace into commits (sha1, revid, tree_sha, testament3_sha1) "
            "values (?, ?, ?, ?)",
            (self._commit.id, self.revid, self._commit.tree, self._testament3_sha1),
        )
        return self._commit


def SqliteBzrGitCache(p):
    return BzrGitCache(SqliteGitShaMap(p), SqliteCacheUpdater)


class SqliteGitCacheFormat(BzrGitCacheFormat):
    def get_format_string(self):
        return b"bzr-git sha map version 1 using sqlite\n"

    def open(self, transport):
        try:
            basepath = transport.local_abspath(".")
        except bzr_errors.NotLocalUrl:
            basepath = get_cache_dir()
        return SqliteBzrGitCache(os.path.join(basepath, "idmap.db"))


class SqliteGitShaMap(GitShaMap):
    """Bazaar GIT Sha map that uses a sqlite database for storage."""

    def __init__(self, path=None):
        import sqlite3

        self.path = path
        if path is None:
            self.db = sqlite3.connect(":memory:")
        else:
            if path not in mapdbs():
                mapdbs()[path] = sqlite3.connect(path)
            self.db = mapdbs()[path]
        self.db.text_factory = str
        self.db.executescript(
            """
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
        create unique index if not exists blobs_fileid_revid on blobs(
            fileid, revid);
        create table if not exists trees(
            sha1 text unique not null check(length(sha1) == 40),
            fileid text not null,
            revid text not null
        );
        create unique index if not exists trees_sha1 on trees(sha1);
        create unique index if not exists trees_fileid_revid on trees(
            fileid, revid);
"""
        )
        try:
            self.db.executescript("ALTER TABLE commits ADD testament3_sha1 TEXT;")
        except sqlite3.OperationalError:
            pass  # Column already exists.

    def __repr__(self):
        return f"{self.__class__.__name__}({self.path!r})"

    def lookup_commit(self, revid):
        cursor = self.db.execute("select sha1 from commits where revid = ?", (revid,))
        row = cursor.fetchone()
        if row is not None:
            return row[0]
        raise KeyError

    def commit_write_group(self):
        self.db.commit()

    def lookup_blob_id(self, fileid, revision):
        row = self.db.execute(
            "select sha1 from blobs where fileid = ? and revid = ?", (fileid, revision)
        ).fetchone()
        if row is not None:
            return row[0]
        raise KeyError(fileid)

    def lookup_tree_id(self, fileid, revision):
        row = self.db.execute(
            "select sha1 from trees where fileid = ? and revid = ?", (fileid, revision)
        ).fetchone()
        if row is not None:
            return row[0]
        raise KeyError(fileid)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            commit: revid, tree sha, verifiers
            tree: fileid, revid
            blob: fileid, revid
        """
        found = False
        cursor = self.db.execute(
            "select revid, tree_sha, testament3_sha1 from commits where sha1 = ?",
            (sha,),
        )
        for row in cursor.fetchall():
            found = True
            verifiers = {"testament3-sha1": row[2]} if row[2] is not None else {}
            yield ("commit", (row[0], row[1], verifiers))
        cursor = self.db.execute(
            "select fileid, revid from blobs where sha1 = ?", (sha,)
        )
        for row in cursor.fetchall():
            found = True
            yield ("blob", row)
        cursor = self.db.execute(
            "select fileid, revid from trees where sha1 = ?", (sha,)
        )
        for row in cursor.fetchall():
            found = True
            yield ("tree", row)
        if not found:
            raise KeyError(sha)

    def revids(self):
        """List the revision ids known."""
        return (row for (row,) in self.db.execute("select revid from commits"))

    def sha1s(self):
        """List the SHA1s."""
        for table in ("blobs", "commits", "trees"):
            for (sha,) in self.db.execute(f"select sha1 from {table}"):  # noqa: S608
                yield sha.encode("ascii")


class TdbCacheUpdater(CacheUpdater):
    """Cache updater for tdb-based caches."""

    def __init__(self, cache, rev):
        self.cache = cache
        self.db = cache.idmap.db
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, bzr_key_data, path):
        if isinstance(obj, tuple):
            (type_name, hexsha) = obj
            sha = hex_to_sha(hexsha)
        else:
            type_name = obj.type_name.decode("ascii")
            sha = obj.sha().digest()
        if type_name == "commit":
            self.db[b"commit\0" + self.revid] = b"\0".join((sha, obj.tree))
            if not isinstance(bzr_key_data, dict):
                raise TypeError(bzr_key_data)
            type_data = (self.revid, obj.tree)
            with contextlib.suppress(KeyError):
                type_data += (bzr_key_data["testament3-sha1"],)
            self._commit = obj
        elif type_name == "blob":
            if bzr_key_data is None:
                return
            self.db[b"\0".join((b"blob", bzr_key_data[0], bzr_key_data[1]))] = sha
            type_data = bzr_key_data
        elif type_name == "tree":
            if bzr_key_data is None:
                return
            type_data = bzr_key_data
        else:
            raise AssertionError
        entry = b"\0".join((type_name.encode("ascii"),) + type_data) + b"\n"
        key = b"git\0" + sha
        try:
            oldval = self.db[key]
        except KeyError:
            self.db[key] = entry
        else:
            if not oldval.endswith(b"\n"):
                self.db[key] = b"".join([oldval, b"\n", entry])
            else:
                self.db[key] = b"".join([oldval, entry])

    def finish(self):
        if self._commit is None:
            raise AssertionError("No commit object added")
        return self._commit


def TdbBzrGitCache(p):
    return BzrGitCache(TdbGitShaMap(p), TdbCacheUpdater)


class TdbGitCacheFormat(BzrGitCacheFormat):
    """Cache format for tdb-based caches."""

    def get_format_string(self):
        return b"bzr-git sha map version 3 using tdb\n"

    def open(self, transport):
        try:
            basepath = transport.local_abspath(".")
        except bzr_errors.NotLocalUrl:
            basepath = get_cache_dir()
        try:
            return TdbBzrGitCache(os.path.join(basepath, "idmap.tdb"))
        except ModuleNotFoundError as err:
            raise ModuleNotFoundError(
                "Unable to open existing bzr-git cache because 'tdb' is not installed."
            ) from err


class TdbGitShaMap(GitShaMap):
    """SHA Map that uses a TDB database.

    Entries:

    "git <sha1>" -> "<type> <type-data1> <type-data2>"
    "commit revid" -> "<sha1> <tree-id>"
    "tree fileid revid" -> "<sha1>"
    "blob fileid revid" -> "<sha1>"
    """

    TDB_MAP_VERSION = 3
    TDB_HASH_SIZE = 50000

    def __init__(self, path=None):
        import tdb

        self.path = path
        if path is None:
            self.db = {}
        else:
            if path not in mapdbs():
                mapdbs()[path] = tdb.Tdb(
                    path, self.TDB_HASH_SIZE, tdb.DEFAULT, os.O_RDWR | os.O_CREAT
                )
            self.db = mapdbs()[path]
        try:
            if int(self.db[b"version"]) not in (2, 3):
                trace.warning(
                    "SHA Map is incompatible (%s -> %d), rebuilding database.",
                    self.db[b"version"],
                    self.TDB_MAP_VERSION,
                )
                self.db.clear()
        except KeyError:
            pass
        self.db[b"version"] = b"%d" % self.TDB_MAP_VERSION

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
        return f"{self.__class__.__name__}({self.path!r})"

    def lookup_commit(self, revid):
        try:
            return sha_to_hex(self.db[b"commit\0" + revid][:20])
        except KeyError as err:
            raise KeyError(f"No cache entry for {revid!r}") from err

    def lookup_blob_id(self, fileid, revision):
        return sha_to_hex(self.db[b"\0".join((b"blob", fileid, revision))])

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            commit: revid, tree sha
            blob: fileid, revid
            tree: fileid, revid
        """
        if len(sha) == 40:
            sha = hex_to_sha(sha)
        value = self.db[b"git\0" + sha]
        for data in value.splitlines():
            data = data.split(b"\0")
            type_name = data[0].decode("ascii")
            if type_name == "commit":
                if len(data) == 3:
                    yield (type_name, (data[1], data[2], {}))
                else:
                    yield (type_name, (data[1], data[2], {"testament3-sha1": data[3]}))
            elif type_name in ("tree", "blob"):
                yield (type_name, tuple(data[1:]))
            else:
                raise AssertionError(f"unknown type {type_name!r}")

    def missing_revisions(self, revids):
        ret = set()
        for revid in revids:
            if self.db.get(b"commit\0" + revid) is None:
                ret.add(revid)
        return ret

    def _keys(self):
        return self.db.keys()

    def revids(self):
        """List the revision ids known."""
        for key in self._keys():
            if key.startswith(b"commit\0"):
                yield key[7:]

    def sha1s(self):
        """List the SHA1s."""
        for key in self._keys():
            if key.startswith(b"git\0"):
                yield sha_to_hex(key[4:])


class VersionedFilesContentCache(ContentCache):
    def __init__(self, vf):
        self._vf = vf

    def add(self, obj):
        self._vf.insert_record_stream(
            [
                versionedfile.ChunkedContentFactory(
                    (obj.id,), [], None, obj.as_legacy_object_chunks()
                )
            ]
        )

    def __getitem__(self, sha):
        stream = self._vf.get_record_stream([(sha,)], "unordered", True)
        entry = next(stream)
        if entry.storage_kind == "absent":
            raise KeyError(sha)
        return ShaFile._parse_legacy_object(entry.get_bytes_as("fulltext"))


class IndexCacheUpdater(CacheUpdater):
    def __init__(self, cache, rev):
        self.cache = cache
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, bzr_key_data, path):
        if isinstance(obj, tuple):
            (type_name, hexsha) = obj
        else:
            type_name = obj.type_name.decode("ascii")
            hexsha = obj.id
        if type_name == "commit":
            self._commit = obj
            if not isinstance(bzr_key_data, dict):
                raise TypeError(bzr_key_data)
            self.cache.idmap._add_git_sha(
                hexsha, b"commit", (self.revid, obj.tree, bzr_key_data)
            )
            self.cache.idmap._add_node(
                (b"commit", self.revid, b"X"), b" ".join((hexsha, obj.tree))
            )
        elif type_name == "blob":
            self.cache.idmap._add_git_sha(hexsha, b"blob", bzr_key_data)
            self.cache.idmap._add_node(
                (b"blob", bzr_key_data[0], bzr_key_data[1]), hexsha
            )
        elif type_name == "tree":
            self.cache.idmap._add_git_sha(hexsha, b"tree", bzr_key_data)
        else:
            raise AssertionError

    def finish(self):
        return self._commit


class IndexBzrGitCache(BzrGitCache):
    def __init__(self, transport=None):
        shamap = IndexGitShaMap(transport.clone("index"))
        super().__init__(shamap, IndexCacheUpdater)


class IndexGitCacheFormat(BzrGitCacheFormat):
    def get_format_string(self):
        return b"bzr-git sha map with git object cache version 1\n"

    def initialize(self, transport):
        super().initialize(transport)
        transport.mkdir("index")
        transport.mkdir("objects")
        from .transportgit import TransportObjectStore

        TransportObjectStore.init(transport.clone("objects"))

    def open(self, transport):
        return IndexBzrGitCache(transport)


class IndexGitShaMap(GitShaMap):
    """SHA Map that uses the Bazaar APIs to store a cache.

    BTree Index file with the following contents:

    ("git", <sha1>, "X") -> "<type> <type-data1> <type-data2>"
    ("commit", <revid>, "X") -> "<sha1> <tree-id>"
    ("blob", <fileid>, <revid>) -> <sha1>

    """

    def __init__(self, transport=None):
        self._name = None
        if transport is None:
            self._transport = None
            self._index = _mod_index.InMemoryGraphIndex(0, key_elements=3)
            self._builder = self._index
        else:
            self._builder = None
            self._transport = transport
            self._index = _mod_index.CombinedGraphIndex([])
            for name in self._transport.list_dir("."):
                if not name.endswith(".rix"):
                    continue
                x = _mod_btree_index.BTreeGraphIndex(
                    self._transport, name, self._transport.stat(name).st_size
                )
                self._index.insert_index(0, x)

    @classmethod
    def from_repository(cls, repository):
        transport = getattr(repository, "_transport", None)
        if transport is not None:
            with contextlib.suppress(FileExists):
                transport.mkdir("git")
            return cls(transport.clone("git"))
        return cls(get_transport_from_path(get_cache_dir()))

    def __repr__(self):
        if self._transport is not None:
            return f"{self.__class__.__name__}({self._transport.base!r})"
        else:
            return f"{self.__class__.__name__}()"

    def repack(self):
        if self._builder is not None:
            raise bzr_errors.BzrError("builder already open")
        self.start_write_group()
        self._builder.add_nodes(
            (key, value) for (_, key, value) in self._index.iter_all_entries()
        )
        to_remove = []
        for name in self._transport.list_dir("."):
            if name.endswith(".rix"):
                to_remove.append(name)
        self.commit_write_group()
        del self._index.indices[1:]
        for name in to_remove:
            self._transport.rename(name, name + ".old")

    def start_write_group(self):
        if self._builder is not None:
            raise bzr_errors.BzrError("builder already open")
        self._builder = _mod_btree_index.BTreeBuilder(0, key_elements=3)
        self._name = hashlib.sha1()  # noqa: S324

    def commit_write_group(self):
        if self._builder is None:
            raise bzr_errors.BzrError("builder not open")
        stream = self._builder.finish()
        name = self._name.hexdigest() + ".rix"
        size = self._transport.put_file(name, stream)
        index = _mod_btree_index.BTreeGraphIndex(self._transport, name, size)
        self._index.insert_index(0, index)
        self._builder = None
        self._name = None

    def abort_write_group(self):
        if self._builder is None:
            raise bzr_errors.BzrError("builder not open")
        self._builder = None
        self._name = None

    def _add_node(self, key, value):
        try:
            self._get_entry(key)
        except KeyError:
            self._builder.add_node(key, value)
            return False
        else:
            return True

    def _get_entry(self, key):
        entries = self._index.iter_entries([key])
        try:
            return next(entries)[2]
        except StopIteration as err:
            if self._builder is None:
                raise KeyError from err
            entries = self._builder.iter_entries([key])
            try:
                return next(entries)[2]
            except StopIteration as err:
                raise KeyError from err

    def _iter_entries_prefix(self, prefix):
        for entry in self._index.iter_entries_prefix([prefix]):
            yield (entry[1], entry[2])
        if self._builder is not None:
            for entry in self._builder.iter_entries_prefix([prefix]):
                yield (entry[1], entry[2])

    def lookup_commit(self, revid):
        return self._get_entry((b"commit", revid, b"X"))[:40]

    def _add_git_sha(self, hexsha, type, type_data):
        if hexsha is not None:
            self._name.update(hexsha)
            if type == b"commit":
                td = (type_data[0], type_data[1])
                with contextlib.suppress(KeyError):
                    td += (type_data[2]["testament3-sha1"],)
            else:
                td = type_data
            self._add_node((b"git", hexsha, b"X"), b" ".join((type,) + td))
        else:
            # This object is not represented in Git - perhaps an empty
            # directory?
            self._name.update(type + b" ".join(type_data))

    def lookup_blob_id(self, fileid, revision):
        return self._get_entry((b"blob", fileid, revision))

    def lookup_git_sha(self, sha):
        if len(sha) == 20:
            sha = sha_to_hex(sha)
        value = self._get_entry((b"git", sha, b"X"))
        data = value.split(b" ", 3)
        if data[0] == b"commit":
            try:
                verifiers = {"testament3-sha1": data[3]} if data[3] else {}
            except IndexError:
                verifiers = {}
            yield ("commit", (data[1], data[2], verifiers))
        else:
            yield (data[0].decode("ascii"), tuple(data[1:]))

    def revids(self):
        """List the revision ids known."""
        for key, _value in self._iter_entries_prefix((b"commit", None, None)):
            yield key[1]

    def missing_revisions(self, revids):
        """Return set of all the revisions that are not present."""
        missing_revids = set(revids)
        for _, key, _value in self._index.iter_entries(
            (b"commit", revid, b"X") for revid in revids
        ):
            missing_revids.remove(key[1])
        return missing_revids

    def sha1s(self):
        """List the SHA1s."""
        for key, _value in self._iter_entries_prefix((b"git", None, None)):
            yield key[1]


formats = registry.Registry[str, BzrGitCacheFormat, None]()
formats.register(TdbGitCacheFormat().get_format_string(), TdbGitCacheFormat())
formats.register(SqliteGitCacheFormat().get_format_string(), SqliteGitCacheFormat())
formats.register(IndexGitCacheFormat().get_format_string(), IndexGitCacheFormat())
# In the future, this will become the default:
formats.register("default", IndexGitCacheFormat())


def migrate_ancient_formats(repo_transport):
    # Migrate older cache formats
    repo_transport = remove_readonly_transport_decorator(repo_transport)
    has_sqlite = repo_transport.has("git.db")
    has_tdb = repo_transport.has("git.tdb")
    if not has_sqlite or has_tdb:
        return
    try:
        repo_transport.mkdir("git")
    except FileExists:
        return
    # Prefer migrating git.db over git.tdb, since the latter may not
    # be openable on some platforms.
    if has_sqlite:
        SqliteGitCacheFormat().initialize(repo_transport.clone("git"))
        repo_transport.rename("git.db", "git/idmap.db")
    elif has_tdb:
        TdbGitCacheFormat().initialize(repo_transport.clone("git"))
        repo_transport.rename("git.tdb", "git/idmap.tdb")


def remove_readonly_transport_decorator(transport):
    if transport.is_readonly():
        try:
            return transport._decorated
        except AttributeError as err:
            raise bzr_errors.ReadOnlyError(transport) from err
    return transport


def from_repository(repository):
    """Open a cache file for a repository.

    If the repository is remote and there is no transport available from it
    this will use a local file in the users cache directory
    (typically ~/.cache/bazaar/git/)

    :param repository: A repository object
    """
    repo_transport = getattr(repository, "_transport", None)
    if repo_transport is not None:
        try:
            migrate_ancient_formats(repo_transport)
        except bzr_errors.ReadOnlyError:
            pass  # Not much we can do
    return BzrGitCacheFormat.from_repository(repository)
