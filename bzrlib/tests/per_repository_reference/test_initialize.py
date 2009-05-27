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


from bzrlib import (
    errors,
    )
from bzrlib.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestInitialize(TestCaseWithExternalReferenceRepository):

    def test_initialize_on_transport_ex(self):
        base = self.make_branch('base')
        network_name = base.repository._format.network_name()
        trans = self.get_transport('stacked')
        result = self.bzrdir_format.initialize_on_transport_ex(
            trans, use_existing_dir=False, create_prefix=False,
            stacked_on='../base', stack_on_pwd=base.base,
            repo_format_name=network_name)
        result_repo, a_bzrdir, require_stacking, repo_policy = result
        result_repo.unlock()
