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

from bzrlib.errors import NoSuchFile, NotBranchError
from bzrlib.transport import Transport
import bzrlib.urlutils as urlutils

from cStringIO import StringIO
import os

from svn.core import SubversionException, Pool
import svn.ra

import svn.core

svn.ra.initialize()

svn_config = svn.core.svn_config_get_config(None)

def _create_auth_baton(pool):
    """ Create a Subversion authentication baton.  """
    import svn.client
    # Give the client context baton a suite of authentication
    # providers.h
    providers = [
        svn.client.get_simple_provider(pool),
        svn.client.get_username_provider(pool),
        svn.client.get_ssl_client_cert_file_provider(pool),
        svn.client.get_ssl_client_cert_pw_file_provider(pool),
        svn.client.get_ssl_server_trust_file_provider(pool),
        ]
    return svn.core.svn_auth_open(providers, pool)


# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []


class SvnRaCallbacks(svn.ra.callbacks2_t):
    def __init__(self, pool):
        svn.ra.callbacks2_t.__init__(self)
        self.auth_baton = _create_auth_baton(pool)
        self.pool = pool

    def open_tmp_file(self):
        print "foo"

    def progress(self, f, c, pool):
        print "%s: %d / %d" % (self, f, c)


class SvnRaTransport(Transport):
    """Fake transport for Subversion-related namespaces. This implements 
    just as much of Transport as is necessary to fool Bazaar-NG. """
    def __init__(self, url="", ra=None):
        self.pool = Pool()
        if not url.startswith("svn+"):
            url = "svn+%s" % url
        Transport.__init__(self, url)

        if url.startswith("svn+") and not url.startswith("svn+ssh://"):
            self.svn_url = url[4:] # Skip svn+
        else:
            self.svn_url = url

        # The SVN libraries don't like trailing slashes...
        self.svn_url = self.svn_url.rstrip('/')

        if ra is None:
            callbacks = SvnRaCallbacks(self.pool)
            try:
                self.ra = svn.ra.open2(self.svn_url.encode('utf8'), callbacks, svn_config)
            except SubversionException, (_, num):
                if num == svn.core.SVN_ERR_RA_ILLEGAL_URL:
                    raise NotBranchError(path=url)
                if num == svn.core.SVN_ERR_RA_LOCAL_REPOS_OPEN_FAILED:
                    raise NotBranchError(path=url)
                raise

        else:
            self.ra = ra
            svn.ra.reparent(self.ra, self.svn_url.encode('utf8'))

    def has(self, relpath):
        return False

    def get(self, relpath):
        raise NoSuchFile(relpath)

    def stat(self, relpath):
        return os.stat('.') #FIXME

    def get_root(self):
        return SvnRaTransport(svn.ra.get_repos_root(self.ra), ra=self.ra)

    def listable(self):
        return False

    class PhonyLock:
        def unlock(self):
            pass

    def lock_write(self, relpath):
        return self.PhonyLock()

    def lock_read(self, relpath):
        return self.PhonyLock()

    def clone(self, offset=None):
        if offset is None:
            return self.__class__(self.base)

        return SvnRaTransport(urlutils.join(self.svn_url, offset), ra=self.ra)
