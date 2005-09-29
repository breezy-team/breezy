# Copyright (C) 2005 by Canonical Ltd

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
import bzrlib.errors
from bzrlib.selftest.testrevision import make_branches
from bzrlib.trace import mutter
from bzrlib.branch import Branch, find_branch
import gzip
import sys
import os

from bzrlib.selftest.HTTPTestUtil import TestCaseWithWebserver

from bzrlib.selftest.testfetch import fetch_steps

class TestFetch(TestCaseWithWebserver):
    def runTest(self):
        from bzrlib.fetch import greedy_fetch
        from bzrlib.selftest.testfetch import has_revision

        def new_branch(name):
            os.mkdir(name)
            return Branch.initialize(name)
            
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches()
        # unpack one of br_a's revision files to test .gz fallbacks
        to_unzip = br_a.revision_history()[-1]
        to_unzip_source = gzip.open(os.path.join(br_a.base, '.bzr', 
                                                  'revision-store',
                                                  to_unzip + '.gz'))
        content = to_unzip_source.read()
        to_unzip_source.close()
        os.unlink(os.path.join(br_a.base, '.bzr', 'revision-store',
                               to_unzip + '.gz'))
        to_unzip_output = open(os.path.join(br_a.base, '.bzr', 
                                             'revision-store', to_unzip), 'wb')
        to_unzip_output.write(content)
        to_unzip_output.close()
        
        br_rem = Branch.open(self.get_remote_url(br_a.base))
        fetch_steps(self, br_rem, br_b, br_a)

