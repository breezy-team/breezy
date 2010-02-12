# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""A Git repository implementation that uses a Bazaar transport."""


from dulwich.errors import (
    NotGitRepository,
    NoIndexPresent,
    )
from dulwich.objects import (
    ShaFile,
    )
from dulwich.object_store import (
    PackBasedObjectStore,
    PACKDIR,
    )
from dulwich.pack import (
    PackData,
    Pack,
    load_pack_index_file,
    )
from dulwich.repo import (
    BaseRepo,
    RefsContainer,
    OBJECTDIR,
    REFSDIR,
    BASE_DIRECTORIES,
    SYMREF,
    check_ref_format,
    read_packed_refs_with_peeled,
    read_packed_refs,
    write_packed_refs,
    )
import errno

from bzrlib import (
    urlutils,
    )
from bzrlib.errors import (
    NoSuchFile,
    )


class TransportRepo(BaseRepo):

    def __init__(self, transport):
        self.transport = transport
        if self.transport.has(urlutils.join(".git", OBJECTDIR)):
            self.bare = False
            self._controltransport = self.transport.clone('.git')
        elif (self.transport.has(OBJECTDIR) and
              self.transport.has(REFSDIR)):
            self.bare = True
            self._controltransport = self.transport
        else:
            raise NotGitRepository(self.transport)
        object_store = TransportObjectStore(
            self._controltransport.clone(OBJECTDIR))
        refs = TransportRefsContainer(self._controltransport)
        super(TransportRepo, self).__init__(object_store, refs)

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

    def put_named_file(self, path, contents):
        self._controltransport.put_bytes(path.lstrip('/'), contents)

    def open_index(self):
        """Open the index for this repository."""
        from dulwich.index import Index
        try:
            return Index(self._controltransport.local_abspath('index'))
        except NoSuchFile:
            raise NoIndexPresent()
        except (IOError, OSError), e:
            if e.errno == errno.ENOENT:
                raise NoIndexPresent()
            raise

    def __repr__(self):
        return "<TransportRepo for %r>" % self.transport

    @classmethod
    def init(cls, transport, mkdir=True):
        transport.mkdir('.git')
        controltransport = transport.clone('.git')
        cls.init_bare(controltransport)
        return cls(controltransport)

    @classmethod
    def init_bare(cls, transport, mkdir=True):
        for d in BASE_DIRECTORIES:
            transport.mkdir(urlutils.join(*d))
        ret = cls(transport)
        ret.refs.set_ref("HEAD", "refs/heads/master")
        ret.put_named_file('description', "Unnamed repository")
        ret.put_named_file('config', """[core]
    repositoryformatversion = 0
    filemode = true
    bare = false
    logallrefupdates = true
""")
        ret.put_named_file('info/excludes', '')
        return ret

    create = init_bare


class TransportObjectStore(PackBasedObjectStore):
    """Git-style object store that exists on disk."""

    def __init__(self, transport):
        """Open an object store.

        :param transport: Transport to open data from
        """
        super(TransportObjectStore, self).__init__()
        self.transport = transport
        self.pack_transport = self.transport.clone(PACKDIR)

    def _load_packs(self):
        pack_files = []
        for name in self.pack_transport.list_dir('.'):
            # TODO: verify that idx exists first
            if name.startswith("pack-") and name.endswith(".pack"):
                # TODO: if stat fails, just use None - after all
                # the st_mtime is just used for sorting
                st = self.pack_transport.stat(name)
                pack_files.append((st.st_mtime, st.st_size, name))
        pack_files.sort(reverse=True)
        suffix_len = len(".pack")
        ret = []
        for _, size, f in pack_files:
            pd = PackData.from_file(self.pack_transport.get(f), size)
            idxname = f.replace(".pack", ".idx")
            idx = load_pack_index_file(idxname, self.pack_transport.get(idxname))
            ret.append(Pack.from_objects(pd, idx))
        return ret

    def _iter_loose_objects(self):
        for base in self.transport.list_dir('.'):
            if len(base) != 2:
                continue
            for rest in self.transport.list_dir(base):
                yield base+rest

    def _split_loose_object(self, sha):
        return (sha[:2], sha[2:])

    def _get_loose_object(self, sha):
        path = '%s/%s' % self._split_loose_object(sha)
        try:
            return ShaFile._parse_file(self.transport.get(path).read())
        except NoSuchFile:
            return None

    def add_object(self, obj):
        """Add a single object to this object store.

        :param obj: Object to add
        """
        (dir, file) = self._split_loose_object(obj.id)
        self.transport.mkdir(dir)
        path = "%s/%s" % (dir, file)
        if self.transport.has(path):
            return # Already there, no need to write again
        self.transport.put_bytes(path, obj.as_legacy_object())

    def add_pack(self):
        """Add a new pack to this object store. 

        :return: Fileobject to write to and a commit function to 
            call when the pack is finished.
        """
        fd, path = tempfile.mkstemp(dir=self.pack_dir, suffix=".pack")
        f = os.fdopen(fd, 'wb')
        def commit():
            os.fsync(fd)
            f.close()
            if os.path.getsize(path) > 0:
                self.move_in_pack(path)
        return f, commit


