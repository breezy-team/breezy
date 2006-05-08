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
