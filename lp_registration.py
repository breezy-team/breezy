# Copyright (C) 2006 by Canonical Ltd
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


import xmlrpclib
## from twisted.web import xmlrpc

class BranchRegistrationRequest(object):
    """Request to tell Launchpad about a bzr branch."""

    def __init__(self, branch_url):
        self.branch_url = branch_url

    def _request_xml(self):
        """Return the string form of the xmlrpc request."""
        return xmlrpclib.dumps(self._request_params(),
                               methodname='register_branch',
                               allow_none=True)

    def _request_params(self):
        """Return xmlrpc request parameters"""
        return (self.branch_url,
               )



