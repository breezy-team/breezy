# Copyright (C) 2008-2011 Canonical Ltd
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

from brzlib import (
    errors,
    remote,
    urlutils,
    )
from brzlib.controldir import ControlDir
from brzlib.tests import multiply_tests
from brzlib.tests.per_repository import (
    all_repository_format_scenarios,
    TestCaseWithRepository,
    )


class TestCaseWithExternalReferenceRepository(TestCaseWithRepository):

    def make_referring(self, relpath, a_repository):
        """Get a new repository that refers to a_repository.

        :param relpath: The path to create the repository at.
        :param a_repository: A repository to refer to.
        """
        repo = self.make_repository(relpath)
        repo.add_fallback_repository(self.readonly_repository(a_repository))
        return repo

    def readonly_repository(self, repo):
        relpath = urlutils.basename(repo.bzrdir.user_url.rstrip('/'))
        return ControlDir.open_from_transport(
            self.get_readonly_transport(relpath)).open_repository()


class TestCorrectFormat(TestCaseWithExternalReferenceRepository):

    def test_repository_format(self):
        # make sure the repository on tree.branch is of the desired format,
        # because developers use this api to setup the tree, branch and
        # repository for their tests: having it not give the right repository
        # type would invalidate the tests.
        tree = self.make_branch_and_tree('repo')
        repo = self.make_referring('referring', tree.branch.repository)
        self.assertIsInstance(repo._format,
            self.repository_format.__class__)


class TestIncompatibleStacking(TestCaseWithRepository):

    def make_repo_and_incompatible_fallback(self):
        referring = self.make_repository('referring')
        if referring._format.supports_chks:
            different_fmt = '1.9'
        else:
            different_fmt = '2a'
        fallback = self.make_repository('fallback', format=different_fmt)
        return referring, fallback

    def test_add_fallback_repository_rejects_incompatible(self):
        # Repository.add_fallback_repository raises IncompatibleRepositories
        # if you take two repositories in different serializations and try to
        # stack them.
        referring, fallback = self.make_repo_and_incompatible_fallback()
        self.assertRaises(errors.IncompatibleRepositories,
                referring.add_fallback_repository, fallback)

    def test_add_fallback_doesnt_leave_fallback_locked(self):
        # Bug #835035. If the referring repository is locked, it wants to lock
        # the fallback repository. But if they are incompatible, the referring
        # repository won't take ownership of the fallback, and thus should not
        # leave the repository in a locked state.
        referring, fallback = self.make_repo_and_incompatible_fallback()
        self.addCleanup(referring.lock_read().unlock)
        # Assert precondition.
        self.assertFalse(fallback.is_locked())
        # Assert action.
        self.assertRaises(errors.IncompatibleRepositories,
                referring.add_fallback_repository, fallback)
        # Assert postcondition.
        self.assertFalse(fallback.is_locked())


def external_reference_test_scenarios():
    """Generate test scenarios for repositories supporting external references.
    """
    result = []
    for test_name, scenario_info in all_repository_format_scenarios():
        format = scenario_info['repository_format']
        if (isinstance(format, remote.RemoteRepositoryFormat)
            or format.supports_external_lookups):
            result.append((test_name, scenario_info))
    return result


def load_tests(standard_tests, module, loader):
    module_list = [
        'brzlib.tests.per_repository_reference.test_add_inventory',
        'brzlib.tests.per_repository_reference.test_add_revision',
        'brzlib.tests.per_repository_reference.test_add_signature_text',
        'brzlib.tests.per_repository_reference.test_all_revision_ids',
        'brzlib.tests.per_repository_reference.test_break_lock',
        'brzlib.tests.per_repository_reference.test_check',
        'brzlib.tests.per_repository_reference.test_commit_with_stacking',
        'brzlib.tests.per_repository_reference.test_default_stacking',
        'brzlib.tests.per_repository_reference.test_fetch',
        'brzlib.tests.per_repository_reference.test_get_record_stream',
        'brzlib.tests.per_repository_reference.test_get_rev_id_for_revno',
        'brzlib.tests.per_repository_reference.test_graph',
        'brzlib.tests.per_repository_reference.test_initialize',
        'brzlib.tests.per_repository_reference.test__make_parents_provider',
        'brzlib.tests.per_repository_reference.test_unlock',
        ]
    # Parameterize per_repository_reference test modules by format.
    standard_tests.addTests(loader.loadTestsFromModuleNames(module_list))
    return multiply_tests(standard_tests, external_reference_test_scenarios(),
        loader.suiteClass())
