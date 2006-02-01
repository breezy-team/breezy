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

"""Tests for the BzrDir facility and any format specific tests.

For interface contract tests, see tests/bzr_dir_implementations.
"""

from StringIO import StringIO

import bzrlib.bzrdir as bzrdir
import bzrlib.errors as errors
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport
from bzrlib.transport.http import HttpServer
from bzrlib.transport.memory import MemoryServer


class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_format = bzrdir.BzrDirFormat.get_default_format()
        # default is BzrDirFormat6
        self.failUnless(isinstance(old_format, bzrdir.BzrDirFormat6))
        bzrdir.BzrDirFormat.set_default_format(SampleBzrDirFormat())
        # creating a bzr dir should now create an instrumented dir.
        try:
            result = bzrdir.BzrDir.create('memory:/')
            self.failUnless(isinstance(result, SampleBzrDir))
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)
        self.assertEqual(old_format, bzrdir.BzrDirFormat.get_default_format())


class SampleBzrDir(bzrdir.BzrDir):
    """A sample BzrDir implementation to allow testing static methods."""

    def create_repository(self):
        """See BzrDir.create_repository."""
        return "A repository"

    def create_branch(self):
        """See BzrDir.create_branch."""
        return "A branch"

    def create_workingtree(self):
        """See BzrDir.create_workingtree."""
        return "A tree"


class SampleBzrDirFormat(bzrdir.BzrDirFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Sample .bzr dir format."

    def initialize(self, url):
        """Create a bzr dir."""
        t = get_transport(url)
        t.mkdir('.bzr')
        t.put('.bzr/branch-format', StringIO(self.get_format_string()))
        return SampleBzrDir(t, self)

    def is_supported(self):
        return False

    def open(self, transport, _found=None):
        return "opened branch."


class TestBzrDirFormat(TestCaseWithTransport):
    """Tests for the BzrDirFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as 
        t = get_transport(self.get_url())
        self.build_tree(["foo/", "bar/"], transport=t)
        def check_format(format, url):
            format.initialize(url)
            t = get_transport(url)
            found_format = bzrdir.BzrDirFormat.find_format(t)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(bzrdir.BzrDirFormat5(), "foo")
        check_format(bzrdir.BzrDirFormat6(), "bar")
        
    def test_find_format_nothing_there(self):
        self.assertRaises(NotBranchError,
                          bzrdir.BzrDirFormat.find_format,
                          get_transport('.'))

    def test_find_format_unknown_format(self):
        t = get_transport(self.get_url())
        t.mkdir('.bzr')
        t.put('.bzr/branch-format', StringIO())
        self.assertRaises(UnknownFormatError,
                          bzrdir.BzrDirFormat.find_format,
                          get_transport('.'))

    def test_register_unregister_format(self):
        format = SampleBzrDirFormat()
        url = self.get_url()
        # make a bzrdir
        format.initialize(url)
        # register a format for it.
        bzrdir.BzrDirFormat.register_format(format)
        # which bzrdir.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, bzrdir.BzrDir.open, url)
        # but open_downlevel will work
        t = get_transport(url)
        self.assertEqual(format.open(t), bzrdir.BzrDir.open_unsupported(url))
        # unregister the format
        bzrdir.BzrDirFormat.unregister_format(format)
        # now open_downlevel should fail too.
        self.assertRaises(UnknownFormatError, bzrdir.BzrDir.open_unsupported, url)

    def test_create_repository(self):
        format = SampleBzrDirFormat()
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(format)
        try:
            repo = bzrdir.BzrDir.create_repository(self.get_url())
            self.assertEqual('A repository', repo)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_and_repo(self):
        format = SampleBzrDirFormat()
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(format)
        try:
            branch = bzrdir.BzrDir.create_branch_and_repo(self.get_url())
            self.assertEqual('A branch', branch)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_standalone_working_tree(self):
        format = SampleBzrDirFormat()
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(format)
        try:
            # note this is deliberately readonly, as this failure should 
            # occur before any writes.
            self.assertRaises(errors.NotLocalUrl,
                              bzrdir.BzrDir.create_standalone_workingtree,
                              self.get_readonly_url())
            tree = bzrdir.BzrDir.create_standalone_workingtree('.')
            self.assertEqual('A tree', tree)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)


class ChrootedTests(TestCaseWithTransport):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super(ChrootedTests, self).setUp()
        if not self.transport_server == MemoryServer:
            self.transport_readonly_server = HttpServer

    def test_open_containing(self):
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing,
                          self.get_readonly_url(''))
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing,
                          self.get_readonly_url('g/p/q'))
        control = bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url(''))
        self.assertEqual('', relpath)
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url('g/p/q'))
        self.assertEqual('g/p/q', relpath)
