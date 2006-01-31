# (C) 2005, 2006 Canonical Ltd

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

"""Tests for bzrdir implementations - tests a bzrdir format."""

import os
import sys

import bzrlib.branch as branch
import bzrlib.bzrdir as bzrdir
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.commit import commit
import bzrlib.errors as errors
from bzrlib.errors import (FileExists,
                           NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
import bzrlib.repository as repository
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.transport import get_transport
from bzrlib.upgrade import upgrade
from bzrlib.workingtree import WorkingTree


class TestCaseWithBzrDir(TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithBzrDir, self).setUp()
        self.bzrdir = None

    def get_bzrdir(self):
        if self.bzrdir is None:
            self.bzrdir = self.make_bzrdir(None)
        return self.bzrdir

    def make_bzrdir(self, relpath):
        try:
            url = self.get_url(relpath)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except FileExists:
                    pass
            return self.bzrdir_format.initialize(url)
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable.")


class TestBzrDir(TestCaseWithBzrDir):

    def test_clone_bzrdir(self):
        #TODO: Test that we can create a clone of a bzr dir 
        #
        #... and all its contents verbatim.
        raise AssertionError('not tested yet.')

        # a bunch of tests needed::
        # create a bzr dir with nothing, clone it check result has nothing
        # create a bzr dir with storage only, clone it check result has same
        # storage contents
        # create bzr dir with branch with no storage, clone, check resulting
        # dir also has no storage but does have branch
        # create bzr dir with a tree but no storage or branch (on local disk
        # as thats how workingtree works) clone and check no branch or 
        # storage is made
        # create a standalone_branch , clone that and check all bits are
        # clone.
        # these should all check that the formats on subthings like repository
        # are the same as the source format.
        # features that are not supported (like detached working trees for
        # older formats, should catch the error and silently pass the test 
        # as they are honouring the format.

    def test_new_line_of_development_bzrdir(self):
        #TODO: Test that we can create a line of development from a 
        raise AssertionError('not tested yet.')
         
        # same permutations as clone_bzrdir, or nearly so, but we want to
        # have checkouts force creation of a new branch because thats the 
        # desired semantic.

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = get_transport(self.get_url())
        readonly_t = get_transport(self.get_readonly_url())
        made_control = self.bzrdir_format.initialize(t.base)
        self.failUnless(isinstance(made_control, bzrdir.BzrDir))
        self.assertEqual(self.bzrdir_format,
                         bzrdir.BzrDirFormat.find_format(readonly_t))
        direct_opened_dir = self.bzrdir_format.open(readonly_t)
        opened_dir = bzrdir.BzrDir.open(t.base)
        self.assertEqual(made_control._format,
                         opened_dir._format)
        self.assertEqual(direct_opened_dir._format,
                         opened_dir._format)
        self.failUnless(isinstance(opened_dir, bzrdir.BzrDir))

    def test_open_not_bzrdir(self):
        # test the formats specific behaviour for no-content or similar dirs.
        self.assertRaises(NotBranchError,
                          self.bzrdir_format.open,
                          get_transport(self.get_readonly_url()))

    def test_create_repository(self):
        # a bzrdir can construct a repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        self.failUnless(isinstance(made_repo, repository.Repository))
        self.assertEqual(made_control, made_repo.bzrdir)
        
    def test_open_repository(self):
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        opened_repo = made_control.open_repository()
        self.assertEqual(made_control, opened_repo.bzrdir)
        self.failUnless(isinstance(opened_repo, made_repo.__class__))
