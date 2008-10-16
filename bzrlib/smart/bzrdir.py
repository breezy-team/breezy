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
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
    )


class SmartServerRequestOpenBzrDir(SmartServerRequest):

    def do(self, path):
        from bzrlib.bzrdir import BzrDirFormat
        try:
            t = self.transport_from_client_path(path)
        except errors.PathNotChild:
            # The client is trying to ask about a path that they have no access
            # to.
            # Ideally we'd return a FailedSmartServerResponse here rather than
            # a "successful" negative, but we want to be compatibile with
            # clients that don't anticipate errors from this method.
            answer = 'no'
        else:
            default_format = BzrDirFormat.get_default_format()
            real_bzrdir = default_format.open(t, _found=True)
            try:
                real_bzrdir._format.probe_transport(t)
            except (errors.NotBranchError, errors.UnknownFormatError):
                answer = 'no'
            else:
                answer = 'yes'
        return SuccessfulSmartServerResponse((answer,))


class SmartServerRequestFindRepository(SmartServerRequest):

    def _boolean_to_yes_no(self, a_boolean):
        if a_boolean:
            return 'yes'
        else:
            return 'no'

    def _find(self, path):
        """try to find a repository from path upwards
        
        This operates precisely like 'bzrdir.find_repository'.
        
        :return: (relpath, rich_root, tree_ref, external_lookup) flags. All are
            strings, relpath is a / prefixed path, and the other three are
            either 'yes' or 'no'.
        :raises errors.NoRepositoryPresent: When there is no repository
            present.
        """
        bzrdir = BzrDir.open_from_transport(
            self.transport_from_client_path(path))
        repository = bzrdir.find_repository()
        # the relpath of the bzrdir in the found repository gives us the 
        # path segments to pop-out.
        relpath = repository.bzrdir.root_transport.relpath(
            bzrdir.root_transport.base)
        if len(relpath):
            segments = ['..'] * len(relpath.split('/'))
        else:
            segments = []
        rich_root = self._boolean_to_yes_no(repository.supports_rich_root())
        tree_ref = self._boolean_to_yes_no(
            repository._format.supports_tree_reference)
        external_lookup = self._boolean_to_yes_no(
            repository._format.supports_external_lookups)
        return '/'.join(segments), rich_root, tree_ref, external_lookup


class SmartServerRequestFindRepositoryV1(SmartServerRequestFindRepository):

    def do(self, path):
        """try to find a repository from path upwards
        
        This operates precisely like 'bzrdir.find_repository'.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.

        This is the initial version of this method introduced with the smart
        server. Modern clients will try the V2 method that adds support for the
        supports_external_lookups attribute.

        :return: norepository or ok, relpath.
        """
        try:
            path, rich_root, tree_ref, external_lookup = self._find(path)
            return SuccessfulSmartServerResponse(('ok', path, rich_root, tree_ref))
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse(('norepository', ))


class SmartServerRequestFindRepositoryV2(SmartServerRequestFindRepository):

    def do(self, path):
        """try to find a repository from path upwards
        
        This operates precisely like 'bzrdir.find_repository'.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.

        This is the second edition of this method introduced in bzr 1.3, which
        returns information about the supports_external_lookups format
        attribute too.

        :return: norepository or ok, relpath.
        """
        try:
            path, rich_root, tree_ref, external_lookup = self._find(path)
            return SuccessfulSmartServerResponse(
                ('ok', path, rich_root, tree_ref, external_lookup))
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse(('norepository', ))


class SmartServerRequestInitializeBzrDir(SmartServerRequest):

    def do(self, path):
        """Initialize a bzrdir at path.

        The default format of the server is used.
        :return: SmartServerResponse(('ok', ))
        """
        target_transport = self.transport_from_client_path(path)
        BzrDirFormat.get_default_format().initialize_on_transport(target_transport)
        return SuccessfulSmartServerResponse(('ok', ))


class SmartServerRequestOpenBranch(SmartServerRequest):

    def do(self, path):
        """try to open a branch at path and return ok/nobranch.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.
        """
        bzrdir = BzrDir.open_from_transport(
            self.transport_from_client_path(path))
        try:
            reference_url = bzrdir.get_branch_reference()
            if reference_url is None:
                return SuccessfulSmartServerResponse(('ok', ''))
            else:
                return SuccessfulSmartServerResponse(('ok', reference_url))
        except errors.NotBranchError:
            return FailedSmartServerResponse(('nobranch', ))
