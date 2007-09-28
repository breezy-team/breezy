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

    def assertReconcileResults(self, scenario):
        """Construct a repository and reconcile it, verifying the state before
        and after.

        :param scenario: a Scenario to test reconcile on.
        """
        repo = self.make_repository_using_factory(scenario.populate_repository)
        self.require_text_parent_corruption(repo)
        for bad_parents, version in scenario.populated_parents():
            file_parents = self.file_parents(repo, version)
            self.assertEqual(bad_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s before "
                "reconcile, but it has %s instead."
                % (version, bad_parents, file_parents))
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        vf_shas = dict((v, vf.get_sha1(v)) for v in scenario.all_versions())
        result = repo.reconcile(thorough=True)
        for good_parents, version in scenario.corrected_parents():
            file_parents = self.file_parents(repo, version)
            self.assertEqual(good_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s after "
                "reconcile, but it has %s instead."
                % (version, good_parents, file_parents))
        # The content of the versionedfile should be the same after the
        # reconcile.
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        self.assertEqual(
            vf_shas, dict((v, vf.get_sha1(v)) for v in scenario.all_versions()))


class Scenario(object):
    """A scenario for testing check and reconcile.

    A scenario needs to define the following methods:
        :populate_repository: a method to use to populate a repository with
            sample revisions, inventories and file versions.
        :all_versions: all the versions in repository.  run_test verifies
            that the text of each of these versions of the file is unchanged
            by the reconcile.
        :populated_parents: a list of (parents list, revision).  Each version
            of the file is verified to have the given parents before running
            the reconcile.  i.e. this is used to assert that the repo from the
            factory is what we expect.
        :corrected_parents: a list of (parents list, revision).  Each version
            of the file is verified to have the given parents after the
            reconcile.  i.e. this is used to assert that reconcile made the
            changes we expect it to make.
    """

    def __init__(self, test_case):
        self.test_case = test_case

    def make_one_file_inventory(self, repo, revision, parents,
                                inv_revision=None, root_revision=None):
        return self.test_case.make_one_file_inventory(
            repo, revision, parents, inv_revision=inv_revision,
            root_revision=root_revision)

    def add_revision(self, repo, revision_id, inv, parent_ids):
        return self.test_case.add_revision(repo, revision_id, inv, parent_ids)


class FileParentIsNotInRevisionAncestryScenario(Scenario):
    """A scenario where a revision 'rev2' has 'a-file' with a
    parent 'rev1b' that is not in the revision ancestry.
    
    Reconcile should remove 'rev1b' from the parents list of 'a-file' in
    'rev2', preserving 'rev1a' as a parent.
    """

    def all_versions(self):
        return ['rev1a', 'rev1b', 'rev2']

    def populated_parents(self):
        return [
            ([], 'rev1a'),
            ([], 'rev1b'),
            (['rev1a', 'rev1b'], 'rev2')]

    def corrected_parents(self):
        return [
            ([], 'rev1a'),
            ([], 'rev1b'),
            (['rev1a'], 'rev2')]

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(
            repo, 'rev1a', [], root_revision='rev1a')
        self.add_revision(repo, 'rev1a', inv, [])

        # make rev1b, which has no Revision, but has an Inventory, and
        # a-file
        inv = self.make_one_file_inventory(
            repo, 'rev1b', [], root_revision='rev1b')
        repo.add_inventory('rev1b', inv, [])

        # make rev2, with a-file.
        # a-file has 'rev1b' as an ancestor, even though this is not
        # mentioned by 'rev1a', making it an unreferenced ancestor
        inv = self.make_one_file_inventory(
            repo, 'rev2', ['rev1a', 'rev1b'])
        self.add_revision(repo, 'rev2', inv, ['rev1a'])


