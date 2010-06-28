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

from cStringIO import StringIO

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
    iter_sha1,
    load_pack_index_file,
    write_pack_index_v2,
    )
from dulwich.repo import (
    BaseRepo,
    DictRefsContainer,
    OBJECTDIR,
    read_info_refs,
    )

from bzrlib.errors import (
    FileExists,
    NoSuchFile,
    TransportNotPossible,
    )


class TransportRepo(BaseRepo):

    def __init__(self, transport):
        self.transport = transport
        try:
            if self.transport.has(".git/info/refs"):
                self.bare = False
                self._controltransport = self.transport.clone('.git')
            elif self.transport.has("info/refs"):
                self.bare = True
                self._controltransport = self.transport
            else:
                raise NotGitRepository(self.transport)
        except NoSuchFile:
            raise NotGitRepository(self.transport)
        object_store = TransportObjectStore(
            self._controltransport.clone(OBJECTDIR))
        refs = {}
        refs["HEAD"] = self._controltransport.get_bytes("HEAD").rstrip("\n")
        refs.update(read_info_refs(self._controltransport.get('info/refs')))
        super(TransportRepo, self).__init__(object_store, 
                DictRefsContainer(refs))

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

    def open_index(self):
        """Open the index for this repository."""
        raise NoIndexPresent()

    def __repr__(self):
        return "<TransportRepo for %r>" % self.transport


class TransportObjectStore(PackBasedObjectStore):
    """Git-style object store that exists on disk."""

    def __init__(self, transport):
        """Open an object store.

        :param transport: Transport to open data from
        """
        super(TransportObjectStore, self).__init__()
        self.transport = transport
        self.pack_transport = self.transport.clone(PACKDIR)
    
    def _pack_cache_stale(self):
        return False # FIXME

    def _pack_names(self):
        try:
            f = self.transport.get('info/packs')
        except NoSuchFile:
            return self.pack_transport.list_dir(".")
        else:
            ret = []
            for line in f.readlines():
                line = line.rstrip("\n")
                if not line:
                    continue
                (kind, name) = line.split(" ", 1)
                if kind != "P":
                    continue
                ret.append(name)
            return ret

    def _load_packs(self):
        ret = []
        for name in self._pack_names():
            if name.startswith("pack-") and name.endswith(".pack"):
                try:
                    size = self.pack_transport.stat(name).st_size
                except TransportNotPossible:
                    def pd():
                        # FIXME: This reads the whole pack file at once
                        f = self.pack_transport.get(name)
                        contents = f.read()
                        return PackData(name, StringIO(contents), size=len(contents))
                else:
                    pd = lambda: PackData(name, self.pack_transport.get(name),
                            size=size)
                idxname = name.replace(".pack", ".idx")
                idx = lambda: load_pack_index_file(idxname, self.pack_transport.get(idxname))
                pack = Pack.from_lazy_objects(pd, idx)
                ret.append(pack)
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
            return ShaFile.from_file(self.transport.get(path))
        except NoSuchFile:
            return None

    def add_object(self, obj):
        """Add a single object to this object store.

        :param obj: Object to add
        """
        (dir, file) = self._split_loose_object(obj.id)
        try:
            self.transport.mkdir(dir)
        except FileExists:
            pass
        path = "%s/%s" % (dir, file)
        if self.transport.has(path):
            return # Already there, no need to write again
        self.transport.put_bytes(path, obj.as_legacy_object())

    def move_in_pack(self, f):
        """Move a specific file containing a pack into the pack directory.

        :note: The file should be on the same file system as the
            packs directory.

        :param path: Path to the pack file.
        """
        f.seek(0)
        p = PackData(None, f, len(f.getvalue()))
        entries = p.sorted_entries()
        basename = "pack-%s" % iter_sha1(entry[0] for entry in entries)
        f.seek(0)
        self.pack_transport.put_file(basename + ".pack", f)
        idxfile = StringIO()
        write_pack_index_v2(idxfile, entries, p.get_stored_checksum())
        idxfile.seek(0)
        self.pack_transport.put_file(basename + ".idx", idxfile)
        idxfile.seek(0)
        idx = load_pack_index_file(basename+".idx", idxfile)
        final_pack = Pack.from_objects(p, idx)
        self._add_known_pack(final_pack)
        return final_pack

    def add_pack(self):
        """Add a new pack to this object store. 

        :return: Fileobject to write to and a commit function to 
            call when the pack is finished.
        """
        from cStringIO import StringIO
        f = StringIO()
        def commit():
            if len(f.getvalue()) > 0:
                return self.move_in_pack(f)
            else:
                return None
        return f, commit

    @classmethod
    def init(cls, transport):
        transport.mkdir('info')
        transport.mkdir(PACKDIR)
        return cls(transport)
