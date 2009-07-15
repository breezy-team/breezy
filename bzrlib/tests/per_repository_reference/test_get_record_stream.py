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

"""Tests that get_record_stream() behaves itself properly when stacked."""

from bzrlib import errors
from bzrlib.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestGetRecordStream(TestCaseWithExternalReferenceRepository):

    def setUp(self):
        super(TestGetRecordStream, self).setUp()
        builder = self.make_branch_builder('all')
        builder.start_series()
        # Graph of revisions:
        #
        #   A
        #   |\
        #   B C
        #   |/|
        #   D E
        #   |\|
        #   F G
        # These can be split up among the different repos as desired
        #

        builder.build_snapshot('A', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'f-id', 'file', 'initial content\n')),
            ])
        builder.build_snapshot('B', ['A'], [
            ('modify', ('f-id', 'initial content\n'
                                'and B content\n')),
            ])
        builder.build_snapshot('C', ['A'], [
            ('modify', ('f-id', 'initial content\n'
                                'and C content\n')),
            ])
        builder.build_snapshot('D', ['B', 'C'], [
            ('modify', ('f-id', 'initial content\n'
                                'and B content\n'
                                'and C content\n')),
            ])
        builder.build_snapshot('E', ['C'], [
            ('modify', ('f-id', 'initial content\n'
                                'and C content\n'
                                'and E content\n')),
            ])
        builder.build_snapshot('F', ['D'], [
            ('modify', ('f-id', 'initial content\n'
                                'and B content\n'
                                'and C content\n'
                                'and F content\n')),
            ])
        builder.build_snapshot('G', ['E', 'D'], [
            ('modify', ('f-id', 'initial content\n'
                                'and B content\n'
                                'and C content\n'
                                'and E content\n')),
            ])
        builder.finish_series()
        self.all_repo = builder.get_branch().repository
        self.all_repo.lock_read()
        self.addCleanup(self.all_repo.unlock)
        self.base_repo = self.make_repository('base')
        self.stacked_repo = self.make_referring('referring', 'base')

    def make_stacked_hold_f(self):
        """Set up the repositories so that everything is in base except F"""
        self.base_repo.fetch(self.all_repo, revision_id='G')
        self.stacked_repo.fetch(self.all_repo, revision_id='F')

    def test_unordered_fetch(self):
        self.make_stacked_hold_f()
        keys = [('f-id', r) for r in ['A', 'B', 'C', 'D', 'F']]
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(
            keys, 'unordered', False)
        record_keys = set()
        for record in stream:
            if record.storage_kind == 'absent':
                raise ValueError('absent record: %s' % (record.key,))
            record_keys.add(record.key)
        # everything should be present, we don't care about the order
        self.assertEqual(keys, sorted(record_keys))
