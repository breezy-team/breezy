# Copyright (C) 2008, 2009 Canonical Ltd
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


"""Repository implementation tests for external reference repositories.

These tests check the conformance of repositories which refer to other
repositories for some data, and are run for each repository format supporting
this.
"""

from bzrlib import (
    repository,
    remote,
    )
from bzrlib.branch import BzrBranchFormat7
from bzrlib.bzrdir import BzrDir
from bzrlib.repofmt.pack_repo import RepositoryFormatKnitPack6
from bzrlib.tests import multiply_tests
from bzrlib.tests.per_repository import (
    all_repository_format_scenarios,
    TestCaseWithRepository,
    )


class TestCaseWithExternalReferenceRepository(TestCaseWithRepository):

    def make_referring(self, relpath, target_path):
        """Get a new repository that refers to a_repository.

        :param relpath: The path to create the repository at.
        :param a_repository: A repository to refer to.
        """
        repo = self.make_repository(relpath)
        repo.add_fallback_repository(self.readonly_repository(target_path))
        return repo

    def readonly_repository(self, relpath):
        return BzrDir.open_from_transport(
            self.get_readonly_transport(relpath)).open_repository()


class TestCorrectFormat(TestCaseWithExternalReferenceRepository):

    def test_repository_format(self):
        # make sure the repository on tree.branch is of the desired format,
        # because developers use this api to setup the tree, branch and
        # repository for their tests: having it not give the right repository
        # type would invalidate the tests.
        self.make_branch_and_tree('repo')
        repo = self.make_referring('referring', 'repo')
        self.assertIsInstance(repo._format,
            self.repository_format.__class__)


def external_reference_test_scenarios():
    """Generate test scenarios for repositories supporting external references.
    """
    result = []
    for test_name, scenario_info in all_repository_format_scenarios():
        format = scenario_info['repository_format']
        if isinstance(format, remote.RemoteRepositoryFormat):
            # This is a RemoteRepositoryFormat scenario.  Force the scenario to
            # use real branch and repository formats that support references.
            scenario_info = dict(scenario_info)
            format = remote.RemoteRepositoryFormat()
            format._custom_format = RepositoryFormatKnitPack6()
            scenario_info['repository_format'] = format
            bzrdir_format = remote.RemoteBzrDirFormat()
            bzrdir_format.repository_format = format
            bzrdir_format.set_branch_format(BzrBranchFormat7())
            scenario_info['bzrdir_format'] = bzrdir_format
        if format.supports_external_lookups:
            result.append((test_name, scenario_info))
    return result


def load_tests(standard_tests, module, loader):
    module_list = [
        'bzrlib.tests.per_repository_reference.test_add_inventory',
        'bzrlib.tests.per_repository_reference.test_add_revision',
        'bzrlib.tests.per_repository_reference.test_add_signature_text',
        'bzrlib.tests.per_repository_reference.test_all_revision_ids',
        'bzrlib.tests.per_repository_reference.test_break_lock',
        'bzrlib.tests.per_repository_reference.test_check',
        'bzrlib.tests.per_repository_reference.test_default_stacking',
        'bzrlib.tests.per_repository_reference.test_fetch',
        'bzrlib.tests.per_repository_reference.test_get_record_stream',
        'bzrlib.tests.per_repository_reference.test_get_rev_id_for_revno',
        'bzrlib.tests.per_repository_reference.test_initialize',
        'bzrlib.tests.per_repository_reference.test_unlock',
        ]
    # Parameterize per_repository_reference test modules by format.
    standard_tests.addTests(loader.loadTestsFromModuleNames(module_list))
    return multiply_tests(standard_tests, external_reference_test_scenarios(),
        loader.suiteClass())
