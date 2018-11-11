# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""A Git repository implementation that uses a Bazaar transport."""

from __future__ import absolute_import

from io import BytesIO

import os
import sys

from dulwich.errors import (
    NoIndexPresent,
    )
from dulwich.file import (
    GitFile,
    FileLocked,
    )
from dulwich.objects import (
    ShaFile,
    )
from dulwich.object_store import (
    PackBasedObjectStore,
    PACKDIR,
    )
from dulwich.pack import (
    MemoryPackIndex,
    PackData,
    Pack,
    iter_sha1,
    load_pack_index_file,
    write_pack_objects,
    write_pack_index_v2,
    )
from dulwich.repo import (
    BaseRepo,
    InfoRefsContainer,
    RefsContainer,
    BASE_DIRECTORIES,
    COMMONDIR,
    CONTROLDIR,
    INDEX_FILENAME,
    OBJECTDIR,
    SYMREF,
    check_ref_format,
    read_packed_refs_with_peeled,
    read_packed_refs,
    write_packed_refs,
    )

from .. import (
    osutils,
    transport as _mod_transport,
    urlutils,
    )
from ..errors import (
    AlreadyControlDirError,
    FileExists,
    LockBroken,
    LockContention,
    NotLocalUrl,
    NoSuchFile,
    ReadError,
    TransportNotPossible,
    )

from ..lock import LogicalLockResult


