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

from io import BytesIO

import os
import sys
import posixpath

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
    read_packs_file,
    )
from dulwich.pack import (
    MemoryPackIndex,
    PackData,
    PackIndexer,
    Pack,
    PackStreamCopier,
    iter_sha1,
    load_pack_index_file,
    write_pack_objects,
    write_pack_index_v2,
    write_pack_header,
    compute_file_sha,
    write_pack_object,
    )
try:
    from dulwich.refs import SymrefLoop
except ImportError:  # dulwich < 0.20.46
    SymrefLoop = KeyError
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
    LockBroken,
    LockContention,
    NotLocalUrl,
    ReadError,
    TransportNotPossible,
    )

from ..lock import LogicalLockResult
from ..trace import warning
from ..transport import (
    FileExists,
    NoSuchFile,
    )


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
        self.transport.clone(posixpath.dirname(path)).create_prefix()

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
            try:
                header = f.read(len(SYMREF))
            except ReadError:
                # probably a directory
                return None
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
        with self.transport.open_write_stream("packed-refs") as f:
            write_packed_refs(f, self._packed_refs, self._peeled_refs)

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
        self._check_refname(name)
        try:
            realnames, _ = self.follow(name)
            realname = realnames[-1]
        except (KeyError, IndexError, SymrefLoop):
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
        config = self.get_config()
        object_store = TransportObjectStore.from_config(
            self._commontransport.clone(OBJECTDIR),
            config)
        if refs_text is not None:
            refs_container = InfoRefsContainer(BytesIO(refs_text))
            try:
                head = TransportRefsContainer(
                    self._commontransport).read_loose_ref(b"HEAD")
            except KeyError:
                pass
            else:
                refs_container._refs[b"HEAD"] = head
        else:
            refs_container = TransportRefsContainer(
                self._commontransport, self._controltransport)
        super(TransportRepo, self).__init__(object_store,
                                            refs_container)

    def controldir(self):
        return self._controltransport.local_abspath('.')

    def commondir(self):
        return self._commontransport.local_abspath('.')

    def close(self):
        """Close any files opened by this repository."""
        self.object_store.close()

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

    def __init__(self, transport,
                 loose_compression_level=-1, pack_compression_level=-1):
        """Open an object store.

        :param transport: Transport to open data from
        """
        super(TransportObjectStore, self).__init__()
        self.pack_compression_level = pack_compression_level
        self.loose_compression_level = loose_compression_level
        self.transport = transport
        self.pack_transport = self.transport.clone(PACKDIR)
        self._alternates = None

    @classmethod
    def from_config(cls, path, config):
        try:
            default_compression_level = int(config.get(
                (b'core', ), b'compression').decode())
        except KeyError:
            default_compression_level = -1
        try:
            loose_compression_level = int(config.get(
                (b'core', ), b'looseCompression').decode())
        except KeyError:
            loose_compression_level = default_compression_level
        try:
            pack_compression_level = int(config.get(
                (b'core', ), 'packCompression').decode())
        except KeyError:
            pack_compression_level = default_compression_level
        return cls(path, loose_compression_level, pack_compression_level)

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

    def _update_pack_cache(self):
        pack_files = set(self._pack_names())
        new_packs = []
        for basename in pack_files:
            pack_name = basename + ".pack"
            if basename not in self._pack_cache:
                try:
                    size = self.pack_transport.stat(pack_name).st_size
                except TransportNotPossible:
                    try:
                        f = self.pack_transport.get(pack_name)
                    except NoSuchFile:
                        warning('Unable to read pack file %s',
                                self.pack_transport.abspath(pack_name))
                        continue
                    from tempfile import SpooledTemporaryFile
                    f = SpooledTemporaryFile(f.read())
                    pd = PackData(pack_name, f)
                else:
                    pd = PackData(
                        pack_name, self.pack_transport.get(pack_name),
                        size=size)
                idxname = basename + ".idx"
                idx = load_pack_index_file(
                    idxname, self.pack_transport.get(idxname))
                pack = Pack.from_objects(pd, idx)
                pack._basename = basename
                self._pack_cache[basename] = pack
                new_packs.append(pack)
        # Remove disappeared pack files
        for f in set(self._pack_cache) - pack_files:
            self._pack_cache.pop(f).close()
        return new_packs

    def _pack_names(self):
        pack_files = []
        try:
            dir_contents = self.pack_transport.list_dir(".")
            for name in dir_contents:
                if name.startswith("pack-") and name.endswith(".pack"):
                    # verify that idx exists first (otherwise the pack was not yet
                    # fully written)
                    idx_name = os.path.splitext(name)[0] + ".idx"
                    if idx_name in dir_contents:
                        pack_files.append(os.path.splitext(name)[0])
        except TransportNotPossible:
            try:
                f = self.transport.get('info/packs')
            except NoSuchFile:
                warning('No info/packs on remote host;'
                        'run \'git update-server-info\' on remote.')
            else:
                with f:
                    pack_files = [
                        os.path.splitext(name)[0]
                        for name in read_packs_file(f)]
        except NoSuchFile:
            pass
        return pack_files

    def _remove_pack(self, pack):
        self.pack_transport.delete(os.path.basename(pack.index.path))
        self.pack_transport.delete(pack.data.filename)
        try:
            del self._pack_cache[os.path.basename(pack._basename)]
        except KeyError:
            pass

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
        # Backwards compatibility with Dulwich < 0.20, which doesn't support
        # the compression_level parameter.
        if self.loose_compression_level not in (-1, None):
            raw_string = obj.as_legacy_object(
                compression_level=self.loose_compression_level)
        else:
            raw_string = obj.as_legacy_object()
        self.transport.put_bytes(path, raw_string)

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
        with self.pack_transport.open_write_stream(basename + ".idx") as idxfile:
            write_pack_index_v2(idxfile, entries, p.get_stored_checksum())
        idxfile = self.pack_transport.get(basename + ".idx")
        idx = load_pack_index_file(basename + ".idx", idxfile)
        final_pack = Pack.from_objects(p, idx)
        final_pack._basename = basename
        self._add_cached_pack(basename, final_pack)
        return final_pack

    def move_in_thin_pack(self, f):
        """Move a specific file containing a pack into the pack directory.

        :note: The file should be on the same file system as the
            packs directory.

        :param path: Path to the pack file.
        """
        f.seek(0)
        data = PackData.from_file(f, len(f.getvalue()))
        if hasattr(Pack, 'sorted_entries'):
            from dulwich.pack import _PackTupleIterable, PackInflater
            sorted_entries = list(
                data.sorted_entries(resolve_ext_ref=self.get_raw))
            pack_sha = iter_sha1(entry[0] for entry in sorted_entries)
            inflater = PackInflater.for_pack_data(
                data, resolve_ext_ref=self.get_raw)
            pack_tuples = _PackTupleIterable(lambda: iter(inflater), len(data))
        else:  # dulwich < 0.20.47
            p = Pack('', resolve_ext_ref=self.get_raw)
            p._data = data
            p._data.pack = p
            sorted_entries = p.data.sorted_entries()

            p._idx_load = lambda: MemoryPackIndex(
                sorted_entries,
                p.data.get_stored_checksum())

            pack_sha = p.index.objects_sha1()
            pack_tuples = p.pack_tuples()

        with self.pack_transport.open_write_stream(
                "pack-%s.pack" % pack_sha.decode('ascii')) as datafile:
            entries, data_sum = write_pack_objects(datafile, pack_tuples)
        entries = sorted([(k, v[0], v[1]) for (k, v) in entries.items()])
        with self.pack_transport.open_write_stream(
                "pack-%s.idx" % pack_sha.decode('ascii')) as idxfile:
            write_pack_index_v2(idxfile, entries, data_sum)

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

    def _get_pack_basepath(self, entries):
        suffix = iter_sha1(entry[0] for entry in entries)
        # TODO: Handle self.pack_dir being bytes
        suffix = suffix.decode('ascii')
        return self.pack_transport.local_abspath("pack-" + suffix)

    def _complete_thin_pack(self, f, path, copier, indexer):
        """Move a specific file containing a pack into the pack directory.

        Note: The file should be on the same file system as the
            packs directory.

        Args:
          f: Open file object for the pack.
          path: Path to the pack file.
          copier: A PackStreamCopier to use for writing pack data.
          indexer: A PackIndexer for indexing the pack.
        """
        entries = list(indexer)

        # Update the header with the new number of objects.
        f.seek(0)
        write_pack_header(f, len(entries) + len(indexer.ext_refs()))

        # Must flush before reading (http://bugs.python.org/issue3207)
        f.flush()

        # Rescan the rest of the pack, computing the SHA with the new header.
        new_sha = compute_file_sha(f, end_ofs=-20)

        # Must reposition before writing (http://bugs.python.org/issue3207)
        f.seek(0, os.SEEK_CUR)

        # Complete the pack.
        for ext_sha in indexer.ext_refs():
            type_num, data = self.get_raw(ext_sha)
            offset = f.tell()
            crc32 = write_pack_object(
                f, type_num, data, sha=new_sha,
                compression_level=self.pack_compression_level)
            entries.append((ext_sha, offset, crc32))
        pack_sha = new_sha.digest()
        f.write(pack_sha)
        f.close()

        # Move the pack in.
        entries.sort()
        pack_base_name = self._get_pack_basepath(entries)
        target_pack = pack_base_name + '.pack'
        if sys.platform == 'win32':
            # Windows might have the target pack file lingering. Attempt
            # removal, silently passing if the target does not exist.
            try:
                os.remove(target_pack)
            except FileNotFoundError:
                pass
        os.rename(path, target_pack)

        # Write the index.
        index_file = GitFile(pack_base_name + '.idx', 'wb')
        try:
            write_pack_index_v2(index_file, entries, pack_sha)
            index_file.close()
        finally:
            index_file.abort()

        # Add the pack to the store and return it.
        final_pack = Pack(pack_base_name)
        final_pack.check_length_and_checksum()
        self._add_cached_pack(pack_base_name, final_pack)
        return final_pack

    def add_thin_pack(self, read_all, read_some):
        """Add a new thin pack to this object store.

        Thin packs are packs that contain deltas with parents that exist
        outside the pack. They should never be placed in the object store
        directly, and always indexed and completed as they are copied.

        Args:
          read_all: Read function that blocks until the number of
            requested bytes are read.
          read_some: Read function that returns at least one byte, but may
            not return the number of bytes requested.
        Returns: A Pack object pointing at the now-completed thin pack in the
            objects/pack directory.
        """
        import tempfile
        fd, path = tempfile.mkstemp(dir=self.pack_transport.local_abspath('.'), prefix='tmp_pack_')
        with os.fdopen(fd, 'w+b') as f:
            indexer = PackIndexer(f, resolve_ext_ref=self.get_raw)
            copier = PackStreamCopier(read_all, read_some, f,
                                      delta_iter=indexer)
            copier.verify()
            return self._complete_thin_pack(f, path, copier, indexer)
