# Foreign branch support for Subversion
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.transport import Transport
from cStringIO import StringIO

class SvnTransport(Transport):
    def __init__(self, url=""):
        Transport.__init__(self,url)
        self.url = url

    def get(self, relpath):
        if relpath == '.bzr/branch-format':
            return StringIO('SVN Repository')
        else:
            raise NotImplementedError(self.get)
