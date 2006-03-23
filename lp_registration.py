# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the # GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from getpass import getpass
import os
from urlparse import urlsplit, urlunsplit
from urllib import unquote, quote
import xmlrpclib

import bzrlib.config

class LaunchpadService(object):
    """A service to talk to Launchpad via XMLRPC."""

    # NB: this should always end in a slash to avoid xmlrpclib appending
    # '/RPC2'
    DEFAULT_SERVICE_URL = 'http://xmlrpc.launchpad.net/bazaar/'

    transport = None
    registrant_email = None
    registrant_password = None

    @property
    def service_url(self):
        """Return the http or https url for the xmlrpc server.

        This does not include the username/password credentials.
        """
        key = 'BZR_LP_XMLRPC_URL'
        if key in os.environ:
            return os.environ[key]
        else:
            return self.DEFAULT_SERVICE_URL


    def get_proxy(self):
        """Return the proxy for XMLRPC requests."""
        # auth info must be in url
        scheme, hostinfo, path = urlsplit(self.service_url)[:3]
        assert '@' not in hostinfo
        assert self.registrant_email is not None
        assert self.registrant_password is not None
        hostinfo = '%s:%s@%s' % (quote(self.registrant_email),
                                 quote(self.registrant_password),
                                 hostinfo)
        url = urlunsplit((scheme, hostinfo, path, '', ''))
        return xmlrpclib.ServerProxy(url, transport=self.transport)

    def gather_user_credentials(self):
        """Get the password from the user."""
        config = bzrlib.config.GlobalConfig()
        self.registrant_email = config.user_email()
        if self.registrant_password is None:
            prompt = 'launchpad.net password for %s: ' % \
                    self.registrant_email
            self.registrant_password = getpass(prompt)

    def send_request(self, method_name, method_params):
        proxy = self.get_proxy()
        assert method_name
        method = getattr(proxy, method_name)
        result = method(*method_params)
        return result


class BaseRequest(object):
    """Base request for talking to a XMLRPC server."""

    # Set this to the XMLRPC method name.
    _methodname = None

    def _request_params(self):
        """Return the arguments to pass to the method"""
        raise NotImplementedError(self._request_params)

    def submit(self, service):
        """Submit request to Launchpad XMLRPC server.

        :param service: LaunchpadService indicating where to send
            the request and the authentication credentials.
        """
        return service.send_request(self._methodname, self._request_params())


class BranchRegistrationRequest(BaseRequest):
    """Request to tell Launchpad about a bzr branch."""

    _methodname = 'register_branch'

    def __init__(self, branch_url, 
                 branch_name='',
                 branch_title='',
                 branch_description='',
                 product_name='',
                 author_email='',
                 ):
        assert branch_url
        self.branch_url = branch_url
        if branch_name:
            self.branch_name = branch_name
        else:
            self.branch_name = self._find_default_branch_name(self.branch_url)
        self.branch_title = branch_title
        self.branch_description = branch_description
        self.author_email = author_email
        self.product_name = product_name

    def _request_params(self):
        """Return xmlrpc request parameters"""
        # This must match the parameter tuple expected by Launchpad for this
        # method
        return (self.branch_url,
                self.branch_name,
                self.branch_title,
                self.branch_description,
                self.author_email,
                self.product_name,
               )

    def _find_default_branch_name(self, branch_url):
        i = branch_url.rfind('/')
        return branch_url[i+1:]


class BranchBugLinkRequest(BaseRequest):
    """Request to link a bzr branch in Launchpad to a bug."""

    _methodname = 'link_branch_to_bug'

    def __init__(self, branch_url, bug_id):
        assert branch_url
        self.bug_id = str(bug_id)
        self.branch_url = branch_url

    def _request_params(self):
        """Return xmlrpc request parameters"""
        # This must match the parameter tuple expected by Launchpad for this
        # method
        return (self.branch_url, self.bug_id, '')
