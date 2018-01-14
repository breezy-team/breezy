# Copyright (C) 2009 Canonical Ltd
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

"""Tests for initializing a repository with external references."""


from breezy import (
    errors,
    tests,
    )
from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestInitialize(TestCaseWithExternalReferenceRepository):

    def initialize_and_check_on_transport(self, base, trans):
        network_name = base.repository._format.network_name()
        result = self.bzrdir_format.initialize_on_transport_ex(
            trans, use_existing_dir=False, create_prefix=False,
            stacked_on='../base', stack_on_pwd=base.base,
            repo_format_name=network_name)
        result_repo, a_controldir, require_stacking, repo_policy = result
        self.addCleanup(result_repo.unlock)
        self.assertEqual(1, len(result_repo._fallback_repositories))
        return result_repo

    def test_initialize_on_transport_ex(self):
        base = self.make_branch('base')
        trans = self.get_transport('stacked')
        repo = self.initialize_and_check_on_transport(base, trans)
        self.assertEqual(base.repository._format.network_name(),
                         repo._format.network_name())

    def test_remote_initialize_on_transport_ex(self):
        # All formats can be initialized appropriately over bzr://
        base = self.make_branch('base')
        trans = self.make_smart_server('stacked')
        repo = self.initialize_and_check_on_transport(base, trans)
        network_name = base.repository._format.network_name()
        self.assertEqual(network_name, repo._format.network_name())
