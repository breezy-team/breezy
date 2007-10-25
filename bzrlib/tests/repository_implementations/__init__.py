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
from bzrlib.repofmt import (
    weaverepo,
    )
from bzrlib.remote import RemoteBzrDirFormat, RemoteRepositoryFormat
from bzrlib.smart.server import (
    SmartTCPServer_for_testing,
    ReadonlySmartTCPServer_for_testing,
    )
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          iter_suite_tests,
                          multiply_scenarios,
                          multiply_tests_from_modules,
                          TestScenarioApplier,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport.memory import MemoryServer


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


class BrokenRepoScenario(object):
    """Base class for defining scenarios for testing check and reconcile.

    A subclass needs to define the following methods:
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
    
    A subclass may define the following optional method as well:
        :corrected_fulltexts: a list of file versions that should be stored as
            fulltexts (not deltas) after reconcile.  run_test will verify that
            this occurs.
    """

    def __init__(self, test_case):
        self.test_case = test_case

    def make_one_file_inventory(self, repo, revision, parents,
                                inv_revision=None, root_revision=None,
                                file_contents=None, make_file_version=True):
        return self.test_case.make_one_file_inventory(
            repo, revision, parents, inv_revision=inv_revision,
            root_revision=root_revision, file_contents=file_contents,
            make_file_version=make_file_version)

    def add_revision(self, repo, revision_id, inv, parent_ids):
        return self.test_case.add_revision(repo, revision_id, inv, parent_ids)

    def corrected_fulltexts(self):
        return []


class UndamagedRepositoryScenario(BrokenRepoScenario):
    """A scenario where the repository has no damage.

    It has a single revision, 'rev1a', with a single file.
    """

    def all_versions(self):
        return ['rev1a']

    def populated_parents(self):
        return [([], 'rev1a')]

    def corrected_parents(self):
        # Same as the populated parents, because there was nothing wrong.
        return self.populated_parents()

    def check_regexes(self):
        return ["0 unreferenced text ancestors"]

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(
            repo, 'rev1a', [], root_revision='rev1a')
        self.add_revision(repo, 'rev1a', inv, [])


class FileParentIsNotInRevisionAncestryScenario(BrokenRepoScenario):
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

    def check_regexes(self):
        return [r"\* a-file-id version rev2 has parents \['rev1a', 'rev1b'\] "
                r"but should have \['rev1a'\]",
                "1 unreferenced text ancestors",
                ]

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


class FileParentHasInaccessibleInventoryScenario(BrokenRepoScenario):
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

    def check_regexes(self):
        return [r"\* a-file-id version rev3 has parents "
                r"\['rev1c'\] but should have \[\]",
                # Also check reporting of unreferenced ancestors
                r"unreferenced ancestor: {rev1c} in a-file-id",
                ]

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
        inv = self.make_one_file_inventory(repo, 'rev3', ['rev1c'])
        self.add_revision(repo, 'rev3', inv, ['rev1c', 'rev1a'])


class FileParentsNotReferencedByAnyInventoryScenario(BrokenRepoScenario):
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
        return ['rev1a', 'rev2c', 'rev4', 'rev5']

    def populated_parents(self):
        return [
            (['rev1a'], 'rev2'),
            (['rev1a'], 'rev2b'),
            (['rev2'], 'rev3'),
            (['rev2'], 'rev4'),
            (['rev2', 'rev2c'], 'rev5')]

    def corrected_parents(self):
        return [
            # rev2 and rev2b have been removed.
            (None, 'rev2'),
            (None, 'rev2b'),
            # rev3's accessible parent inventories all have rev1a as the last
            # modifier.
            (['rev1a'], 'rev3'),
            # rev1a features in both rev4's parents but should only appear once
            # in the result
            (['rev1a'], 'rev4'),
            # rev2c is the head of rev1a and rev2c, the inventory provided
            # per-file last-modified revisions.
            (['rev2c'], 'rev5')]

    def check_regexes(self):
        return [
            "5 inconsistent parents",
            r"a-file-id version rev2 has parents \['rev1a'\] "
            r"but should have \[\]",
            r"a-file-id version rev2b has parents \['rev1a'\] "
            r"but should have \[\]",
            r"a-file-id version rev3 has parents \['rev2'\] "
            r"but should have \['rev1a'\]",
            r"a-file-id version rev5 has parents \['rev2', 'rev2c'\] "
            r"but should have \['rev2c'\]",
            r"a-file-id version rev4 has parents \['rev2'\] "
            r"but should have \['rev1a'\]",
            ]

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv = self.make_one_file_inventory(
            repo, 'rev1a', [], root_revision='rev1a')
        self.add_revision(repo, 'rev1a', inv, [])

        # make rev2, with a-file.
        # a-file is unmodified from rev1a, and an unreferenced rev2 file
        # version is present in the repository.
        self.make_one_file_inventory(
            repo, 'rev2', ['rev1a'], inv_revision='rev1a')
        self.add_revision(repo, 'rev2', inv, ['rev1a'])

        # make rev3 with a-file
        # a-file has 'rev2' as its ancestor, but the revision in 'rev2' was
        # rev1a so this is inconsistent with rev2's inventory - it should
        # be rev1a, and at the revision level 1c is not present - it is a
        # ghost, so only the details from rev1a are available for
        # determining whether a delta is acceptable, or a full is needed,
        # and what the correct parents are.
        inv = self.make_one_file_inventory(repo, 'rev3', ['rev2'])
        self.add_revision(repo, 'rev3', inv, ['rev1c', 'rev1a'])

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


