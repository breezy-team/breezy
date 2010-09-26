# Copyright (C) 2010 Canonical Ltd
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

"""Tests for VersionedFile classes"""

from bzrlib import (
    errors,
    groupcompress,
    multiparent,
    tests,
    versionedfile,
    )


class Test_MPDiffGenerator(tests.TestCaseWithMemoryTransport):
    # Should this be a per vf test?

    def make_vf(self):
        t = self.get_transport('')
        factory = groupcompress.make_pack_factory(True, True, 1)
        return factory(t)

    def make_three_vf(self):
        vf = self.make_vf()
        vf.add_lines(('one',), (), ['first\n'])
        vf.add_lines(('two',), [('one',)], ['first\n', 'second\n'])
        vf.add_lines(('three',), [('one',), ('two',)],
                    ['first\n', 'second\n', 'third\n'])
        return vf

    def test_finds_parents(self):
        vf = self.make_three_vf()
        gen = versionedfile._MPDiffGenerator(vf, [('three',)])
        needed_keys, refcount = gen._find_needed_keys()
        self.assertEqual(sorted([('one',), ('two',), ('three',)]),
                         sorted(needed_keys))
        self.assertEqual({('one',): 1, ('two',): 1}, refcount)

    def test_ignores_ghost_parents(self):
        # If a parent is a ghost, it is just ignored
        vf = self.make_vf()
        vf.add_lines(('two',), [('one',)], ['first\n', 'second\n'])
        gen = versionedfile._MPDiffGenerator(vf, [('two',)])
        needed_keys, refcount = gen._find_needed_keys()
        self.assertEqual(sorted([('two',)]), sorted(needed_keys))
        # It is returned, but we don't really care as we won't extract it
        self.assertEqual({('one',): 1}, refcount)
        self.assertEqual([('one',)], sorted(gen.ghost_parents))
        self.assertEqual([], sorted(gen.present_parents))

    def test_raises_on_ghost_keys(self):
        # If the requested key is a ghost, then we have a problem
        vf = self.make_vf()
        gen = versionedfile._MPDiffGenerator(vf, [('one',)])
        self.assertRaises(errors.RevisionNotPresent,
                          gen._find_needed_keys)

    def test_refcount_multiple_children(self):
        vf = self.make_three_vf()
        gen = versionedfile._MPDiffGenerator(vf, [('two',), ('three',)])
        needed_keys, refcount = gen._find_needed_keys()
        self.assertEqual(sorted([('one',), ('two',), ('three',)]),
                         sorted(needed_keys))
        self.assertEqual({('one',): 2, ('two',): 1}, refcount)
        self.assertEqual([('one',)], sorted(gen.present_parents))

    def test_process_contents(self):
        vf = self.make_three_vf()
        gen = versionedfile._MPDiffGenerator(vf, [('two',), ('three',)])
        gen._find_needed_keys()
        self.assertEqual({('two',): (('one',),),
                          ('three',): (('one',), ('two',))},
                         gen.parent_map)
        self.assertEqual({('one',): 2, ('two',): 1}, gen.refcounts)
        self.assertEqual(sorted([('one',), ('two',), ('three',)]),
                         sorted(gen.needed_keys))
        stream = vf.get_record_stream(gen.needed_keys, 'topological', True)
        record = stream.next()
        self.assertEqual(('one',), record.key)
        # one is not needed in the output, but it is needed by children. As
        # such, it should end up in the various caches
        gen._process_one_record(record.key, record.get_bytes_as('chunked'))
        # The chunks should be cached, the refcount untouched
        self.assertEqual([('one',)], gen.chunks.keys())
        self.assertEqual({('one',): 2, ('two',): 1}, gen.refcounts)
        self.assertEqual([], gen.diffs.keys())
        # Next we get 'two', which is something we output, but also needed for
        # three
        record = stream.next()
        self.assertEqual(('two',), record.key)
        gen._process_one_record(record.key, record.get_bytes_as('chunked'))
        # Both are now cached, and the diff for two has been extracted, and
        # one's refcount has been updated. two has been removed from the
        # parent_map
        self.assertEqual(sorted([('one',), ('two',)]),
                         sorted(gen.chunks.keys()))
        self.assertEqual({('one',): 1, ('two',): 1}, gen.refcounts)
        self.assertEqual([('two',)], gen.diffs.keys())
        self.assertEqual({('three',): (('one',), ('two',))},
                         gen.parent_map)
        # Finally 'three', which allows us to remove all parents from the
        # caches
        record = stream.next()
        self.assertEqual(('three',), record.key)
        gen._process_one_record(record.key, record.get_bytes_as('chunked'))
        # Both are now cached, and the diff for two has been extracted, and
        # one's refcount has been updated
        self.assertEqual([], gen.chunks.keys())
        self.assertEqual({}, gen.refcounts)
        self.assertEqual(sorted([('two',), ('three',)]),
                         sorted(gen.diffs.keys()))

    def test_compute_diffs(self):
        vf = self.make_three_vf()
        # The content is in the order requested, even if it isn't topological
        gen = versionedfile._MPDiffGenerator(vf, [('two',), ('three',),
                                                  ('one',)])
        diffs = gen.compute_diffs()
        expected_diffs = [
            multiparent.MultiParent([multiparent.ParentText(0, 0, 0, 1),
                                     multiparent.NewText(['second\n'])]),
            multiparent.MultiParent([multiparent.ParentText(1, 0, 0, 2),
                                     multiparent.NewText(['third\n'])]),
            multiparent.MultiParent([multiparent.NewText(['first\n'])]),
            ]
        self.assertEqual(expected_diffs, diffs)
