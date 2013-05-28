# Copyright (C) 2006-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the smart wire/domain protocol.

This module contains tests for the domain-level smart requests and responses,
such as the 'Branch.lock_write' request. Many of these use specific disk
formats to exercise calls that only make sense for formats with specific
properties.

Tests for low-level protocol encoding are found in test_smart_transport.
"""

import bz2

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    errors,
    tests,
    transport,
    urlutils,
    versionedfile,
    )
from bzrlib.smart import (
    branch as smart_branch,
    bzrdir as smart_dir,
    repository as smart_repo,
    packrepository as smart_packrepo,
    request as smart_req,
    server,
    vfs,
    )
from bzrlib.tests import test_server
from bzrlib.transport import (
    chroot,
    memory,
    )


def load_tests(standard_tests, module, loader):
    """Multiply tests version and protocol consistency."""
    # FindRepository tests.
    scenarios = [
        ("find_repository", {
            "_request_class": smart_dir.SmartServerRequestFindRepositoryV1}),
        ("find_repositoryV2", {
            "_request_class": smart_dir.SmartServerRequestFindRepositoryV2}),
        ("find_repositoryV3", {
            "_request_class": smart_dir.SmartServerRequestFindRepositoryV3}),
        ]
    to_adapt, result = tests.split_suite_by_re(standard_tests,
        "TestSmartServerRequestFindRepository")
    v2_only, v1_and_2 = tests.split_suite_by_re(to_adapt,
        "_v2")
    tests.multiply_tests(v1_and_2, scenarios, result)
    # The first scenario is only applicable to v1 protocols, it is deleted
    # since.
    tests.multiply_tests(v2_only, scenarios[1:], result)
    return result


class TestCaseWithChrootedTransport(tests.TestCaseWithTransport):

    def setUp(self):
        self.vfs_transport_factory = memory.MemoryServer
        tests.TestCaseWithTransport.setUp(self)
        self._chroot_server = None

    def get_transport(self, relpath=None):
        if self._chroot_server is None:
            backing_transport = tests.TestCaseWithTransport.get_transport(self)
            self._chroot_server = chroot.ChrootServer(backing_transport)
            self.start_server(self._chroot_server)
        t = transport.get_transport(self._chroot_server.get_url())
        if relpath is not None:
            t = t.clone(relpath)
        return t


class TestCaseWithSmartMedium(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        super(TestCaseWithSmartMedium, self).setUp()
        # We're allowed to set  the transport class here, so that we don't use
        # the default or a parameterized class, but rather use the
        # TestCaseWithTransport infrastructure to set up a smart server and
        # transport.
        self.overrideAttr(self, "transport_server", self.make_transport_server)

    def make_transport_server(self):
        return test_server.SmartTCPServer_for_testing('-' + self.id())

    def get_smart_medium(self):
        """Get a smart medium to use in tests."""
        return self.get_transport().get_smart_medium()


class TestByteStreamToStream(tests.TestCase):

    def test_repeated_substreams_same_kind_are_one_stream(self):
        # Make a stream - an iterable of bytestrings.
        stream = [('text', [versionedfile.FulltextContentFactory(('k1',), None,
            None, 'foo')]),('text', [
            versionedfile.FulltextContentFactory(('k2',), None, None, 'bar')])]
        fmt = bzrdir.format_registry.get('pack-0.92')().repository_format
        bytes = smart_repo._stream_to_byte_stream(stream, fmt)
        streams = []
        # Iterate the resulting iterable; checking that we get only one stream
        # out.
        fmt, stream = smart_repo._byte_stream_to_stream(bytes)
        for kind, substream in stream:
            streams.append((kind, list(substream)))
        self.assertLength(1, streams)
        self.assertLength(2, streams[0][1])


class TestSmartServerResponse(tests.TestCase):

    def test__eq__(self):
        self.assertEqual(smart_req.SmartServerResponse(('ok', )),
            smart_req.SmartServerResponse(('ok', )))
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), 'body'),
            smart_req.SmartServerResponse(('ok', ), 'body'))
        self.assertNotEqual(smart_req.SmartServerResponse(('ok', )),
            smart_req.SmartServerResponse(('notok', )))
        self.assertNotEqual(smart_req.SmartServerResponse(('ok', ), 'body'),
            smart_req.SmartServerResponse(('ok', )))
        self.assertNotEqual(None,
            smart_req.SmartServerResponse(('ok', )))

    def test__str__(self):
        """SmartServerResponses can be stringified."""
        self.assertEqual(
            "<SuccessfulSmartServerResponse args=('args',) body='body'>",
            str(smart_req.SuccessfulSmartServerResponse(('args',), 'body')))
        self.assertEqual(
            "<FailedSmartServerResponse args=('args',) body='body'>",
            str(smart_req.FailedSmartServerResponse(('args',), 'body')))


class TestSmartServerRequest(tests.TestCaseWithMemoryTransport):

    def test_translate_client_path(self):
        transport = self.get_transport()
        request = smart_req.SmartServerRequest(transport, 'foo/')
        self.assertEqual('./', request.translate_client_path('foo/'))
        self.assertRaises(
            errors.InvalidURLJoin, request.translate_client_path, 'foo/..')
        self.assertRaises(
            errors.PathNotChild, request.translate_client_path, '/')
        self.assertRaises(
            errors.PathNotChild, request.translate_client_path, 'bar/')
        self.assertEqual('./baz', request.translate_client_path('foo/baz'))
        e_acute = u'\N{LATIN SMALL LETTER E WITH ACUTE}'.encode('utf-8')
        self.assertEqual('./' + urlutils.escape(e_acute),
                         request.translate_client_path('foo/' + e_acute))

    def test_translate_client_path_vfs(self):
        """VfsRequests receive escaped paths rather than raw UTF-8."""
        transport = self.get_transport()
        request = vfs.VfsRequest(transport, 'foo/')
        e_acute = u'\N{LATIN SMALL LETTER E WITH ACUTE}'.encode('utf-8')
        escaped = urlutils.escape('foo/' + e_acute)
        self.assertEqual('./' + urlutils.escape(e_acute),
                         request.translate_client_path(escaped))

    def test_transport_from_client_path(self):
        transport = self.get_transport()
        request = smart_req.SmartServerRequest(transport, 'foo/')
        self.assertEqual(
            transport.base,
            request.transport_from_client_path('foo/').base)


class TestSmartServerBzrDirRequestCloningMetaDir(
    tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.cloning_metadir."""

    def test_cloning_metadir(self):
        """When there is a bzrdir present, the call succeeds."""
        backing = self.get_transport()
        dir = self.make_bzrdir('.')
        local_result = dir.cloning_metadir()
        request_class = smart_dir.SmartServerBzrDirRequestCloningMetaDir
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse(
            (local_result.network_name(),
            local_result.repository_format.network_name(),
            ('branch', local_result.get_branch_format().network_name())))
        self.assertEqual(expected, request.execute('', 'False'))

    def test_cloning_metadir_reference(self):
        """The request fails when bzrdir contains a branch reference."""
        backing = self.get_transport()
        referenced_branch = self.make_branch('referenced')
        dir = self.make_bzrdir('.')
        local_result = dir.cloning_metadir()
        reference = _mod_branch.BranchReferenceFormat().initialize(
            dir, target_branch=referenced_branch)
        reference_url = _mod_branch.BranchReferenceFormat().get_reference(dir)
        # The server shouldn't try to follow the branch reference, so it's fine
        # if the referenced branch isn't reachable.
        backing.rename('referenced', 'moved')
        request_class = smart_dir.SmartServerBzrDirRequestCloningMetaDir
        request = request_class(backing)
        expected = smart_req.FailedSmartServerResponse(('BranchReference',))
        self.assertEqual(expected, request.execute('', 'False'))


