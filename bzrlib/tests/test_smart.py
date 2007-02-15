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

from bzrlib import bzrdir, errors, smart, tests
from bzrlib.smart.request import SmartServerResponse
import bzrlib.smart.bzrdir
import bzrlib.smart.branch
import bzrlib.smart.repository


class TestCaseWithSmartMedium(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithSmartMedium, self).setUp()
        # We're allowed to set  the transport class here, so that we don't use
        # the default or a parameterized class, but rather use the
        # TestCaseWithTransport infrastructure to set up a smart server and
        # transport.
        self.transport_server = smart.server.SmartTCPServer_for_testing

    def get_smart_medium(self):
        """Get a smart medium to use in tests."""
        return self.get_transport().get_smart_medium()


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
        self.assertNotEqual(None,
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


class TestSmartServerRequestInitializeBzrDir(tests.TestCaseWithTransport):

    def test_empty_dir(self):
        """Initializing an empty dir should succeed and do it."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.assertEqual(SmartServerResponse(('ok', )),
            request.execute(backing.local_abspath('.')))
        made_dir = bzrdir.BzrDir.open_from_transport(backing)
        # no branch, tree or repository is expected with the current 
        # default formart.
        self.assertRaises(errors.NoWorkingTree, made_dir.open_workingtree)
        self.assertRaises(errors.NotBranchError, made_dir.open_branch)
        self.assertRaises(errors.NoRepositoryPresent, made_dir.open_repository)

    def test_missing_dir(self):
        """Initializing a missing directory should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.assertRaises(errors.NoSuchFile,
            request.execute, backing.local_abspath('subdir'))

    def test_initialized_dir(self):
        """Initializing an extant bzrdir should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.FileExists,
            request.execute, backing.local_abspath('subdir'))


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


class TestSmartServerBranchRequest(tests.TestCaseWithTransport):

    def test_no_branch(self):
        """When there is a bzrdir and no branch, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequest(backing)
        self.make_bzrdir('.')
        self.assertRaises(errors.NotBranchError,
            request.execute, backing.local_abspath(''))

    def test_branch_reference(self):
        """When there is a branch reference, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequest(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        self.assertRaises(errors.NotBranchError,
            request.execute, backing.local_abspath('checkout'))


class TestSmartServerBranchRequestLastRevisionInfo(tests.TestCaseWithTransport):

    def test_empty(self):
        """For an empty branch, the result is ('ok', '0', '')."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLastRevisionInfo(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', '0', '')),
            request.execute(backing.local_abspath('')))

    def test_not_empty(self):
        """For a non-empty branch, the result is ('ok', 'revno', 'revid')."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLastRevisionInfo(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8')
        tree.unlock()
        self.assertEqual(
            SmartServerResponse(('ok', '2', u'\xc8'.encode('utf8'))),
            request.execute(backing.local_abspath('')))


class TestSmartServerBranchRequestGetConfigFile(tests.TestCaseWithTransport):

    def test_default(self):
        """With no file, we get empty content."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        # there should be no file by default
        content = ''
        self.assertEqual(SmartServerResponse(('ok', ), content),
            request.execute(backing.local_abspath('')))

    def test_with_content(self):
        # SmartServerBranchGetConfigFile should return the content from
        # branch.control_files.get('branch.conf') for now - in the future it may
        # perform more complex processing. 
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        branch.control_files.put_utf8('branch.conf', 'foo bar baz')
        self.assertEqual(SmartServerResponse(('ok', ), 'foo bar baz'),
            request.execute(backing.local_abspath('')))


