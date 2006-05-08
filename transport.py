# Foreign branch support for Subversion
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.transport import Transport
from cStringIO import StringIO
import os

# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []

class SvnTransport(Transport):
    def __init__(self, url=""):
        Transport.__init__(self,url)
        self.url = url
        # The SVN libraries don't like trailing slashes...
        url = url.rstrip('/')


    def get(self, relpath):
        if relpath == '.bzr/branch-format':
            return StringIO('Subversion Smart Server')
        else:
            raise NotImplementedError(self.get)

    def stat(self, relpath):
        return os.stat('.') #FIXME

    def listable(self):
        return False

    def lock_read(self, relpath):
        # FIXME
        class PhonyLock:
            def unlock(self):
                pass
        return PhonyLock()
