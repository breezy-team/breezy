# (C) 2006 Canonical Ltd

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

"""Tests for the Repository facility that are not interface tests.

For interface tests see tests/repository_implementations/*.py.

For concrete class tests see this file, and for storage formats tests
also see this file.
"""

from StringIO import StringIO

import bzrlib.bzrdir as bzrdir
from bzrlib.errors import (NotBranchError,
                           NoSuchFile,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )
import bzrlib.repository as repository
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport
from bzrlib.transport.http import HttpServer
from bzrlib.transport.memory import MemoryServer


class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_format = repository.RepositoryFormat.get_default_format()
        # default is None - we cannot create a Repository independently yet
        self.assertEqual(old_format, None)
        repository.RepositoryFormat.set_default_format(SampleRepositoryFormat())
        # creating a repository should now create an instrumented dir.
        try:
            # directly
            control = bzrdir.BzrDir.create('memory:/')
            result = repository.Repository.create(control)
            self.assertEqual(result, 'A bzr repository dir')
        finally:
            repository.RepositoryFormat.set_default_format(old_format)
        self.assertEqual(old_format, repository.RepositoryFormat.get_default_format())


class SampleRepositoryFormat(repository.RepositoryFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Sample .bzr repository format."

    def initialize(self, a_bzrdir):
        """Initialize a repository in a BzrDir"""
        t = a_bzrdir.transport
        t.mkdir('repository')
        t.put('repository/format', StringIO(self.get_format_string()))
        return 'A bzr repository dir'

    def is_supported(self):
        return False

    def open(self, a_bzrdir):
        return "opened repository."


class TestFormat6(TestCaseWithTransport):

    def test_no_ancestry_weave(self):
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = repository.RepositoryFormat6().initialize(control)
        # We no longer need to create the ancestry.weave file
        # since it is *never* used.
        self.assertRaises(NoSuchFile,
                          control.transport.get,
                          'ancestry.weave')

