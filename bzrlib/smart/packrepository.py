# Copyright (C) 2008 Canonical Ltd
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

"""Server-side pack repository related request implmentations."""

from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SuccessfulSmartServerResponse,
    )


from bzrlib.smart.repository import (
    SmartServerRepositoryRequest,
    )


class SmartServerPackRepoRequest(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, *args):
        pack_collection = getattr(repository, '_pack_collection', None)
        if pack_collection is None:
            return FailedSmartServerResponse(('NotPackRepository',))
        return self.do_pack_repo_request(repository, *args)


class SmartServerPackRepositoryAutopack(SmartServerPackRepoRequest):

    def do_pack_repo_request(self, repository):
        repository.lock_write()
        try:
            repository._pack_collection.autopack()
        finally:
            repository.unlock()
        pack_names_index = repository._pack_collection._iter_disk_pack_index()
        pack_names_index = tuple((k, v) for (idx, k, v) in pack_names_index)
        return SuccessfulSmartServerResponse(tuple(pack_names_index))


