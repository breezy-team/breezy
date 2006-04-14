# Foreign branch support for Subversion
# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.repository import Repository
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.trace import mutter
from bzrlib.revision import Revision
import svn.core
import bzrlib
from branch import auth_baton

"""
Provides a simplified interface to a Subversion repository 
by using the RA (remote access) API from subversion
"""
class SvnRepository(Repository):
    branch_paths = [".","branches","tags"]

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

        self.uuid = svn.client.uuid_from_url(self.url.encode('utf8'), 
                self.client, self.pool)

        mutter("Connected to repository at %s, UUID %s" % (self.url, self.uuid))

    def __del__(self):
        svn.core.svn_pool_destroy(self.pool)

    def get_inventory(self):
        raise NotImplementedError()

    def all_revision_ids(self):
        raise NotImplementedError()

    def get_inventory_weave(self):
        # FIXME
        raise NotImplementedError()

    def get_ancestry(self, revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)

        url = self.url + "/" + path

        revt_begin = svn.core.svn_opt_revision_t()
        revt_begin.kind = svn.core.svn_opt_revision_number
        revt_begin.value.number = 0

        revt_peg = svn.core.svn_opt_revision_t()
        revt_peg.kind = svn.core.svn_opt_revision_number
        revt_peg.value.number = revnum

        revt_end = svn.core.svn_opt_revision_t()
        revt_end.kind = svn.core.svn_opt_revision_number
        revt_end.value.number = revnum - 1

        self._ancestry = [None]

        def rcvr(paths,rev,author,date,message,pool):
            revid = "%d@%s-%s" % (rev,self.uuid,path)
            self._ancestry.append(revid)

        mutter("log3 %s" % url)
        svn.client.log3([url.encode('utf8')], revt_peg, revt_begin, \
                revt_end, 1, False, False, rcvr, 
                self.client, self.pool)

        return self._ancestry

    def has_revision(self,revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)

        url = self.url + "/" + path

        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_number
        revt.value.number = revnum

        self._found = False

        def rcvr(paths,rev,author,date,message,pool):
            self._found = True

        mutter("log3 %s" % url)
        svn.client.log3([url.encode('utf8')], revt, revt, \
                revt, 1, False, False, rcvr, 
                self.client, self.pool)

        return self._found

    def get_revision(self,revision_id):
        (path,revnum) = self.parse_revision_id(revision_id)
        
        url = self.url + "/" + path

        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = revnum
        mutter('svn proplist -r %r %r' % (revnum,url))
        (svn_props, actual_rev) = svn.client.revprop_list(url.encode('utf8'), rev, self.client, self.pool)
        assert actual_rev == revnum

        revt_begin = svn.core.svn_opt_revision_t()
        revt_begin.kind = svn.core.svn_opt_revision_number
        revt_begin.value.number = revnum - 1

        revt_end = svn.core.svn_opt_revision_t()
        revt_end.kind = svn.core.svn_opt_revision_number
        revt_end.value.number = 0

        parent_ids = []

        def rcvr(paths,rev,author,date,message,pool):
            revid = "%d@%s-%s" % (rev,self.uuid,path)
            parent_ids.append(revid)

        mutter("log3 %s" % url)
        svn.client.log3([url.encode('utf8')], revt_begin, revt_begin, \
                revt_end, 1, False, False, rcvr, 
                self.client, self.pool)

        # Commit SVN revision properties to a Revision object
        bzr_props = {}
        rev = Revision(revision_id=revision_id,
                       parent_ids=parent_ids)

        for name in svn_props:
            bzr_props[name] = svn_props[name].decode('utf8')

        rev.timestamp = svn.core.secs_from_timestr(bzr_props[svn.core.SVN_PROP_REVISION_DATE], self.pool) * 1.0
        rev.timezone = None

        rev.committer = bzr_props[svn.core.SVN_PROP_REVISION_AUTHOR]
        rev.message = bzr_props[svn.core.SVN_PROP_REVISION_LOG]

        rev.properties = bzr_props
        
        return rev

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError()

    def fileid_involved_between_revs(self, from_revid, to_revid):
        raise NotImplementedError()

    def fileid_involved(self, last_revid=None):
        raise NotImplementedError()

    def get_inventory_xml(self, revision_id):
        raise NotImplementedError()

    def fileid_involved_by_set(self, changes):
        ids = []

        for revid in changes:
            pass #FIXME

        return ids

    def parse_revision_id(self,revid):
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]

        if uuid != self.uuid:
            raise NoSuchRevision()

        return (revid[fash+1:],int(revid[0:at]))

    def get_revision_graph_with_ghosts(self, revision_id):
        raise NotImplementedError()

    def get_revision_graph(self, revision_id):
        if revision_id is None:
            raise NotImplementedError()

        (path,revnum) = self.parse_revision_id(revision_id)

        revt_begin = svn.core.svn_opt_revision_t()
        revt_begin.kind = svn.core.svn_opt_revision_number
        revt_begin.value.number = revnum - 1

        revt_end = svn.core.svn_opt_revision_t()
        revt_end.kind = svn.core.svn_opt_revision_number
        revt_end.value.number = 0

        self._previous = revision_id
        self._ancestry = {}
        
        def rcvr(paths,rev,author,date,message,pool):
            revid = "%d@%s-%s" % (rev,self.uuid,path)
            self._ancestry[self._previous] = [revid]
            self._previous = revid

        url = self.url + "/" + path

        mutter("log3 %s" % (url))
        svn.client.log3([url.encode('utf8')], revt_begin, revt_begin, \
                revt_end, 0, False, False, rcvr, 
                self.client, self.pool)

        self._ancestry[self._previous] = [None]
        self._ancestry[None] = []

        return self._ancestry