class TransportRefsContainer(RefsContainer):
    """Refs container that reads refs from a transport."""

    def __init__(self, transport, worktree_transport=None):
        self.transport = transport
        if worktree_transport is None:
            worktree_transport = transport
        self.worktree_transport = worktree_transport
        self._packed_refs = None
        self._peeled_refs = None

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.transport)

    def _ensure_dir_exists(self, path):
        for n in range(path.count("/")):
            dirname = "/".join(path.split("/")[:n + 1])
            try:
                self.transport.mkdir(dirname)
            except FileExists:
                pass

    def subkeys(self, base):
        """Refs present in this container under a base.

        :param base: The base to return refs under.
        :return: A set of valid refs in this container under the base; the base
            prefix is stripped from the ref names returned.
        """
        keys = set()
        base_len = len(base) + 1
        for refname in self.allkeys():
            if refname.startswith(base):
                keys.add(refname[base_len:])
        return keys

    def allkeys(self):
        keys = set()
        try:
            self.worktree_transport.get_bytes("HEAD")
        except NoSuchFile:
            pass
        else:
            keys.add(b"HEAD")
        try:
            iter_files = list(self.transport.clone(
                "refs").iter_files_recursive())
            for filename in iter_files:
                unquoted_filename = urlutils.unquote_to_bytes(filename)
                refname = osutils.pathjoin(b"refs", unquoted_filename)
                if check_ref_format(refname):
                    keys.add(refname)
        except (TransportNotPossible, NoSuchFile):
            pass
        keys.update(self.get_packed_refs())
        return keys

    def get_packed_refs(self):
        """Get contents of the packed-refs file.

        :return: Dictionary mapping ref names to SHA1s

        :note: Will return an empty dictionary when no packed-refs file is
            present.
        """
        # TODO: invalidate the cache on repacking
        if self._packed_refs is None:
            # set both to empty because we want _peeled_refs to be
            # None if and only if _packed_refs is also None.
            self._packed_refs = {}
            self._peeled_refs = {}
            try:
                f = self.transport.get("packed-refs")
            except NoSuchFile:
                return {}
            try:
                first_line = next(iter(f)).rstrip()
                if (first_line.startswith(b"# pack-refs") and b" peeled" in
                        first_line):
                    for sha, name, peeled in read_packed_refs_with_peeled(f):
                        self._packed_refs[name] = sha
                        if peeled:
                            self._peeled_refs[name] = peeled
                else:
                    f.seek(0)
                    for sha, name in read_packed_refs(f):
                        self._packed_refs[name] = sha
            finally:
                f.close()
        return self._packed_refs

    def get_peeled(self, name):
        """Return the cached peeled value of a ref, if available.

        :param name: Name of the ref to peel
        :return: The peeled value of the ref. If the ref is known not point to
            a tag, this will be the SHA the ref refers to. If the ref may point
            to a tag, but no cached information is available, None is returned.
        """
        self.get_packed_refs()
        if self._peeled_refs is None or name not in self._packed_refs:
            # No cache: no peeled refs were read, or this ref is loose
            return None
        if name in self._peeled_refs:
            return self._peeled_refs[name]
        else:
            # Known not peelable
            return self[name]

    def read_loose_ref(self, name):
        """Read a reference file and return its contents.

        If the reference file a symbolic reference, only read the first line of
        the file. Otherwise, only read the first 40 bytes.

        :param name: the refname to read, relative to refpath
        :return: The contents of the ref file, or None if the file does not
            exist.
        :raises IOError: if any other error occurs
        """
        if name == b'HEAD':
            transport = self.worktree_transport
        else:
            transport = self.transport
        try:
            f = transport.get(urlutils.quote_from_bytes(name))
        except NoSuchFile:
            return None
        with f:
            header = f.read(len(SYMREF))
            if header == SYMREF:
                # Read only the first line
                return header + next(iter(f)).rstrip(b"\r\n")
            else:
                # Read only the first 40 bytes
                return header + f.read(40 - len(SYMREF))

    def _remove_packed_ref(self, name):
        if self._packed_refs is None:
            return
        # reread cached refs from disk, while holding the lock

        self._packed_refs = None
        self.get_packed_refs()

        if name not in self._packed_refs:
            return

        del self._packed_refs[name]
        if name in self._peeled_refs:
            del self._peeled_refs[name]
        f = self.transport.open_write_stream("packed-refs")
        try:
            write_packed_refs(f, self._packed_refs, self._peeled_refs)
        finally:
            f.close()

    def set_symbolic_ref(self, name, other):
        """Make a ref point at another ref.

        :param name: Name of the ref to set
        :param other: Name of the ref to point at
        """
        self._check_refname(name)
        self._check_refname(other)
        if name != b'HEAD':
            transport = self.transport
            self._ensure_dir_exists(urlutils.quote_from_bytes(name))
        else:
            transport = self.worktree_transport
        transport.put_bytes(urlutils.quote_from_bytes(
            name), SYMREF + other + b'\n')

    def set_if_equals(self, name, old_ref, new_ref):
        """Set a refname to new_ref only if it currently equals old_ref.

        This method follows all symbolic references, and can be used to perform
        an atomic compare-and-swap operation.

        :param name: The refname to set.
        :param old_ref: The old sha the refname must refer to, or None to set
            unconditionally.
        :param new_ref: The new sha the refname will refer to.
        :return: True if the set was successful, False otherwise.
        """
        try:
            realnames, _ = self.follow(name)
            realname = realnames[-1]
        except (KeyError, IndexError):
            realname = name
        if realname == b'HEAD':
            transport = self.worktree_transport
        else:
            transport = self.transport
            self._ensure_dir_exists(urlutils.quote_from_bytes(realname))
        transport.put_bytes(urlutils.quote_from_bytes(
            realname), new_ref + b"\n")
        return True

    def add_if_new(self, name, ref):
        """Add a new reference only if it does not already exist.

        This method follows symrefs, and only ensures that the last ref in the
        chain does not exist.

        :param name: The refname to set.
        :param ref: The new sha the refname will refer to.
        :return: True if the add was successful, False otherwise.
        """
        try:
            realnames, contents = self.follow(name)
            if contents is not None:
                return False
            realname = realnames[-1]
        except (KeyError, IndexError):
            realname = name
        self._check_refname(realname)
        if realname == b'HEAD':
            transport = self.worktree_transport
        else:
            transport = self.transport
            self._ensure_dir_exists(urlutils.quote_from_bytes(realname))
        transport.put_bytes(urlutils.quote_from_bytes(realname), ref + b"\n")
        return True

    def remove_if_equals(self, name, old_ref):
        """Remove a refname only if it currently equals old_ref.

        This method does not follow symbolic references. It can be used to
        perform an atomic compare-and-delete operation.

        :param name: The refname to delete.
        :param old_ref: The old sha the refname must refer to, or None to
            delete unconditionally.
        :return: True if the delete was successful, False otherwise.
        """
        self._check_refname(name)
        # may only be packed
        if name == b'HEAD':
            transport = self.worktree_transport
        else:
            transport = self.transport
        try:
            transport.delete(urlutils.quote_from_bytes(name))
        except NoSuchFile:
            pass
        self._remove_packed_ref(name)
        return True

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    def unlock_ref(self, name):
        if name == b"HEAD":
            transport = self.worktree_transport
        else:
            transport = self.transport
        lockname = name + b".lock"
        try:
            transport.delete(urlutils.quote_from_bytes(lockname))
        except NoSuchFile:
            pass

    def lock_ref(self, name):
        if name == b"HEAD":
            transport = self.worktree_transport
        else:
            transport = self.transport
        self._ensure_dir_exists(urlutils.quote_from_bytes(name))
        lockname = urlutils.quote_from_bytes(name + b".lock")
        try:
            local_path = transport.local_abspath(
                urlutils.quote_from_bytes(name))
        except NotLocalUrl:
            # This is racy, but what can we do?
            if transport.has(lockname):
                raise LockContention(name)
            transport.put_bytes(lockname, b'Locked by brz-git')
            return LogicalLockResult(lambda: transport.delete(lockname))
        else:
            try:
                gf = GitFile(local_path, 'wb')
            except FileLocked as e:
                raise LockContention(name, e)
            else:
                def unlock():
                    try:
                        transport.delete(lockname)
                    except NoSuchFile:
                        raise LockBroken(lockname)
                    # GitFile.abort doesn't care if the lock has already
                    # disappeared
                    gf.abort()
                return LogicalLockResult(unlock)


