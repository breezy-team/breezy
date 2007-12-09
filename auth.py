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

from bzrlib.config import AuthenticationConfig
from svn.core import (svn_auth_cred_username_t, 
                      svn_auth_cred_simple_t,
                      svn_auth_cred_ssl_client_cert_t,
                      svn_auth_cred_ssl_client_cert_pw_t,
                      svn_auth_cred_ssl_server_trust_t,
                      svn_auth_get_username_prompt_provider,
                      svn_auth_get_simple_prompt_provider)


class SubversionAuthenticationConfig(AuthenticationConfig):
    """Simple extended version of AuthenticationConfig that can provide 
    the information Subversion requires.
    """
    def __init__(self, file=None, scheme="svn"):
        super(SubversionAuthenticationConfig, self).__init__(file)
        self.scheme = scheme

    def get_svn_username(realm, may_save, pool=None):
        """Look up a Subversion user name in the Bazaar authentication cache.

        :param realm: Authentication realm (optional)
        :param may_save: Whether or not the username should be saved.
        :param pool: Allocation pool, is ignored.
        """
        username_cred = svn_auth_cred_username_t()
        username_cred.username = self.auth_config.get_user(self.scheme, host=None, realm=realm)
        username_cred.may_save = False
        return username_cred

    def get_svn_simple(realm, username, may_save, pool):
        """Look up a Subversion user name+password combination in the Bazaar authentication cache.

        :param realm: Authentication realm (optional)
        :param username: Username, if it is already known, or None.
        :param may_save: Whether or not the username should be saved.
        :param pool: Allocation pool, is ignored.
        """
        simple_cred = svn_auth_cred_simple_t()
        simple_cred.username = username or self.get_username(realm, may_save, pool)
        simple_cred.password = self.auth_config.get_password(self.scheme, host=None, 
                                    user=simple_cred.username, realm=realm)
        simple_cred.may_save = False
        return simple_cred

    def get_svn_username_prompt_provider(self, retries):
        """Return a Subversion auth provider for retrieving the username, as 
        accepted by svn_auth_open().
        
        :param retries: Number of allowed retries.
        """
        return svn_auth_get_username_prompt_provider(self.get_svn_username, retries)

    def get_svn_simple_prompt_provider(self, retries):
        """Return a Subversion auth provider for retrieving a 
        username+password combination, as accepted by svn_auth_open().
        
        :param retries: Number of allowed retries.
        """
        return svn_auth_get_simple_prompt_provider(self.get_svn_simple, retries)


def get_ssl_client_cert(realm, may_save, pool):
    ssl_cred = svn_auth_cred_ssl_client_cert_t()
    ssl_cred.cert_file = "my-certs-file"
    ssl_cred.may_save = False
    return ssl_cred


def get_ssl_client_cert_pw(realm, may_save, pool):
    ssl_cred_pw = svn_auth_cred_ssl_client_cert_pw_t()
    ssl_cred_pw.password = "supergeheim"
    ssl_cred_pw.may_save = False
    return ssl_cred_pw


def get_ssl_server_trust(realm, failures, cert_info, may_save, pool):
    ssl_server_trust = svn_auth_cred_ssl_server_trust_t()
    ssl_server_trust.accepted_failures = 0
    ssl_server_trust.may_save = False
    return ssl_server_trust
