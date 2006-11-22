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
from bzrlib.bzrdir import BzrDir
from bzrlib.smart.request import SmartServerRequest, SmartServerResponse


class SmartServerRequestOpenBranch(SmartServerRequest):

    def do(self, path):
        """try to open a branch at path and return ok/nobranch.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.
        """
        bzrdir = BzrDir.open(path)
        try:
            reference_url = bzrdir.get_branch_reference()
            if reference_url is None:
                return SmartServerResponse(('ok', ''))
            else:
                return SmartServerResponse(('ok', reference_url))
        except errors.NotBranchError:
            return SmartServerResponse(('nobranch', ))