class TestSmartServerRequestCreateRepository(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.create_repository."""

    def test_makes_repository(self):
        """When there is a bzrdir present, the call succeeds."""
        backing = self.get_transport()
        self.make_bzrdir('.')
        request_class = smart_dir.SmartServerRequestCreateRepository
        request = request_class(backing)
        reference_bzrdir_format = bzrdir.format_registry.get('pack-0.92')()
        reference_format = reference_bzrdir_format.repository_format
        network_name = reference_format.network_name()
        expected = smart_req.SuccessfulSmartServerResponse(
            ('ok', 'no', 'no', 'no', network_name))
        self.assertEqual(expected, request.execute('', network_name, 'True'))


class TestSmartServerRequestFindRepository(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.find_repository."""

    def test_no_repository(self):
        """When there is no repository to be found, ('norepository', ) is returned."""
        backing = self.get_transport()
        request = self._request_class(backing)
        self.make_bzrdir('.')
        self.assertEqual(smart_req.SmartServerResponse(('norepository', )),
            request.execute(''))

    def test_nonshared_repository(self):
        # nonshared repositorys only allow 'find' to return a handle when the
        # path the repository is being searched on is the same as that that
        # the repository is at.
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result()
        self.assertEqual(result, request.execute(''))
        self.make_bzrdir('subdir')
        self.assertEqual(smart_req.SmartServerResponse(('norepository', )),
            request.execute('subdir'))

    def _make_repository_and_result(self, shared=False, format=None):
        """Convenience function to setup a repository.

        :result: The SmartServerResponse to expect when opening it.
        """
        repo = self.make_repository('.', shared=shared, format=format)
        if repo.supports_rich_root():
            rich_root = 'yes'
        else:
            rich_root = 'no'
        if repo._format.supports_tree_reference:
            subtrees = 'yes'
        else:
            subtrees = 'no'
        if repo._format.supports_external_lookups:
            external = 'yes'
        else:
            external = 'no'
        if (smart_dir.SmartServerRequestFindRepositoryV3 ==
            self._request_class):
            return smart_req.SuccessfulSmartServerResponse(
                ('ok', '', rich_root, subtrees, external,
                 repo._format.network_name()))
        elif (smart_dir.SmartServerRequestFindRepositoryV2 ==
            self._request_class):
            # All tests so far are on formats, and for non-external
            # repositories.
            return smart_req.SuccessfulSmartServerResponse(
                ('ok', '', rich_root, subtrees, external))
        else:
            return smart_req.SuccessfulSmartServerResponse(
                ('ok', '', rich_root, subtrees))

    def test_shared_repository(self):
        """When there is a shared repository, we get 'ok', 'relpath-to-repo'."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(shared=True)
        self.assertEqual(result, request.execute(''))
        self.make_bzrdir('subdir')
        result2 = smart_req.SmartServerResponse(
            result.args[0:1] + ('..', ) + result.args[2:])
        self.assertEqual(result2,
            request.execute('subdir'))
        self.make_bzrdir('subdir/deeper')
        result3 = smart_req.SmartServerResponse(
            result.args[0:1] + ('../..', ) + result.args[2:])
        self.assertEqual(result3,
            request.execute('subdir/deeper'))

    def test_rich_root_and_subtree_encoding(self):
        """Test for the format attributes for rich root and subtree support."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(
            format='dirstate-with-subtree')
        # check the test will be valid
        self.assertEqual('yes', result.args[2])
        self.assertEqual('yes', result.args[3])
        self.assertEqual(result, request.execute(''))

    def test_supports_external_lookups_no_v2(self):
        """Test for the supports_external_lookups attribute."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(
            format='dirstate-with-subtree')
        # check the test will be valid
        self.assertEqual('no', result.args[4])
        self.assertEqual(result, request.execute(''))


class TestSmartServerBzrDirRequestGetConfigFile(
    tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.get_config_file."""

    def test_present(self):
        backing = self.get_transport()
        dir = self.make_bzrdir('.')
        dir.get_config().set_default_stack_on("/")
        local_result = dir._get_config()._get_config_file().read()
        request_class = smart_dir.SmartServerBzrDirRequestConfigFile
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((), local_result)
        self.assertEqual(expected, request.execute(''))

    def test_missing(self):
        backing = self.get_transport()
        dir = self.make_bzrdir('.')
        request_class = smart_dir.SmartServerBzrDirRequestConfigFile
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((), '')
        self.assertEqual(expected, request.execute(''))


class TestSmartServerRequestInitializeBzrDir(tests.TestCaseWithMemoryTransport):

    def test_empty_dir(self):
        """Initializing an empty dir should succeed and do it."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestInitializeBzrDir(backing)
        self.assertEqual(smart_req.SmartServerResponse(('ok', )),
            request.execute(''))
        made_dir = bzrdir.BzrDir.open_from_transport(backing)
        # no branch, tree or repository is expected with the current
        # default formart.
        self.assertRaises(errors.NoWorkingTree, made_dir.open_workingtree)
        self.assertRaises(errors.NotBranchError, made_dir.open_branch)
        self.assertRaises(errors.NoRepositoryPresent, made_dir.open_repository)

    def test_missing_dir(self):
        """Initializing a missing directory should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestInitializeBzrDir(backing)
        self.assertRaises(errors.NoSuchFile,
            request.execute, 'subdir')

    def test_initialized_dir(self):
        """Initializing an extant bzrdir should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestInitializeBzrDir(backing)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.FileExists,
            request.execute, 'subdir')


class TestSmartServerRequestBzrDirInitializeEx(
    tests.TestCaseWithMemoryTransport):
    """Basic tests for BzrDir.initialize_ex_1.16 in the smart server.

    The main unit tests in test_bzrdir exercise the API comprehensively.
    """

    def test_empty_dir(self):
        """Initializing an empty dir should succeed and do it."""
        backing = self.get_transport()
        name = self.make_bzrdir('reference')._format.network_name()
        request = smart_dir.SmartServerRequestBzrDirInitializeEx(backing)
        self.assertEqual(
            smart_req.SmartServerResponse(('', '', '', '', '', '', name,
                                           'False', '', '', '')),
            request.execute(name, '', 'True', 'False', 'False', '', '', '', '',
                            'False'))
        made_dir = bzrdir.BzrDir.open_from_transport(backing)
        # no branch, tree or repository is expected with the current
        # default format.
        self.assertRaises(errors.NoWorkingTree, made_dir.open_workingtree)
        self.assertRaises(errors.NotBranchError, made_dir.open_branch)
        self.assertRaises(errors.NoRepositoryPresent, made_dir.open_repository)

    def test_missing_dir(self):
        """Initializing a missing directory should fail like the bzrdir api."""
        backing = self.get_transport()
        name = self.make_bzrdir('reference')._format.network_name()
        request = smart_dir.SmartServerRequestBzrDirInitializeEx(backing)
        self.assertRaises(errors.NoSuchFile, request.execute, name,
            'subdir/dir', 'False', 'False', 'False', '', '', '', '', 'False')

    def test_initialized_dir(self):
        """Initializing an extant directory should fail like the bzrdir api."""
        backing = self.get_transport()
        name = self.make_bzrdir('reference')._format.network_name()
        request = smart_dir.SmartServerRequestBzrDirInitializeEx(backing)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.FileExists, request.execute, name, 'subdir',
            'False', 'False', 'False', '', '', '', '', 'False')


class TestSmartServerRequestOpenBzrDir(tests.TestCaseWithMemoryTransport):

    def test_no_directory(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir(backing)
        self.assertEqual(smart_req.SmartServerResponse(('no', )),
            request.execute('does-not-exist'))

    def test_empty_directory(self):
        backing = self.get_transport()
        backing.mkdir('empty')
        request = smart_dir.SmartServerRequestOpenBzrDir(backing)
        self.assertEqual(smart_req.SmartServerResponse(('no', )),
            request.execute('empty'))

    def test_outside_root_client_path(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir(backing,
            root_client_path='root')
        self.assertEqual(smart_req.SmartServerResponse(('no', )),
            request.execute('not-root'))


class TestSmartServerRequestOpenBzrDir_2_1(tests.TestCaseWithMemoryTransport):

    def test_no_directory(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        self.assertEqual(smart_req.SmartServerResponse(('no', )),
            request.execute('does-not-exist'))

    def test_empty_directory(self):
        backing = self.get_transport()
        backing.mkdir('empty')
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        self.assertEqual(smart_req.SmartServerResponse(('no', )),
            request.execute('empty'))

    def test_present_without_workingtree(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        self.make_bzrdir('.')
        self.assertEqual(smart_req.SmartServerResponse(('yes', 'no')),
            request.execute(''))

    def test_outside_root_client_path(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing,
            root_client_path='root')
        self.assertEqual(smart_req.SmartServerResponse(('no',)),
            request.execute('not-root'))


class TestSmartServerRequestOpenBzrDir_2_1_disk(TestCaseWithChrootedTransport):

    def test_present_with_workingtree(self):
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        bd = self.make_bzrdir('.')
        bd.create_repository()
        bd.create_branch()
        bd.create_workingtree()
        self.assertEqual(smart_req.SmartServerResponse(('yes', 'yes')),
            request.execute(''))


class TestSmartServerRequestOpenBranch(TestCaseWithChrootedTransport):

    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        self.make_bzrdir('.')
        self.assertEqual(smart_req.SmartServerResponse(('nobranch', )),
            request.execute(''))

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        self.make_branch('.')
        self.assertEqual(smart_req.SmartServerResponse(('ok', '')),
            request.execute(''))

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        reference_url = _mod_branch.BranchReferenceFormat().get_reference(
            checkout.bzrdir)
        self.assertFileEqual(reference_url, 'reference/.bzr/branch/location')
        self.assertEqual(smart_req.SmartServerResponse(('ok', reference_url)),
            request.execute('reference'))

    def test_notification_on_branch_from_repository(self):
        """When there is a repository, the error should return details."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        repo = self.make_repository('.')
        self.assertEqual(smart_req.SmartServerResponse(('nobranch',)),
            request.execute(''))