# TODO(jelmer): Use upstream read_gitfile; unfortunately that expects strings
# rather than bytes..
def read_gitfile(f):
    """Read a ``.git`` file.

    The first line of the file should start with "gitdir: "

    :param f: File-like object to read from
    :return: A path
    """
    cs = f.read()
    if not cs.startswith(b"gitdir: "):
        raise ValueError("Expected file to start with 'gitdir: '")
    return cs[len(b"gitdir: "):].rstrip(b"\n")


class TransportRepo(BaseRepo):

    def __init__(self, transport, bare, refs_text=None):
        self.transport = transport
        self.bare = bare
        try:
            with transport.get(CONTROLDIR) as f:
                path = read_gitfile(f)
        except (ReadError, NoSuchFile):
            if self.bare:
                self._controltransport = self.transport
            else:
                self._controltransport = self.transport.clone('.git')
        else:
            self._controltransport = self.transport.clone(
                urlutils.quote_from_bytes(path))
        commondir = self.get_named_file(COMMONDIR)
        if commondir is not None:
            with commondir:
                commondir = os.path.join(
                    self.controldir(),
                    commondir.read().rstrip(b"\r\n").decode(
                        sys.getfilesystemencoding()))
                self._commontransport = \
                    _mod_transport.get_transport_from_path(commondir)
        else:
            self._commontransport = self._controltransport
        object_store = TransportObjectStore(
            self._commontransport.clone(OBJECTDIR))
        if refs_text is not None:
            refs_container = InfoRefsContainer(BytesIO(refs_text))
            try:
                head = TransportRefsContainer(
                    self._commontransport).read_loose_ref("HEAD")
            except KeyError:
                pass
            else:
                refs_container._refs["HEAD"] = head
        else:
            refs_container = TransportRefsContainer(
                self._commontransport, self._controltransport)
        super(TransportRepo, self).__init__(object_store,
                                            refs_container)

    def controldir(self):
        return self._controltransport.local_abspath('.')

    def commondir(self):
        return self._commontransport.local_abspath('.')

    @property
    def path(self):
        return self.transport.local_abspath('.')

    def _determine_file_mode(self):
        # Be consistent with bzr
        if sys.platform == 'win32':
            return False
        return True

    def get_named_file(self, path):
        """Get a file from the control dir with a specific name.

        Although the filename should be interpreted as a filename relative to
        the control dir in a disk-baked Repo, the object returned need not be
        pointing to a file in that location.

        :param path: The path to the file, relative to the control dir.
        :return: An open file object, or None if the file does not exist.
        """
        try:
            return self._controltransport.get(path.lstrip('/'))
        except NoSuchFile:
            return None

    def _put_named_file(self, relpath, contents):
        self._controltransport.put_bytes(relpath, contents)

    def index_path(self):
        """Return the path to the index file."""
        return self._controltransport.local_abspath(INDEX_FILENAME)

    def open_index(self):
        """Open the index for this repository."""
        from dulwich.index import Index
        if not self.has_index():
            raise NoIndexPresent()
        return Index(self.index_path())

    def has_index(self):
        """Check if an index is present."""
        # Bare repos must never have index files; non-bare repos may have a
        # missing index file, which is treated as empty.
        return not self.bare

    def get_config(self):
        from dulwich.config import ConfigFile
        try:
            with self._controltransport.get('config') as f:
                return ConfigFile.from_file(f)
        except NoSuchFile:
            return ConfigFile()

    def get_config_stack(self):
        from dulwich.config import StackedConfig
        backends = []
        p = self.get_config()
        if p is not None:
            backends.append(p)
            writable = p
        else:
            writable = None
        backends.extend(StackedConfig.default_backends())
        return StackedConfig(backends, writable=writable)

    def __repr__(self):
        return "<%s for %r>" % (self.__class__.__name__, self.transport)

    @classmethod
    def init(cls, transport, bare=False):
        if not bare:
            try:
                transport.mkdir(".git")
            except FileExists:
                raise AlreadyControlDirError(transport.base)
            control_transport = transport.clone(".git")
        else:
            control_transport = transport
        for d in BASE_DIRECTORIES:
            try:
                control_transport.mkdir("/".join(d))
            except FileExists:
                pass
        try:
            control_transport.mkdir(OBJECTDIR)
        except FileExists:
            raise AlreadyControlDirError(transport.base)
        TransportObjectStore.init(control_transport.clone(OBJECTDIR))
        ret = cls(transport, bare)
        ret.refs.set_symbolic_ref(b"HEAD", b"refs/heads/master")
        ret._init_files(bare)
        return ret


