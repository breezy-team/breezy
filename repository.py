# Foreign branch support for Subversion
# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.repository import Repository
from bzrlib.lockable_files import LockableFiles, TransportLock
import bzrlib

"""
Provides a simplified interface to a Subversion repository 
by using the RA (remote access) API from subversion
"""
class SvnRepository(Repository):
    def __init__(self, bzrdir, _revision_store, control_store, text_store):
        control_files = LockableFiles(bzrdir.transport, '', TransportLock)
        Repository.__init__(self, 'SVN Repository', bzrdir, control_files, _revision_store, control_store, text_store)