class TestSmartServerRequestOpenBranchV2(TestCaseWithChrootedTransport):

    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        self.make_bzrdir('.')
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        self.assertEqual(smart_req.SmartServerResponse(('nobranch', )),
            request.execute(''))

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        expected = self.make_branch('.')._format.network_name()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(
                ('branch', expected)),
                         request.execute(''))

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        reference_url = _mod_branch.BranchReferenceFormat().get_reference(
            checkout.bzrdir)
        self.assertFileEqual(reference_url, 'reference/.bzr/branch/location')
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(
                ('ref', reference_url)),
                         request.execute('reference'))

    def test_stacked_branch(self):
        """Opening a stacked branch does not open the stacked-on branch."""
        trunk = self.make_branch('trunk')
        feature = self.make_branch('feature')
        feature.set_stacked_on_url(trunk.base)
        opened_branches = []
        _mod_branch.Branch.hooks.install_named_hook(
            'open', opened_branches.append, None)
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        request.setup_jail()
        try:
            response = request.execute('feature')
        finally:
            request.teardown_jail()
        expected_format = feature._format.network_name()
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(
                ('branch', expected_format)),
                         response)
        self.assertLength(1, opened_branches)

    def test_notification_on_branch_from_repository(self):
        """When there is a repository, the error should return details."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        repo = self.make_repository('.')
        self.assertEqual(smart_req.SmartServerResponse(('nobranch',)),
            request.execute(''))


class TestSmartServerRequestOpenBranchV3(TestCaseWithChrootedTransport):

    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        self.make_bzrdir('.')
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        self.assertEqual(smart_req.SmartServerResponse(('nobranch',)),
            request.execute(''))

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        expected = self.make_branch('.')._format.network_name()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(
                ('branch', expected)),
                         request.execute(''))

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        reference_url = _mod_branch.BranchReferenceFormat().get_reference(
            checkout.bzrdir)
        self.assertFileEqual(reference_url, 'reference/.bzr/branch/location')
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(
                ('ref', reference_url)),
                         request.execute('reference'))

    def test_stacked_branch(self):
        """Opening a stacked branch does not open the stacked-on branch."""
        trunk = self.make_branch('trunk')
        feature = self.make_branch('feature')
        feature.set_stacked_on_url(trunk.base)
        opened_branches = []
        _mod_branch.Branch.hooks.install_named_hook(
            'open', opened_branches.append, None)
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        request.setup_jail()
        try:
            response = request.execute('feature')
        finally:
            request.teardown_jail()
        expected_format = feature._format.network_name()
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(
                ('branch', expected_format)),
                         response)
        self.assertLength(1, opened_branches)

    def test_notification_on_branch_from_repository(self):
        """When there is a repository, the error should return details."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        repo = self.make_repository('.')
        self.assertEqual(smart_req.SmartServerResponse(
                ('nobranch', 'location is a repository')),
                         request.execute(''))


