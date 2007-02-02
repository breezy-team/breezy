# Copyright (C) 2006 Canonical Ltd
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

"""Server-side repository related request implmentations."""


from bzrlib import errors
from bzrlib.bzrdir import BzrDir
from bzrlib.smart.request import SmartServerRequest, SmartServerResponse


class SmartServerRepositoryRequest(SmartServerRequest):
    """Common base class for Repository requests."""

    def do(self, path, *args):
        """Execute a repository request.
        
        The repository must be at the exact path - no searching is done.

        The actual logic is delegated to self.do_repository_request.

        :param path: The path for the repository.
        :return: A smart server from self.do_repository_request().
        """
        transport = self._backing_transport.clone(path)
        bzrdir = BzrDir.open_from_transport(transport)
        repository = bzrdir.open_repository()
        return self.do_repository_request(repository, *args)


class SmartServerRequestHasRevision(SmartServerRepositoryRequest):

    def do_repository_request(self, repository, revision_id):
        """Return ok if a specific revision is in the repository at path.

        :param repository: The repository to query in.
        :param revision_id: The utf8 encoded revision_id to lookup.
        :return: A smart server response of ('ok', ) if the revision is
            present.
        """
        decoded_revision_id = revision_id.decode('utf8')
        if repository.has_revision(decoded_revision_id):
            return SmartServerResponse(('ok', ))
        else:
            return SmartServerResponse(('no', ))
