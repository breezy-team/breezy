# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Authentication token retrieval."""

from bzrlib.config import AuthenticationConfig
from bzrlib.trace import mutter
from bzrlib.ui import ui_factory

from bzrlib.plugins.svn import ra

import urlparse
import urllib

AUTH_PARAM_DEFAULT_USERNAME = 'svn:auth:username'
AUTH_PARAM_DEFAULT_PASSWORD = 'svn:auth:password'

SSL_NOTYETVALID = 0x00000001
SSL_EXPIRED     = 0x00000002
SSL_CNMISMATCH  = 0x00000004
SSL_UNKNOWNCA   = 0x00000008
SSL_OTHER       = 0x40000000

class SubversionAuthenticationConfig(AuthenticationConfig):
    """Simple extended version of AuthenticationConfig that can provide 
    the information Subversion requires.
    """
    def __init__(self, scheme, host, port, path, file=None):
        super(SubversionAuthenticationConfig, self).__init__(file)
        self.scheme = scheme
        self.host = host
        self.port = port
        self.path = path
       
    def get_svn_username(self, realm, may_save):
        """Look up a Subversion user name in the Bazaar authentication cache.

        :param realm: Authentication realm (optional)
        :param may_save: Whether or not the username should be saved.
        """
        mutter("Obtaining username for SVN connection")
        username = self.get_user(self.scheme, host=self.host, path=self.path, realm=realm)
        if username is None:
            return None
        return (username, False)

    def get_svn_simple(self, realm, username, may_save):
        """Look up a Subversion user name+password combination in the Bazaar 
        authentication cache.

        :param realm: Authentication realm (optional)
        :param username: Username, if it is already known, or None.
        :param may_save: Whether or not the username should be saved.
        """
        mutter("Obtaining username and password for SVN connection")
        username = self.get_user(self.scheme, 
                host=self.host, path=self.path, realm=realm) or username
        password = self.get_password(self.scheme, host=self.host, 
            path=self.path, user=username, 
            realm=realm, prompt="%s %s password" % (realm, username))
        return (username, password, False)

    def get_svn_ssl_server_trust(self, realm, failures, cert_info, may_save):
        """Return a Subversion auth provider that verifies SSL server trust.

        :param realm: Realm name (optional)
        :param failures: Failures to check for (bit field, SVN_AUTH_SSL_*)
        :param cert_info: Certificate information
        :param may_save: Whether this information may be stored.
        """
        mutter("Verifying SSL server: %s", realm)
        credentials = self.get_credentials(self.scheme, host=self.host)
        if (credentials is not None and 
            credentials.has_key("verify_certificates") and 
            credentials["verify_certificates"] == False):
            accepted_failures = (
                    SSL_NOTYETVALID + 
                    SSL_EXPIRED +
                    SSL_CNMISMATCH +
                    SSL_UNKNOWNCA +
                    SSL_OTHER)
        else:
            accepted_failures = 0
        return (accepted_failures, False)

    def get_svn_username_prompt_provider(self, retries):
        """Return a Subversion auth provider for retrieving the username, as 
        accepted by svn_auth_open().
        
        :param retries: Number of allowed retries.
        """
        return ra.get_username_prompt_provider(self.get_svn_username, 
                                                     retries)

    def get_svn_simple_prompt_provider(self, retries):
        """Return a Subversion auth provider for retrieving a 
        username+password combination, as accepted by svn_auth_open().
        
        :param retries: Number of allowed retries.
        """
        return ra.get_simple_prompt_provider(self.get_svn_simple, retries)

    def get_svn_ssl_server_trust_prompt_provider(self):
        """Return a Subversion auth provider for checking 
        whether a SSL server is trusted."""
        return ra.get_ssl_server_trust_prompt_provider(self.get_svn_ssl_server_trust)

    def get_svn_auth_providers(self):
        """Return a list of auth providers for this authentication file.
        """
        return [self.get_svn_username_prompt_provider(1),
                self.get_svn_simple_prompt_provider(1),
                self.get_svn_ssl_server_trust_prompt_provider()]


def get_ssl_client_cert_pw(realm, may_save):
    """Simple SSL client certificate password prompter.

    :param realm: Realm, optional.
    :param may_save: Whether the password can be cached.
    """
    password = ui_factory.get_password(
            "Please enter password for client certificate[realm=%s]" % realm)
    return (password, False)


def get_ssl_client_cert_pw_provider(tries):
    return ra.get_ssl_client_cert_pw_prompt_provider(
                get_ssl_client_cert_pw, tries)


def get_stock_svn_providers():
    providers = [ra.get_simple_provider(),
            ra.get_username_provider(),
            ra.get_ssl_client_cert_file_provider(),
            ra.get_ssl_client_cert_pw_file_provider(),
            ra.get_ssl_server_trust_file_provider(),
            ]

    if getattr(ra, 'get_windows_simple_provider', None):
        providers.append(ra.get_windows_simple_provider())

    if getattr(ra, 'get_keychain_simple_provider', None):
        providers.append(ra.get_keychain_simple_provider())

    if getattr(ra, 'get_windows_ssl_server_trust_provider', None):
        providers.append(ra.get_windows_ssl_server_trust_provider())

    return providers


def create_auth_baton(url):
    """Create an authentication baton for the specified URL."""
    assert isinstance(url, str)
    (scheme, netloc, path, _, _) = urlparse.urlsplit(url)
    (creds, host) = urllib.splituser(netloc)
    (host, port) = urllib.splitport(host)

    auth_config = SubversionAuthenticationConfig(scheme, host, port, path)

    # Specify Subversion providers first, because they use file data
    # rather than prompting the user.
    providers = []
    providers += get_stock_svn_providers()
    providers += auth_config.get_svn_auth_providers()
    providers += [get_ssl_client_cert_pw_provider(1)]

    auth_baton = ra.Auth(providers)
    if creds is not None:
        (user, password) = urllib.splitpasswd(creds)
        if user is not None:
            auth_baton.set_parameter(AUTH_PARAM_DEFAULT_USERNAME, user)
        if password is not None:
            auth_baton.set_parameter(AUTH_PARAM_DEFAULT_PASSWORD, password)
    return auth_baton