class TestSmartServerRequestRevisionHistory(tests.TestCaseWithMemoryTransport):

    def test_empty(self):
        """For an empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart_branch.SmartServerRequestRevisionHistory(backing)
        self.make_branch('.')
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), ''),
            request.execute(''))

    def test_not_empty(self):
        """For a non-empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart_branch.SmartServerRequestRevisionHistory(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()
        self.assertEqual(
            smart_req.SmartServerResponse(('ok', ), ('\x00'.join([r1, r2]))),
            request.execute(''))


class TestSmartServerBranchRequest(tests.TestCaseWithMemoryTransport):

    def test_no_branch(self):
        """When there is a bzrdir and no branch, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequest(backing)
        self.make_bzrdir('.')
        self.assertRaises(errors.NotBranchError,
            request.execute, '')

    def test_branch_reference(self):
        """When there is a branch reference, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequest(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        self.assertRaises(errors.NotBranchError,
            request.execute, 'checkout')


class TestSmartServerBranchRequestLastRevisionInfo(
    tests.TestCaseWithMemoryTransport):

    def test_empty(self):
        """For an empty branch, the result is ('ok', '0', 'null:')."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLastRevisionInfo(backing)
        self.make_branch('.')
        self.assertEqual(smart_req.SmartServerResponse(('ok', '0', 'null:')),
            request.execute(''))

    def test_not_empty(self):
        """For a non-empty branch, the result is ('ok', 'revno', 'revid')."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLastRevisionInfo(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=rev_id_utf8)
        tree.unlock()
        self.assertEqual(
            smart_req.SmartServerResponse(('ok', '2', rev_id_utf8)),
            request.execute(''))


class TestSmartServerBranchRequestGetConfigFile(
    tests.TestCaseWithMemoryTransport):

    def test_default(self):
        """With no file, we get empty content."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        # there should be no file by default
        content = ''
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), content),
            request.execute(''))

    def test_with_content(self):
        # SmartServerBranchGetConfigFile should return the content from
        # branch.control_files.get('branch.conf') for now - in the future it may
        # perform more complex processing.
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        branch._transport.put_bytes('branch.conf', 'foo bar baz')
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), 'foo bar baz'),
            request.execute(''))


class TestLockedBranch(tests.TestCaseWithMemoryTransport):

    def get_lock_tokens(self, branch):
        branch_token = branch.lock_write().branch_token
        repo_token = branch.repository.lock_write().repository_token
        branch.repository.unlock()
        return branch_token, repo_token


class TestSmartServerBranchRequestSetConfigOption(TestLockedBranch):

    def test_value_name(self):
        branch = self.make_branch('.')
        request = smart_branch.SmartServerBranchRequestSetConfigOption(
            branch.bzrdir.root_transport)
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute('', branch_token, repo_token, 'bar', 'foo',
            '')
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual('bar', config.get_option('foo'))
        # Cleanup
        branch.unlock()

    def test_value_name_section(self):
        branch = self.make_branch('.')
        request = smart_branch.SmartServerBranchRequestSetConfigOption(
            branch.bzrdir.root_transport)
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute('', branch_token, repo_token, 'bar', 'foo',
            'gam')
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual('bar', config.get_option('foo', 'gam'))
        # Cleanup
        branch.unlock()


class TestSmartServerBranchRequestSetConfigOptionDict(TestLockedBranch):

    def setUp(self):
        TestLockedBranch.setUp(self)
        # A dict with non-ascii keys and values to exercise unicode
        # roundtripping.
        self.encoded_value_dict = (
            'd5:ascii1:a11:unicode \xe2\x8c\x9a3:\xe2\x80\xbde')
        self.value_dict = {
            'ascii': 'a', u'unicode \N{WATCH}': u'\N{INTERROBANG}'}

    def test_value_name(self):
        branch = self.make_branch('.')
        request = smart_branch.SmartServerBranchRequestSetConfigOptionDict(
            branch.bzrdir.root_transport)
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute('', branch_token, repo_token,
            self.encoded_value_dict, 'foo', '')
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual(self.value_dict, config.get_option('foo'))
        # Cleanup
        branch.unlock()

    def test_value_name_section(self):
        branch = self.make_branch('.')
        request = smart_branch.SmartServerBranchRequestSetConfigOptionDict(
            branch.bzrdir.root_transport)
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute('', branch_token, repo_token,
            self.encoded_value_dict, 'foo', 'gam')
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual(self.value_dict, config.get_option('foo', 'gam'))
        # Cleanup
        branch.unlock()


class TestSmartServerBranchRequestSetTagsBytes(TestLockedBranch):
    # Only called when the branch format and tags match [yay factory
    # methods] so only need to test straight forward cases.

    def test_set_bytes(self):
        base_branch = self.make_branch('base')
        tag_bytes = base_branch._get_tags_bytes()
        # get_lock_tokens takes out a lock.
        branch_token, repo_token = self.get_lock_tokens(base_branch)
        request = smart_branch.SmartServerBranchSetTagsBytes(
            self.get_transport())
        response = request.execute('base', branch_token, repo_token)
        self.assertEqual(None, response)
        response = request.do_chunk(tag_bytes)
        self.assertEqual(None, response)
        response = request.do_end()
        self.assertEquals(
            smart_req.SuccessfulSmartServerResponse(()), response)
        base_branch.unlock()

    def test_lock_failed(self):
        base_branch = self.make_branch('base')
        base_branch.lock_write()
        tag_bytes = base_branch._get_tags_bytes()
        request = smart_branch.SmartServerBranchSetTagsBytes(
            self.get_transport())
        self.assertRaises(errors.TokenMismatch, request.execute,
            'base', 'wrong token', 'wrong token')
        # The request handler will keep processing the message parts, so even
        # if the request fails immediately do_chunk and do_end are still
        # called.
        request.do_chunk(tag_bytes)
        request.do_end()
        base_branch.unlock()



class SetLastRevisionTestBase(TestLockedBranch):
    """Base test case for verbs that implement set_last_revision."""

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)
        backing_transport = self.get_transport()
        self.request = self.request_class(backing_transport)
        self.tree = self.make_branch_and_memory_tree('.')

    def lock_branch(self):
        return self.get_lock_tokens(self.tree.branch)

    def unlock_branch(self):
        self.tree.branch.unlock()

    def set_last_revision(self, revision_id, revno):
        branch_token, repo_token = self.lock_branch()
        response = self._set_last_revision(
            revision_id, revno, branch_token, repo_token)
        self.unlock_branch()
        return response

    def assertRequestSucceeds(self, revision_id, revno):
        response = self.set_last_revision(revision_id, revno)
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(('ok',)),
                         response)


class TestSetLastRevisionVerbMixin(object):
    """Mixin test case for verbs that implement set_last_revision."""

    def test_set_null_to_null(self):
        """An empty branch can have its last revision set to 'null:'."""
        self.assertRequestSucceeds('null:', 0)

    def test_NoSuchRevision(self):
        """If the revision_id is not present, the verb returns NoSuchRevision.
        """
        revision_id = 'non-existent revision'
        self.assertEqual(smart_req.FailedSmartServerResponse(('NoSuchRevision',
                                                              revision_id)),
                         self.set_last_revision(revision_id, 1))

    def make_tree_with_two_commits(self):
        self.tree.lock_write()
        self.tree.add('')
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        r1 = self.tree.commit('1st commit', rev_id=rev_id_utf8)
        r2 = self.tree.commit('2nd commit', rev_id='rev-2')
        self.tree.unlock()

    def test_branch_last_revision_info_is_updated(self):
        """A branch's tip can be set to a revision that is present in its
        repository.
        """
        # Make a branch with an empty revision history, but two revisions in
        # its repository.
        self.make_tree_with_two_commits()
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        self.tree.branch.set_last_revision_info(0, 'null:')
        self.assertEqual(
            (0, 'null:'), self.tree.branch.last_revision_info())
        # We can update the branch to a revision that is present in the
        # repository.
        self.assertRequestSucceeds(rev_id_utf8, 1)
        self.assertEqual(
            (1, rev_id_utf8), self.tree.branch.last_revision_info())

    def test_branch_last_revision_info_rewind(self):
        """A branch's tip can be set to a revision that is an ancestor of the
        current tip.
        """
        self.make_tree_with_two_commits()
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        self.assertEqual(
            (2, 'rev-2'), self.tree.branch.last_revision_info())
        self.assertRequestSucceeds(rev_id_utf8, 1)
        self.assertEqual(
            (1, rev_id_utf8), self.tree.branch.last_revision_info())

    def test_TipChangeRejected(self):
        """If a pre_change_branch_tip hook raises TipChangeRejected, the verb
        returns TipChangeRejected.
        """
        rejection_message = u'rejection message\N{INTERROBANG}'
        def hook_that_rejects(params):
            raise errors.TipChangeRejected(rejection_message)
        _mod_branch.Branch.hooks.install_named_hook(
            'pre_change_branch_tip', hook_that_rejects, None)
        self.assertEqual(
            smart_req.FailedSmartServerResponse(
                ('TipChangeRejected', rejection_message.encode('utf-8'))),
            self.set_last_revision('null:', 0))


class TestSmartServerBranchRequestSetLastRevision(
        SetLastRevisionTestBase, TestSetLastRevisionVerbMixin):
    """Tests for Branch.set_last_revision verb."""

    request_class = smart_branch.SmartServerBranchRequestSetLastRevision

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(
            '', branch_token, repo_token, revision_id)


class TestSmartServerBranchRequestSetLastRevisionInfo(
        SetLastRevisionTestBase, TestSetLastRevisionVerbMixin):
    """Tests for Branch.set_last_revision_info verb."""

    request_class = smart_branch.SmartServerBranchRequestSetLastRevisionInfo

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(
            '', branch_token, repo_token, revno, revision_id)

    def test_NoSuchRevision(self):
        """Branch.set_last_revision_info does not have to return
        NoSuchRevision if the revision_id is absent.
        """
        raise tests.TestNotApplicable()


class TestSmartServerBranchRequestSetLastRevisionEx(
        SetLastRevisionTestBase, TestSetLastRevisionVerbMixin):
    """Tests for Branch.set_last_revision_ex verb."""

    request_class = smart_branch.SmartServerBranchRequestSetLastRevisionEx

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(
            '', branch_token, repo_token, revision_id, 0, 0)

    def assertRequestSucceeds(self, revision_id, revno):
        response = self.set_last_revision(revision_id, revno)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(('ok', revno, revision_id)),
            response)

    def test_branch_last_revision_info_rewind(self):
        """A branch's tip can be set to a revision that is an ancestor of the
        current tip, but only if allow_overwrite_descendant is passed.
        """
        self.make_tree_with_two_commits()
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        self.assertEqual(
            (2, 'rev-2'), self.tree.branch.last_revision_info())
        # If allow_overwrite_descendant flag is 0, then trying to set the tip
        # to an older revision ID has no effect.
        branch_token, repo_token = self.lock_branch()
        response = self.request.execute(
            '', branch_token, repo_token, rev_id_utf8, 0, 0)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(('ok', 2, 'rev-2')),
            response)
        self.assertEqual(
            (2, 'rev-2'), self.tree.branch.last_revision_info())

        # If allow_overwrite_descendant flag is 1, then setting the tip to an
        # ancestor works.
        response = self.request.execute(
            '', branch_token, repo_token, rev_id_utf8, 0, 1)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(('ok', 1, rev_id_utf8)),
            response)
        self.unlock_branch()
        self.assertEqual(
            (1, rev_id_utf8), self.tree.branch.last_revision_info())

    def make_branch_with_divergent_history(self):
        """Make a branch with divergent history in its repo.

        The branch's tip will be 'child-2', and the repo will also contain
        'child-1', which diverges from a common base revision.
        """
        self.tree.lock_write()
        self.tree.add('')
        r1 = self.tree.commit('1st commit')
        revno_1, revid_1 = self.tree.branch.last_revision_info()
        r2 = self.tree.commit('2nd commit', rev_id='child-1')
        # Undo the second commit
        self.tree.branch.set_last_revision_info(revno_1, revid_1)
        self.tree.set_parent_ids([revid_1])
        # Make a new second commit, child-2.  child-2 has diverged from
        # child-1.
        new_r2 = self.tree.commit('2nd commit', rev_id='child-2')
        self.tree.unlock()

    def test_not_allow_diverged(self):
        """If allow_diverged is not passed, then setting a divergent history
        returns a Diverged error.
        """
        self.make_branch_with_divergent_history()
        self.assertEqual(
            smart_req.FailedSmartServerResponse(('Diverged',)),
            self.set_last_revision('child-1', 2))
        # The branch tip was not changed.
        self.assertEqual('child-2', self.tree.branch.last_revision())

    def test_allow_diverged(self):
        """If allow_diverged is passed, then setting a divergent history
        succeeds.
        """
        self.make_branch_with_divergent_history()
        branch_token, repo_token = self.lock_branch()
        response = self.request.execute(
            '', branch_token, repo_token, 'child-1', 1, 0)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(('ok', 2, 'child-1')),
            response)
        self.unlock_branch()
        # The branch tip was changed.
        self.assertEqual('child-1', self.tree.branch.last_revision())


class TestSmartServerBranchRequestGetParent(tests.TestCaseWithMemoryTransport):

    def test_get_parent_none(self):
        base_branch = self.make_branch('base')
        request = smart_branch.SmartServerBranchGetParent(self.get_transport())
        response = request.execute('base')
        self.assertEquals(
            smart_req.SuccessfulSmartServerResponse(('',)), response)

    def test_get_parent_something(self):
        base_branch = self.make_branch('base')
        base_branch.set_parent(self.get_url('foo'))
        request = smart_branch.SmartServerBranchGetParent(self.get_transport())
        response = request.execute('base')
        self.assertEquals(
            smart_req.SuccessfulSmartServerResponse(("../foo",)),
            response)


class TestSmartServerBranchRequestSetParent(TestLockedBranch):

    def test_set_parent_none(self):
        branch = self.make_branch('base', format="1.9")
        branch.lock_write()
        branch._set_parent_location('foo')
        branch.unlock()
        request = smart_branch.SmartServerBranchRequestSetParentLocation(
            self.get_transport())
        branch_token, repo_token = self.get_lock_tokens(branch)
        try:
            response = request.execute('base', branch_token, repo_token, '')
        finally:
            branch.unlock()
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), response)
        self.assertEqual(None, branch.get_parent())

    def test_set_parent_something(self):
        branch = self.make_branch('base', format="1.9")
        request = smart_branch.SmartServerBranchRequestSetParentLocation(
            self.get_transport())
        branch_token, repo_token = self.get_lock_tokens(branch)
        try:
            response = request.execute('base', branch_token, repo_token,
            'http://bar/')
        finally:
            branch.unlock()
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), response)
        self.assertEqual('http://bar/', branch.get_parent())


class TestSmartServerBranchRequestGetTagsBytes(
    tests.TestCaseWithMemoryTransport):
    # Only called when the branch format and tags match [yay factory
    # methods] so only need to test straight forward cases.

    def test_get_bytes(self):
        base_branch = self.make_branch('base')
        request = smart_branch.SmartServerBranchGetTagsBytes(
            self.get_transport())
        response = request.execute('base')
        self.assertEquals(
            smart_req.SuccessfulSmartServerResponse(('',)), response)


class TestSmartServerBranchRequestGetStackedOnURL(tests.TestCaseWithMemoryTransport):

    def test_get_stacked_on_url(self):
        base_branch = self.make_branch('base', format='1.6')
        stacked_branch = self.make_branch('stacked', format='1.6')
        # typically should be relative
        stacked_branch.set_stacked_on_url('../base')
        request = smart_branch.SmartServerBranchRequestGetStackedOnURL(
            self.get_transport())
        response = request.execute('stacked')
        self.assertEquals(
            smart_req.SmartServerResponse(('ok', '../base')),
            response)


class TestSmartServerBranchRequestLockWrite(TestLockedBranch):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)

    def test_lock_write_on_unlocked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        repository = branch.repository
        response = request.execute('')
        branch_nonce = branch.control_files._lock.peek().get('nonce')
        repository_nonce = repository.control_files._lock.peek().get('nonce')
        self.assertEqual(smart_req.SmartServerResponse(
                ('ok', branch_nonce, repository_nonce)),
                         response)
        # The branch (and associated repository) is now locked.  Verify that
        # with a new branch object.
        new_branch = repository.bzrdir.open_branch()
        self.assertRaises(errors.LockContention, new_branch.lock_write)
        # Cleanup
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        response = request.execute('', branch_nonce, repository_nonce)

    def test_lock_write_on_locked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.')
        branch_token = branch.lock_write().branch_token
        branch.leave_lock_in_place()
        branch.unlock()
        response = request.execute('')
        self.assertEqual(
            smart_req.SmartServerResponse(('LockContention',)), response)
        # Cleanup
        branch.lock_write(branch_token)
        branch.dont_leave_lock_in_place()
        branch.unlock()

    def test_lock_write_with_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch_token, repo_token = self.get_lock_tokens(branch)
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute('',
                                   branch_token, repo_token)
        self.assertEqual(
            smart_req.SmartServerResponse(('ok', branch_token, repo_token)),
            response)
        # Cleanup
        branch.repository.lock_write(repo_token)
        branch.repository.dont_leave_lock_in_place()
        branch.repository.unlock()
        branch.lock_write(branch_token)
        branch.dont_leave_lock_in_place()
        branch.unlock()

    def test_lock_write_with_mismatched_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch_token, repo_token = self.get_lock_tokens(branch)
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute('',
                                   branch_token+'xxx', repo_token)
        self.assertEqual(
            smart_req.SmartServerResponse(('TokenMismatch',)), response)
        # Cleanup
        branch.repository.lock_write(repo_token)
        branch.repository.dont_leave_lock_in_place()
        branch.repository.unlock()
        branch.lock_write(branch_token)
        branch.dont_leave_lock_in_place()
        branch.unlock()

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        repo = branch.repository
        repo_token = repo.lock_write().repository_token
        repo.leave_lock_in_place()
        repo.unlock()
        response = request.execute('')
        self.assertEqual(
            smart_req.SmartServerResponse(('LockContention',)), response)
        # Cleanup
        repo.lock_write(repo_token)
        repo.dont_leave_lock_in_place()
        repo.unlock()

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.')
        root = self.get_transport().clone('/')
        path = urlutils.relative_url(root.base, self.get_transport().base)
        response = request.execute(path)
        error_name, lock_str, why_str = response.args
        self.assertFalse(response.is_successful())
        self.assertEqual('LockFailed', error_name)


class TestSmartServerBranchRequestUnlock(TestLockedBranch):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)

    def test_unlock_on_locked_branch_and_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        # Lock the branch
        branch_token, repo_token = self.get_lock_tokens(branch)
        # Unlock the branch (and repo) object, leaving the physical locks
        # in place.
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute('',
                                   branch_token, repo_token)
        self.assertEqual(
            smart_req.SmartServerResponse(('ok',)), response)
        # The branch is now unlocked.  Verify that with a new branch
        # object.
        new_branch = branch.bzrdir.open_branch()
        new_branch.lock_write()
        new_branch.unlock()

    def test_unlock_on_unlocked_branch_unlocked_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        response = request.execute(
            '', 'branch token', 'repo token')
        self.assertEqual(
            smart_req.SmartServerResponse(('TokenMismatch',)), response)

    def test_unlock_on_unlocked_branch_locked_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        # Lock the repository.
        repo_token = branch.repository.lock_write().repository_token
        branch.repository.leave_lock_in_place()
        branch.repository.unlock()
        # Issue branch lock_write request on the unlocked branch (with locked
        # repo).
        response = request.execute('', 'branch token', repo_token)
        self.assertEqual(
            smart_req.SmartServerResponse(('TokenMismatch',)), response)
        # Cleanup
        branch.repository.lock_write(repo_token)
        branch.repository.dont_leave_lock_in_place()
        branch.repository.unlock()


class TestSmartServerRepositoryRequest(tests.TestCaseWithMemoryTransport):

    def test_no_repository(self):
        """Raise NoRepositoryPresent when there is a bzrdir and no repo."""
        # we test this using a shared repository above the named path,
        # thus checking the right search logic is used - that is, that
        # its the exact path being looked at and the server is not
        # searching.
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryRequest(backing)
        self.make_repository('.', shared=True)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.NoRepositoryPresent,
            request.execute, 'subdir')


class TestSmartServerRepositoryGetParentMap(tests.TestCaseWithMemoryTransport):

    def test_trivial_bzipped(self):
        # This tests that the wire encoding is actually bzipped
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetParentMap(backing)
        tree = self.make_branch_and_memory_tree('.')

        self.assertEqual(None,
            request.execute('', 'missing-id'))
        # Note that it returns a body that is bzipped.
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(('ok', ), bz2.compress('')),
            request.do_body('\n\n0\n'))

    def test_trivial_include_missing(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetParentMap(backing)
        tree = self.make_branch_and_memory_tree('.')

        self.assertEqual(None,
            request.execute('', 'missing-id', 'include-missing:'))
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(('ok', ),
                bz2.compress('missing:missing-id')),
            request.do_body('\n\n0\n'))


class TestSmartServerRepositoryGetRevisionGraph(
    tests.TestCaseWithMemoryTransport):

    def test_none_argument(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()

        # the lines of revision_id->revision_parent_list has no guaranteed
        # order coming out of a dict, so sort both our test and response
        lines = sorted([' '.join([r2, r1]), r1])
        response = request.execute('', '')
        response.body = '\n'.join(sorted(response.body.split('\n')))

        self.assertEqual(
            smart_req.SmartServerResponse(('ok', ), '\n'.join(lines)), response)

    def test_specific_revision_argument(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc9'.encode('utf-8')
        r1 = tree.commit('1st commit', rev_id=rev_id_utf8)
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()

        self.assertEqual(smart_req.SmartServerResponse(('ok', ), rev_id_utf8),
            request.execute('', rev_id_utf8))

    def test_no_such_revision(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        tree.unlock()

        # Note that it still returns body (of zero bytes).
        self.assertEqual(smart_req.SmartServerResponse(
                ('nosuchrevision', 'missingrevision', ), ''),
                         request.execute('', 'missingrevision'))


class TestSmartServerRepositoryGetRevIdForRevno(
    tests.TestCaseWithMemoryTransport):

    def test_revno_found(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevIdForRevno(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev1_id_utf8 = u'\xc8'.encode('utf-8')
        rev2_id_utf8 = u'\xc9'.encode('utf-8')
        tree.commit('1st commit', rev_id=rev1_id_utf8)
        tree.commit('2nd commit', rev_id=rev2_id_utf8)
        tree.unlock()

        self.assertEqual(smart_req.SmartServerResponse(('ok', rev1_id_utf8)),
            request.execute('', 1, (2, rev2_id_utf8)))

    def test_known_revid_missing(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevIdForRevno(backing)
        repo = self.make_repository('.')
        self.assertEqual(
            smart_req.FailedSmartServerResponse(('nosuchrevision', 'ghost')),
            request.execute('', 1, (2, 'ghost')))

    def test_history_incomplete(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevIdForRevno(backing)
        parent = self.make_branch_and_memory_tree('parent', format='1.9')
        parent.lock_write()
        parent.add([''], ['TREE_ROOT'])
        r1 = parent.commit(message='first commit')
        r2 = parent.commit(message='second commit')
        parent.unlock()
        local = self.make_branch_and_memory_tree('local', format='1.9')
        local.branch.pull(parent.branch)
        local.set_parent_ids([r2])
        r3 = local.commit(message='local commit')
        local.branch.create_clone_on_transport(
            self.get_transport('stacked'), stacked_on=self.get_url('parent'))
        self.assertEqual(
            smart_req.SmartServerResponse(('history-incomplete', 2, r2)),
            request.execute('stacked', 1, (3, r3)))


class GetStreamTestBase(tests.TestCaseWithMemoryTransport):

    def make_two_commit_repo(self):
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()
        repo = tree.branch.repository
        return repo, r1, r2


class TestSmartServerRepositoryGetStream(GetStreamTestBase):

    def test_ancestry_of(self):
        """The search argument may be a 'ancestry-of' some heads'."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStream(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        fetch_spec = ['ancestry-of', r2]
        lines = '\n'.join(fetch_spec)
        request.execute('', repo._format.network_name())
        response = request.do_body(lines)
        self.assertEqual(('ok',), response.args)
        stream_bytes = ''.join(response.body_stream)
        self.assertStartsWith(stream_bytes, 'Bazaar pack format 1')

    def test_search(self):
        """The search argument may be a 'search' of some explicit keys."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStream(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        fetch_spec = ['search', '%s %s' % (r1, r2), 'null:', '2']
        lines = '\n'.join(fetch_spec)
        request.execute('', repo._format.network_name())
        response = request.do_body(lines)
        self.assertEqual(('ok',), response.args)
        stream_bytes = ''.join(response.body_stream)
        self.assertStartsWith(stream_bytes, 'Bazaar pack format 1')

    def test_search_everything(self):
        """A search of 'everything' returns a stream."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStream_1_19(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        serialised_fetch_spec = 'everything'
        request.execute('', repo._format.network_name())
        response = request.do_body(serialised_fetch_spec)
        self.assertEqual(('ok',), response.args)
        stream_bytes = ''.join(response.body_stream)
        self.assertStartsWith(stream_bytes, 'Bazaar pack format 1')


class TestSmartServerRequestHasRevision(tests.TestCaseWithMemoryTransport):

    def test_missing_revision(self):
        """For a missing revision, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRequestHasRevision(backing)
        self.make_repository('.')
        self.assertEqual(smart_req.SmartServerResponse(('no', )),
            request.execute('', 'revid'))

    def test_present_revision(self):
        """For a present revision, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRequestHasRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        r1 = tree.commit('a commit', rev_id=rev_id_utf8)
        tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(rev_id_utf8))
        self.assertEqual(smart_req.SmartServerResponse(('yes', )),
            request.execute('', rev_id_utf8))


class TestSmartServerRepositoryGatherStats(tests.TestCaseWithMemoryTransport):

    def test_empty_revid(self):
        """With an empty revid, we get only size an number and revisions"""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGatherStats(backing)
        repository = self.make_repository('.')
        stats = repository.gather_stats()
        expected_body = 'revisions: 0\n'
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), expected_body),
                         request.execute('', '', 'no'))

    def test_revid_with_committers(self):
        """For a revid we get more infos."""
        backing = self.get_transport()
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        request = smart_repo.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600)
        tree.commit('a commit', timestamp=654321.4, timezone=0,
                    rev_id=rev_id_utf8)
        tree.unlock()

        stats = tree.branch.repository.gather_stats()
        expected_body = ('firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n')
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), expected_body),
                         request.execute('',
                                         rev_id_utf8, 'no'))

    def test_not_empty_repository_with_committers(self):
        """For a revid and requesting committers we get the whole thing."""
        backing = self.get_transport()
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        request = smart_repo.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600,
                    committer='foo')
        tree.commit('a commit', timestamp=654321.4, timezone=0,
                    committer='bar', rev_id=rev_id_utf8)
        tree.unlock()
        stats = tree.branch.repository.gather_stats()

        expected_body = ('committers: 2\n'
                         'firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n')
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), expected_body),
                         request.execute('',
                                         rev_id_utf8, 'yes'))


