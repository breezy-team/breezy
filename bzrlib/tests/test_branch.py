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

from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport

class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_format = branch.BranchFormat.get_default_format()
        # default is 5
        self.assertTrue(isinstance(old_format, branch.BzrBranchFormat5))
        branch.BranchFormat.set_default_format(SampleBranchFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize('memory:/')
            result = dir.create_branch()
            self.assertEqual(result, 'A branch')
        finally:
            branch.BranchFormat.set_default_format(old_format)
        self.assertEqual(old_format, branch.BranchFormat.get_default_format())


class SampleBranchFormat(branch.BranchFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrBranchFormat.get_format_string()."""
        return "Sample branch format."

    def initialize(self, a_bzrdir):
        """Format 4 branches cannot be created."""
        t = a_bzrdir.get_branch_transport(self)
        t.put('format', StringIO(self.get_format_string()))
        return 'A branch'

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        return "opened branch."


class TestBzrBranchFormat(TestCaseWithTransport):
    """Tests for the BzrBranchFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as 
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            format.initialize(dir)
            t = get_transport(url)
            found_format = branch.BranchFormat.find_format(dir)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(branch.BzrBranchFormat5(), "bar")
        
    def test_find_format_not_branch(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        self.assertRaises(NotBranchError,
                          branch.BranchFormat.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        SampleBranchFormat().initialize(dir)
        self.assertRaises(UnknownFormatError,
                          branch.BranchFormat.find_format,
                          dir)

    def test_register_unregister_format(self):
        format = SampleBranchFormat()
        # make a control dir
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        # make a branch
        format.initialize(dir)
        # register a format for it.
        branch.BranchFormat.register_format(format)
        # which branch.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, branch.Branch.open, self.get_url())
        # but open_downlevel will work
        self.assertEqual(format.open(dir), branch.Branch.open_downlevel(self.get_url()))
        # unregister the format
        branch.BranchFormat.unregister_format(format)
