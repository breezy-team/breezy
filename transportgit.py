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
    DictRefsContainer,
    OBJECTDIR,
    BASE_DIRECTORIES,
    read_info_refs,
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
        if self.transport.has(".git/info/refs"):
            self.bare = False
            self._controltransport = self.transport.clone('.git')
        elif self.transport.has("info/refs"):
            self.bare = True
            self._controltransport = self.transport
        else:
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
        return []
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
