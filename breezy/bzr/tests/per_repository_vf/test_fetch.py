# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tests for fetch between repositories of the same type."""

from breezy.bzr import (
    vf_search,
    )
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
    )
from breezy.tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestSource(TestCaseWithRepository):
    """Tests for/about the results of Repository._get_source."""

    scenarios = all_repository_vf_format_scenarios()

    def test_no_absent_records_in_stream_with_ghosts(self):
        # XXX: Arguably should be in per_interrepository but
        # doesn't actually gain coverage there; need a specific set of
        # permutations to cover it.
        # bug lp:376255 was reported about this.
        builder = self.make_branch_builder('repo')
        builder.start_series()
        builder.build_snapshot([b'ghost'],
                               [('add', ('', b'ROOT_ID', 'directory', ''))],
                               allow_leftmost_as_ghost=True, revision_id=b'tip')
        builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        repo = b.repository
        source = repo._get_source(repo._format)
        search = vf_search.PendingAncestryResult([b'tip'], repo)
        stream = source.get_stream(search)
        for substream_type, substream in stream:
            for record in substream:
                self.assertNotEqual('absent', record.storage_kind,
                                    "Absent record for %s" % (((substream_type,) + record.key),))
