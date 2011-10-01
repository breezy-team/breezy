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

from bzrlib import (
    errors,
    knit,
    )
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
        self.stacked_repo = self.make_referring('referring', self.base_repo)

    def make_simple_split(self):
        """Set up the repositories so that everything is in base except F"""
        self.base_repo.fetch(self.all_repo, revision_id='G')
        self.stacked_repo.fetch(self.all_repo, revision_id='F')

    def make_complex_split(self):
        """intermix the revisions so that base holds left stacked holds right.

        base will hold
            A B D F (and C because it is a parent of D)
        referring will hold
            C E G (only)
        """
        self.base_repo.fetch(self.all_repo, revision_id='B')
        self.stacked_repo.fetch(self.all_repo, revision_id='C')
        self.base_repo.fetch(self.all_repo, revision_id='F')
        self.stacked_repo.fetch(self.all_repo, revision_id='G')

    def test_unordered_fetch_simple_split(self):
        self.make_simple_split()
        keys = [('f-id', r) for r in 'ABCDF']
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

    def test_unordered_fetch_complex_split(self):
        self.make_complex_split()
        keys = [('f-id', r) for r in 'ABCDEG']
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

    def test_ordered_no_closure(self):
        self.make_complex_split()
        # Topological ordering allows B & C and D & E to be returned with
        # either one first, so the required ordering is:
        # [A (B C) (D E) G]
        keys = [('f-id', r) for r in 'ABCDEG']
        alt_1 = [('f-id', r) for r in 'ACBDEG']
        alt_2 = [('f-id', r) for r in 'ABCEDG']
        alt_3 = [('f-id', r) for r in 'ACBEDG']
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(
            keys, 'topological', False)
        record_keys = []
        for record in stream:
            if record.storage_kind == 'absent':
                raise ValueError('absent record: %s' % (record.key,))
            record_keys.append(record.key)
        self.assertTrue(record_keys in (keys, alt_1, alt_2, alt_3))

    def test_ordered_fulltext_simple(self):
        self.make_simple_split()
        # This is a common case in asking to annotate a file that exists on a
        # stacked branch.
        # See https://bugs.launchpad.net/bzr/+bug/393366
        # Topological ordering allows B & C and D & E to be returned with
        # either one first, so the required ordering is:
        # [A (B C) D F]
        keys = [('f-id', r) for r in 'ABCDF']
        alt_1 = [('f-id', r) for r in 'ACBDF']
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(
            keys, 'topological', True)
        record_keys = []
        for record in stream:
            if record.storage_kind == 'absent':
                raise ValueError('absent record: %s' % (record.key,))
            record_keys.append(record.key)
        self.assertTrue(record_keys in (keys, alt_1))

    def test_ordered_fulltext_complex(self):
        self.make_complex_split()
        # Topological ordering allows B & C and D & E to be returned with
        # either one first, so the required ordering is:
        # [A (B C) (D E) G]
        keys = [('f-id', r) for r in 'ABCDEG']
        alt_1 = [('f-id', r) for r in 'ACBDEG']
        alt_2 = [('f-id', r) for r in 'ABCEDG']
        alt_3 = [('f-id', r) for r in 'ACBEDG']
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(
            keys, 'topological', True)
        record_keys = []
        for record in stream:
            if record.storage_kind == 'absent':
                raise ValueError('absent record: %s' % (record.key,))
            record_keys.append(record.key)
        # Note that currently --2a format repositories do this correctly, but
        # KnitPack format repositories do not.
        if isinstance(self.stacked_repo.texts, knit.KnitVersionedFiles):
            # See https://bugs.launchpad.net/bzr/+bug/399884
            self.expectFailure('KVF does not weave fulltexts from fallback'
                ' repositories to preserve perfect order',
                self.assertTrue, record_keys in (keys, alt_1, alt_2, alt_3))
        self.assertTrue(record_keys in (keys, alt_1, alt_2, alt_3))
