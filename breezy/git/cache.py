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

from .. import errors as bzr_errors
from .. import registry, trace
from .._git_rs import get_cache_dir
from ..bzr import btree_index as _mod_btree_index
from ..bzr import index as _mod_index
from ..bzr import versionedfile
from ..transport import FileExists, NoSuchFile, get_transport_from_path


def get_remote_cache_transport(repository):
    """Retrieve the transport to use when accessing (unwritable) remote repositories.

    Args:
        repository: Repository object to get cache transport for.

    Returns:
        Transport object for cache access.
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
    """Get a cache for this thread's database connections.

    Returns:
        dict: Dictionary cache for database connections in current thread.
    """
    try:
        return _mapdbs.cache
    except AttributeError:
        _mapdbs.cache = {}
        return _mapdbs.cache


class GitShaMap:
    """Abstract base class for Git SHA to Bazaar revision ID mapping databases.

    This class defines the interface for mapping Git SHAs to Bazaar revision data
    and vice versa.
    """

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

        Args:
            file_id: File id of the file/symlink.
            revision: Revision in which the file was last changed.

        Returns:
            Git blob SHA as bytes.
        """
        raise NotImplementedError(self.lookup_blob_id)

    def lookup_tree_id(self, file_id, revision):
        """Retrieve a Git tree SHA by file id.

        Args:
            file_id: File ID to look up.
            revision: Revision to look up tree in.

        Returns:
            Git tree SHA as bytes.
        """
        raise NotImplementedError(self.lookup_tree_id)

    def lookup_commit(self, revid):
        """Retrieve a Git commit SHA by Bazaar revision id.

        Args:
            revid: Bazaar revision ID to look up.

        Returns:
            Git commit SHA as bytes.
        """
        raise NotImplementedError(self.lookup_commit)

    def revids(self):
        """List the revision ids known.

        Returns:
            Iterator of revision IDs.
        """
        raise NotImplementedError(self.revids)

    def missing_revisions(self, revids):
        """Return set of all the revisions that are not present.

        Args:
            revids: Collection of revision IDs to check.

        Returns:
            set: Set of revision IDs that are missing from the cache.
        """
        present_revids = set(self.revids())
        if not isinstance(revids, set):
            revids = set(revids)
        return revids - present_revids

    def sha1s(self):
        """List the SHA1s.

        Returns:
            Iterator of Git SHA1s as bytes.
        """
        raise NotImplementedError(self.sha1s)

    def start_write_group(self):
        """Start writing changes.

        Begin a write transaction for batch updates.
        """

    def commit_write_group(self):
        """Commit any pending changes.

        Commits all changes made since the last start_write_group call.
        """

    def abort_write_group(self):
        """Abort any pending changes.

        Discards all changes made since the last start_write_group call.
        """


class ContentCache:
    """Abstract base class for caching Git objects.

    Provides an interface for storing and retrieving Git objects by their SHA.
    """

    def add(self, object):
        """Add an object to the cache.

        Args:
            object: Git object to add.
        """
        raise NotImplementedError(self.add)

    def add_multi(self, objects):
        """Add multiple objects to the cache.

        Args:
            objects: Iterable of Git objects to add.
        """
        for obj in objects:
            self.add(obj)

    def __getitem__(self, sha):
        """Retrieve an item by SHA.

        Args:
            sha: Git SHA to retrieve.

        Returns:
            Git object corresponding to the SHA.

        Raises:
            KeyError: If the SHA is not found in cache.
        """
        raise NotImplementedError(self.__getitem__)


