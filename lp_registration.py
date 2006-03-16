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


from urlparse import urlsplit, urlunsplit
from urllib import unquote, quote
import xmlrpclib
## from twisted.web import xmlrpc


# TODO: use last component of path as default id?

class BranchRegistrationRequest(object):
    """Request to tell Launchpad about a bzr branch."""

    _methodname = 'register_branch'

    # NB this should always end in a slash to avoid xmlrpclib appending
    # '/RPC2'
    DEFAULT_SERVICE_URL = 'http://xmlrpc.launchpad.net/branch/'

    def __init__(self, branch_url, branch_id):
        self.branch_url = branch_url
        self.branch_id = branch_id
        self.branch_description = ''
        self.owner_email = ''
        self.service_url = self.DEFAULT_SERVICE_URL
        self.registrant = 'testuser@launchpad.net'
        self.password = 'testpassword'

    def _request_params(self):
        """Return xmlrpc request parameters"""
        # This must match the parameter tuple expected by Launchpad for this
        # method
        return (self.branch_url,
                self.branch_id,
                self.branch_description,
                self.owner_email,
               )

    def submit(self, transport=None):
        """Submit registration request to the server.
        
        The particular server to use is set in self.service_url; this 
        should only need to be changed for testing.

        :param transport: If non-null, use a special xmlrpclib.Transport
            to send the request.  This has no connection to bzrlib
            Transports.
        """
        # auth info must be in url
        scheme, hostinfo, path = urlsplit(self.service_url)[:3]
        assert '@' not in hostinfo
        hostinfo = '%s:%s@%s' % (quote(self.registrant),
                                 quote(self.password),
                                 hostinfo)
        url = urlunsplit((scheme, hostinfo, path, '', ''))
        proxy = xmlrpclib.ServerProxy(url, transport=transport)
        proxy.register_branch(*self._request_params())

