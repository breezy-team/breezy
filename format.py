from bzrlib.bzrdir import BzrDirFormat, BzrDir
from repository import SvnRepository
from branch import RemoteSvnBranch

class SvnRemoteAccess(BzrDir):
    def __init__(self, _transport, _format):
        self.transport = _transport
        self.format = _format
        if _transport.url.startswith("svn://") or \
           _transport.url.startswith("svn+ssh://"):
            self.url = _transport.url
        else:
            self.url = _transport.url[4:] # Skip svn+



    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        raise NotImplementedError(SvnRemoteAccess.clone)

    def find_repository(self):
        return SvnRepository(self, None, None, None)

    def open_branch(self, unsupported=True):
        try:
            branch = RemoteSvnBranch(self.url)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_RA_ILLEGAL_URL or \
               num == svn.core.SVN_ERR_WC_NOT_DIRECTORY or \
               num == svn.core.SVN_ERR_RA_NO_REPOS_UUID or \
               num == svn.core.SVN_ERR_RA_SVN_REPOS_NOT_FOUND or \
               num == svn.core.SVN_ERR_RA_DAV_REQUEST_FAILED:
               raise NotBranchError(path=self.url)
        except:
            raise
 
        branch.repository = self.find_repository()
        return branch

class SvnFormat(BzrDirFormat):
    def _open(self, transport):
        return SvnRemoteAccess(transport, self)

    def get_format_string(self):
        return 'SVN Repository'