class TransportObjectStore(PackBasedObjectStore):
    """Git-style object store that exists on disk."""

    def __init__(self, transport):
        """Open an object store.

        :param transport: Transport to open data from
        """
        super(TransportObjectStore, self).__init__()
        self.transport = transport
        self.pack_transport = self.transport.clone(PACKDIR)
        self._alternates = None

    def __eq__(self, other):
        if not isinstance(other, TransportObjectStore):
            return False
        return self.transport == other.transport

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.transport)

    @property
    def alternates(self):
        if self._alternates is not None:
            return self._alternates
        self._alternates = []
        for path in self._read_alternate_paths():
            # FIXME: Check path
            t = _mod_transport.get_transport_from_path(path)
            self._alternates.append(self.__class__(t))
        return self._alternates

    def _read_alternate_paths(self):
        try:
            f = self.transport.get("info/alternates")
        except NoSuchFile:
            return []
        ret = []
        with f:
            for l in f.read().splitlines():
                if l[0] == b"#":
                    continue
                if os.path.isabs(l):
                    continue
                ret.append(l)
            return ret

    @property
    def packs(self):
        # FIXME: Never invalidates.
        if not self._pack_cache:
            self._update_pack_cache()
        return self._pack_cache.values()

    def _update_pack_cache(self):
        for pack in self._load_packs():
            self._pack_cache[pack._basename] = pack

    def _pack_names(self):
        try:
            return self.pack_transport.list_dir(".")
        except TransportNotPossible:
            try:
                f = self.transport.get('info/packs')
            except NoSuchFile:
                # Hmm, warn about running 'git update-server-info' ?
                return iter([])
            else:
                # TODO(jelmer): Move to top-level after dulwich
                # 0.19.7 is released.
                from dulwich.object_store import read_packs_file
                with f:
                    return read_packs_file(f)
        except NoSuchFile:
            return iter([])

    def _remove_pack(self, pack):
        self.pack_transport.delete(os.path.basename(pack.index.path))
        self.pack_transport.delete(pack.data.filename)

    def _load_packs(self):
        ret = []
        for name in self._pack_names():
            if name.startswith("pack-") and name.endswith(".pack"):
                try:
                    size = self.pack_transport.stat(name).st_size
                except TransportNotPossible:
                    f = self.pack_transport.get(name)
                    pd = PackData(name, f)
                else:
                    pd = PackData(name, self.pack_transport.get(name),
                                  size=size)
                idxname = name.replace(".pack", ".idx")
                idx = load_pack_index_file(
                    idxname, self.pack_transport.get(idxname))
                pack = Pack.from_objects(pd, idx)
                pack._basename = idxname[:-4]
                ret.append(pack)
        return ret

    def _iter_loose_objects(self):
        for base in self.transport.list_dir('.'):
            if len(base) != 2:
                continue
            for rest in self.transport.list_dir(base):
                yield (base + rest).encode(sys.getfilesystemencoding())

    def _split_loose_object(self, sha):
        return (sha[:2], sha[2:])

    def _remove_loose_object(self, sha):
        path = osutils.joinpath(self._split_loose_object(sha))
        self.transport.delete(urlutils.quote_from_bytes(path))

    def _get_loose_object(self, sha):
        path = osutils.joinpath(self._split_loose_object(sha))
        try:
            with self.transport.get(urlutils.quote_from_bytes(path)) as f:
                return ShaFile.from_file(f)
        except NoSuchFile:
            return None

    def add_object(self, obj):
        """Add a single object to this object store.

        :param obj: Object to add
        """
        (dir, file) = self._split_loose_object(obj.id)
        try:
            self.transport.mkdir(urlutils.quote_from_bytes(dir))
        except FileExists:
            pass
        path = urlutils.quote_from_bytes(osutils.pathjoin(dir, file))
        if self.transport.has(path):
            return  # Already there, no need to write again
        self.transport.put_bytes(path, obj.as_legacy_object())

    def move_in_pack(self, f):
        """Move a specific file containing a pack into the pack directory.

        :note: The file should be on the same file system as the
            packs directory.

        :param path: Path to the pack file.
        """
        f.seek(0)
        p = PackData("", f, len(f.getvalue()))
        entries = p.sorted_entries()
        basename = "pack-%s" % iter_sha1(entry[0]
                                         for entry in entries).decode('ascii')
        p._filename = basename + ".pack"
        f.seek(0)
        self.pack_transport.put_file(basename + ".pack", f)
        idxfile = self.pack_transport.open_write_stream(basename + ".idx")
        try:
            write_pack_index_v2(idxfile, entries, p.get_stored_checksum())
        finally:
            idxfile.close()
        idxfile = self.pack_transport.get(basename + ".idx")
        idx = load_pack_index_file(basename + ".idx", idxfile)
        final_pack = Pack.from_objects(p, idx)
        final_pack._basename = basename
        self._add_known_pack(basename, final_pack)
        return final_pack

    def move_in_thin_pack(self, f):
        """Move a specific file containing a pack into the pack directory.

        :note: The file should be on the same file system as the
            packs directory.

        :param path: Path to the pack file.
        """
        f.seek(0)
        p = Pack('', resolve_ext_ref=self.get_raw)
        p._data = PackData.from_file(f, len(f.getvalue()))
        p._data.pack = p
        p._idx_load = lambda: MemoryPackIndex(
            p.data.sorted_entries(), p.data.get_stored_checksum())

        pack_sha = p.index.objects_sha1()

        datafile = self.pack_transport.open_write_stream(
            "pack-%s.pack" % pack_sha.decode('ascii'))
        try:
            entries, data_sum = write_pack_objects(datafile, p.pack_tuples())
        finally:
            datafile.close()
        entries = sorted([(k, v[0], v[1]) for (k, v) in entries.items()])
        idxfile = self.pack_transport.open_write_stream(
            "pack-%s.idx" % pack_sha.decode('ascii'))
        try:
            write_pack_index_v2(idxfile, entries, data_sum)
        finally:
            idxfile.close()
        # TODO(jelmer): Just add new pack to the cache
        self._flush_pack_cache()

    def add_pack(self):
        """Add a new pack to this object store.

        :return: Fileobject to write to and a commit function to
            call when the pack is finished.
        """
        f = BytesIO()

        def commit():
            if len(f.getvalue()) > 0:
                return self.move_in_pack(f)
            else:
                return None

        def abort():
            return None
        return f, commit, abort

    @classmethod
    def init(cls, transport):
        try:
            transport.mkdir('info')
        except FileExists:
            pass
        try:
            transport.mkdir(PACKDIR)
        except FileExists:
            pass
        return cls(transport)
