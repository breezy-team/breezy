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


class SmartServerRequestHasRevision(SmartServerRequest):

    def do(self, path, revision_id):
        """Return ok if a specific revision is in the repository at path.

        The repository must be at the exact path - no searching is done.

        :param path: The path for the repository.
        :param revision_id: The utf8 encoded revision_id to lookup.
        :return: A smart server response of ('ok', ) if the revision is
            present.
        """
        transport = self._backing_transport.clone(path)
        bzrdir = BzrDir.open_from_transport(transport)
        repository = bzrdir.open_repository()
        decoded_revision_id = revision_id.decode('utf8')
        if repository.has_revision(decoded_revision_id):
            return SmartServerResponse(('ok', ))
        else:
            return SmartServerResponse(('no', ))
