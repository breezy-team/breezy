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


from bzrlib.smart import server
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestDefaultStackingPolicy(TestCaseWithRepository):

    def test_sprout_from_stacked_with_short_history(self):
        builder = self.make_branch_builder('source')
        content = ['content lines\n'
                   'for the first revision\n'
                   'which is a marginal amount of content\n'
                  ]
        builder.start_series()
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('a', 'a-id', 'file', ''.join(content))),
            ])
        content.append('and some more lines for B\n')
        builder.build_snapshot('B-id', ['A-id'], [
            ('modify', ('a-id', ''.join(content)))])
        content.append('and yet even more content for C\n')
        builder.build_snapshot('C-id', ['B-id'], [
            ('modify', ('a-id', ''.join(content)))])
        builder.finish_series()
        source_b = builder.get_branch()
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        # Now copy this data into a branch, and stack on it
        # Use 'make_branch' which gives us a bzr:// branch when appropriate,
        # rather than creating a branch-on-disk
        stack_b = self.make_branch('stack-on')
        stack_b.pull(source_b, stop_revision='B-id')
        target_b = self.make_branch('target')
        target_b.set_stacked_on_url('../stack-on')
        target_b.pull(source_b, stop_revision='C-id')
        # At this point, we should have a target branch, with 1 revision, on
        # top of the source.
        final_b = target_b.bzrdir.sprout('final').open_branch()
        final_b.lock_read()
        self.addCleanup(final_b.unlock)
        self.assertEqual('C-id', final_b.last_revision())
        text_keys = [('a-id', 'A-id'), ('a-id', 'B-id'), ('a-id', 'C-id')]
        stream = final_b.repository.texts.get_record_stream(text_keys,
            'unordered', True)
        records = []
        for record in stream:
            records.append(record.key)
            if record.key == ('a-id', 'A-id'):
                self.assertEqual(''.join(content[:-2]),
                                 record.get_bytes_as('fulltext'))
            elif record.key == ('a-id', 'B-id'):
                self.assertEqual(''.join(content[:-1]),
                                 record.get_bytes_as('fulltext'))
            elif record.key == ('a-id', 'C-id'):
                self.assertEqual(''.join(content),
                                 record.get_bytes_as('fulltext'))
            else:
                self.fail('Unexpected record: %s' % (record.key,))
        self.assertEqual(text_keys, sorted(records))
