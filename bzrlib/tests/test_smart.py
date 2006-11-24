# Copyright (C) 2006 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the smart wire/domain protococl."""

from bzrlib import errors, smart, tests
from bzrlib.smart.request import SmartServerResponse
import bzrlib.smart.bzrdir
import bzrlib.smart.branch


class TestSmartServerResponse(tests.TestCase):

    def test__eq__(self):
        self.assertEqual(SmartServerResponse(('ok', )),
            SmartServerResponse(('ok', )))
        self.assertEqual(SmartServerResponse(('ok', ), 'body'),
            SmartServerResponse(('ok', ), 'body'))
        self.assertNotEqual(SmartServerResponse(('ok', )),
            SmartServerResponse(('notok', )))
        self.assertNotEqual(SmartServerResponse(('ok', ), 'body'),
            SmartServerResponse(('ok', )))


class TestSmartServerRequestFindRepository(tests.TestCaseWithTransport):

    def test_no_repository(self):
        """When there is no repository to be found, ('norepository', ) is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestFindRepository(backing)
        self.make_bzrdir('.')
        self.assertEqual(SmartServerResponse(('norepository', )),
            request.execute(backing.local_abspath('')))

    def test_nonshared_repository(self):
        # nonshared repositorys only allow 'find' to return a handle when the 
        # path the repository is being searched on is the same as that that 
        # the repository is at.
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestFindRepository(backing)
        self.make_repository('.')
        self.assertEqual(SmartServerResponse(('ok', '')),
            request.execute(backing.local_abspath('')))
        self.make_bzrdir('subdir')
        self.assertEqual(SmartServerResponse(('norepository', )),
            request.execute(backing.local_abspath('subdir')))

    def test_shared_repository(self):
        """When there is a shared repository, we get 'ok', 'relpath-to-repo'."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestFindRepository(backing)
        self.make_repository('.', shared=True)
        self.assertEqual(SmartServerResponse(('ok', '')),
            request.execute(backing.local_abspath('')))
        self.make_bzrdir('subdir')
        self.assertEqual(SmartServerResponse(('ok', '..')),
            request.execute(backing.local_abspath('subdir')))
        self.make_bzrdir('subdir/deeper')
        self.assertEqual(SmartServerResponse(('ok', '../..')),
            request.execute(backing.local_abspath('subdir/deeper')))


class TestSmartServerRequestOpenBranch(tests.TestCaseWithTransport):

    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        self.make_bzrdir('.')
        self.assertEqual(SmartServerResponse(('nobranch', )),
            request.execute(backing.local_abspath('')))

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', '')),
            request.execute(backing.local_abspath('')))

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        # TODO: once we have an API to probe for references of any sort, we
        # can use it here.
        reference_url = backing.abspath('branch') + '/'
        self.assertFileEqual(reference_url, 'reference/.bzr/branch/location')
        self.assertEqual(SmartServerResponse(('ok', reference_url)),
            request.execute(backing.local_abspath('reference')))


class TestSmartServerRequestRevisionHistory(tests.TestCaseWithTransport):

    def test_no_branch(self):
        """When there is a bzrdir and no branch, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        self.make_bzrdir('.')
        self.assertRaises(errors.NotBranchError,
            request.execute, backing.local_abspath(''))

    def test_empty(self):
        """For an empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', ), ''),
            request.execute(backing.local_abspath('')))

    def test_not_empty(self):
        """For a non-empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8')
        tree.unlock()
        self.assertEqual(SmartServerResponse(('ok', ),
            ('\x00'.join([r1, r2])).encode('utf8')),
            request.execute(backing.local_abspath('')))

    def test_branch_reference(self):
        """When there is a branch reference, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        self.assertRaises(errors.NotBranchError,
            request.execute, backing.local_abspath('checkout'))


class TestHandlers(tests.TestCase):
    """Tests for the request.request_handlers object."""

    def test_registered_methods(self):
        """Test that known methods are registered to the correct object."""
        self.assertEqual(
            smart.request.request_handlers.get('Branch.revision_history'),
            smart.branch.SmartServerRequestRevisionHistory)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.find_repository'),
            smart.bzrdir.SmartServerRequestFindRepository)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.open_branch'),
            smart.bzrdir.SmartServerRequestOpenBranch)
