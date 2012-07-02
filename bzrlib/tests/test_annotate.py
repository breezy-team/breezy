# Copyright (C) 2006-2009, 2011 Canonical Ltd
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

"""Whitebox tests for annotate functionality."""

import codecs
from cStringIO import StringIO

from bzrlib import (
    annotate,
    symbol_versioning,
    tests,
    )


def annotation(text):
    return [tuple(l.split(' ', 1)) for l in text.splitlines(True)]


parent_1 = annotation("""\
rev1 a
rev2 b
rev3 c
rev4 d
rev5 e
""")


parent_2 = annotation("""\
rev1 a
rev3 c
rev4 d
rev6 f
rev7 e
rev8 h
""")


expected_2_1 = annotation("""\
rev1 a
blahblah b
rev3 c
rev4 d
rev7 e
""")


# a: in both, same value, kept
# b: in 1, kept
# c: in both, same value, kept
# d: in both, same value, kept
# e: 1 and 2 disagree, so it goes to blahblah
# f: in 2, but not in new, so ignored
# g: not in 1 or 2, so it goes to blahblah
# h: only in parent 2, so 2 gets it
expected_1_2_2 = annotation("""\
rev1 a
rev2 b
rev3 c
rev4 d
blahblah e
blahblah g
rev8 h
""")


new_1 = """\
a
b
c
d
e
""".splitlines(True)

expected_1 = annotation("""\
blahblah a
blahblah b
blahblah c
blahblah d
blahblah e
""")


new_2 = """\
a
b
c
d
e
g
h
""".splitlines(True)


# For the 'duplicate' series, both sides introduce the same change, which then
# gets merged around. The last-modified should properly reflect this.
# We always change the fourth line so that the file is properly tracked as
# being modified in each revision. In reality, this probably would happen over
# many revisions, and it would be a different line that changes.
# BASE
#  |\
#  A B  # line should be annotated as new for A and B
#  |\|
#  C D  # line should 'converge' and say A
#  |/
#  E    # D should supersede A and stay as D (not become E because C references
#         A)
duplicate_base = annotation("""\
rev-base first
rev-base second
rev-base third
rev-base fourth-base
""")

duplicate_A = annotation("""\
rev-base first
rev-A alt-second
rev-base third
rev-A fourth-A
""")

duplicate_B = annotation("""\
rev-base first
rev-B alt-second
rev-base third
rev-B fourth-B
""")

duplicate_C = annotation("""\
rev-base first
rev-A alt-second
rev-base third
rev-C fourth-C
""")

duplicate_D = annotation("""\
rev-base first
rev-A alt-second
rev-base third
rev-D fourth-D
""")

duplicate_E = annotation("""\
rev-base first
rev-A alt-second
rev-base third
rev-E fourth-E
""")


