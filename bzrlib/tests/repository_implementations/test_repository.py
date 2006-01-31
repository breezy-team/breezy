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
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from bzrlib.transport import get_transport
from bzrlib.upgrade import upgrade
from bzrlib.workingtree import WorkingTree


class TestCaseWithRepository(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithRepository, self).setUp()

    def make_repository(self, relpath):
        bzrdir = self.make_bzrdir(relpath)
        return bzrdir.create_repository()


class TestRepository(TestCaseWithRepository):

    def test_clone(self):
        #TODO: Test that cloning a repository preserves all the information
        # such as signatures etc etc.
        raise AssertionError('not tested yet.')

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.repository_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = get_transport(self.get_url())
        readonly_t = get_transport(self.get_readonly_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = self.repository_format.initialize(made_control)
        self.failUnless(isinstance(made_repo, repository.Repository))
        self.assertEqual(made_control, made_repo.bzrdir)

        # find it via bzrdir opening:
        opened_control = bzrdir.BzrDir.open(readonly_t.base)
        direct_opened_repo = opened_control.open_repository()
        self.assertEqual(direct_opened_repo.__class__, made_repo.__class__)
        self.assertEqual(opened_control, direct_opened_repo.bzrdir)

        self.failUnless(isinstance(direct_opened_repo._format,
                        self.repository_format.__class__))
        # find it via Repository.open
        opened_repo = repository.Repository.open(readonly_t.base)
        self.failUnless(isinstance(opened_repo, made_repo.__class__))
        self.assertEqual(made_repo._format.__class__,
                         opened_repo._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.repository_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.repository_format,
                         repository.RepositoryFormat.find_format(opened_control))


    def test_create_repository(self):
        # a repository can be constructedzrdir can construct a repository for itself.
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
