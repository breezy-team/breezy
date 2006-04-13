# Foreign branch support for Subversion
# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.repository import Repository
from bzrlib.lockable_files import LockableFiles, TransportLock
import svn.core
import bzrlib
from branch import auth_baton

"""
Provides a simplified interface to a Subversion repository 
by using the RA (remote access) API from subversion
"""
class SvnRepository(Repository):
    def __init__(self, bzrdir, url):
        self.url = url
        _revision_store = None
        control_store = None
        text_store = None
        control_files = LockableFiles(bzrdir.transport, '', TransportLock)
        Repository.__init__(self, 'SVN Repository', bzrdir, control_files, _revision_store, control_store, text_store)

        self.pool = svn.core.svn_pool_create(None)

        self.client = svn.client.svn_client_create_context(self.pool)
        self.client.config = svn.core.svn_config_get_config(None)
        self.client.auth_baton = auth_baton

        self.uuid = svn.client.uuid_from_url(self.url.encode('utf8'), self.client, self.pool)

    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)
