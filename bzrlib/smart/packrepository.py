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

from bzrlib import errors
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SuccessfulSmartServerResponse,
    )


from bzrlib.smart.repository import (
    SmartServerRepositoryRequest,
    )


# XXX: define a base class that checks that 'repository' is a pack repo.

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
        return SuccessfulSmartServerResponse(('ok',))


class SmartServerPackRepositoryCheckReferences(SmartServerPackRepoRequest):

    def do_pack_repo_request(self, repository, *external_refs):
        repository.lock_read()
        try:
            external_refs = set(
                tuple(external_ref) for external_ref in external_refs)
            try:
                repository._pack_collection._check_references_present(
                    external_refs)
            except errors.RevisionNotPresent, e:
                return FailedSmartServerResponse(
                    ('RevisionNotPresent', e.revision_id, e.file_id))
        finally:
            repository.unlock()
        return SuccessfulSmartServerResponse(('ok',))

