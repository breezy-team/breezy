# Copyright (C) 2008 Canonical Ltd
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

"""Tests for check on a repository with external references."""

import bzrlib.ui
from bzrlib import errors
from bzrlib.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestCheck(TestCaseWithExternalReferenceRepository):

    def test_check_file_graph_across_external_boundary_ok(self):
        tree = self.make_branch_and_tree('base')
        self.build_tree(['base/file'])
        tree.add(['file'], ['file-id'])
        rev1_id = tree.commit('one')
        referring = self.make_branch_and_tree('referring')
        readonly_base = self.readonly_repository('base')
        referring.branch.repository.add_fallback_repository(readonly_base)
        self.build_tree_contents([('referring/file', 'change')])
        rev2_id = referring.commit('two')
        check_result = referring.branch.repository.check(
            referring.branch.repository.all_revision_ids())
        check_result.report_results(verbose=False)
        log = self._get_log(keep_log_file=True)
        self.assertFalse("inconsistent parents" in log)
