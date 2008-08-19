# Copyright (C) 2006 Canonical Ltd
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

"""Whitebox tests for annotate functionality."""

import codecs
from cStringIO import StringIO

from bzrlib import (
    annotate,
    conflicts,
    errors,
    tests,
    trace,
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

        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/a', 'first\n')])
        tree1.add(['a'], ['a-id'])
        tree1.commit('a', rev_id='rev-1',
                     committer="joe@foo.com",
                     timestamp=1166046000.00, timezone=0)

        tree2 = tree1.bzrdir.sprout('tree2').open_workingtree()

        self.build_tree_contents([('tree1/a', 'first\nsecond\n')])
        tree1.commit('b', rev_id='rev-2',
                     committer='joe@foo.com',
                     timestamp=1166046001.00, timezone=0)

        self.build_tree_contents([('tree2/a', 'first\nthird\n')])
        tree2.commit('c', rev_id='rev-1_1_1',
                     committer="barry@foo.com",
                     timestamp=1166046002.00, timezone=0)

        num_conflicts = tree1.merge_from_branch(tree2.branch)
        self.assertEqual(1, num_conflicts)

        self.build_tree_contents([('tree1/a',
                                 'first\nsecond\nthird\n')])
        tree1.set_conflicts(conflicts.ConflictList())
        tree1.commit('merge 2', rev_id='rev-3',
                     committer='sal@foo.com',
                     timestamp=1166046003.00, timezone=0)
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        return tree1, tree2

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
        tree1, tree2 = self.create_merged_trees()
        tree1.unlock()

        tree3 = tree2.bzrdir.sprout('tree3').open_workingtree()

        tree2.commit('noop', rev_id='rev-1_1_2')
        self.assertEqual(0, tree1.merge_from_branch(tree2.branch))
        tree1.commit('noop merge', rev_id='rev-4')

        self.build_tree_contents([('tree3/a', 'first\nthird\nfourth\n')])
        tree3.commit('four', rev_id='rev-1_2_1',
                     committer='jerry@foo.com',
                     timestamp=1166046003.00, timezone=0)

        tree4 = tree3.bzrdir.sprout('tree4').open_workingtree()

        tree3.commit('noop', rev_id='rev-1_2_2',
                     committer='jerry@foo.com',
                     timestamp=1166046004.00, timezone=0)
        self.assertEqual(0, tree1.merge_from_branch(tree3.branch))
        tree1.commit('merge four', rev_id='rev-5')

        self.build_tree_contents([('tree4/a',
                                   'first\nthird\nfourth\nfifth\nsixth\n')])
        tree4.commit('five and six', rev_id='rev-1_3_1',
                     committer='george@foo.com',
                     timestamp=1166046005.00, timezone=0)
        self.assertEqual(0, tree1.merge_from_branch(tree4.branch))
        tree1.commit('merge five and six', rev_id='rev-6')
        tree1.lock_read()
        return tree1

    def create_duplicate_lines_tree(self):
        tree1 = self.make_branch_and_tree('tree1')
        base_text = ''.join(l for r, l in duplicate_base)
        a_text = ''.join(l for r, l in duplicate_A)
        b_text = ''.join(l for r, l in duplicate_B)
        c_text = ''.join(l for r, l in duplicate_C)
        d_text = ''.join(l for r, l in duplicate_D)
        e_text = ''.join(l for r, l in duplicate_E)
        self.build_tree_contents([('tree1/file', base_text)])
        tree1.add(['file'], ['file-id'])
        tree1.commit('base', rev_id='rev-base')
        tree2 = tree1.bzrdir.sprout('tree2').open_workingtree()

        self.build_tree_contents([('tree1/file', a_text),
                                  ('tree2/file', b_text)])
        tree1.commit('A', rev_id='rev-A')
        tree2.commit('B', rev_id='rev-B')

        tree2.merge_from_branch(tree1.branch)
        conflicts.resolve(tree2, None) # Resolve the conflicts
        self.build_tree_contents([('tree2/file', d_text)])
        tree2.commit('D', rev_id='rev-D')

        self.build_tree_contents([('tree1/file', c_text)])
        tree1.commit('C', rev_id='rev-C')

        tree1.merge_from_branch(tree2.branch)
        conflicts.resolve(tree1, None) # Resolve the conflicts
        self.build_tree_contents([('tree1/file', e_text)])
        tree1.commit('E', rev_id='rev-E')
        return tree1

    def assertRepoAnnotate(self, expected, repo, file_id, revision_id):
        """Assert that the revision is properly annotated."""
        actual = list(repo.revision_tree(revision_id).annotate_iter(file_id))
        if actual != expected:
            # Create an easier to understand diff when the lines don't actually
            # match
            self.assertEqualDiff(''.join('\t'.join(l) for l in expected),
                                 ''.join('\t'.join(l) for l in actual))

    def test_annotate_duplicate_lines(self):
        # XXX: Should this be a repository_implementations test?
        tree1 = self.create_duplicate_lines_tree()
        repo = tree1.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertRepoAnnotate(duplicate_base, repo, 'file-id', 'rev-base')
        self.assertRepoAnnotate(duplicate_A, repo, 'file-id', 'rev-A')
        self.assertRepoAnnotate(duplicate_B, repo, 'file-id', 'rev-B')
        self.assertRepoAnnotate(duplicate_C, repo, 'file-id', 'rev-C')
        self.assertRepoAnnotate(duplicate_D, repo, 'file-id', 'rev-D')
        self.assertRepoAnnotate(duplicate_E, repo, 'file-id', 'rev-E')

    def test_annotate_shows_dotted_revnos(self):
        tree1, tree2 = self.create_merged_trees()

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-3', 'a-id',
                               to_file=sio)
        self.assertEqualDiff('1     joe@foo | first\n'
                             '2     joe@foo | second\n'
                             '1.1.1 barry@f | third\n',
                             sio.getvalue())

    def test_annotate_limits_dotted_revnos(self):
        """Annotate should limit dotted revnos to a depth of 12"""
        tree1 = self.create_deeply_merged_trees()

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, verbose=False, full=False)
        self.assertEqualDiff('1     joe@foo | first\n'
                             '2     joe@foo | second\n'
                             '1.1.1 barry@f | third\n'
                             '1.2.1 jerry@f | fourth\n'
                             '1.3.1 george@ | fifth\n'
                             '              | sixth\n',
                             sio.getvalue())

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, verbose=False, full=True)
        self.assertEqualDiff('1     joe@foo | first\n'
                             '2     joe@foo | second\n'
                             '1.1.1 barry@f | third\n'
                             '1.2.1 jerry@f | fourth\n'
                             '1.3.1 george@ | fifth\n'
                             '1.3.1 george@ | sixth\n',
                             sio.getvalue())

        # verbose=True shows everything, the full revno, user id, and date
        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, verbose=True, full=False)
        self.assertEqualDiff('1     joe@foo.com    20061213 | first\n'
                             '2     joe@foo.com    20061213 | second\n'
                             '1.1.1 barry@foo.com  20061213 | third\n'
                             '1.2.1 jerry@foo.com  20061213 | fourth\n'
                             '1.3.1 george@foo.com 20061213 | fifth\n'
                             '                              | sixth\n',
                             sio.getvalue())

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, verbose=True, full=True)
        self.assertEqualDiff('1     joe@foo.com    20061213 | first\n'
                             '2     joe@foo.com    20061213 | second\n'
                             '1.1.1 barry@foo.com  20061213 | third\n'
                             '1.2.1 jerry@foo.com  20061213 | fourth\n'
                             '1.3.1 george@foo.com 20061213 | fifth\n'
                             '1.3.1 george@foo.com 20061213 | sixth\n',
                             sio.getvalue())

    def test_annotate_uses_branch_context(self):
        """Dotted revnos should use the Branch context.

        When annotating a non-mainline revision, the annotation should still
        use dotted revnos from the mainline.
        """
        tree1 = self.create_deeply_merged_trees()

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-1_3_1', 'a-id',
                               to_file=sio, verbose=False, full=False)
        self.assertEqualDiff('1     joe@foo | first\n'
                             '1.1.1 barry@f | third\n'
                             '1.2.1 jerry@f | fourth\n'
                             '1.3.1 george@ | fifth\n'
                             '              | sixth\n',
                             sio.getvalue())

    def test_annotate_show_ids(self):
        tree1 = self.create_deeply_merged_trees()

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, show_ids=True, full=False)

        # It looks better with real revision ids :)
        self.assertEqualDiff('    rev-1 | first\n'
                             '    rev-2 | second\n'
                             'rev-1_1_1 | third\n'
                             'rev-1_2_1 | fourth\n'
                             'rev-1_3_1 | fifth\n'
                             '          | sixth\n',
                             sio.getvalue())

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, show_ids=True, full=True)

        self.assertEqualDiff('    rev-1 | first\n'
                             '    rev-2 | second\n'
                             'rev-1_1_1 | third\n'
                             'rev-1_2_1 | fourth\n'
                             'rev-1_3_1 | fifth\n'
                             'rev-1_3_1 | sixth\n',
                             sio.getvalue())

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
        # this passes if no exception is raised
        to_file = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-1', 'a-id', to_file=to_file)

        sio = StringIO()
        to_file = codecs.getwriter('ascii')(sio)
        to_file.encoding = 'ascii' # codecs does not set it
        annotate.annotate_file(tree1.branch, 'rev-2', 'b-id', to_file=to_file)
        self.assertEqualDiff('2   p?rez   | bye\n', sio.getvalue())

        # test now with to_file.encoding = None
        to_file = tests.StringIOWrapper()
        to_file.encoding = None
        annotate.annotate_file(tree1.branch, 'rev-2', 'b-id', to_file=to_file)
        self.assertContainsRe('2   p.rez   | bye\n', to_file.getvalue())

        # and when it does not exist
        to_file = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-2', 'b-id', to_file=to_file)
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
                     author='Author <author@example.com>',
                     timestamp=1166046000.00, timezone=0)

        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        to_file = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-1', 'a-id', to_file=to_file)
        self.assertEqual('1   committ | hello\n', to_file.getvalue())

        to_file = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-2', 'b-id', to_file=to_file)
        self.assertEqual('2   author@ | bye\n', to_file.getvalue())


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
