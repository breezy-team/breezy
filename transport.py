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
from scheme import DefaultBranchingScheme

# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []

class SvnTransport(Transport):
    """ Fake transport for Subversion-related namespaces. This implements 
    just as much of Transport as is necessary to fool Bazaar-NG. """
    def __init__(self, url="", ra=None, root_url=None, scheme=None):
        from branch import auth_baton
        Transport.__init__(self,url)

        if url.startswith("svn://") or \
           url.startswith("svn+ssh://"):
            self.svn_url = url
        else:
            self.svn_url = url[4:] # Skip svn+

        # The SVN libraries don't like trailing slashes...
        self.svn_url = self.svn_url.rstrip('/')

        callbacks = svn.ra.callbacks2_t()
        callbacks.auth_baton = auth_baton

        if not ra:
            self.ra = svn.ra.open2(self.svn_url.encode('utf8'), callbacks, None, None)
            self.svn_root_url = svn.ra.get_repos_root(self.ra)
            svn.ra.reparent(self.ra, self.svn_root_url.encode('utf8'))
        else:
            self.ra = ra
            self.svn_root_url = root_url

        self.root_url = self.svn_root_url
        if not self.root_url.startswith("svn+"):
            self.root_url = "svn+%s" % self.root_url

        assert self.svn_url.startswith(self.svn_root_url)

        self.path = self.svn_url[len(self.svn_root_url)+1:]

        if not scheme:
            scheme = DefaultBranchingScheme()

        self._scheme = scheme
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
        parts = self.svn_url.split("/")
        
        # FIXME: Handle more complicated paths
        if path == '..':
            parts.pop()
        elif path != '.':
            parts.append(path)

        return SvnTransport("/".join(parts),ra=self.ra,root_url=self.svn_root_url)
