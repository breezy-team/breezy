# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.transport import Transport
from cStringIO import StringIO
import svn.ra
import os
from bzrlib.errors import NoSuchFile, NotBranchError
from scheme import NoBranchingScheme

def _create_auth_baton(pool):
    """ Create a Subversion authentication baton.
    
    :param pool: An APR memory pool
    """
    import svn.client
    # Give the client context baton a suite of authentication
    # providers.h
    providers = [
        svn.client.svn_client_get_simple_provider(pool),
        svn.client.svn_client_get_ssl_client_cert_file_provider(pool),
        svn.client.svn_client_get_ssl_client_cert_pw_file_provider(pool),
        svn.client.svn_client_get_ssl_server_trust_file_provider(pool),
        svn.client.svn_client_get_username_provider(pool),
        ]
    return svn.core.svn_auth_open(providers, pool)


# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []

class SvnRaCallbacks(svn.ra.callbacks2_t):
    def __init__(self):
        svn.ra.callbacks2_t.__init__(self)
        from branch import _global_pool
        self.auth_baton = _create_auth_baton(_global_pool)

    def open_tmp_file(self):
        print "foo"

    def progress(self, f, c, pool):
        print "%s: %d / %d" % (self, f, c)


class SvnRaTransport(Transport):
    """Fake transport for Subversion-related namespaces. This implements 
    just as much of Transport as is necessary to fool Bazaar-NG. """
    def __init__(self, url="", ra=None, root_url=None, scheme=None):
        Transport.__init__(self, url)

        if url.startswith("svn://") or \
           url.startswith("svn+ssh://"):
            self.svn_url = url
        else:
            self.svn_url = url[4:] # Skip svn+

        # The SVN libraries don't like trailing slashes...
        self.svn_url = self.svn_url.rstrip('/')

        callbacks = SvnRaCallbacks()

        if not ra:
            self.ra = svn.ra.open2(self.svn_url.encode('utf8'), callbacks, None, None)
            self.svn_root_url = svn.ra.get_repos_root(self.ra)
            svn.ra.reparent(self.ra, self.svn_root_url.encode('utf8'))
        else:
            self.ra = ra
            self.svn_root_url = root_url

        self.root_url = self.svn_root_url
        if not self.root_url.startswith("svn+"):
            self.root_url = "svn+%s" % self.root_url

        # Browsed above this directory
        if not self.svn_url.startswith(self.svn_root_url):
            raise NotBranchError(url)

        self.path = self.svn_url[len(self.svn_root_url)+1:]

        if not scheme:
            scheme = NoBranchingScheme()

        self._scheme = scheme
        self.is_branch_root = scheme.is_branch(self.path)

    def has(self, relpath):
        return False

    def get(self, relpath):
        raise NoSuchFile(relpath)

    def stat(self, relpath):
        return os.stat('.') #FIXME

    def listable(self):
        return False

    def lock_read(self, relpath):
        class PhonyLock:
            def unlock(self):
                pass
        return PhonyLock()

    def clone(self, path):
        parts = self.svn_url.split("/")
        
        # FIXME: Handle more complicated paths
        if path == '..':
            parts.pop()
        elif path != '.':
            parts.append(path)

        return SvnRaTransport("/".join(parts),ra=self.ra,root_url=self.svn_root_url)