class TransportRefsContainer(RefsContainer):
    """Refs container that reads refs from a transport."""

    def __init__(self, transport):
        self.transport = transport
        self._packed_refs = None
        self._peeled_refs = {}

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.transport)

    def subkeys(self, base):
        keys = set()
        for filename in self.transport.clone(base).iter_files_recursive():
            refname = ("%s/%s" % (base, filename)).strip("/")
            # check_ref_format requires at least one /, so we prepend the
            # base before calling it.
            if check_ref_format("%s/%s" % (base, refname)):
                keys.add(refname)
        for key in self.get_packed_refs():
            if key.startswith(base):
                keys.add(key[len(base):].strip("/"))
        return keys

    def allkeys(self):
        keys = set()
        if self.transport.has("HEAD"):
            keys.add("HEAD")
        for filename in self.transport.clone('refs').iter_files_recursive():
            refname = ("refs/%s" % filename).strip("/")
            if check_ref_format(refname):
                keys.add(refname)
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
            self._packed_refs = {}
            try:
                f = self.transport.get('packed-refs')
            except NoSuchFile:
                return {}
            try:
                first_line = iter(f).next().rstrip()
                if (first_line.startswith("# pack-refs") and " peeled" in
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

    def read_loose_ref(self, name):
        try:
            f = self.transport.get(name)
            try:
                header = f.read(len(SYMREF))
                if header == SYMREF:
                    # Read only the first line
                    return header + iter(f).next().rstrip("\n")
                else:
                    # Read only the first 40 bytes
                    return header + f.read(40-len(SYMREF))
            finally:
                f.close()
        except NoSuchFile:
            return None

    def _remove_packed_ref(self, name):
        if self._packed_refs is None:
            return
        filename = os.path.join(self.path, 'packed-refs')
        # reread cached refs from disk, while holding the lock
        f = GitFile(filename, 'wb')
        try:
            self._packed_refs = None
            self.get_packed_refs()

            if name not in self._packed_refs:
                return

            del self._packed_refs[name]
            if name in self._peeled_refs:
                del self._peeled_refs[name]
            write_packed_refs(f, self._packed_refs, self._peeled_refs)
            f.close()
        finally:
            f.abort()

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
            realname, _ = self._follow(name)
        except KeyError:
            realname = name
        dir_transport = self.transport.clone(urlutils.dirname(realname))
        dir_transport.create_prefix()
        f = GitFile(filename, 'wb')
        try:
            if old_ref is not None:
                try:
                    # read again while holding the lock
                    orig_ref = self.read_loose_ref(realname)
                    if orig_ref is None:
                        orig_ref = self.get_packed_refs().get(realname, None)
                    if orig_ref != old_ref:
                        f.abort()
                        return False
                except (OSError, IOError):
                    f.abort()
                    raise
            try:
                f.write(new_ref+"\n")
            except (OSError, IOError):
                f.abort()
                raise
        finally:
            f.close()
        return True

    def add_if_new(self, name, ref):
        """Add a new reference only if it does not already exist."""
        self._check_refname(name)
        ensure_dir_exists(urlutils.dirname(filename))
        f = GitFile(filename, 'wb')
        try:
            if self.transport.has(name) or name in self.get_packed_refs():
                f.abort()
                return False
            try:
                f.write(ref+"\n")
            except (OSError, IOError):
                f.abort()
                raise
        finally:
            f.close()
        return True

    def __setitem__(self, name, ref):
        """Set a reference name to point to the given SHA1.

        This method follows all symbolic references.

        :note: This method unconditionally overwrites the contents of a reference
            on disk. To update atomically only if the reference has not changed
            on disk, use set_if_equals().
        """
        self.set_if_equals(name, None, ref)

    def remove_if_equals(self, name, old_ref):
        """Remove a refname only if it currently equals old_ref.

        This method does not follow symbolic references. It can be used to
        perform an atomic compare-and-delete operation.

        :param name: The refname to delete.
        :param old_ref: The old sha the refname must refer to, or None to delete
            unconditionally.
        :return: True if the delete was successful, False otherwise.
        """
        self._check_refname(name)
        filename = self.refpath(name)
        ensure_dir_exists(os.path.dirname(filename))
        f = GitFile(filename, 'wb')
        try:
            if old_ref is not None:
                orig_ref = self.read_loose_ref(name)
                if orig_ref is None:
                    orig_ref = self.get_packed_refs().get(name, None)
                if orig_ref != old_ref:
                    return False
            # may only be packed
            if os.path.exists(filename):
                os.remove(filename)
            self._remove_packed_ref(name)
        finally:
            # never write, we just wanted the lock
            f.abort()
        return True

    def __delitem__(self, name):
        """Remove a refname.

        This method does not follow symbolic references.
        :note: This method unconditionally deletes the contents of a reference
            on disk. To delete atomically only if the reference has not changed
            on disk, use set_if_equals().
        """
        self.remove_if_equals(name, None)
