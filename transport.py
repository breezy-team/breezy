# Foreign branch support for Subversion
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

from bzrlib.transport import Transport
from cStringIO import StringIO
import os


class SvnTransport(Transport):
    def __init__(self, url=""):
        Transport.__init__(self,url)
        self.url = url
        # The SVN libraries don't like trailing slashes...
        url = url.rstrip('/')


    def get(self, relpath):
        if relpath == '.bzr/branch-format':
            return StringIO('SVN Repository')
        else:
            raise NotImplementedError(self.get)

    def stat(self, relpath):
        print "FIXME: Stat on %s" % relpath
        return os.stat('.')

    def lock_read(self, relpath):
        class PhonyLock:
            def unlock(self):
                pass
        print "FIXME: lock_read on %s" % relpath
        return PhonyLock()