class UnreferencedFileParentsFromNoOpMergeScenario(BrokenRepoScenario):
    """
    rev1a and rev1b with identical contents
    rev2 revision has parents of [rev1a, rev1b]
    There is a a-file:rev2 file version, not referenced by the inventory.
    """

    def all_versions(self):
        return ['rev1a', 'rev1b', 'rev2', 'rev4']

    def populated_parents(self):
        return [
            ([], 'rev1a'),
            ([], 'rev1b'),
            (['rev1a', 'rev1b'], 'rev2'),
            (None, 'rev3'),
            (['rev2'], 'rev4'),
            ]

    def corrected_parents(self):
        return [
            ([], 'rev1a'),
            ([], 'rev1b'),
            ([], 'rev2'),
            (None, 'rev3'),
            (['rev2'], 'rev4'),
            ]

    def corrected_fulltexts(self):
        return ['rev4']

    def check_regexes(self):
        return []

    def populate_repository(self, repo):
        # make rev1a: A well-formed revision, containing 'a-file'
        inv1a = self.make_one_file_inventory(
            repo, 'rev1a', [], root_revision='rev1a')
        self.add_revision(repo, 'rev1a', inv1a, [])

        # make rev1b: A well-formed revision, containing 'a-file'
        # rev1b of a-file has the exact same contents as rev1a.
        file_contents = repo.revision_tree('rev1a').get_file_text('a-file-id')
        inv = self.make_one_file_inventory(
            repo, 'rev1b', [], root_revision='rev1b',
            file_contents=file_contents)
        self.add_revision(repo, 'rev1b', inv, [])

        # make rev2, a merge of rev1a and rev1b, with a-file.
        # a-file is unmodified from rev1a and rev1b, but a new version is
        # wrongly present anyway.
        inv = self.make_one_file_inventory(
            repo, 'rev2', ['rev1a', 'rev1b'], inv_revision='rev1a',
            file_contents=file_contents)
        self.add_revision(repo, 'rev2', inv, ['rev1a', 'rev1b'])

        # rev3: a-file unchanged from rev2, but wrongly referencing rev2 of the
        # file in its inventory.
        inv = self.make_one_file_inventory(
            repo, 'rev3', ['rev2'], inv_revision='rev2',
            file_contents=file_contents, make_file_version=False)
        self.add_revision(repo, 'rev3', inv, ['rev2'])

        # rev4: a modification of a-file on top of rev3.
        inv = self.make_one_file_inventory(repo, 'rev4', ['rev2'])
        self.add_revision(repo, 'rev4', inv, ['rev3'])


class TooManyParentsScenario(BrokenRepoScenario):
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


