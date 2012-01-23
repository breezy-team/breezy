# Copyright (C) 2006-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from __future__ import absolute_import


import os
import socket
from urlparse import urlsplit, urlunsplit
import urllib
import xmlrpclib

from bzrlib import (
    config,
    errors,
    urlutils,
    __version__ as _bzrlib_version,
    )
from bzrlib.transport.http import _urllib2_wrappers


# for testing, do
'''
export BZR_LP_XMLRPC_URL=http://xmlrpc.staging.launchpad.net/bazaar/
'''

class InvalidLaunchpadInstance(errors.BzrError):

    _fmt = "%(lp_instance)s is not a valid Launchpad instance."

    def __init__(self, lp_instance):
        errors.BzrError.__init__(self, lp_instance=lp_instance)


class NotLaunchpadBranch(errors.BzrError):

    _fmt = "%(url)s is not registered on Launchpad."

    def __init__(self, url):
        errors.BzrError.__init__(self, url=url)


class XMLRPCTransport(xmlrpclib.Transport):

    def __init__(self, scheme):
        xmlrpclib.Transport.__init__(self)
        self._scheme = scheme
        self._opener = _urllib2_wrappers.Opener()
        self.verbose = 0

    def request(self, host, handler, request_body, verbose=0):
        self.verbose = verbose
        url = self._scheme + "://" + host + handler
        request = _urllib2_wrappers.Request("POST", url, request_body)
        # FIXME: _urllib2_wrappers will override user-agent with its own
        # request.add_header("User-Agent", self.user_agent)
        request.add_header("Content-Type", "text/xml")

        response = self._opener.open(request)
        if response.code != 200:
            raise xmlrpclib.ProtocolError(host + handler, response.code,
                                          response.msg, response.info())
        return self.parse_response(response)


class LaunchpadService(object):
    """A service to talk to Launchpad via XMLRPC.

    See http://wiki.bazaar.canonical.com/Specs/LaunchpadRpc for the methods we can call.
    """

    LAUNCHPAD_DOMAINS = {
        'production': 'launchpad.net',
        'staging': 'staging.launchpad.net',
        'qastaging': 'qastaging.launchpad.net',
        'demo': 'demo.launchpad.net',
        'dev': 'launchpad.dev',
        }

    # NB: these should always end in a slash to avoid xmlrpclib appending
    # '/RPC2'
    LAUNCHPAD_INSTANCE = {}
    for instance, domain in LAUNCHPAD_DOMAINS.iteritems():
        LAUNCHPAD_INSTANCE[instance] = 'https://xmlrpc.%s/bazaar/' % domain

    # We use production as the default because edge has been deprecated circa
    # 2010-11 (see bug https://bugs.launchpad.net/bzr/+bug/583667)
    DEFAULT_INSTANCE = 'production'
    DEFAULT_SERVICE_URL = LAUNCHPAD_INSTANCE[DEFAULT_INSTANCE]

    transport = None
    registrant_email = None
    registrant_password = None


    def __init__(self, transport=None, lp_instance=None):
        """Construct a new service talking to the launchpad rpc server"""
        self._lp_instance = lp_instance
        if transport is None:
            uri_type = urllib.splittype(self.service_url)[0]
            transport = XMLRPCTransport(uri_type)
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

    @classmethod
    def for_url(cls, url, **kwargs):
        """Return the Launchpad service corresponding to the given URL."""
        result = urlsplit(url)
        lp_instance = result[1]
        if lp_instance == '':
            lp_instance = None
        elif lp_instance not in cls.LAUNCHPAD_INSTANCE:
            raise errors.InvalidURL(path=url)
        return cls(lp_instance=lp_instance, **kwargs)

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
            hostinfo = '%s:%s@%s' % (urlutils.quote(self.registrant_email),
                                     urlutils.quote(self.registrant_password),
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
        except socket.gaierror, e:
            raise errors.ConnectionError(
                "Could not resolve '%s'" % self.domain,
                orig_error=e)
        return result

    @property
    def domain(self):
        if self._lp_instance is None:
            instance = self.DEFAULT_INSTANCE
        else:
            instance = self._lp_instance
        return self.LAUNCHPAD_DOMAINS[instance]

    def _guess_branch_path(self, branch_url, _request_factory=None):
        scheme, hostinfo, path = urlsplit(branch_url)[:3]
        if _request_factory is None:
            _request_factory = ResolveLaunchpadPathRequest
        if scheme == 'lp':
            resolve = _request_factory(path)
            try:
                result = resolve.submit(self)
            except xmlrpclib.Fault, fault:
                raise errors.InvalidURL(branch_url, str(fault))
            branch_url = result['urls'][0]
            path = urlsplit(branch_url)[2]
        else:
            domains = (
                'bazaar.%s' % domain
                for domain in self.LAUNCHPAD_DOMAINS.itervalues())
            if hostinfo not in domains:
                raise NotLaunchpadBranch(branch_url)
        return path.lstrip('/')

    def get_web_url_from_branch_url(self, branch_url, _request_factory=None):
        """Get the Launchpad web URL for the given branch URL.

        :raise errors.InvalidURL: if 'branch_url' cannot be identified as a
            Launchpad branch URL.
        :return: The URL of the branch on Launchpad.
        """
        path = self._guess_branch_path(branch_url, _request_factory)
        return urlutils.join('https://code.%s' % self.domain, path)


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
                                    extra="You must specify a project.")
        self.path = path

    def _request_params(self):
        """Return xmlrpc request parameters"""
        return (self.path,)