class TestSmartServerBranchRequestSetLastRevision(tests.TestCaseWithTransport):

    def test_empty(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok',)),
            request.execute(backing.local_abspath(''), ''))

    def test_not_present_revision_id(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        self.make_branch('.')
        revision_id = 'non-existent revision'
        self.assertEqual(SmartServerResponse(('NoSuchRevision', revision_id)),
            request.execute(backing.local_abspath(''), revision_id))

    def test_revision_id_present(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit', rev_id=u'\xc8')
        r2 = tree.commit('2nd commit')
        tree.unlock()
        self.assertEqual(
            SmartServerResponse(('ok',)),
            request.execute(backing.local_abspath(''), u'\xc8'.encode('utf8')))
        self.assertEqual([u'\xc8'], tree.branch.revision_history())

    def test_revision_id_present2(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit', rev_id=u'\xc8')
        r2 = tree.commit('2nd commit')
        tree.unlock()
        tree.branch.set_revision_history([])
        self.assertEqual(
            SmartServerResponse(('ok',)),
            request.execute(backing.local_abspath(''), u'\xc8'.encode('utf8')))
        self.assertEqual([u'\xc8'], tree.branch.revision_history())


class TestSmartServerRepositoryRequest(tests.TestCaseWithTransport):

    def test_no_repository(self):
        """Raise NoRepositoryPresent when there is a bzrdir and no repo."""
        # we test this using a shared repository above the named path,
        # thus checking the right search logic is used - that is, that
        # its the exact path being looked at and the server is not
        # searching.
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryRequest(backing)
        self.make_repository('.', shared=True)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.NoRepositoryPresent,
            request.execute, backing.local_abspath('subdir'))


class TestSmartServerRepositoryGetRevisionGraph(tests.TestCaseWithTransport):

    def test_none_argument(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8')
        tree.unlock()

        # the lines of revision_id->revision_parent_list has no guaranteed
        # order coming out of a dict, so sort both our test and response
        lines = sorted([' '.join([r2, r1]), r1])
        response = request.execute(backing.local_abspath(''), '')
        response.body = '\n'.join(sorted(response.body.split('\n')))

        self.assertEqual(SmartServerResponse(('ok', ),
            '\n'.join(lines).encode('utf8')),
            response)

    def test_specific_revision_argument(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit', rev_id=u'\xc9')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8')
        tree.unlock()

        self.assertEqual(SmartServerResponse(('ok', ),
            u'\xc9'.encode('utf8')),
            request.execute(backing.local_abspath(''), u'\xc9'.encode('utf8')))
    
    def test_no_such_revision(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        tree.unlock()

        self.assertEqual(SmartServerResponse(
            ('nosuchrevision', 'missingrevision', )),
            request.execute(backing.local_abspath(''), 'missingrevision'))

class TestSmartServerRequestHasRevision(tests.TestCaseWithTransport):

    def test_missing_revision(self):
        """For a missing revision, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRequestHasRevision(backing)
        self.make_repository('.')
        self.assertEqual(SmartServerResponse(('no', )),
            request.execute(backing.local_abspath(''), 'revid'))

    def test_present_revision(self):
        """For a present revision, ('ok', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRequestHasRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('a commit', rev_id=u'\xc8abc')
        tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(u'\xc8abc'))
        self.assertEqual(SmartServerResponse(('ok', )),
            request.execute(backing.local_abspath(''),
                u'\xc8abc'.encode('utf8')))


class TestSmartServerRepositoryGatherStats(tests.TestCaseWithTransport):

    def test_empty_revid(self):
        """With an empty revid, we get only size an number and revisions"""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        repository = self.make_repository('.')
        stats = repository.gather_stats()
        size = stats['size']
        expected_body = 'revisions: 0\nsize: %d\n' % size
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute(backing.local_abspath(''), '', 'no'))

    def test_revid_with_committers(self):
        """For a revid we get more infos."""
        backing = self.get_transport()
        rev_id = u'\xc8abc'
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600)
        tree.commit('a commit', timestamp=654321.4, timezone=0, rev_id=rev_id)
        tree.unlock()

        stats = tree.branch.repository.gather_stats()
        size = stats['size']
        expected_body = ('firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n'
                         'size: %d\n' % size)
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute(backing.local_abspath(''),
                                         rev_id.encode('utf8'), 'no'))

    def test_not_empty_repository_with_committers(self):
        """For a revid and requesting committers we get the whole thing."""
        backing = self.get_transport()
        rev_id = u'\xc8abc'
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600,
                    committer='foo')
        tree.commit('a commit', timestamp=654321.4, timezone=0,
                    committer='bar', rev_id=rev_id)
        tree.unlock()
        stats = tree.branch.repository.gather_stats()

        size = stats['size']
        expected_body = ('committers: 2\n'
                         'firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n'
                         'size: %d\n' % size)
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute(backing.local_abspath(''),
                                         rev_id.encode('utf8'), 'yes'))


class TestSmartServerRepositoryIsShared(tests.TestCaseWithTransport):

    def test_is_shared(self):
        """For a shared repository, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=True)
        self.assertEqual(SmartServerResponse(('yes', )),
            request.execute(backing.local_abspath(''), ))

    def test_is_not_shared(self):
        """For a shared repository, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=False)
        self.assertEqual(SmartServerResponse(('no', )),
            request.execute(backing.local_abspath(''), ))


class TestHandlers(tests.TestCase):
    """Tests for the request.request_handlers object."""

    def test_registered_methods(self):
        """Test that known methods are registered to the correct object."""
        self.assertEqual(
            smart.request.request_handlers.get('Branch.get_config_file'),
            smart.branch.SmartServerBranchGetConfigFile)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.last_revision_info'),
            smart.branch.SmartServerBranchRequestLastRevisionInfo)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.revision_history'),
            smart.branch.SmartServerRequestRevisionHistory)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.set_last_revision'),
            smart.branch.SmartServerBranchRequestSetLastRevision)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.find_repository'),
            smart.bzrdir.SmartServerRequestFindRepository)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDirFormat.initialize'),
            smart.bzrdir.SmartServerRequestInitializeBzrDir)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.open_branch'),
            smart.bzrdir.SmartServerRequestOpenBranch)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.gather_stats'),
            smart.repository.SmartServerRepositoryGatherStats)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.get_revision_graph'),
            smart.repository.SmartServerRepositoryGetRevisionGraph)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.has_revision'),
            smart.repository.SmartServerRequestHasRevision)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.is_shared'),
            smart.repository.SmartServerRepositoryIsShared)