class TestAnnotate(tests.TestCaseWithTransport):

    def create_merged_trees(self):
        """create 2 trees with merges between them.

        rev-1 --+
         |      |
        rev-2  rev-1_1_1
         |      |
         +------+
         |
        rev-3
        """
        builder = self.make_branch_builder('branch')
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('a', 'a-id', 'file', 'first\n')),
            ], timestamp=1166046000.00, timezone=0, committer="joe@foo.com")
        builder.build_snapshot('rev-2', ['rev-1'], [
            ('modify', ('a-id', 'first\nsecond\n')),
            ], timestamp=1166046001.00, timezone=0, committer="joe@foo.com")
        builder.build_snapshot('rev-1_1_1', ['rev-1'], [
            ('modify', ('a-id', 'first\nthird\n')),
            ], timestamp=1166046002.00, timezone=0, committer="barry@foo.com")
        builder.build_snapshot('rev-3', ['rev-2', 'rev-1_1_1'], [
            ('modify', ('a-id', 'first\nsecond\nthird\n')),
            ], timestamp=1166046003.00, timezone=0, committer="sal@foo.com")
        return builder

    def create_deeply_merged_trees(self):
        """Create some trees with a more complex merge history.

        rev-1 --+
         |      |
        rev-2  rev-1_1_1 --+
         |      |          |
         +------+          |
         |      |          |
        rev-3  rev-1_1_2  rev-1_2_1 ------+
         |      |          |              |
         +------+          |              |
         |                 |              |
        rev-4             rev-1_2_2  rev-1_3_1
         |                 |              |
         +-----------------+              |
         |                                |
        rev-5                             |
         |                                |
         +--------------------------------+
         |
        rev-6
        """
        builder = self.create_merged_trees()
        builder.build_snapshot('rev-1_1_2', ['rev-1_1_1'], [])
        builder.build_snapshot('rev-4', ['rev-3', 'rev-1_1_2'], [])
        builder.build_snapshot('rev-1_2_1', ['rev-1_1_1'], [
            ('modify', ('a-id', 'first\nthird\nfourth\n')),
            ], timestamp=1166046003.00, timezone=0, committer="jerry@foo.com")
        builder.build_snapshot('rev-1_2_2', ['rev-1_2_1'], [],
            timestamp=1166046004.00, timezone=0, committer="jerry@foo.com")
        builder.build_snapshot('rev-5', ['rev-4', 'rev-1_2_2'], [
            ('modify', ('a-id', 'first\nsecond\nthird\nfourth\n')),
            ], timestamp=1166046004.00, timezone=0, committer="jerry@foo.com")
        builder.build_snapshot('rev-1_3_1', ['rev-1_2_1'], [
            ('modify', ('a-id', 'first\nthird\nfourth\nfifth\nsixth\n')),
            ], timestamp=1166046005.00, timezone=0, committer="george@foo.com")
        builder.build_snapshot('rev-6', ['rev-5', 'rev-1_3_1'], [
            ('modify', ('a-id',
                        'first\nsecond\nthird\nfourth\nfifth\nsixth\n')),
            ])
        return builder

    def create_duplicate_lines_tree(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        self.addCleanup(builder.finish_series)
        base_text = ''.join(l for r, l in duplicate_base)
        a_text = ''.join(l for r, l in duplicate_A)
        b_text = ''.join(l for r, l in duplicate_B)
        c_text = ''.join(l for r, l in duplicate_C)
        d_text = ''.join(l for r, l in duplicate_D)
        e_text = ''.join(l for r, l in duplicate_E)
        builder.build_snapshot('rev-base', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', base_text)),
            ])
        builder.build_snapshot('rev-A', ['rev-base'], [
            ('modify', ('file-id', a_text))])
        builder.build_snapshot('rev-B', ['rev-base'], [
            ('modify', ('file-id', b_text))])
        builder.build_snapshot('rev-C', ['rev-A'], [
            ('modify', ('file-id', c_text))])
        builder.build_snapshot('rev-D', ['rev-B', 'rev-A'], [
            ('modify', ('file-id', d_text))])
        builder.build_snapshot('rev-E', ['rev-C', 'rev-D'], [
            ('modify', ('file-id', e_text))])
        return builder

    def assertAnnotateEqualDiff(self, actual, expected):
        if actual != expected:
            # Create an easier to understand diff when the lines don't actually
            # match
            self.assertEqualDiff(''.join('\t'.join(l) for l in expected),
                                 ''.join('\t'.join(l) for l in actual))

    def assertBranchAnnotate(self, expected, branch, file_id, revision_id,
            verbose=False, full=False, show_ids=False):
        tree = branch.repository.revision_tree(revision_id)
        to_file = StringIO()
        annotate.annotate_file_tree(tree, file_id, to_file,
            verbose=verbose, full=full, show_ids=show_ids, branch=branch)
        self.assertAnnotateEqualDiff(to_file.getvalue(), expected)

    def assertRepoAnnotate(self, expected, repo, file_id, revision_id):
        """Assert that the revision is properly annotated."""
        actual = list(repo.revision_tree(revision_id).annotate_iter(file_id))
        self.assertAnnotateEqualDiff(actual, expected)

    def test_annotate_duplicate_lines(self):
        # XXX: Should this be a per_repository test?
        builder = self.create_duplicate_lines_tree()
        repo = builder.get_branch().repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertRepoAnnotate(duplicate_base, repo, 'file-id', 'rev-base')
        self.assertRepoAnnotate(duplicate_A, repo, 'file-id', 'rev-A')
        self.assertRepoAnnotate(duplicate_B, repo, 'file-id', 'rev-B')
        self.assertRepoAnnotate(duplicate_C, repo, 'file-id', 'rev-C')
        self.assertRepoAnnotate(duplicate_D, repo, 'file-id', 'rev-D')
        self.assertRepoAnnotate(duplicate_E, repo, 'file-id', 'rev-E')

    def test_annotate_shows_dotted_revnos(self):
        builder = self.create_merged_trees()

        self.assertBranchAnnotate('1     joe@foo | first\n'
                                  '2     joe@foo | second\n'
                                  '1.1.1 barry@f | third\n',
                                  builder.get_branch(), 'a-id', 'rev-3')

    def test_annotate_limits_dotted_revnos(self):
        """Annotate should limit dotted revnos to a depth of 12"""
        builder = self.create_deeply_merged_trees()

        self.assertBranchAnnotate('1     joe@foo | first\n'
                                  '2     joe@foo | second\n'
                                  '1.1.1 barry@f | third\n'
                                  '1.2.1 jerry@f | fourth\n'
                                  '1.3.1 george@ | fifth\n'
                                  '              | sixth\n',
                                  builder.get_branch(), 'a-id', 'rev-6',
                                  verbose=False, full=False)

        self.assertBranchAnnotate('1     joe@foo | first\n'
                                  '2     joe@foo | second\n'
                                  '1.1.1 barry@f | third\n'
                                  '1.2.1 jerry@f | fourth\n'
                                  '1.3.1 george@ | fifth\n'
                                  '1.3.1 george@ | sixth\n',
                                  builder.get_branch(), 'a-id', 'rev-6',
                                  verbose=False, full=True)

        # verbose=True shows everything, the full revno, user id, and date
        self.assertBranchAnnotate('1     joe@foo.com    20061213 | first\n'
                                  '2     joe@foo.com    20061213 | second\n'
                                  '1.1.1 barry@foo.com  20061213 | third\n'
                                  '1.2.1 jerry@foo.com  20061213 | fourth\n'
                                  '1.3.1 george@foo.com 20061213 | fifth\n'
                                  '                              | sixth\n',
                                  builder.get_branch(), 'a-id', 'rev-6',
                                  verbose=True, full=False)

        self.assertBranchAnnotate('1     joe@foo.com    20061213 | first\n'
                                  '2     joe@foo.com    20061213 | second\n'
                                  '1.1.1 barry@foo.com  20061213 | third\n'
                                  '1.2.1 jerry@foo.com  20061213 | fourth\n'
                                  '1.3.1 george@foo.com 20061213 | fifth\n'
                                  '1.3.1 george@foo.com 20061213 | sixth\n',
                                  builder.get_branch(), 'a-id', 'rev-6',
                                  verbose=True, full=True)

    def test_annotate_uses_branch_context(self):
        """Dotted revnos should use the Branch context.

        When annotating a non-mainline revision, the annotation should still
        use dotted revnos from the mainline.
        """
        builder = self.create_deeply_merged_trees()

        self.assertBranchAnnotate('1     joe@foo | first\n'
                                  '1.1.1 barry@f | third\n'
                                  '1.2.1 jerry@f | fourth\n'
                                  '1.3.1 george@ | fifth\n'
                                  '              | sixth\n',
                                  builder.get_branch(), 'a-id', 'rev-1_3_1',
                                  verbose=False, full=False)

    def test_annotate_show_ids(self):
        builder = self.create_deeply_merged_trees()

        # It looks better with real revision ids :)
        self.assertBranchAnnotate('    rev-1 | first\n'
                                  '    rev-2 | second\n'
                                  'rev-1_1_1 | third\n'
                                  'rev-1_2_1 | fourth\n'
                                  'rev-1_3_1 | fifth\n'
                                  '          | sixth\n',
                                  builder.get_branch(), 'a-id', 'rev-6',
                                  show_ids=True, full=False)

        self.assertBranchAnnotate('    rev-1 | first\n'
                                  '    rev-2 | second\n'
                                  'rev-1_1_1 | third\n'
                                  'rev-1_2_1 | fourth\n'
                                  'rev-1_3_1 | fifth\n'
                                  'rev-1_3_1 | sixth\n',
                                  builder.get_branch(), 'a-id', 'rev-6',
                                  show_ids=True, full=True)

    def test_annotate_unicode_author(self):
        tree1 = self.make_branch_and_tree('tree1')

        self.build_tree_contents([('tree1/a', 'adi\xc3\xb3s')])
        tree1.add(['a'], ['a-id'])
        tree1.commit('a', rev_id='rev-1',
                     committer=u'Pepe P\xe9rez <pperez@ejemplo.com>',
                     timestamp=1166046000.00, timezone=0)

        self.build_tree_contents([('tree1/b', 'bye')])
        tree1.add(['b'], ['b-id'])
        tree1.commit('b', rev_id='rev-2',
                     committer=u'p\xe9rez',
                     timestamp=1166046000.00, timezone=0)

        tree1.lock_read()
        self.addCleanup(tree1.unlock)

        revtree_1 = tree1.branch.repository.revision_tree('rev-1')
        revtree_2 = tree1.branch.repository.revision_tree('rev-2')

        # this passes if no exception is raised
        to_file = StringIO()
        annotate.annotate_file_tree(revtree_1, 'a-id',
            to_file=to_file, branch=tree1.branch)

        sio = StringIO()
        to_file = codecs.getwriter('ascii')(sio)
        to_file.encoding = 'ascii' # codecs does not set it
        annotate.annotate_file_tree(revtree_2, 'b-id',
            to_file=to_file, branch=tree1.branch)
        self.assertEqualDiff('2   p?rez   | bye\n', sio.getvalue())

        # test now with to_file.encoding = None
        to_file = tests.StringIOWrapper()
        to_file.encoding = None
        annotate.annotate_file_tree(revtree_2, 'b-id',
            to_file=to_file, branch=tree1.branch)
        self.assertContainsRe('2   p.rez   | bye\n', to_file.getvalue())

        # and when it does not exist
        to_file = StringIO()
        annotate.annotate_file_tree(revtree_2, 'b-id',
            to_file=to_file, branch=tree1.branch)
        self.assertContainsRe('2   p.rez   | bye\n', to_file.getvalue())

    def test_annotate_author_or_committer(self):
        tree1 = self.make_branch_and_tree('tree1')

        self.build_tree_contents([('tree1/a', 'hello')])
        tree1.add(['a'], ['a-id'])
        tree1.commit('a', rev_id='rev-1',
                     committer='Committer <committer@example.com>',
                     timestamp=1166046000.00, timezone=0)

        self.build_tree_contents([('tree1/b', 'bye')])
        tree1.add(['b'], ['b-id'])
        tree1.commit('b', rev_id='rev-2',
                     committer='Committer <committer@example.com>',
                     authors=['Author <author@example.com>'],
                     timestamp=1166046000.00, timezone=0)

        tree1.lock_read()
        self.addCleanup(tree1.unlock)

        self.assertBranchAnnotate('1   committ | hello\n', tree1.branch,
            'a-id', 'rev-1')

        to_file = StringIO()
        self.assertBranchAnnotate('2   author@ | bye\n', tree1.branch,
            'b-id', 'rev-2')