class BzrGitCacheFormat:
    """Abstract base class for Bazaar-Git cache formats.

    Defines the interface for different storage formats of the Git SHA mapping cache.
    """

    def get_format_string(self):
        """Return a single-line unique format string for this cache format.

        Returns:
            bytes: Format identification string.
        """
        raise NotImplementedError(self.get_format_string)

    def open(self, transport):
        """Open this format on a transport.

        Args:
            transport: Transport to open cache on.

        Returns:
            BzrGitCache instance.
        """
        raise NotImplementedError(self.open)

    def initialize(self, transport):
        """Create a new instance of this cache format at transport.

        Args:
            transport: Transport to initialize cache on.
        """
        transport.put_bytes("format", self.get_format_string())

    @classmethod
    def from_transport(self, transport):
        """Open a cache file present on a transport, or initialize one.

        Args:
            transport: Transport to use.

        Returns:
            BzrGitCache instance.
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

        Args:
            repository: Repository to open the cache for.

        Returns:
            BzrGitCache instance.
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
    """Abstract base class for objects that can update a bzr-git cache.

    Provides interface for adding objects to the cache during revision processing.
    """

    def add_object(self, obj, bzr_key_data, path):
        """Add an object.

        :param obj: Object type ("commit", "blob" or "tree")
        :param bzr_key_data: bzr key store data or testament_sha in case
            of commit
        :param path: Path of the object (optional)
        """
        raise NotImplementedError(self.add_object)

    def finish(self):
        """Complete the cache update operation.

        Returns:
            The commit object that was added.
        """
        raise NotImplementedError(self.finish)


class BzrGitCache:
    """Main caching backend for Git SHA to Bazaar mappings.

    Combines an ID mapping database with a cache updater for managing
    the cache lifecycle.
    """

    def __init__(self, idmap, cache_updater_klass):
        """Initialize BzrGitCache.

        Args:
            idmap: GitShaMap instance for storing mappings.
            cache_updater_klass: Class to use for cache updates.
        """
        self.idmap = idmap
        self._cache_updater_klass = cache_updater_klass

    def get_updater(self, rev):
        """Create an object that implements the CacheUpdater interface for updating this cache.

        Args:
            rev: Revision object to create updater for.

        Returns:
            CacheUpdater instance for the given revision.
        """
        return self._cache_updater_klass(self, rev)


def DictBzrGitCache():
    """Create a dictionary-based BzrGitCache for testing.

    Returns:
        BzrGitCache instance using in-memory dictionary storage.
    """
    return BzrGitCache(DictGitShaMap(), DictCacheUpdater)


class DictCacheUpdater(CacheUpdater):
    """Cache updater for dictionary-based caches.

    Used primarily for testing, stores cache data in memory dictionaries.
    """

    def __init__(self, cache, rev):
        """Initialize DictCacheUpdater.

        Args:
            cache: BzrGitCache instance.
            rev: Revision object being processed.
        """
        self.cache = cache
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, bzr_key_data, path):
        """Add a Git object to the cache.

        Args:
            obj: Git object (commit, blob, or tree) or tuple of (type_name, hexsha).
            bzr_key_data: Bazaar key data or testament SHA for commits.
            path: Path of the object (optional, currently unused).

        Raises:
            TypeError: If hexsha is not bytes or bzr_key_data has wrong type.
            AssertionError: If object type is not supported.
        """
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
        """Complete the cache update operation.

        Returns:
            The commit object that was added.

        Raises:
            AssertionError: If no commit object was added during the update.
        """
        if self._commit is None:
            raise AssertionError("No commit object added")
        return self._commit


class DictGitShaMap(GitShaMap):
    """Git SHA map implementation using in-memory dictionaries.

    Used primarily for testing, stores all mappings in memory dictionaries.
    """

    def __init__(self):
        """Initialize DictGitShaMap with empty dictionaries."""
        self._by_sha = {}
        self._by_fileid = {}
        self._by_revid = {}

    def lookup_blob_id(self, fileid, revision):
        """Retrieve a Git blob SHA by file ID and revision.

        Args:
            fileid: File ID to look up.
            revision: Revision to look up blob in.

        Returns:
            Git blob SHA as bytes.

        Raises:
            KeyError: If the file ID or revision is not found.
        """
        return self._by_fileid[revision][fileid]

    def lookup_git_sha(self, sha):
        """Lookup a Git SHA in the database.

        Args:
            sha: Git object SHA as bytes.

        Yields:
            tuple: (type, type_data) tuples with type_data being:
                - commit: (revid, tree_sha, verifiers)
                - blob: (fileid, revid)
                - tree: (fileid, revid)

        Raises:
            TypeError: If sha is not bytes.
            KeyError: If SHA is not found in cache.
        """
        if not isinstance(sha, bytes):
            raise TypeError(sha)
        yield from self._by_sha[sha].values()

    def lookup_tree_id(self, fileid, revision):
        """Retrieve a Git tree SHA by file ID and revision.

        Args:
            fileid: File ID to look up.
            revision: Revision to look up tree in.

        Returns:
            Git tree SHA as bytes.

        Raises:
            KeyError: If the file ID or revision is not found.
        """
        return self._by_fileid[revision][fileid]

    def lookup_commit(self, revid):
        """Retrieve a Git commit SHA by Bazaar revision ID.

        Args:
            revid: Bazaar revision ID to look up.

        Returns:
            Git commit SHA as bytes.

        Raises:
            KeyError: If the revision ID is not found.
        """
        return self._by_revid[revid]

    def revids(self):
        """List the revision IDs known in the cache.

        Yields:
            bytes: Bazaar revision IDs for all commits in the cache.
        """
        for _key, entries in self._by_sha.items():
            for type, type_data in entries.values():
                if type == "commit":
                    yield type_data[0]

    def sha1s(self):
        """List the SHA1s stored in the cache.

        Returns:
            dict_keys: All Git SHA1s as bytes stored in the cache.
        """
        return self._by_sha.keys()


class SqliteCacheUpdater(CacheUpdater):
    """Cache updater for SQLite-based caches.

    Handles updates to SQLite database storage format.
    """

    def __init__(self, cache, rev):
        """Initialize SqliteCacheUpdater.

        Args:
            cache: BzrGitCache instance.
            rev: Revision object being processed.
        """
        self.cache = cache
        self.db = self.cache.idmap.db
        self.revid = rev.revision_id
        self._commit = None
        self._trees = []
        self._blobs = []

    def add_object(self, obj, bzr_key_data, path):
        """Add a Git object to the SQLite cache.

        Args:
            obj: Git object (commit, blob, or tree) or tuple of (type_name, hexsha).
            bzr_key_data: Bazaar key data or testament SHA for commits.
            path: Path of the object (optional, currently unused).

        Raises:
            TypeError: If hexsha is not bytes or bzr_key_data has wrong type.
            AssertionError: If object type is not supported.
        """
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
        """Complete the SQLite cache update operation.

        Writes all collected trees, blobs, and commit data to the SQLite database.

        Returns:
            The commit object that was added.

        Raises:
            AssertionError: If no commit object was added during the update.
        """
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
    """Create a SQLite-based BzrGitCache.

    Args:
        p: Path to SQLite database file.

    Returns:
        BzrGitCache instance using SQLite storage.
    """
    return BzrGitCache(SqliteGitShaMap(p), SqliteCacheUpdater)


class SqliteGitCacheFormat(BzrGitCacheFormat):
    """Cache format using SQLite database storage."""

    def get_format_string(self):
        """Return the format string for SQLite cache format.

        Returns:
            bytes: Format identification string for SQLite cache.
        """
        return b"bzr-git sha map version 1 using sqlite\n"

    def open(self, transport):
        """Open a SQLite cache on the given transport.

        Args:
            transport: Transport to open cache on.

        Returns:
            BzrGitCache instance using SQLite storage.
        """
        try:
            basepath = transport.local_abspath(".")
        except bzr_errors.NotLocalUrl:
            basepath = get_cache_dir()
        return SqliteBzrGitCache(os.path.join(basepath, "idmap.db"))


class SqliteGitShaMap(GitShaMap):
    """Git SHA map implementation using SQLite database for storage.

    Uses SQLite database with separate tables for commits, blobs, and trees
    to provide persistent storage of Git SHA to Bazaar mappings.
    """

    def __init__(self, path=None):
        """Initialize SqliteGitShaMap.

        Args:
            path: Path to SQLite database file. If None, uses in-memory database.
        """
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
        """Return string representation of SqliteGitShaMap.

        Returns:
            str: String representation showing class name and database path.
        """
        return f"{self.__class__.__name__}({self.path!r})"

    def lookup_commit(self, revid):
        """Retrieve a Git commit SHA by Bazaar revision ID from SQLite.

        Args:
            revid: Bazaar revision ID to look up.

        Returns:
            str: Git commit SHA as hex string.

        Raises:
            KeyError: If the revision ID is not found.
        """
        cursor = self.db.execute("select sha1 from commits where revid = ?", (revid,))
        row = cursor.fetchone()
        if row is not None:
            return row[0]
        raise KeyError

    def commit_write_group(self):
        """Commit any pending SQLite database changes.

        Commits the current SQLite transaction.
        """
        self.db.commit()

    def lookup_blob_id(self, fileid, revision):
        """Retrieve a Git blob SHA by file ID and revision from SQLite.

        Args:
            fileid: File ID to look up.
            revision: Revision to look up blob in.

        Returns:
            str: Git blob SHA as hex string.

        Raises:
            KeyError: If the file ID or revision is not found.
        """
        row = self.db.execute(
            "select sha1 from blobs where fileid = ? and revid = ?", (fileid, revision)
        ).fetchone()
        if row is not None:
            return row[0]
        raise KeyError(fileid)

    def lookup_tree_id(self, fileid, revision):
        """Retrieve a Git tree SHA by file ID and revision from SQLite.

        Args:
            fileid: File ID to look up.
            revision: Revision to look up tree in.

        Returns:
            str: Git tree SHA as hex string.

        Raises:
            KeyError: If the file ID or revision is not found.
        """
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
        """List the revision IDs known in the SQLite cache.

        Returns:
            Generator[str, None, None]: Generator yielding revision ID strings.
        """
        return (row for (row,) in self.db.execute("select revid from commits"))

    def sha1s(self):
        """List the SHA1s stored in the SQLite cache.

        Yields:
            bytes: All Git SHA1s as bytes from blobs, commits, and trees tables.
        """
        for table in ("blobs", "commits", "trees"):
            for (sha,) in self.db.execute(f"select sha1 from {table}"):  # noqa: S608
                yield sha.encode("ascii")


class TdbCacheUpdater(CacheUpdater):
    """Cache updater for TDB-based caches.

    Handles updates to Trivial Database (TDB) storage format.
    """

    def __init__(self, cache, rev):
        """Initialize TdbCacheUpdater.

        Args:
            cache: BzrGitCache instance.
            rev: Revision object being processed.
        """
        self.cache = cache
        self.db = cache.idmap.db
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, bzr_key_data, path):
        """Add a Git object to the TDB cache.

        Args:
            obj: Git object (commit, blob, or tree) or tuple of (type_name, hexsha).
            bzr_key_data: Bazaar key data or testament SHA for commits.
            path: Path of the object (optional, currently unused).

        Raises:
            TypeError: If bzr_key_data has wrong type for commits.
            AssertionError: If object type is not supported.
        """
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
        """Complete the TDB cache update operation.

        Returns:
            The commit object that was added.

        Raises:
            AssertionError: If no commit object was added during the update.
        """
        if self._commit is None:
            raise AssertionError("No commit object added")
        return self._commit


def TdbBzrGitCache(p):
    """Create a TDB-based BzrGitCache.

    Args:
        p: Path to TDB database file.

    Returns:
        BzrGitCache instance using TDB storage.
    """
    return BzrGitCache(TdbGitShaMap(p), TdbCacheUpdater)


class TdbGitCacheFormat(BzrGitCacheFormat):
    """Cache format using Trivial Database (TDB) storage.

    Uses TDB for fast key-value storage of Git SHA mappings.
    """

    def get_format_string(self):
        """Return the format string for TDB cache format.

        Returns:
            bytes: Format identification string for TDB cache.
        """
        return b"bzr-git sha map version 3 using tdb\n"

    def open(self, transport):
        """Open a TDB cache on the given transport.

        Args:
            transport: Transport to open cache on.

        Returns:
            BzrGitCache instance using TDB storage.

        Raises:
            ModuleNotFoundError: If TDB module is not available.
        """
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
        """Initialize TdbGitShaMap.

        Args:
            path: Path to TDB database file. If None, uses in-memory storage.
        """
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

    def __repr__(self):
        """Return string representation of TdbGitShaMap.

        Returns:
            str: String representation showing class name and database path.
        """
        return f"{self.__class__.__name__}({self.path!r})"

    def start_write_group(self):
        """Start writing changes.

        Begins a TDB transaction for batch updates.
        """
        self.db.transaction_start()

    def commit_write_group(self):
        """Commit any pending changes.

        Commits the current TDB transaction.
        """
        self.db.transaction_commit()

    def abort_write_group(self):
        """Abort any pending changes.

        Cancels the current TDB transaction.
        """
        self.db.transaction_cancel()

    def __repr__(self):
        return f"{self.__class__.__name__}({self.path!r})"

    def lookup_commit(self, revid):
        """Retrieve a Git commit SHA by Bazaar revision ID from TDB.

        Args:
            revid: Bazaar revision ID to look up.

        Returns:
            str: Git commit SHA as hex string.

        Raises:
            KeyError: If the revision ID is not found.
        """
        try:
            return sha_to_hex(self.db[b"commit\0" + revid][:20])
        except KeyError as err:
            raise KeyError(f"No cache entry for {revid!r}") from err

    def lookup_blob_id(self, fileid, revision):
        """Retrieve a Git blob SHA by file ID and revision from TDB.

        Args:
            fileid: File ID to look up.
            revision: Revision to look up blob in.

        Returns:
            str: Git blob SHA as hex string.

        Raises:
            KeyError: If the file ID or revision is not found.
        """
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
        """Return set of all the revisions that are not present in TDB.

        Args:
            revids: Collection of revision IDs to check.

        Returns:
            set: Set of revision IDs that are missing from the TDB cache.
        """
        ret = set()
        for revid in revids:
            if self.db.get(b"commit\0" + revid) is None:
                ret.add(revid)
        return ret

    def _keys(self):
        """Get all keys from the TDB database.

        Returns:
            Iterator of database keys as bytes.
        """
        return self.db.keys()

    def revids(self):
        """List the revision IDs known in the TDB cache.

        Yields:
            bytes: Bazaar revision IDs for all commits in the TDB cache.
        """
        for key in self._keys():
            if key.startswith(b"commit\0"):
                yield key[7:]

    def sha1s(self):
        """List the SHA1s stored in the TDB cache.

        Yields:
            str: All Git SHA1s as hex strings from the TDB cache.
        """
        for key in self._keys():
            if key.startswith(b"git\0"):
                yield sha_to_hex(key[4:])


class VersionedFilesContentCache(ContentCache):
    """Content cache using Bazaar's versioned files storage.

    Stores Git objects using Bazaar's versioned file format.
    """

    def __init__(self, vf):
        """Initialize VersionedFilesContentCache.

        Args:
            vf: VersionedFiles instance to store objects in.
        """
        self._vf = vf

    def add(self, obj):
        """Add a Git object to the versioned files cache.

        Args:
            obj: Git object to add to the cache.
        """
        self._vf.insert_record_stream(
            [
                versionedfile.ChunkedContentFactory(
                    (obj.id,), [], None, obj.as_legacy_object_chunks()
                )
            ]
        )

    def __getitem__(self, sha):
        """Retrieve a Git object by SHA from versioned files cache.

        Args:
            sha: Git SHA to retrieve.

        Returns:
            Git object corresponding to the SHA.

        Raises:
            KeyError: If the SHA is not found in cache.
        """
        stream = self._vf.get_record_stream([(sha,)], "unordered", True)
        entry = next(stream)
        if entry.storage_kind == "absent":
            raise KeyError(sha)
        return ShaFile._parse_legacy_object(entry.get_bytes_as("fulltext"))


class IndexCacheUpdater(CacheUpdater):
    """Cache updater for index-based caches.

    Updates Bazaar BTree index-based cache storage.
    """

    def __init__(self, cache, rev):
        """Initialize IndexCacheUpdater.

        Args:
            cache: BzrGitCache instance.
            rev: Revision object being processed.
        """
        self.cache = cache
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, bzr_key_data, path):
        """Add a Git object to the index cache.

        Args:
            obj: Git object (commit, blob, or tree) or tuple of (type_name, hexsha).
            bzr_key_data: Bazaar key data or testament SHA for commits.
            path: Path of the object (optional, currently unused).

        Raises:
            TypeError: If bzr_key_data has wrong type for commits.
            AssertionError: If object type is not supported.
        """
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
        """Complete the index cache update operation.

        Returns:
            The commit object that was added.
        """
        return self._commit


class IndexBzrGitCache(BzrGitCache):
    """BzrGitCache implementation using Bazaar index storage.

    Uses Bazaar's BTree index format for storing SHA mappings.
    """

    def __init__(self, transport=None):
        """Initialize IndexBzrGitCache.

        Args:
            transport: Transport to use for index storage.
        """
        shamap = IndexGitShaMap(transport.clone("index"))
        super().__init__(shamap, IndexCacheUpdater)


class IndexGitCacheFormat(BzrGitCacheFormat):
    """Cache format using Bazaar BTree index storage with Git object cache."""

    def get_format_string(self):
        """Return the format string for index cache format.

        Returns:
            bytes: Format identification string for index-based cache with Git objects.
        """
        return b"bzr-git sha map with git object cache version 1\n"

    def initialize(self, transport):
        """Initialize an index-based cache format on the transport.

        Args:
            transport: Transport to initialize cache on.
        """
        super().initialize(transport)
        transport.mkdir("index")
        transport.mkdir("objects")
        from .transportgit import TransportObjectStore

        TransportObjectStore.init(transport.clone("objects"))

    def open(self, transport):
        """Open an index-based cache on the given transport.

        Args:
            transport: Transport to open cache on.

        Returns:
            IndexBzrGitCache instance.
        """
        return IndexBzrGitCache(transport)


class IndexGitShaMap(GitShaMap):
    """SHA Map that uses the Bazaar APIs to store a cache.

    BTree Index file with the following contents:

    ("git", <sha1>, "X") -> "<type> <type-data1> <type-data2>"
    ("commit", <revid>, "X") -> "<sha1> <tree-id>"
    ("blob", <fileid>, <revid>) -> <sha1>

    """

    def __init__(self, transport=None):
        """Initialize IndexGitShaMap.

        Args:
            transport: Transport for index storage. If None, uses in-memory storage.
        """
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
        """Create an IndexGitShaMap for a repository.

        Args:
            repository: Repository to create cache for.

        Returns:
            IndexGitShaMap instance for the repository.
        """
        transport = getattr(repository, "_transport", None)
        if transport is not None:
            with contextlib.suppress(FileExists):
                transport.mkdir("git")
            return cls(transport.clone("git"))
        return cls(get_transport_from_path(get_cache_dir()))

    def __repr__(self):
        """Return string representation of IndexGitShaMap.

        Returns:
            str: String representation showing class name and transport base or empty.
        """
        if self._transport is not None:
            return f"{self.__class__.__name__}({self._transport.base!r})"
        else:
            return f"{self.__class__.__name__}()"

    def repack(self):
        """Repack the index by combining all index files into one.

        Combines all existing index files into a single new index file and marks
        old files for removal by renaming them with .old extension.

        Raises:
            BzrError: If a write group is already active.
        """
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
        """Start a write group for batch index updates.

        Raises:
            BzrError: If a builder is already open.
        """
        if self._builder is not None:
            raise bzr_errors.BzrError("builder already open")
        self._builder = _mod_btree_index.BTreeBuilder(0, key_elements=3)
        self._name = hashlib.sha1()  # noqa: S324

    def commit_write_group(self):
        """Commit the current write group to a new index file.

        Raises:
            BzrError: If no builder is open.
        """
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
        """Abort the current write group.

        Raises:
            BzrError: If no builder is open.
        """
        if self._builder is None:
            raise bzr_errors.BzrError("builder not open")
        self._builder = None
        self._name = None

    def _add_node(self, key, value):
        """Add a node to the index if it doesn't exist.

        Args:
            key: Index key tuple.
            value: Value to store.

        Returns:
            bool: True if node already existed, False if it was added.
        """
        try:
            self._get_entry(key)
        except KeyError:
            self._builder.add_node(key, value)
            return False
        else:
            return True

    def _get_entry(self, key):
        """Get an entry from the index by key.

        Args:
            key: Index key to look up.

        Returns:
            The value associated with the key.

        Raises:
            KeyError: If the key is not found in the index or builder.
        """
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
        """Iterate entries matching a prefix.

        Args:
            prefix: Key prefix tuple to match.

        Yields:
            tuple: (key, value) pairs for matching entries.
        """
        for entry in self._index.iter_entries_prefix([prefix]):
            yield (entry[1], entry[2])
        if self._builder is not None:
            for entry in self._builder.iter_entries_prefix([prefix]):
                yield (entry[1], entry[2])

    def lookup_commit(self, revid):
        """Retrieve a Git commit SHA by Bazaar revision ID from index.

        Args:
            revid: Bazaar revision ID to look up.

        Returns:
            str: First 40 characters of the commit SHA from the index entry.

        Raises:
            KeyError: If the revision ID is not found.
        """
        return self._get_entry((b"commit", revid, b"X"))[:40]

    def _add_git_sha(self, hexsha, type, type_data):
        """Add a Git SHA mapping to the index.

        Args:
            hexsha: Git SHA as bytes, or None for objects not in Git.
            type: Object type (b"commit", b"blob", or b"tree").
            type_data: Type-specific data tuple.
        """
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
        """Retrieve a Git blob SHA by file ID and revision from index.

        Args:
            fileid: File ID to look up.
            revision: Revision to look up blob in.

        Returns:
            bytes: Git blob SHA from the index entry.

        Raises:
            KeyError: If the file ID or revision is not found.
        """
        return self._get_entry((b"blob", fileid, revision))

    def lookup_git_sha(self, sha):
        """Lookup a Git SHA in the index.

        Args:
            sha: Git object SHA as bytes or hex string.

        Yields:
            tuple: (type, type_data) with type_data being:
                - commit: (revid, tree_sha, verifiers)
                - blob/tree: (fileid, revid)

        Raises:
            KeyError: If SHA is not found in index.
        """
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
        """List the revision IDs known in the index.

        Yields:
            bytes: Bazaar revision IDs for all commits in the index.
        """
        for key, _value in self._iter_entries_prefix((b"commit", None, None)):
            yield key[1]

    def missing_revisions(self, revids):
        """Return set of all the revisions that are not present in index.

        Args:
            revids: Collection of revision IDs to check.

        Returns:
            set: Set of revision IDs that are missing from the index.
        """
        missing_revids = set(revids)
        for _, key, _value in self._index.iter_entries(
            (b"commit", revid, b"X") for revid in revids
        ):
            missing_revids.remove(key[1])
        return missing_revids

    def sha1s(self):
        """List the SHA1s stored in the index.

        Yields:
            bytes: All Git SHA1s as bytes from the index.
        """
        for key, _value in self._iter_entries_prefix((b"git", None, None)):
            yield key[1]


formats = registry.Registry[str, BzrGitCacheFormat, None]()
formats.register(TdbGitCacheFormat().get_format_string(), TdbGitCacheFormat())
formats.register(SqliteGitCacheFormat().get_format_string(), SqliteGitCacheFormat())
formats.register(IndexGitCacheFormat().get_format_string(), IndexGitCacheFormat())
# In the future, this will become the default:
formats.register("default", IndexGitCacheFormat())


def migrate_ancient_formats(repo_transport):
    """Migrate older cache formats to the current directory structure.

    Args:
        repo_transport: Transport for the repository.
    """
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
    """Remove read-only decorator from transport if present.

    Args:
        transport: Transport to remove decorator from.

    Returns:
        Transport without read-only decorator.

    Raises:
        ReadOnlyError: If transport cannot be made writable.
    """
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

    Args:
        repository: A repository object.

    Returns:
        BzrGitCache instance for the repository.
    """
    repo_transport = getattr(repository, "_transport", None)
    if repo_transport is not None:
        try:
            migrate_ancient_formats(repo_transport)
        except bzr_errors.ReadOnlyError:
            pass  # Not much we can do
    return BzrGitCacheFormat.from_repository(repository)
