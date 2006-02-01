# (C) 2005 Canonical Ltd

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

"""Tests for the Branch facility that are not interface  tests.

For interface tests see tests/branch_implementations/*.py.

For concrete class tests see this file, and for meta-branch tests
also see this file.
"""

from StringIO import StringIO

import bzrlib.branch as branch
import bzrlib.bzrdir as bzrdir
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )

from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.transport import get_transport

#class TestDefaultFormat(TestCase):
#
#    def test_get_set_default_format(self):
#        old_format = branch.BranchFormat.get_default_format()
#        # default is None - we cannot create a Branch independently yet
#        self.assertEqual(old_format, None)
#        branch.BranchFormat.set_default_format(SampleBranchFormat())
#        try:
#            """default branch formats make no sense until we have
#            multiple formats per bzrdir format."""
#            # directly
#            #result = branch.Branch.create('memory:/')
#            #self.assertEqual(result, 'A bzr branch dir')
#        finally:
#            branch.BranchFormat.set_default_format(old_format)
#        self.assertEqual(old_format, branch.BranchFormat.get_default_format())
