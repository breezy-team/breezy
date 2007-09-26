# Copyright (C) 2006, 2007 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
#          and others
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


"""Repository implementation tests for bzr.

These test the conformance of all the repository variations to the expected API.
Specific tests for individual formats are in the tests/test_repository.py file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib import (
    repository,
    )
from bzrlib.inventory import Inventory, InventoryFile
from bzrlib.repofmt import (
    weaverepo,
    )
from bzrlib.revision import Revision
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestNotApplicable,
                          TestScenarioApplier,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport.memory import MemoryServer

import sha


class RepositoryTestProviderAdapter(TestScenarioApplier):
    """A tool to generate a suite testing multiple repository formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and bzrdir_format and
    repository_format classes into each copy. Each copy is also given a new id()
    to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats,
                 vfs_transport_factory=None):
        TestScenarioApplier.__init__(self)
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._vfs_transport_factory = vfs_transport_factory
        self.scenarios = self.formats_to_scenarios(formats)
    
    def formats_to_scenarios(self, formats):
        """Transform the input formats to a list of scenarios.

        :param formats: A list of (repository_format, bzrdir_format).
        """
        result = []
        for repository_format, bzrdir_format in formats:
            scenario = (repository_format.__class__.__name__,
                {"transport_server":self._transport_server,
                 "transport_readonly_server":self._transport_readonly_server,
                 "bzrdir_format":bzrdir_format,
                 "repository_format":repository_format,
                 })
            # Only override the test's vfs_transport_factory if one was
            # specified, otherwise just leave the default in place.
            if self._vfs_transport_factory:
                scenario[1]['vfs_transport_factory'] = self._vfs_transport_factory
            result.append(scenario)
        return result


class TestCaseWithRepository(TestCaseWithBzrDir):

    def make_repository(self, relpath, format=None):
        if format is None:
            # Create a repository of the type we are trying to test.
            made_control = self.make_bzrdir(relpath)
            repo = self.repository_format.initialize(made_control)
            if getattr(self, "repository_to_test_repository", None):
                repo = self.repository_to_test_repository(repo)
            return repo
        else:
            return super(TestCaseWithRepository, self).make_repository(
                relpath, format=format)


class TestCaseWithInconsistentRepository(TestCaseWithRepository):

    def make_repository_using_factory(self, factory):
        """Create a new repository populated by the given factory."""
        repo = self.make_repository('broken-repo')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                factory(repo)
                repo.commit_write_group()
                return repo
            except:
                repo.abort_write_group()
                raise
        finally:
            repo.unlock()

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = Revision(revision_id, committer='jrandom@example.com',
            timestamp=0, inventory_sha1='', timezone=0, message='foo',
            parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def make_one_file_inventory(self, repo, revision, parents,
                                inv_revision=None, root_revision=None):
        """Make an inventory containing a version of a file with ID 'a-file'.

        The file's ID will be 'a-file', and its filename will be 'a file name',
        stored at the tree root.

        :param repo: a repository to add the new file version to.
        :param revision: the revision ID of the new inventory.
        :param parents: the parents for this revision of 'a-file'.
        :param inv_revision: if not None, the revision ID to store in the
            inventory entry.  Otherwise, this defaults to revision.
        :param root_revision: if not None, the inventory's root.revision will
            be set to this.
        """
        inv = Inventory(revision_id=revision)
        if root_revision is not None:
            inv.root.revision = root_revision
        file_id = 'a-file-id'
        entry = InventoryFile(file_id, 'a file name', 'TREE_ROOT')
        if inv_revision is not None:
            entry.revision = inv_revision
        else:
            entry.revision = revision
        entry.text_size = 0
        file_contents = '%sline\n' % revision
        entry.text_sha1 = sha.sha(file_contents).hexdigest()
        inv.add(entry)
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, [file_contents])
        return inv

    def require_text_parent_corruption(self, repo):
        if not repo._reconcile_fixes_text_parents:
            raise TestNotApplicable(
                    "Format does not support text parent reconciliation")

    def file_parents(self, repo, revision_id):
        return repo.weave_store.get_weave('a-file-id',
            repo.get_transaction()).get_parents(revision_id)

    def assertReconcileResults(self, factory, all_versions, affected_before,
            affected_after):
        """Construct a repository and reconcile it, verifying the state before
        and after.

        :param factory: a method to use to populate a repository with sample
            revisions, inventories and file versions.
        :param all_versions: all the versions in repository.  run_test verifies
            that the text of each of these versions of the file is unchanged
            by the reconcile.
        :param affected_before: a list of (parents list, revision).  Each
            version of the file is verified to have the given parents before
            running the reconcile.  i.e. this is used to assert that the repo
            from the factory is what we expect.
        :param affected_after: a list of (parents list, revision).  Each
            version of the file is verified to have the given parents after the
            reconcile.  i.e. this is used to assert that reconcile made the
            changes we expect it to make.
        """
        repo = self.make_repository_using_factory(factory)
        self.require_text_parent_corruption(repo)
        for bad_parents, version in affected_before:
            file_parents = self.file_parents(repo, version)
            self.assertEqual(bad_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s before "
                "reconcile, but it has %s instead."
                % (version, bad_parents, file_parents))
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        vf_shas = dict((v, vf.get_sha1(v)) for v in all_versions)
        result = repo.reconcile(thorough=True)
        for good_parents, version in affected_after:
            file_parents = self.file_parents(repo, version)
            self.assertEqual(good_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s after "
                "reconcile, but it has %s instead."
                % (version, good_parents, file_parents))
        # The content of the versionedfile should be the same after the
        # reconcile.
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        self.assertEqual(
            vf_shas, dict((v, vf.get_sha1(v)) for v in all_versions))



def test_suite():
    result = TestSuite()
    test_repository_implementations = [
        'bzrlib.tests.repository_implementations.test_break_lock',
        'bzrlib.tests.repository_implementations.test_check',
        'bzrlib.tests.repository_implementations.test_commit_builder',
        'bzrlib.tests.repository_implementations.test_fetch',
        'bzrlib.tests.repository_implementations.test_fileid_involved',
        'bzrlib.tests.repository_implementations.test_has_same_location',
        'bzrlib.tests.repository_implementations.test_iter_reverse_revision_history',
        'bzrlib.tests.repository_implementations.test_pack',
        'bzrlib.tests.repository_implementations.test_reconcile',
        'bzrlib.tests.repository_implementations.test_repository',
        'bzrlib.tests.repository_implementations.test_revision',
        'bzrlib.tests.repository_implementations.test_statistics',
        'bzrlib.tests.repository_implementations.test_write_group',
        ]

    from bzrlib.smart.server import (
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        )
    from bzrlib.remote import RemoteBzrDirFormat, RemoteRepositoryFormat

    registry = repository.format_registry
    all_formats = [registry.get(k) for k in registry.keys()]
    all_formats.extend(weaverepo._legacy_formats)
    adapter = RepositoryTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        [(format, format._matchingbzrdir) for format in all_formats])
    loader = TestLoader()
    adapt_modules(test_repository_implementations, adapter, loader, result)

    adapt_to_smart_server = RepositoryTestProviderAdapter(
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteRepositoryFormat(), RemoteBzrDirFormat())],
        MemoryServer
        )
    adapt_modules(test_repository_implementations,
                  adapt_to_smart_server,
                  loader,
                  result)

    return result