class FileParentHasInaccessibleInventoryScenario(Scenario):
    """A scenario where a revision 'rev3' containing 'a-file' modified in
    'rev3', and with a parent which is in the revision ancestory, but whose
    inventory cannot be accessed at all.

    Reconcile should remove the file version parent whose inventory is
    inaccessbile (i.e. remove 'rev1c' from the parents of a-file's rev3).
    """

    def all_versions(self):
        return ['rev2', 'rev3']

    def populated_parents(self):
        return [
            ([], 'rev2'),
            (['rev1c'], 'rev3')]

    def corrected_parents(self):
        return [
            ([], 'rev2'),
            ([], 'rev3')]

    def populate_repository(self, repo):
        # make rev2, with a-file
        # a-file is sane
        inv = self.make_one_file_inventory(repo, 'rev2', [])
        self.add_revision(repo, 'rev2', inv, [])

        # make ghost revision rev1c, with a version of a-file present so
        # that we generate a knit delta against this version.  In real life
        # the ghost might never have been present or rev3 might have been
        # generated against a revision that was present at the time.  So
        # currently we have the full history of a-file present even though
        # the inventory and revision objects are not.
        self.make_one_file_inventory(repo, 'rev1c', [])

        # make rev3 with a-file
        # a-file refers to 'rev1c', which is a ghost in this repository, so
        # a-file cannot have rev1c as its ancestor.
        # XXX: I've sent a mail to the list about this.  It's not necessarily
        # right that it cannot have rev1c as its ancestor, though it is correct
        # that it should not be a delta against rev1c because we cannot verify
        # that the inventory of rev1c includes a-file as modified in rev1c.
        inv = self.make_one_file_inventory(repo, 'rev3', ['rev1c'])
        self.add_revision(repo, 'rev3', inv, ['rev1c', 'rev1a'])


class FileParentsNotReferencedByAnyInventoryScenario(Scenario):
    """A scenario where a repository with file 'a-file' which has extra
    per-file versions that are not referenced by any inventory (even though
    they have the same ID as actual revisions).  The inventory of 'rev2'
    references 'rev1a' of 'a-file', but there is a 'rev2' of 'some-file' stored
    and erroneously referenced by later per-file versions (revisions 'rev4' and
    'rev5').

    Reconcile should remove the file parents that are not referenced by any
    inventory.
    """

    def all_versions(self):
        return ['rev1a', 'rev2', 'rev4', 'rev2b', 'rev4', 'rev2c', 'rev5']

    def populated_parents(self):
        return [
            (['rev2'], 'rev3'),
            (['rev2'], 'rev4'),
            (['rev2', 'rev2c'], 'rev5')]

    def corrected_parents(self):
        return [
            # rev3's accessible parent inventories all have rev1a as the last
            # modifier.
            (['rev1a'], 'rev3'),
            # rev1a features in both rev4's parents but should only appear once
            # in the result
            (['rev1a'], 'rev4'),
            # rev2c is the head of rev1a and rev2c, the inventory provided
            # per-file last-modified revisions.
            (['rev2c'], 'rev5')]

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(
            repo, 'rev1a', [], root_revision='rev1a')
        self.add_revision(repo, 'rev1a', inv, [])

        # make rev2, with a-file.
        # a-file is unmodified from rev1a.
        self.make_one_file_inventory(
            repo, 'rev2', ['rev1a'], inv_revision='rev1a')
        self.add_revision(repo, 'rev2', inv, ['rev1a'])

        # make rev3 with a-file
        # a-file has 'rev2' as its ancestor, but the revision in 'rev2' was
        # rev1a so this is inconsistent with rev2's inventory - it should
        # be rev1a, and at the revision level 1c is not present - it is a
        # ghost, so only the details from rev1a are available for
        # determining whether a delta is acceptable, or a full is needed,
        # and what the correct parents are. ### same problem as the vf2 # # ghost case has in this respect
        inv = self.make_one_file_inventory(repo, 'rev3', ['rev2'])
        self.add_revision(repo, 'rev3', inv, ['rev1c', 'rev1a']) # XXX: extra parent irrevelvant?

        # In rev2b, the true last-modifying-revision of a-file is rev1a,
        # inherited from rev2, but there is a version rev2b of the file, which
        # reconcile could remove, leaving no rev2b.  Most importantly,
        # revisions descending from rev2b should not have per-file parents of
        # a-file-rev2b.
        # ??? This is to test deduplication in fixing rev4
        inv = self.make_one_file_inventory(
            repo, 'rev2b', ['rev1a'], inv_revision='rev1a')
        self.add_revision(repo, 'rev2b', inv, ['rev1a'])

        # rev4 is for testing that when the last modified of a file in
        # multiple parent revisions is the same, that it only appears once
        # in the generated per file parents list: rev2 and rev2b both
        # descend from 1a and do not change the file a-file, so there should
        # be no version of a-file 'rev2' or 'rev2b', but rev4 does change
        # a-file, and is a merge of rev2 and rev2b, so it should end up with
        # a parent of just rev1a - the starting file parents list is simply
        # completely wrong.
        inv = self.make_one_file_inventory(repo, 'rev4', ['rev2'])
        self.add_revision(repo, 'rev4', inv, ['rev2', 'rev2b'])

        # rev2c changes a-file from rev1a, so the version it of a-file it
        # introduces is a head revision when rev5 is checked.
        inv = self.make_one_file_inventory(repo, 'rev2c', ['rev1a'])
        self.add_revision(repo, 'rev2c', inv, ['rev1a'])

        # rev5 descends from rev2 and rev2c; as rev2 does not alter a-file,
        # but rev2c does, this should use rev2c as the parent for the per
        # file history, even though more than one per-file parent is
        # available, because we use the heads of the revision parents for
        # the inventory modification revisions of the file to determine the
        # parents for the per file graph.
        inv = self.make_one_file_inventory(repo, 'rev5', ['rev2', 'rev2c'])
        self.add_revision(repo, 'rev5', inv, ['rev2', 'rev2c'])


