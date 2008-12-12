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

"""Server-side versioned files related request implmentations."""

from bzrlib import (
    trace,
    versionedfile,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SuccessfulSmartServerResponse,
    )
from bzrlib.smart.repository import SmartServerRepositoryRequest
from bzrlib.util import bencode


class SmartServerVersionedFilesRequest(SmartServerRepositoryRequest):
    """Common base class for Repository requests."""

    def do(self, path, *args):
        """Execute a repository request.
        
        All Repository requests take a path to the repository as their first
        argument.  The repository must be at the exact path given by the
        client - no searching is done.

        The actual logic is delegated to self.do_repository_request.

        :param client_path: The path for the repository as received from the
            client.
        :return: A SmartServerResponse from self.do_repository_request().
        """
        transport = self.transport_from_client_path(path)
        bzrdir = BzrDir.open_from_transport(transport)
        # Save the repository for use with do_body.
        self._repository = bzrdir.open_repository()
        return self.do_repository_request(self._repository, *args)

    def do_repository_request(self, repository, vf_name, *args):
        if vf_name not in ['texts', 'inventories', 'signatures', 'revisions']:
            return FailedSmartServerResponse(('NoSuchVersionedFile', vf_name))
        versioned_files = getattr(repository, vf_name)
        return self.do_versioned_files_request(versioned_files, *args)

    def do_versioned_files_request(self, versioned_files, *args):
        """Override to provide an implementation for a verb."""


class SmartServerVersionedFilesInsertRecordStream(SmartServerVersionedFilesRequest):

    def do_versioned_files_request(self, versioned_files, lock_token):
        self._repository.lock_write(token=lock_token)
        self._repository.start_write_group()
        self.versioned_files = versioned_files

    def do_chunk(self, stream_chunk):
        record = deserialise_record(stream_chunk)
#        trace.mutter('inserting record %s (kind: %s, parents: %r)',
#            record.key, record.storage_kind, record.parents)
        self.versioned_files.insert_record_stream([record])
    
    def do_end(self):
        self._repository.commit_write_group()
        self._repository.unlock()
        self._repository = self.versioned_files = None
        return SuccessfulSmartServerResponse(('ok',))


from bzrlib.knit import KnitContentFactory

def deserialise_record(stream_chunk):
    struct = bencode.bdecode(stream_chunk)

    (sha1, storage_kind, key, parents, build_details, bytes) = struct
    if parents == 'nil':
        parents = None
    if sha1 == '':
        sha1 = None
    if storage_kind.startswith('knit-'):
        annotated = bool(storage_kind.startswith('knit-annotated-'))
        record = KnitContentFactory(key, parents, build_details, sha1, bytes,
            annotated)
        if record.storage_kind != storage_kind:
            raise AssertionError(
                'Reconstructed record kind %r does not match expected kind %r'
                % (record.storage_kind, storage_kind))
    elif storage_kind == 'fulltext':
        record = versionedfile.FulltextContentFactory(
            key, parents, sha1, bytes)
    return record