class TestSmartServerRepositoryIsShared(tests.TestCaseWithMemoryTransport):

    def test_is_shared(self):
        """For a shared repository, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=True)
        self.assertEqual(smart_req.SmartServerResponse(('yes', )),
            request.execute('', ))

    def test_is_not_shared(self):
        """For a shared repository, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=False)
        self.assertEqual(smart_req.SmartServerResponse(('no', )),
            request.execute('', ))


class TestSmartServerRepositoryLockWrite(tests.TestCaseWithMemoryTransport):

    def test_lock_write_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute('')
        nonce = repository.control_files._lock.peek().get('nonce')
        self.assertEqual(smart_req.SmartServerResponse(('ok', nonce)), response)
        # The repository is now locked.  Verify that with a new repository
        # object.
        new_repo = repository.bzrdir.open_repository()
        self.assertRaises(errors.LockContention, new_repo.lock_write)
        # Cleanup
        request = smart_repo.SmartServerRepositoryUnlock(backing)
        response = request.execute('', nonce)

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        repo_token = repository.lock_write().repository_token
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute('')
        self.assertEqual(
            smart_req.SmartServerResponse(('LockContention',)), response)
        # Cleanup
        repository.lock_write(repo_token)
        repository.dont_leave_lock_in_place()
        repository.unlock()

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart_repo.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute('')
        self.assertFalse(response.is_successful())
        self.assertEqual('LockFailed', response.args[0])


