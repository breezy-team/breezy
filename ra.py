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

import svn.core

get_username_prompt_provider = svn.core.svn_auth_get_username_prompt_provider
get_simple_prompt_provider = svn.core.svn_auth_get_simple_prompt_provider
get_ssl_client_cert_pw_prompt_provider = svn.core.svn_auth_get_ssl_client_cert_pw_prompt_provider
get_ssl_server_trust_prompt_provider = svn.core.svn_auth_get_ssl_server_trust_prompt_provider

DIRENT_KIND = 0x0001

class Auth:
    def __init__(self, providers=[]):
        self.providers = providers
        self.auth_baton = svn.core.svn_auth_open(self.providers)
        self.parameters = {}
        self.auth_baton._base = self.auth_baton # evil hack

    def set_parameter(self, name, value):
        self.parameters[name] = value
        svn.core.svn_auth_set_parameter(self.auth_baton, name, value)

    def get_parameter(self, name):
        return svn.core.svn_auth_get_parameter(self.auth_baton, name)