class ClaimedFileParentDidNotModifyFileScenario(BrokenRepoScenario):
    """A scenario where the file parent is the same as the revision parent, but
    should not be because that revision did not modify the file.

    Specifically, the parent revision of 'current' is
    'modified-something-else', which does not modify 'a-file', but the
    'current' version of 'a-file' erroneously claims that
    'modified-something-else' is the parent file version.
    """

    def all_versions(self):
        return ['basis', 'current']

    def populated_parents(self):
        return [
            ([], 'basis'),
            (['basis'], 'modified-something-else'),
            (['modified-something-else'], 'current')]

    def corrected_parents(self):
        return [
            ([], 'basis'),
            (None, 'modified-something-else'),
            (['basis'], 'current')]

    def check_regexes(self):
        return [
            '2 inconsistent parents',
            r"\* a-file-id version current has parents "
            r"\['modified-something-else'\] but should have \['basis'\]",
            r"\* a-file-id version modified-something-else has parents "
            r"\['basis'\] but should have \[\]",
            ]

    def populate_repository(self, repo):
        inv = self.make_one_file_inventory(repo, 'basis', [])
        self.add_revision(repo, 'basis', inv, [])

        # 'modified-something-else' is a correctly recorded revision, but it
        # does not modify the file we are looking at, so the inventory for that
        # file in this revision points to 'basis'.
        inv = self.make_one_file_inventory(
            repo, 'modified-something-else', ['basis'], inv_revision='basis')
        self.add_revision(repo, 'modified-something-else', inv, ['basis'])

        # The 'current' revision has 'modified-something-else' as its parent,
        # but the 'current' version of 'a-file' should have 'basis' as its
        # parent.
        inv = self.make_one_file_inventory(
            repo, 'current', ['modified-something-else'])
        self.add_revision(repo, 'current', inv, ['modified-something-else'])


class IncorrectlyOrderedParentsScenario(BrokenRepoScenario):
    """A scenario where the set parents of a version of a file are correct, but
    the order of those parents is incorrect.

    This defines a 'broken-revision-1-2' and a 'broken-revision-2-1' which both
    have their file version parents reversed compared to the revision parents,
    which is invalid.  (We use two revisions with opposite orderings of the
    same parents to make sure that accidentally relying on dictionary/set
    ordering cannot make the test pass; the assumption is that while dict/set
    iteration order is arbitrary, it is also consistent within a single test).
    """

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

    def check_regexes(self):
        return [
            "2 inconsistent parents",
            r"\* a-file-id version broken-revision-1-2 has parents "
            r"\['parent-2', 'parent-1'\] but should have "
            r"\['parent-1', 'parent-2'\]",
            r"\* a-file-id version broken-revision-2-1 has parents "
            r"\['parent-1', 'parent-2'\] but should have "
            r"\['parent-2', 'parent-1'\]"]

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


all_broken_scenario_classes = [
    UndamagedRepositoryScenario,
    FileParentIsNotInRevisionAncestryScenario,
    FileParentHasInaccessibleInventoryScenario,
    FileParentsNotReferencedByAnyInventoryScenario,
    TooManyParentsScenario,
    ClaimedFileParentDidNotModifyFileScenario,
    IncorrectlyOrderedParentsScenario,
    UnreferencedFileParentsFromNoOpMergeScenario,
    ]
    

def test_suite():
    registry = repository.format_registry
    all_formats = [registry.get(k) for k in registry.keys()]
    all_formats.extend(weaverepo._legacy_formats)
    disk_format_adapter = RepositoryTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        [(format, format._matchingbzrdir) for format in all_formats])

    remote_repo_adapter = RepositoryTestProviderAdapter(
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteRepositoryFormat(), RemoteBzrDirFormat())],
        MemoryServer
        )

    # format_scenarios is all the implementations of Repository; i.e. all disk
    # formats plus RemoteRepository.
    format_scenarios = (disk_format_adapter.scenarios +
                        remote_repo_adapter.scenarios)

    prefix = 'bzrlib.tests.repository_implementations.'
    test_repository_modules = [
        'test_break_lock',
        'test_check',
        # test_check_reconcile is intentionally omitted, see below.
        'test_commit_builder',
        'test_fetch',
        'test_fileid_involved',
        'test_has_same_location',
        'test_is_write_locked',
        'test_iter_reverse_revision_history',
        'test_pack',
        'test_reconcile',
        'test_repository',
        'test_revision',
        'test_statistics',
        'test_write_group',
        ]
    module_name_list = [prefix + module_name
                        for module_name in test_repository_modules]

    # Parameterise repository_implementations test modules by format.
    result = multiply_tests_from_modules(module_name_list, format_scenarios)

    # test_check_reconcile needs to be parameterised by format *and* by broken
    # repository scenario.
    broken_scenarios = [(s.__name__, {'scenario_class': s})
                        for s in all_broken_scenario_classes]
    broken_scenarios_for_all_formats = multiply_scenarios(
        format_scenarios, broken_scenarios)
    broken_scenario_applier = TestScenarioApplier()
    broken_scenario_applier.scenarios = broken_scenarios_for_all_formats
    loader = TestLoader()
    adapt_modules(
        [prefix + 'test_check_reconcile'],
        broken_scenario_applier, loader, result)

    return result
