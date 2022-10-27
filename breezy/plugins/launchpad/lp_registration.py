# Copyright (C) 2006-2017 Canonical Ltd
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

from io import BytesIO
import os
import socket
from urllib.parse import urlsplit, urlunsplit
import urllib
from xmlrpc.client import (
    __version__ as xmlrpc_version,
    Fault,
    ProtocolError,
    ServerProxy,
    Transport,
    )

from ... import (
    errors,
    urlutils,
    __version__ as _breezy_version,
    )
from ...transport import http, get_transport

from .uris import (
    DEFAULT_INSTANCE,
    LAUNCHPAD_DOMAINS,
    LAUNCHPAD_BAZAAR_DOMAINS,
    )


# for testing, do
'''
export BRZ_LP_XMLRPC_URL=http://xmlrpc.staging.launchpad.net/bazaar/
'''


class InvalidURL(errors.PathError):

    _fmt = 'Invalid url supplied to transport: "%(path)s"%(extra)s'


class InvalidLaunchpadInstance(errors.BzrError):

    _fmt = "%(lp_instance)s is not a valid Launchpad instance."

    def __init__(self, lp_instance):
        errors.BzrError.__init__(self, lp_instance=lp_instance)


class NotLaunchpadBranch(errors.BzrError):

    _fmt = "%(url)s is not registered on Launchpad."

    def __init__(self, url):
        errors.BzrError.__init__(self, url=url)


class XMLRPCTransport(Transport):

    def __init__(self, scheme):
        Transport.__init__(self)
        self._scheme = scheme
        self.verbose = 0
        self._possible_bzr_transports = []

    def request(self, host, handler, request_body, verbose=0):
        self.verbose = verbose
        url = self._scheme + "://" + host + handler
        transport = get_transport(
            url, possible_transports=self._possible_bzr_transports)
        response = transport.request("POST", url, body=request_body, headers={
            "Content-Type": "text/xml"})

        if response.status != 200:
            raise ProtocolError(url, response.status,
                                response.text, response.headers)
        return self.parse_response(BytesIO(response.data))


class LaunchpadService(object):
    """A service to talk to Launchpad via XMLRPC.

    See http://wiki.bazaar.canonical.com/Specs/LaunchpadRpc for the methods we
    can call.
    """

    # NB: these should always end in a slash to avoid xmlrpclib appending
    # '/RPC2'
    LAUNCHPAD_INSTANCE = {}
    for instance, domain in LAUNCHPAD_DOMAINS.items():
        LAUNCHPAD_INSTANCE[instance] = 'https://xmlrpc.%s/bazaar/' % domain

    DEFAULT_SERVICE_URL = LAUNCHPAD_INSTANCE[DEFAULT_INSTANCE]

    transport = None
    registrant_email = None
    registrant_password = None

    def __init__(self, transport=None, lp_instance=None):
        """Construct a new service talking to the launchpad rpc server"""
        self._lp_instance = lp_instance
        if transport is None:
            uri_type = urlutils.parse_url(self.service_url)[0]
            transport = XMLRPCTransport(uri_type)
        self.transport = transport

    @property
    def service_url(self):
        """Return the http or https url for the xmlrpc server.

        This does not include the username/password credentials.
        """
        key = 'BRZ_LP_XMLRPC_URL'
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
            raise InvalidURL(url)
        return cls(lp_instance=lp_instance, **kwargs)

    def get_proxy(self):
        """Return the proxy for XMLRPC requests."""
        url = self.service_url
        return ServerProxy(url, transport=self.transport)

    def send_request(self, method_name, method_params):
        proxy = self.get_proxy()
        method = getattr(proxy, method_name)
        try:
            result = method(*method_params)
        except ProtocolError as e:
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
        except socket.gaierror as e:
            raise errors.ConnectionError(
                "Could not resolve '%s'" % self.domain,
                orig_error=e)
        return result

    @property
    def domain(self):
        if self._lp_instance is None:
            instance = DEFAULT_INSTANCE
        else:
            instance = self._lp_instance
        return LAUNCHPAD_DOMAINS[instance]

    def _guess_branch_path(self, branch_url, _request_factory=None):
        scheme, hostinfo, path = urlsplit(branch_url)[:3]
        if _request_factory is None:
            _request_factory = ResolveLaunchpadPathRequest
        if scheme == 'lp':
            resolve = _request_factory(path)
            try:
                result = resolve.submit(self)
            except Fault as fault:
                raise InvalidURL(branch_url, str(fault))
            branch_url = result['urls'][0]
            path = urlsplit(branch_url)[2]
        else:
            if hostinfo not in LAUNCHPAD_BAZAAR_DOMAINS:
                raise NotLaunchpadBranch(branch_url)
        return path.lstrip('/')

    def get_web_url_from_branch_url(self, branch_url, _request_factory=None):
        """Get the Launchpad web URL for the given branch URL.

        :raise InvalidURL: if 'branch_url' cannot be identified as a
            Launchpad branch URL.
        :return: The URL of the branch on Launchpad.
        """
        path = self._guess_branch_path(branch_url, _request_factory)
        return urlutils.join('https://code.%s' % self.domain, path)


class BaseRequest(object):
    """Base request for talking to a XMLRPC server."""

    # Set this to the XMLRPC method name.
    _methodname = None

    def _request_params(self):
        """Return the arguments to pass to the method"""
        raise NotImplementedError(self._request_params)

    def submit(self, service):
        """Submit request to Launchpad XMLRPC server.

        :param service: LaunchpadService indicating where to send the request.
        """
        return service.send_request(self._methodname, self._request_params())


class DryRunLaunchpadService(LaunchpadService):
    """Service that just absorbs requests without sending to server."""

    def send_request(self, method_name, method_params):
        pass


class ResolveLaunchpadPathRequest(BaseRequest):
    """Request to resolve the path component of an lp: URL."""

    _methodname = 'resolve_lp_path'

    def __init__(self, path):
        if not path:
            raise InvalidURL(url=path, extra="You must specify a project.")
        self.path = path

    def _request_params(self):
        """Return xmlrpc request parameters"""
        return (self.path,)
