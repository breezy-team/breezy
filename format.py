from bzrlib.bzrdir import BzrDirFormat, BzrDir
from repository import SvnRepository
from branch import RemoteSvnBranch

class SvnDir(BzrDir):
    def __init__(self, _transport, _format):
        self.transport = _transport
        self.format = _format
        pass

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        raise NotImplementedError(SvnDir.clone)

    def find_repository(self):
        return SvnRepository()

    def open_branch(self, unsupported=True):
        return RemoteSvnBranch(self.transport.url)

class SvnFormat(BzrDirFormat):
    def _open(self, transport):
        print "Connected to %s" % transport
        return SvnDir(transport, self)

    def get_format_string(self):
        return 'SVN Repository'

