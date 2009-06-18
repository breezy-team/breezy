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

"""Tests for Annotators."""

from bzrlib import (
    errors,
    _annotator_py,
    tests,
    )


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = [
        ('python', {'module': _annotator_py}),
    ]
    suite = loader.suiteClass()
    if CompiledAnnotator.available():
        from bzrlib import _annotator_pyx
        scenarios.append(('C', {'module': _annotator_pyx}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledAnnotator)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    result = tests.multiply_tests(standard_tests, scenarios, suite)
    return result


class _CompiledAnnotator(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._annotator_pyx
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._annotator_pyx'

CompiledAnnotator = _CompiledAnnotator()


class TestAnnotator(tests.TestCaseWithMemoryTransport):

    module = None # Set by load_tests

    fa_key = ('f-id', 'a-id')
    fb_key = ('f-id', 'b-id')
    fc_key = ('f-id', 'c-id')
    fd_key = ('f-id', 'd-id')
    fe_key = ('f-id', 'e-id')
    ff_key = ('f-id', 'f-id')

    def make_simple_text(self):
        self.repo = self.make_repository('repo')
        self.repo.lock_write()
        self.addCleanup(self.repo.unlock)
        vf = self.repo.texts
        self.vf = vf
        # This assumes nothing special happens during __init__, which may be
        # valid
        self.ann = self.module.Annotator(self.vf)
        self.repo.start_write_group()
        try:
            self.vf.add_lines(self.fa_key, [], ['simple\n', 'content\n'])
            self.vf.add_lines(self.fb_key, [self.fa_key],
                              ['simple\n', 'new content\n'])
        except:
            self.repo.abort_write_group()
            raise
        else:
            self.repo.commit_write_group()

    def make_merge_text(self):
        self.make_simple_text()
        self.repo.start_write_group()
        try:
            self.vf.add_lines(self.fc_key, [self.fa_key],
                              ['simple\n', 'from c\n', 'content\n'])
            self.vf.add_lines(self.fd_key, [self.fb_key, self.fc_key],
                              ['simple\n', 'from c\n', 'new content\n',
                               'introduced in merge\n'])
        except:
            self.repo.abort_write_group()
            raise
        else:
            self.repo.commit_write_group()

    def make_common_merge_text(self):
        """Both sides of the merge will have introduced a line."""
        self.make_simple_text()
        self.repo.start_write_group()
        try:
            self.vf.add_lines(self.fc_key, [self.fa_key],
                              ['simple\n', 'new content\n'])
            self.vf.add_lines(self.fd_key, [self.fb_key, self.fc_key],
                              ['simple\n', 'new content\n'])
        except:
            self.repo.abort_write_group()
            raise
        else:
            self.repo.commit_write_group()

    def make_many_way_common_merge_text(self):
        self.make_simple_text()
        self.repo.start_write_group()
        try:
            self.vf.add_lines(self.fc_key, [self.fa_key],
                              ['simple\n', 'new content\n'])
            self.vf.add_lines(self.fd_key, [self.fb_key, self.fc_key],
                              ['simple\n', 'new content\n'])
            self.vf.add_lines(self.fe_key, [self.fa_key],
                              ['simple\n', 'new content\n'])
            self.vf.add_lines(self.ff_key, [self.fd_key, self.fe_key],
                              ['simple\n', 'new content\n'])
        except:
            self.repo.abort_write_group()
            raise
        else:
            self.repo.commit_write_group()

    def make_merge_and_restored_text(self):
        self.make_simple_text()
        self.repo.start_write_group()
        try:
            # c reverts back to 'a' for the new content line
            self.vf.add_lines(self.fc_key, [self.fb_key],
                              ['simple\n', 'content\n'])
            # d merges 'a' and 'c', to find both claim last modified
            self.vf.add_lines(self.fd_key, [self.fa_key, self.fc_key],
                              ['simple\n', 'content\n'])
        except:
            self.repo.abort_write_group()
            raise
        else:
            self.repo.commit_write_group()

    def assertAnnotateEqual(self, expected_annotation, annotator, key):
        annotation, lines = annotator.annotate(key)
        self.assertEqual(expected_annotation, annotation)
        record = self.vf.get_record_stream([key], 'unordered', True).next()
        exp_text = record.get_bytes_as('fulltext')
        self.assertEqualDiff(exp_text, ''.join(lines))

    def test_annotate_missing(self):
        self.make_simple_text()
        self.assertRaises(errors.RevisionNotPresent,
                          self.ann.annotate, ('not', 'present'))

    def test_annotate_simple(self):
        self.make_simple_text()
        self.assertAnnotateEqual([(self.fa_key,)]*2, self.ann, self.fa_key)
        self.assertAnnotateEqual([(self.fa_key,), (self.fb_key,)],
                                 self.ann, self.fb_key)

    def test_annotate_merge_text(self):
        self.make_merge_text()
        self.assertAnnotateEqual([(self.fa_key,), (self.fc_key,),
                                  (self.fb_key,), (self.fd_key,)],
                                 self.ann, self.fd_key)

    def test_annotate_common_merge_text(self):
        self.make_common_merge_text()
        self.assertAnnotateEqual([(self.fa_key,), (self.fb_key, self.fc_key)],
                                 self.ann, self.fd_key)

    def test_annotate_many_way_common_merge_text(self):
        self.make_many_way_common_merge_text()
        self.assertAnnotateEqual([(self.fa_key,),
                                  (self.fb_key, self.fc_key, self.fe_key)],
                                 self.ann, self.ff_key)

    def test_annotate_merge_and_restored(self):
        self.make_merge_and_restored_text()
        self.assertAnnotateEqual([(self.fa_key,), (self.fa_key, self.fc_key)],
                                 self.ann, self.fd_key)

    def test_annotate_flat_simple(self):
        self.make_simple_text()
        self.assertEqual([(self.fa_key, 'simple\n'),
                          (self.fa_key, 'content\n'),
                         ], self.ann.annotate_flat(self.fa_key))
        self.assertEqual([(self.fa_key, 'simple\n'),
                          (self.fb_key, 'new content\n'),
                         ], self.ann.annotate_flat(self.fb_key))

    def test_annotate_flat_merge_and_restored_text(self):
        self.make_merge_and_restored_text()
        # fc is a simple dominator of fa
        self.assertEqual([(self.fa_key, 'simple\n'),
                          (self.fc_key, 'content\n'),
                         ], self.ann.annotate_flat(self.fd_key))

    def test_annotate_common_merge_text(self):
        self.make_common_merge_text()
        # there is no common point, so we just pick the lexicographical lowest
        # and 'b-id' comes before 'c-id'
        self.assertEqual([(self.fa_key, 'simple\n'),
                          (self.fb_key, 'new content\n'),
                         ], self.ann.annotate_flat(self.fd_key))

    def test_annotate_many_way_common_merge_text(self):
        self.make_many_way_common_merge_text()
        self.assertEqual([(self.fa_key, 'simple\n'),
                         (self.fb_key, 'new content\n')],
                         self.ann.annotate_flat(self.ff_key))


    def test_needed_keys_simple(self):
        self.make_simple_text()
        keys = self.ann._get_needed_keys(self.fb_key)
        self.assertEqual([self.fa_key, self.fb_key], sorted(keys))
        self.assertEqual({self.fa_key: 1, self.fb_key: 1},
                         self.ann._num_needed_children)

    def test_needed_keys_many(self):
        self.make_many_way_common_merge_text()
        keys = self.ann._get_needed_keys(self.ff_key)
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
        self.ann._record_annotation(self.fd_key, [self.fb_key, self.fc_key], [])
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