class TestInsertStreamBase(tests.TestCaseWithMemoryTransport):

    def make_empty_byte_stream(self, repo):
        byte_stream = smart_repo._stream_to_byte_stream([], repo._format)
        return ''.join(byte_stream)


class TestSmartServerRepositoryInsertStream(TestInsertStreamBase):

    def test_insert_stream_empty(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryInsertStream(backing)
        repository = self.make_repository('.')
        response = request.execute('', '')
        self.assertEqual(None, response)
        response = request.do_chunk(self.make_empty_byte_stream(repository))
        self.assertEqual(None, response)
        response = request.do_end()
        self.assertEqual(smart_req.SmartServerResponse(('ok', )), response)


class TestSmartServerRepositoryInsertStreamLocked(TestInsertStreamBase):

    def test_insert_stream_empty(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryInsertStreamLocked(
            backing)
        repository = self.make_repository('.', format='knit')
        lock_token = repository.lock_write().repository_token
        response = request.execute('', '', lock_token)
        self.assertEqual(None, response)
        response = request.do_chunk(self.make_empty_byte_stream(repository))
        self.assertEqual(None, response)
        response = request.do_end()
        self.assertEqual(smart_req.SmartServerResponse(('ok', )), response)
        repository.unlock()

    def test_insert_stream_with_wrong_lock_token(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryInsertStreamLocked(
            backing)
        repository = self.make_repository('.', format='knit')
        lock_token = repository.lock_write().repository_token
        self.assertRaises(
            errors.TokenMismatch, request.execute, '', '', 'wrong-token')
        repository.unlock()


class TestSmartServerRepositoryUnlock(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)

    def test_unlock_on_locked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryUnlock(backing)
        repository = self.make_repository('.', format='knit')
        token = repository.lock_write().repository_token
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute('', token)
        self.assertEqual(
            smart_req.SmartServerResponse(('ok',)), response)
        # The repository is now unlocked.  Verify that with a new repository
        # object.
        new_repo = repository.bzrdir.open_repository()
        new_repo.lock_write()
        new_repo.unlock()

    def test_unlock_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryUnlock(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute('', 'some token')
        self.assertEqual(
            smart_req.SmartServerResponse(('TokenMismatch',)), response)


class TestSmartServerIsReadonly(tests.TestCaseWithMemoryTransport):

    def test_is_readonly_no(self):
        backing = self.get_transport()
        request = smart_req.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(
            smart_req.SmartServerResponse(('no',)), response)

    def test_is_readonly_yes(self):
        backing = self.get_readonly_transport()
        request = smart_req.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(
            smart_req.SmartServerResponse(('yes',)), response)


class TestSmartServerRepositorySetMakeWorkingTrees(
    tests.TestCaseWithMemoryTransport):

    def test_set_false(self):
        backing = self.get_transport()
        repo = self.make_repository('.', shared=True)
        repo.set_make_working_trees(True)
        request_class = smart_repo.SmartServerRepositorySetMakeWorkingTrees
        request = request_class(backing)
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(('ok',)),
            request.execute('', 'False'))
        repo = repo.bzrdir.open_repository()
        self.assertFalse(repo.make_working_trees())

    def test_set_true(self):
        backing = self.get_transport()
        repo = self.make_repository('.', shared=True)
        repo.set_make_working_trees(False)
        request_class = smart_repo.SmartServerRepositorySetMakeWorkingTrees
        request = request_class(backing)
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(('ok',)),
            request.execute('', 'True'))
        repo = repo.bzrdir.open_repository()
        self.assertTrue(repo.make_working_trees())


class TestSmartServerPackRepositoryAutopack(tests.TestCaseWithTransport):

    def make_repo_needing_autopacking(self, path='.'):
        # Make a repo in need of autopacking.
        tree = self.make_branch_and_tree('.', format='pack-0.92')
        repo = tree.branch.repository
        # monkey-patch the pack collection to disable autopacking
        repo._pack_collection._max_pack_count = lambda count: count
        for x in range(10):
            tree.commit('commit %s' % x)
        self.assertEqual(10, len(repo._pack_collection.names()))
        del repo._pack_collection._max_pack_count
        return repo

    def test_autopack_needed(self):
        repo = self.make_repo_needing_autopacking()
        repo.lock_write()
        self.addCleanup(repo.unlock)
        backing = self.get_transport()
        request = smart_packrepo.SmartServerPackRepositoryAutopack(
            backing)
        response = request.execute('')
        self.assertEqual(smart_req.SmartServerResponse(('ok',)), response)
        repo._pack_collection.reload_pack_names()
        self.assertEqual(1, len(repo._pack_collection.names()))

    def test_autopack_not_needed(self):
        tree = self.make_branch_and_tree('.', format='pack-0.92')
        repo = tree.branch.repository
        repo.lock_write()
        self.addCleanup(repo.unlock)
        for x in range(9):
            tree.commit('commit %s' % x)
        backing = self.get_transport()
        request = smart_packrepo.SmartServerPackRepositoryAutopack(
            backing)
        response = request.execute('')
        self.assertEqual(smart_req.SmartServerResponse(('ok',)), response)
        repo._pack_collection.reload_pack_names()
        self.assertEqual(9, len(repo._pack_collection.names()))

    def test_autopack_on_nonpack_format(self):
        """A request to autopack a non-pack repo is a no-op."""
        repo = self.make_repository('.', format='knit')
        backing = self.get_transport()
        request = smart_packrepo.SmartServerPackRepositoryAutopack(
            backing)
        response = request.execute('')
        self.assertEqual(smart_req.SmartServerResponse(('ok',)), response)


class TestSmartServerVfsGet(tests.TestCaseWithMemoryTransport):

    def test_unicode_path(self):
        """VFS requests expect unicode paths to be escaped."""
        filename = u'foo\N{INTERROBANG}'
        filename_escaped = urlutils.escape(filename)
        backing = self.get_transport()
        request = vfs.GetRequest(backing)
        backing.put_bytes_non_atomic(filename_escaped, 'contents')
        self.assertEqual(smart_req.SmartServerResponse(('ok', ), 'contents'),
            request.execute(filename_escaped))


class TestHandlers(tests.TestCase):
    """Tests for the request.request_handlers object."""

    def test_all_registrations_exist(self):
        """All registered request_handlers can be found."""
        # If there's a typo in a register_lazy call, this loop will fail with
        # an AttributeError.
        for key in smart_req.request_handlers.keys():
            try:
                item = smart_req.request_handlers.get(key)
            except AttributeError, e:
                raise AttributeError('failed to get %s: %s' % (key, e))

    def assertHandlerEqual(self, verb, handler):
        self.assertEqual(smart_req.request_handlers.get(verb), handler)

    def test_registered_methods(self):
        """Test that known methods are registered to the correct object."""
        self.assertHandlerEqual('Branch.get_config_file',
            smart_branch.SmartServerBranchGetConfigFile)
        self.assertHandlerEqual('Branch.get_parent',
            smart_branch.SmartServerBranchGetParent)
        self.assertHandlerEqual('Branch.get_tags_bytes',
            smart_branch.SmartServerBranchGetTagsBytes)
        self.assertHandlerEqual('Branch.lock_write',
            smart_branch.SmartServerBranchRequestLockWrite)
        self.assertHandlerEqual('Branch.last_revision_info',
            smart_branch.SmartServerBranchRequestLastRevisionInfo)
        self.assertHandlerEqual('Branch.revision_history',
            smart_branch.SmartServerRequestRevisionHistory)
        self.assertHandlerEqual('Branch.set_config_option',
            smart_branch.SmartServerBranchRequestSetConfigOption)
        self.assertHandlerEqual('Branch.set_last_revision',
            smart_branch.SmartServerBranchRequestSetLastRevision)
        self.assertHandlerEqual('Branch.set_last_revision_info',
            smart_branch.SmartServerBranchRequestSetLastRevisionInfo)
        self.assertHandlerEqual('Branch.set_last_revision_ex',
            smart_branch.SmartServerBranchRequestSetLastRevisionEx)
        self.assertHandlerEqual('Branch.set_parent_location',
            smart_branch.SmartServerBranchRequestSetParentLocation)
        self.assertHandlerEqual('Branch.unlock',
            smart_branch.SmartServerBranchRequestUnlock)
        self.assertHandlerEqual('BzrDir.find_repository',
            smart_dir.SmartServerRequestFindRepositoryV1)
        self.assertHandlerEqual('BzrDir.find_repositoryV2',
            smart_dir.SmartServerRequestFindRepositoryV2)
        self.assertHandlerEqual('BzrDirFormat.initialize',
            smart_dir.SmartServerRequestInitializeBzrDir)
        self.assertHandlerEqual('BzrDirFormat.initialize_ex_1.16',
            smart_dir.SmartServerRequestBzrDirInitializeEx)
        self.assertHandlerEqual('BzrDir.cloning_metadir',
            smart_dir.SmartServerBzrDirRequestCloningMetaDir)
        self.assertHandlerEqual('BzrDir.get_config_file',
            smart_dir.SmartServerBzrDirRequestConfigFile)
        self.assertHandlerEqual('BzrDir.open_branch',
            smart_dir.SmartServerRequestOpenBranch)
        self.assertHandlerEqual('BzrDir.open_branchV2',
            smart_dir.SmartServerRequestOpenBranchV2)
        self.assertHandlerEqual('BzrDir.open_branchV3',
            smart_dir.SmartServerRequestOpenBranchV3)
        self.assertHandlerEqual('PackRepository.autopack',
            smart_packrepo.SmartServerPackRepositoryAutopack)
        self.assertHandlerEqual('Repository.gather_stats',
            smart_repo.SmartServerRepositoryGatherStats)
        self.assertHandlerEqual('Repository.get_parent_map',
            smart_repo.SmartServerRepositoryGetParentMap)
        self.assertHandlerEqual('Repository.get_rev_id_for_revno',
            smart_repo.SmartServerRepositoryGetRevIdForRevno)
        self.assertHandlerEqual('Repository.get_revision_graph',
            smart_repo.SmartServerRepositoryGetRevisionGraph)
        self.assertHandlerEqual('Repository.get_stream',
            smart_repo.SmartServerRepositoryGetStream)
        self.assertHandlerEqual('Repository.get_stream_1.19',
            smart_repo.SmartServerRepositoryGetStream_1_19)
        self.assertHandlerEqual('Repository.has_revision',
            smart_repo.SmartServerRequestHasRevision)
        self.assertHandlerEqual('Repository.insert_stream',
            smart_repo.SmartServerRepositoryInsertStream)
        self.assertHandlerEqual('Repository.insert_stream_locked',
            smart_repo.SmartServerRepositoryInsertStreamLocked)
        self.assertHandlerEqual('Repository.is_shared',
            smart_repo.SmartServerRepositoryIsShared)
        self.assertHandlerEqual('Repository.lock_write',
            smart_repo.SmartServerRepositoryLockWrite)
        self.assertHandlerEqual('Repository.tarball',
            smart_repo.SmartServerRepositoryTarball)
        self.assertHandlerEqual('Repository.unlock',
            smart_repo.SmartServerRepositoryUnlock)
        self.assertHandlerEqual('Transport.is_readonly',
            smart_req.SmartServerIsReadonly)


class SmartTCPServerHookTests(tests.TestCaseWithMemoryTransport):
    """Tests for SmartTCPServer hooks."""

    def setUp(self):
        super(SmartTCPServerHookTests, self).setUp()
        self.server = server.SmartTCPServer(self.get_transport())

    def test_run_server_started_hooks(self):
        """Test the server started hooks get fired properly."""
        started_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_started',
            lambda backing_urls, url: started_calls.append((backing_urls, url)),
            None)
        started_ex_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_started_ex',
            lambda backing_urls, url: started_ex_calls.append((backing_urls, url)),
            None)
        self.server._sockname = ('example.com', 42)
        self.server.run_server_started_hooks()
        self.assertEquals(started_calls,
            [([self.get_transport().base], 'bzr://example.com:42/')])
        self.assertEquals(started_ex_calls,
            [([self.get_transport().base], self.server)])

    def test_run_server_started_hooks_ipv6(self):
        """Test that socknames can contain 4-tuples."""
        self.server._sockname = ('::', 42, 0, 0)
        started_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_started',
            lambda backing_urls, url: started_calls.append((backing_urls, url)),
            None)
        self.server.run_server_started_hooks()
        self.assertEquals(started_calls,
                [([self.get_transport().base], 'bzr://:::42/')])

    def test_run_server_stopped_hooks(self):
        """Test the server stopped hooks."""
        self.server._sockname = ('example.com', 42)
        stopped_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_stopped',
            lambda backing_urls, url: stopped_calls.append((backing_urls, url)),
            None)
        self.server.run_server_stopped_hooks()
        self.assertEquals(stopped_calls,
            [([self.get_transport().base], 'bzr://example.com:42/')])
