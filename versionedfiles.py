# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.revision import (
    NULL_REVISION,
    )
from bzrlib.versionedfile import (
    AbsentContentFactory,
    FulltextContentFactory,
    VersionedFiles,
    )

from bzrlib.plugins.git.converter import (
    GitObjectConverter,
    )

class GitTexts(VersionedFiles):

    def __init__(self, repository):
        self.repository = repository
        

    def check(self, progressbar=None):
        return True

    def add_mpdiffs(self, records):
        raise NotImplementedError(self.add_mpdiffs)

    def get_record_stream(self, keys, ordering, include_delta_closure):
        for key in keys:
            (fileid, revid) = key
            (foreign_revid, mapping) = self.repository.revision_id_bzr_to_foreign(revid)
            idmap = GitObjectConverter(self.repository, mapping)._idmap
            path = mapping.parse_file_id(fileid)
            try:
                sha = idmap.lookup_tree(path, revid)
            except KeyError:
                try:
                    sha = idmap.lookup_blob(fileid, revid)
                except KeyError:
                    yield AbsentContentFactory(key)
                else:
                    blob = self.repository.object_store[sha]
                    yield FulltextContentFactory(key, None, None, "")
            else:
                yield FulltextContentFactory(key, None, None, blob)

    def get_parent_map(self, keys):
        raise NotImplementedError(self.get_parent_map)

