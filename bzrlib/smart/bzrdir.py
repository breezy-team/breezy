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

"""Server-side bzrdir related request implmentations."""


from bzrlib import errors
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.smart.request import SmartServerRequest, SmartServerResponse


class SmartServerRequestFindRepository(SmartServerRequest):

    def do(self, path):
        """try to find a repository from path upwards
        
        This operates precisely like 'bzrdir.find_repository'.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.

        :return: norepository or ok, relpath.
        """
        bzrdir = BzrDir.open_from_transport(self._backing_transport.clone(path))
        try:
            repository = bzrdir.find_repository()
            # the relpath of the bzrdir in the found repository gives us the 
            # path segments to pop-out.
            relpath = repository.bzrdir.root_transport.relpath(bzrdir.root_transport.base)
            if len(relpath):
                segments = ['..'] * len(relpath.split('/'))
            else:
                segments = []
            return SmartServerResponse(('ok', '/'.join(segments)))
        except errors.NoRepositoryPresent:
            return SmartServerResponse(('norepository', ))


class SmartServerRequestInitializeBzrDir(SmartServerRequest):

    def do(self, path):
        """Initialize a bzrdir at path.

        The default format of the server is used.
        :return: SmartServerResponse(('ok', ))
        """
        target_transport = self._backing_transport.clone(path)
        BzrDirFormat.get_default_format().initialize_on_transport(target_transport)
        return SmartServerResponse(('ok', ))


class SmartServerRequestOpenBranch(SmartServerRequest):

    def do(self, path):
        """try to open a branch at path and return ok/nobranch.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.
        """
        bzrdir = BzrDir.open_from_transport(self._backing_transport.clone(path))
        try:
            reference_url = bzrdir.get_branch_reference()
            if reference_url is None:
                return SmartServerResponse(('ok', ''))
            else:
                return SmartServerResponse(('ok', reference_url))
        except errors.NotBranchError:
            return SmartServerResponse(('nobranch', ))
