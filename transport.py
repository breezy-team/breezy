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
import svn.ra
import os
from bzrlib.errors import NoSuchFile

class BzrCallbacks(svn.ra.callbacks2_t):
    def __init__(self):
        svn.ra.callbacks2_t.__init__(self)

class BranchingScheme:
    @staticmethod
    def is_branch(name):
        raise NotImplementedError

class DefaultBranchingScheme:
    @staticmethod
    def is_branch(name):
        parts = name.split("/")
        if len(parts) == 1 and parts[0] == "trunk":
            return True

        if len(parts) == 2 and (parts[0] == "branches" or parts[0] == "tags"):
            return True

        return False

# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []

class SvnTransport(Transport):
    def __init__(self, url="", ra=None, scheme=None):
        Transport.__init__(self,url)
        self.url = url
        
        # The SVN libraries don't like trailing slashes...
        url = url.rstrip('/')

        callbacks = BzrCallbacks()

        if ra:
            self.ra = ra
            svn.ra.reparent(self.ra, url.encode('utf8'))
        else:
            self.ra = svn.ra.open2(url.encode('utf8'), callbacks, None, None)

        self.root_url = svn.ra.get_repos_root(self.ra)

        assert url.startswith(self.root_url)

        self.path = url[len(self.root_url)+1:]

        if not scheme:
            scheme = DefaultBranchingScheme()

        self.is_branch_root = scheme.is_branch(self.path)

    def get(self, relpath):
        if relpath == '.bzr/branch-format':
            if self.is_branch_root:
                return StringIO('Subversion Smart Server')
            else:
                raise NoSuchFile(relpath)
        else:
            raise NotImplementedError(self.get)

    def stat(self, relpath):
        return os.stat('.') #FIXME

    def listable(self):
        return False

    def lock_read(self, relpath):
        class PhonyLock:
            def unlock(self):
                pass
        return PhonyLock()

    def clone(self,path):
        parts = self.url.split("/")
        
        # FIXME: Handle more complicated paths
        if path == '..':
            parts.pop()
        elif path != '.':
            parts.append(path)

        return SvnTransport("/".join(parts),self.ra)
