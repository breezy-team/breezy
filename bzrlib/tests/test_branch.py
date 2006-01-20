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

For interface tests see test_branch_implementations.py.

For concrete class tests see this file, and for meta-branch tests
also see this file.
"""

from StringIO import StringIO

import bzrlib.branch as branch
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )

from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.transport import get_transport

class TestDefaultFormat(TestCase):

    def test_get_set_default_initializer(self):
        old_initializer = branch.Branch.get_default_initializer()
        # default is BzrBranch._initialize
        self.assertEqual(branch.BzrBranch._initialize, old_initializer)
        def recorder(url):
            return "a branch %s" % url
        branch.Branch.set_default_initializer(recorder)
        try:
            b = branch.Branch.initialize("memory:/")
            self.assertEqual("a branch memory:/", b)
        finally:
            branch.Branch.set_default_initializer(old_initializer)
        self.assertEqual(old_initializer, branch.Branch.get_default_initializer())


class SampleBranchFormat(branch.BzrBranchFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrBranchFormat.get_format_string()."""
        return "Sample branch format."

    def initialize(self, url):
        """Format 4 branches cannot be created."""
        t = get_transport(url)
        t.mkdir('.bzr')
        t.put('.bzr/branch-format', StringIO(self.get_format_string()))
        return 'A branch'

    def is_supported(self):
        return False

    def open(self, transport):
        return "opened branch."


class TestBzrBranchFormat(TestCaseInTempDir):
    """Tests for the BzrBranchFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as 
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            format.initialize(url)
            t = get_transport(url)
            found_format = branch.BzrBranchFormat.find_format(t)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(branch.BzrBranchFormat5(), "foo")
        check_format(branch.BzrBranchFormat6(), "bar")
        
    def test_find_format_not_branch(self):
        self.assertRaises(NotBranchError,
                          branch.BzrBranchFormat.find_format,
                          get_transport('.'))

    def test_find_format_unknown_format(self):
        t = get_transport('.')
        t.mkdir('.bzr')
        t.put('.bzr/branch-format', StringIO())
        self.assertRaises(UnknownFormatError,
                          branch.BzrBranchFormat.find_format,
                          get_transport('.'))

    def test_register_unregister_format(self):
        format = SampleBranchFormat()
        # make a branch
        format.initialize('.')
        # register a format for it.
        branch.BzrBranchFormat.register_format(format)
        # which branch.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, branch.Branch.open, '.')
        # but open_downlevel will work
        t = get_transport('.')
        self.assertEqual(format.open(t), branch.Branch.open_downlevel('.'))
        # unregister the format
        branch.BzrBranchFormat.unregister_format(format)
        # now open_downlevel should fail too.
        self.assertRaises(UnknownFormatError, branch.Branch.open_downlevel, '.')
