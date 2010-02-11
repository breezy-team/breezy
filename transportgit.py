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
    )
from dulwich.repo import (
    BaseRepo,
    OBJECTDIR,
    REFSDIR,
    BASE_DIRECTORIES
    )

from bzrlib import (
    urlutils,
    )
from bzrlib.errors import (
    NoSuchFile,
    )


class TransportRepo(BaseRepo):

    def __init__(self, transport):
        super(TransportRepo, self).__init__()
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
        BaseRepo.__init__(self, object_store, refs)

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
        raise NotImplementedError

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

