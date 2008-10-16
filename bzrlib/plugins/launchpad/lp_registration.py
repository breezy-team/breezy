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


from getpass import getpass
import os
from urlparse import urlsplit, urlunsplit
import urllib
import xmlrpclib

from bzrlib import (
    config,
    errors,
    __version__ as _bzrlib_version,
    )

# for testing, do
'''
export BZR_LP_XMLRPC_URL=http://xmlrpc.staging.launchpad.net/bazaar/
'''

class InvalidLaunchpadInstance(errors.BzrError):

    _fmt = "%(lp_instance)s is not a valid Launchpad instance."

    def __init__(self, lp_instance):
        errors.BzrError.__init__(self, lp_instance=lp_instance)


class LaunchpadService(object):
    """A service to talk to Launchpad via XMLRPC.

    See http://bazaar-vcs.org/Specs/LaunchpadRpc for the methods we can call.
    """

    # NB: these should always end in a slash to avoid xmlrpclib appending
    # '/RPC2'
    # We use edge as the default because:
    # Beta users get redirected to it
    # All users can use it
    # There is a bug in the launchpad side where redirection causes an OOPS.
    LAUNCHPAD_INSTANCE = {
        'production': 'https://xmlrpc.launchpad.net/bazaar/',
        'edge': 'https://xmlrpc.edge.launchpad.net/bazaar/',
        'staging': 'https://xmlrpc.staging.launchpad.net/bazaar/',
        'demo': 'https://xmlrpc.demo.launchpad.net/bazaar/',
        'dev': 'http://xmlrpc.launchpad.dev/bazaar/',
        }
    DEFAULT_SERVICE_URL = LAUNCHPAD_INSTANCE['edge']

    transport = None
    registrant_email = None
    registrant_password = None


    def __init__(self, transport=None, lp_instance=None):
        """Construct a new service talking to the launchpad rpc server"""
        self._lp_instance = lp_instance
        if transport is None:
            uri_type = urllib.splittype(self.service_url)[0]
            if uri_type == 'https':
                transport = xmlrpclib.SafeTransport()
            else:
                transport = xmlrpclib.Transport()
            transport.user_agent = 'bzr/%s (xmlrpclib/%s)' \
                    % (_bzrlib_version, xmlrpclib.__version__)
        self.transport = transport


    @property
    def service_url(self):
        """Return the http or https url for the xmlrpc server.

        This does not include the username/password credentials.
        """
        key = 'BZR_LP_XMLRPC_URL'
        if key in os.environ:
            return os.environ[key]
        elif self._lp_instance is not None:
            try:
                return self.LAUNCHPAD_INSTANCE[self._lp_instance]
            except KeyError:
                raise InvalidLaunchpadInstance(self._lp_instance)
        else:
            return self.DEFAULT_SERVICE_URL

    def get_proxy(self, authenticated):
        """Return the proxy for XMLRPC requests."""
        if authenticated:
            # auth info must be in url
            # TODO: if there's no registrant email perhaps we should
            # just connect anonymously?
            scheme, hostinfo, path = urlsplit(self.service_url)[:3]
            if '@' in hostinfo:
                raise AssertionError(hostinfo)
            if self.registrant_email is None:
                raise AssertionError()
            if self.registrant_password is None:
                raise AssertionError()
            # TODO: perhaps fully quote the password to make it very slightly
            # obscured
            # TODO: can we perhaps add extra Authorization headers
            # directly to the request, rather than putting this into
            # the url?  perhaps a bit more secure against accidentally
            # revealing it.  std66 s3.2.1 discourages putting the
            # password in the url.
            hostinfo = '%s:%s@%s' % (urllib.quote(self.registrant_email),
                                     urllib.quote(self.registrant_password),
                                     hostinfo)
            url = urlunsplit((scheme, hostinfo, path, '', ''))
        else:
            url = self.service_url
        return xmlrpclib.ServerProxy(url, transport=self.transport)

    def gather_user_credentials(self):
        """Get the password from the user."""
        the_config = config.GlobalConfig()
        self.registrant_email = the_config.user_email()
        if self.registrant_password is None:
            auth = config.AuthenticationConfig()
            scheme, hostinfo = urlsplit(self.service_url)[:2]
            prompt = 'launchpad.net password for %s: ' % \
                    self.registrant_email
            # We will reuse http[s] credentials if we can, prompt user
            # otherwise
            self.registrant_password = auth.get_password(scheme, hostinfo,
                                                         self.registrant_email,
                                                         prompt=prompt)

    def send_request(self, method_name, method_params, authenticated):
        proxy = self.get_proxy(authenticated)
        method = getattr(proxy, method_name)
        try:
            result = method(*method_params)
        except xmlrpclib.ProtocolError, e:
            if e.errcode == 301:
                # TODO: This can give a ProtocolError representing a 301 error, whose
                # e.headers['location'] tells where to go and e.errcode==301; should
                # probably log something and retry on the new url.
                raise NotImplementedError("should resend request to %s, but this isn't implemented"
                        % e.headers.get('Location', 'NO-LOCATION-PRESENT'))
            else:
                # we don't want to print the original message because its
                # str representation includes the plaintext password.
                # TODO: print more headers to help in tracking down failures
                raise errors.BzrError("xmlrpc protocol error connecting to %s: %s %s"
                        % (self.service_url, e.errcode, e.errmsg))
        return result


class BaseRequest(object):
    """Base request for talking to a XMLRPC server."""

    # Set this to the XMLRPC method name.
    _methodname = None
    _authenticated = True

    def _request_params(self):
        """Return the arguments to pass to the method"""
        raise NotImplementedError(self._request_params)

    def submit(self, service):
        """Submit request to Launchpad XMLRPC server.

        :param service: LaunchpadService indicating where to send
            the request and the authentication credentials.
        """
        return service.send_request(self._methodname, self._request_params(),
                                    self._authenticated)


class DryRunLaunchpadService(LaunchpadService):
    """Service that just absorbs requests without sending to server.
    
    The dummy service does not need authentication.
    """

    def send_request(self, method_name, method_params, authenticated):
        pass

    def gather_user_credentials(self):
        pass


class BranchRegistrationRequest(BaseRequest):
    """Request to tell Launchpad about a bzr branch."""

    _methodname = 'register_branch'

    def __init__(self, branch_url,
                 branch_name='',
                 branch_title='',
                 branch_description='',
                 author_email='',
                 product_name='',
                 ):
        if not branch_url:
            raise errors.InvalidURL(branch_url, "You need to specify a non-empty branch URL.")
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
        self.bug_id = bug_id
        self.branch_url = branch_url

    def _request_params(self):
        """Return xmlrpc request parameters"""
        # This must match the parameter tuple expected by Launchpad for this
        # method
        return (self.branch_url, self.bug_id, '')


class ResolveLaunchpadPathRequest(BaseRequest):
    """Request to resolve the path component of an lp: URL."""

    _methodname = 'resolve_lp_path'
    _authenticated = False

    def __init__(self, path):
        if not path:
            raise errors.InvalidURL(path=path,
                                    extra="You must specify a product.")
        self.path = path

    def _request_params(self):
        """Return xmlrpc request parameters"""
        return (self.path,)