class TestReannotate(tests.TestCase):

    def annotateEqual(self, expected, parents, newlines, revision_id,
                      blocks=None):
        annotate_list = list(annotate.reannotate(parents, newlines,
                             revision_id, blocks))
        self.assertEqual(len(expected), len(annotate_list))
        for e, a in zip(expected, annotate_list):
            self.assertEqual(e, a)

    def test_reannotate(self):
        self.annotateEqual(parent_1, [parent_1], new_1, 'blahblah')
        self.annotateEqual(expected_2_1, [parent_2], new_1, 'blahblah')
        self.annotateEqual(expected_1_2_2, [parent_1, parent_2], new_2,
                           'blahblah')

    def test_reannotate_no_parents(self):
        self.annotateEqual(expected_1, [], new_1, 'blahblah')

    def test_reannotate_left_matching_blocks(self):
        """Ensure that left_matching_blocks has an impact.

        In this case, the annotation is ambiguous, so the hint isn't actually
        lying.
        """
        parent = [('rev1', 'a\n')]
        new_text = ['a\n', 'a\n']
        blocks = [(0, 0, 1), (1, 2, 0)]
        self.annotateEqual([('rev1', 'a\n'), ('rev2', 'a\n')], [parent],
                           new_text, 'rev2', blocks)
        blocks = [(0, 1, 1), (1, 2, 0)]
        self.annotateEqual([('rev2', 'a\n'), ('rev1', 'a\n')], [parent],
                           new_text, 'rev2', blocks)
