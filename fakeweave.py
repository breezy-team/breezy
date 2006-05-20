# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.versionedfile import VersionedFile
from cStringIO import StringIO
from bzrlib.trace import mutter
from libsvn.core import SubversionException
import svn.ra

class FakeFileWeave(VersionedFile):
    def __init__(self,repository,weave_name,access_mode='w'):
        VersionedFile.__init__(self,access_mode)
        self.repository = repository
        self.file_id = weave_name
        assert self.file_id

    def get_lines(self, version_id):
        assert version_id != None

        (path,revnum) = self.repository.path_from_file_id(version_id, self.file_id)

        stream = StringIO()
        mutter('svn cat -r %r %s' % (revnum, path))
        try:
            (revnum,props) = svn.ra.get_file(self.repository.ra, path.encode('utf8'), revnum, stream)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NOT_FILE:
                return []
            raise

        stream.seek(0)

        return stream.readlines()

    def has_version(self,version_id):
        assert version_id
        (path,path_revnum) = self.repository.path_from_file_id(version_id, self.file_id)

        mutter("svn check_path -r%d %s" % (path_revnum,path))
        kind = svn.ra.check_path(self.repository.ra, path.encode('utf8'), path_revnum)

        return (kind != svn.core.svn_node_none)

    def get_parents(self,version):
        #FIXME
        mutter("GET_PARENTS: %s,%s" % (version,self.file_id))
        return []

class FakeFileStore(object):
    def __init__(self,repository):
        self.repository = repository

    def get_weave(self,file_id,transaction):
        return FakeFileWeave(self.repository,file_id)


class FakeInventoryWeave(VersionedFile):
    def __init__(self,repository,access_mode='w'):
        VersionedFile.__init__(self,access_mode)
        self.repository = repository

    def has_version(self,version):
        return self.repository.has_revision(version)

    def get_parents(self,version):
        return self.repository.revision_parents(version)

    def get_ancestry(self,version):
        return self.repository.get_ancestry(version)

    def versions(self):
        raise NotImplementedError(self.versions)

    def get_lines(self, version_id):
        if version_id is None:
            return []
        return self.repository.get_inventory_xml(version_id).splitlines()

    def get_graph(self,versions):
        if versions is None:
            return self.repository.get_revision_graph()

        ret = {}
        for vers in versions:
            ret.update(self.repository.get_revision_graph(vers))
        return ret

