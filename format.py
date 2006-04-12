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
        print "Connected to %s" % self.url

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        raise NotImplementedError(SvnRemoteAccess.clone)

    def find_repository(self):
        return SvnRepository()

    def open_branch(self, unsupported=True):
        return RemoteSvnBranch(self.url)

class SvnFormat(BzrDirFormat):
    def _open(self, transport):
        return SvnRemoteAccess(transport, self)

    def get_format_string(self):
        return 'SVN Repository'

