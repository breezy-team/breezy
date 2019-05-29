# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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

"""Tests for Annotators."""

from .. import (
    annotate,
    errors,
    revision,
    tests,
    )

from ..bzr import (
    knit,
    )


def load_tests(loader, standard_tests, pattern):
    """Parameterize tests for all versions of groupcompress."""
    suite, _ = tests.permute_tests_for_extension(standard_tests, loader,
                                                 'breezy._annotator_py', 'breezy._annotator_pyx')
    return suite


class TestAnnotator(tests.TestCaseWithMemoryTransport):

    module = None  # Set by load_tests

    fa_key = (b'f-id', b'a-id')
    fb_key = (b'f-id', b'b-id')
    fc_key = (b'f-id', b'c-id')
    fd_key = (b'f-id', b'd-id')
    fe_key = (b'f-id', b'e-id')
    ff_key = (b'f-id', b'f-id')

    def make_no_graph_texts(self):
        factory = knit.make_pack_factory(False, False, 2)
        self.vf = factory(self.get_transport())
        self.ann = self.module.Annotator(self.vf)
        self.vf.add_lines(self.fa_key, (), [b'simple\n', b'content\n'])
        self.vf.add_lines(self.fb_key, (), [b'simple\n', b'new content\n'])

    def make_simple_text(self):
        # TODO: all we really need is a VersionedFile instance, we'd like to
        #       avoid creating all the intermediate stuff
        factory = knit.make_pack_factory(True, True, 2)
        self.vf = factory(self.get_transport())
        # This assumes nothing special happens during __init__, which may be
        # valid
        self.ann = self.module.Annotator(self.vf)
        #  A    'simple|content|'
        #  |
        #  B    'simple|new content|'
        self.vf.add_lines(self.fa_key, [], [b'simple\n', b'content\n'])
        self.vf.add_lines(self.fb_key, [self.fa_key],
                          [b'simple\n', b'new content\n'])

    def make_merge_text(self):
        self.make_simple_text()
        #  A    'simple|content|'
        #  |\
        #  B |  'simple|new content|'
        #  | |
        #  | C  'simple|from c|content|'
        #  |/
        #  D    'simple|from c|new content|introduced in merge|'
        self.vf.add_lines(self.fc_key, [self.fa_key],
                          [b'simple\n', b'from c\n', b'content\n'])
        self.vf.add_lines(self.fd_key, [self.fb_key, self.fc_key],
                          [b'simple\n', b'from c\n', b'new content\n',
                           b'introduced in merge\n'])

    def make_common_merge_text(self):
        """Both sides of the merge will have introduced a line."""
        self.make_simple_text()
        #  A    'simple|content|'
        #  |\
        #  B |  'simple|new content|'
        #  | |
        #  | C  'simple|new content|'
        #  |/
        #  D    'simple|new content|'
        self.vf.add_lines(self.fc_key, [self.fa_key],
                          [b'simple\n', b'new content\n'])
        self.vf.add_lines(self.fd_key, [self.fb_key, self.fc_key],
                          [b'simple\n', b'new content\n'])

    def make_many_way_common_merge_text(self):
        self.make_simple_text()
        #  A-.    'simple|content|'
        #  |\ \
        #  B | |  'simple|new content|'
        #  | | |
        #  | C |  'simple|new content|'
        #  |/  |
        #  D   |  'simple|new content|'
        #  |   |
        #  |   E  'simple|new content|'
        #  |  /
        #  F-'    'simple|new content|'
        self.vf.add_lines(self.fc_key, [self.fa_key],
                          [b'simple\n', b'new content\n'])
        self.vf.add_lines(self.fd_key, [self.fb_key, self.fc_key],
                          [b'simple\n', b'new content\n'])
        self.vf.add_lines(self.fe_key, [self.fa_key],
                          [b'simple\n', b'new content\n'])
        self.vf.add_lines(self.ff_key, [self.fd_key, self.fe_key],
                          [b'simple\n', b'new content\n'])

    def make_merge_and_restored_text(self):
        self.make_simple_text()
        #  A    'simple|content|'
        #  |\
        #  B |  'simple|new content|'
        #  | |
        #  C |  'simple|content|' # reverted to A
        #   \|
        #    D  'simple|content|'
        # c reverts back to 'a' for the new content line
        self.vf.add_lines(self.fc_key, [self.fb_key],
                          [b'simple\n', b'content\n'])
        # d merges 'a' and 'c', to find both claim last modified
        self.vf.add_lines(self.fd_key, [self.fa_key, self.fc_key],
                          [b'simple\n', b'content\n'])

    def assertAnnotateEqual(self, expected_annotation, key, exp_text=None):
        annotation, lines = self.ann.annotate(key)
        self.assertEqual(expected_annotation, annotation)
        if exp_text is None:
            record = next(self.vf.get_record_stream([key], 'unordered', True))
            exp_text = record.get_bytes_as('fulltext')
        self.assertEqualDiff(exp_text, b''.join(lines))

    def test_annotate_missing(self):
        self.make_simple_text()
        self.assertRaises(errors.RevisionNotPresent,
                          self.ann.annotate, (b'not', b'present'))

    def test_annotate_simple(self):
        self.make_simple_text()
        self.assertAnnotateEqual([(self.fa_key,)] * 2, self.fa_key)
        self.assertAnnotateEqual([(self.fa_key,), (self.fb_key,)], self.fb_key)

    def test_annotate_merge_text(self):
        self.make_merge_text()
        self.assertAnnotateEqual([(self.fa_key,), (self.fc_key,),
                                  (self.fb_key,), (self.fd_key,)],
                                 self.fd_key)

    def test_annotate_common_merge_text(self):
        self.make_common_merge_text()
        self.assertAnnotateEqual([(self.fa_key,), (self.fb_key, self.fc_key)],
                                 self.fd_key)

    def test_annotate_many_way_common_merge_text(self):
        self.make_many_way_common_merge_text()
        self.assertAnnotateEqual([(self.fa_key,),
                                  (self.fb_key, self.fc_key, self.fe_key)],
                                 self.ff_key)

    def test_annotate_merge_and_restored(self):
        self.make_merge_and_restored_text()
        self.assertAnnotateEqual([(self.fa_key,), (self.fa_key, self.fc_key)],
                                 self.fd_key)

    def test_annotate_flat_simple(self):
        self.make_simple_text()
        self.assertEqual([(self.fa_key, b'simple\n'),
                          (self.fa_key, b'content\n'),
                          ], self.ann.annotate_flat(self.fa_key))
        self.assertEqual([(self.fa_key, b'simple\n'),
                          (self.fb_key, b'new content\n'),
                          ], self.ann.annotate_flat(self.fb_key))

    def test_annotate_flat_merge_and_restored_text(self):
        self.make_merge_and_restored_text()
        # fc is a simple dominator of fa
        self.assertEqual([(self.fa_key, b'simple\n'),
                          (self.fc_key, b'content\n'),
                          ], self.ann.annotate_flat(self.fd_key))

    def test_annotate_common_merge_text(self):
        self.make_common_merge_text()
        # there is no common point, so we just pick the lexicographical lowest
        # and b'b-id' comes before b'c-id'
        self.assertEqual([(self.fa_key, b'simple\n'),
                          (self.fb_key, b'new content\n'),
                          ], self.ann.annotate_flat(self.fd_key))

    def test_annotate_many_way_common_merge_text(self):
        self.make_many_way_common_merge_text()
        self.assertEqual([(self.fa_key, b'simple\n'),
                          (self.fb_key, b'new content\n')],
                         self.ann.annotate_flat(self.ff_key))

    def test_annotate_flat_respects_break_ann_tie(self):
        seen = set()

        def custom_tiebreaker(annotated_lines):
            self.assertEqual(2, len(annotated_lines))
            left = annotated_lines[0]
            self.assertEqual(2, len(left))
            self.assertEqual(b'new content\n', left[1])
            right = annotated_lines[1]
            self.assertEqual(2, len(right))
            self.assertEqual(b'new content\n', right[1])
            seen.update([left[0], right[0]])
            # Our custom tiebreaker takes the *largest* value, rather than
            # the *smallest* value
            if left[0] < right[0]:
                return right
            else:
                return left
        self.overrideAttr(annotate, '_break_annotation_tie', custom_tiebreaker)
        self.make_many_way_common_merge_text()
        self.assertEqual([(self.fa_key, b'simple\n'),
                          (self.fe_key, b'new content\n')],
                         self.ann.annotate_flat(self.ff_key))
        # Calls happen in set iteration order but should keys should be seen
        self.assertEqual({self.fb_key, self.fc_key, self.fe_key}, seen)

    def test_needed_keys_simple(self):
        self.make_simple_text()
        keys, ann_keys = self.ann._get_needed_keys(self.fb_key)
        self.assertEqual([self.fa_key, self.fb_key], sorted(keys))
        self.assertEqual({self.fa_key: 1, self.fb_key: 1},
                         self.ann._num_needed_children)
        self.assertEqual(set(), ann_keys)

    def test_needed_keys_many(self):
        self.make_many_way_common_merge_text()
        keys, ann_keys = self.ann._get_needed_keys(self.ff_key)
        self.assertEqual([self.fa_key, self.fb_key, self.fc_key,
                          self.fd_key, self.fe_key, self.ff_key,
                          ], sorted(keys))
        self.assertEqual({self.fa_key: 3,
                          self.fb_key: 1,
                          self.fc_key: 1,
                          self.fd_key: 1,
                          self.fe_key: 1,
                          self.ff_key: 1,
                          }, self.ann._num_needed_children)
        self.assertEqual(set(), ann_keys)

    def test_needed_keys_with_special_text(self):
        self.make_many_way_common_merge_text()
        spec_key = (b'f-id', revision.CURRENT_REVISION)
        spec_text = b'simple\nnew content\nlocally modified\n'
        self.ann.add_special_text(spec_key, [self.fd_key, self.fe_key],
                                  spec_text)
        keys, ann_keys = self.ann._get_needed_keys(spec_key)
        self.assertEqual([self.fa_key, self.fb_key, self.fc_key,
                          self.fd_key, self.fe_key,
                          ], sorted(keys))
        self.assertEqual([spec_key], sorted(ann_keys))

    def test_needed_keys_with_parent_texts(self):
        self.make_many_way_common_merge_text()
        # If 'D' and 'E' are already annotated, we don't need to extract all
        # the texts
        #  D   |  'simple|new content|'
        #  |   |
        #  |   E  'simple|new content|'
        #  |  /
        #  F-'    'simple|new content|'
        self.ann._parent_map[self.fd_key] = (self.fb_key, self.fc_key)
        self.ann._text_cache[self.fd_key] = [b'simple\n', b'new content\n']
        self.ann._annotations_cache[self.fd_key] = [
            (self.fa_key,),
            (self.fb_key, self.fc_key),
            ]
        self.ann._parent_map[self.fe_key] = (self.fa_key,)
        self.ann._text_cache[self.fe_key] = [b'simple\n', b'new content\n']
        self.ann._annotations_cache[self.fe_key] = [
            (self.fa_key,),
            (self.fe_key,),
            ]
        keys, ann_keys = self.ann._get_needed_keys(self.ff_key)
        self.assertEqual([self.ff_key], sorted(keys))
        self.assertEqual({self.fd_key: 1,
                          self.fe_key: 1,
                          self.ff_key: 1,
                          }, self.ann._num_needed_children)
        self.assertEqual([], sorted(ann_keys))

    def test_record_annotation_removes_texts(self):
        self.make_many_way_common_merge_text()
        # Populate the caches
        for x in self.ann._get_needed_texts(self.ff_key):
            continue
        self.assertEqual({self.fa_key: 3,
                          self.fb_key: 1,
                          self.fc_key: 1,
                          self.fd_key: 1,
                          self.fe_key: 1,
                          self.ff_key: 1,
                          }, self.ann._num_needed_children)
        self.assertEqual([self.fa_key, self.fb_key, self.fc_key,
                          self.fd_key, self.fe_key, self.ff_key,
                          ], sorted(self.ann._text_cache.keys()))
        self.ann._record_annotation(self.fa_key, [], [])
        self.ann._record_annotation(self.fb_key, [self.fa_key], [])
        self.assertEqual({self.fa_key: 2,
                          self.fb_key: 1,
                          self.fc_key: 1,
                          self.fd_key: 1,
                          self.fe_key: 1,
                          self.ff_key: 1,
                          }, self.ann._num_needed_children)
        self.assertTrue(self.fa_key in self.ann._text_cache)
        self.assertTrue(self.fa_key in self.ann._annotations_cache)
        self.ann._record_annotation(self.fc_key, [self.fa_key], [])
        self.ann._record_annotation(
            self.fd_key, [self.fb_key, self.fc_key], [])
        self.assertEqual({self.fa_key: 1,
                          self.fb_key: 0,
                          self.fc_key: 0,
                          self.fd_key: 1,
                          self.fe_key: 1,
                          self.ff_key: 1,
                          }, self.ann._num_needed_children)
        self.assertTrue(self.fa_key in self.ann._text_cache)
        self.assertTrue(self.fa_key in self.ann._annotations_cache)
        self.assertFalse(self.fb_key in self.ann._text_cache)
        self.assertFalse(self.fb_key in self.ann._annotations_cache)
        self.assertFalse(self.fc_key in self.ann._text_cache)
        self.assertFalse(self.fc_key in self.ann._annotations_cache)

    def test_annotate_special_text(self):
        # Things like WT and PreviewTree want to annotate an arbitrary text
        # ('current:') so we need a way to add that to the group of files to be
        # annotated.
        self.make_many_way_common_merge_text()
        #  A-.    'simple|content|'
        #  |\ \
        #  B | |  'simple|new content|'
        #  | | |
        #  | C |  'simple|new content|'
        #  |/  |
        #  D   |  'simple|new content|'
        #  |   |
        #  |   E  'simple|new content|'
        #  |  /
        #  SPEC   'simple|new content|locally modified|'
        spec_key = (b'f-id', revision.CURRENT_REVISION)
        spec_text = b'simple\nnew content\nlocally modified\n'
        self.ann.add_special_text(spec_key, [self.fd_key, self.fe_key],
                                  spec_text)
        self.assertAnnotateEqual([(self.fa_key,),
                                  (self.fb_key, self.fc_key, self.fe_key),
                                  (spec_key,),
                                  ], spec_key,
                                 exp_text=spec_text)

    def test_no_graph(self):
        self.make_no_graph_texts()
        self.assertAnnotateEqual([(self.fa_key,),
                                  (self.fa_key,),
                                  ], self.fa_key)
        self.assertAnnotateEqual([(self.fb_key,),
                                  (self.fb_key,),
                                  ], self.fb_key)