class TooManyParentsScenario(Scenario):
    """A scenario where 'broken-revision' of 'a-file' claims to have parents
    ['good-parent', 'bad-parent'].  However 'bad-parent' is in the ancestry of
    'good-parent', so the correct parent list for that file version are is just
    ['good-parent'].
    """

    def all_versions(self):
        return ['bad-parent', 'good-parent', 'broken-revision']

    def populated_parents(self):
        return [
            ([], 'bad-parent'),
            (['bad-parent'], 'good-parent'),
            (['good-parent', 'bad-parent'], 'broken-revision')]

    def corrected_parents(self):
        return [
            ([], 'bad-parent'),
            (['bad-parent'], 'good-parent'),
            (['good-parent'], 'broken-revision')]

    def check_regexes(self):
        return [
            '     1 inconsistent parents',
            (r"      \* a-file-id version broken-revision has parents "
             r"\['good-parent', 'bad-parent'\] but "
             r"should have \['good-parent'\]")]

    def populate_repository(self, repo):
        inv = self.make_one_file_inventory(
            repo, 'bad-parent', [], root_revision='bad-parent')
        self.add_revision(repo, 'bad-parent', inv, [])
        
        inv = self.make_one_file_inventory(
            repo, 'good-parent', ['bad-parent'])
        self.add_revision(repo, 'good-parent', inv, ['bad-parent'])
        
        inv = self.make_one_file_inventory(
            repo, 'broken-revision', ['good-parent', 'bad-parent'])
        self.add_revision(repo, 'broken-revision', inv, ['good-parent'])


class FooScenario(Scenario):

    def all_versions(self):
        return ['basis', 'modified-something-else', 'current']

    def populated_parents(self):
        return [
            ([], 'basis'),
            (['basis'], 'modified-something-else'),
            (['modified-something-else'], 'current')]

    def corrected_parents(self):
        return [
            ([], 'basis'),
            (['basis'], 'modified-something-else'),
            (['basis'], 'current')]

    def populate_repository(self, repo):
        inv = self.make_one_file_inventory(repo, 'basis', [])
        self.add_revision(repo, 'basis', inv, [])

        inv = self.make_one_file_inventory(
            repo, 'modified-something-else', ['basis'], inv_revision='basis')
        self.add_revision(repo, 'modified-something-else', inv, ['basis'])

        inv = self.make_one_file_inventory(
            repo, 'current', ['modified-something-else'])
        self.add_revision(repo, 'current', inv, ['modified-something-else'])


class IncorrectlyOrderedParentsScenario(Scenario):

    def all_versions(self):
        return ['parent-1', 'parent-2', 'broken-revision-1-2',
                'broken-revision-2-1']

    def populated_parents(self):
        return [
            ([], 'parent-1'),
            ([], 'parent-2'),
            (['parent-2', 'parent-1'], 'broken-revision-1-2'),
            (['parent-1', 'parent-2'], 'broken-revision-2-1')]

    def corrected_parents(self):
        return [
            ([], 'parent-1'),
            ([], 'parent-2'),
            (['parent-1', 'parent-2'], 'broken-revision-1-2'),
            (['parent-2', 'parent-1'], 'broken-revision-2-1')]

    def populate_repository(self, repo):
        inv = self.make_one_file_inventory(repo, 'parent-1', [])
        self.add_revision(repo, 'parent-1', inv, [])

        inv = self.make_one_file_inventory(repo, 'parent-2', [])
        self.add_revision(repo, 'parent-2', inv, [])

        inv = self.make_one_file_inventory(
            repo, 'broken-revision-1-2', ['parent-2', 'parent-1'])
        self.add_revision(
            repo, 'broken-revision-1-2', inv, ['parent-1', 'parent-2'])

        inv = self.make_one_file_inventory(
            repo, 'broken-revision-2-1', ['parent-1', 'parent-2'])
        self.add_revision(
            repo, 'broken-revision-2-1', inv, ['parent-2', 'parent-1'])


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
