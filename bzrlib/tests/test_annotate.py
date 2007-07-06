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


new_2 = """\
a
b
c
d
e
g
h
""".splitlines(True)


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

        tree2 = tree1.bzrdir.clone('tree2').open_workingtree()

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
        return tree1, tree2

    def create_deeply_merged_trees(self):
        """Create some trees with a more complex merge history.

        rev-1 --+
         |      |
        rev-2  rev-1_1_1 --+
         |      |          |
         +------+          |
         |      |          |
        rev-3  rev-1_1_2  rev-1_1_1_1_1 --+
         |      |          |              |
         +------+          |              |
         |                 |              |
        rev-4             rev-1_1_1_1_2  rev-1_1_1_1_1_1_1
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

        tree3 = tree2.bzrdir.clone('tree3').open_workingtree()

        tree2.commit('noop', rev_id='rev-1_1_2')
        self.assertEqual(0, tree1.merge_from_branch(tree2.branch))
        tree1.commit('noop merge', rev_id='rev-4')

        self.build_tree_contents([('tree3/a', 'first\nthird\nfourth\n')])
        tree3.commit('four', rev_id='rev-1_1_1_1_1',
                     committer='jerry@foo.com',
                     timestamp=1166046003.00, timezone=0)

        tree4 = tree3.bzrdir.clone('tree4').open_workingtree()

        tree3.commit('noop', rev_id='rev-1_1_1_1_2',
                     committer='jerry@foo.com',
                     timestamp=1166046004.00, timezone=0)
        self.assertEqual(0, tree1.merge_from_branch(tree3.branch))
        tree1.commit('merge four', rev_id='rev-5')

        self.build_tree_contents([('tree4/a',
                                   'first\nthird\nfourth\nfifth\nsixth\n')])
        tree4.commit('five and six', rev_id='rev-1_1_1_1_1_1_1',
                     committer='george@foo.com',
                     timestamp=1166046005.00, timezone=0)
        self.assertEqual(0, tree1.merge_from_branch(tree4.branch))
        tree1.commit('merge five and six', rev_id='rev-6')
        return tree1

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
        self.assertEqualDiff('1            joe@foo | first\n'
                             '2            joe@foo | second\n'
                             '1.1.1        barry@f | third\n'
                             '1.1.1.1.1    jerry@f | fourth\n'
                             '1.1.1.1.1.1> george@ | fifth\n'
                             '                     | sixth\n',
                             sio.getvalue())

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, verbose=False, full=True)
        self.assertEqualDiff('1            joe@foo | first\n'
                             '2            joe@foo | second\n'
                             '1.1.1        barry@f | third\n'
                             '1.1.1.1.1    jerry@f | fourth\n'
                             '1.1.1.1.1.1> george@ | fifth\n'
                             '1.1.1.1.1.1> george@ | sixth\n',
                             sio.getvalue())

        # verbose=True shows everything, the full revno, user id, and date
        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, verbose=True, full=False)
        self.assertEqualDiff('1             joe@foo.com    20061213 | first\n'
                             '2             joe@foo.com    20061213 | second\n'
                             '1.1.1         barry@foo.com  20061213 | third\n'
                             '1.1.1.1.1     jerry@foo.com  20061213 | fourth\n'
                             '1.1.1.1.1.1.1 george@foo.com 20061213 | fifth\n'
                             '                                      | sixth\n',
                             sio.getvalue())

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, verbose=True, full=True)
        self.assertEqualDiff('1             joe@foo.com    20061213 | first\n'
                             '2             joe@foo.com    20061213 | second\n'
                             '1.1.1         barry@foo.com  20061213 | third\n'
                             '1.1.1.1.1     jerry@foo.com  20061213 | fourth\n'
                             '1.1.1.1.1.1.1 george@foo.com 20061213 | fifth\n'
                             '1.1.1.1.1.1.1 george@foo.com 20061213 | sixth\n',
                             sio.getvalue())

    def test_annotate_uses_branch_context(self):
        """Dotted revnos should use the Branch context.

        When annotating a non-mainline revision, the annotation should still
        use dotted revnos from the mainline.
        """
        tree1 = self.create_deeply_merged_trees()

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-1_1_1_1_1_1_1', 'a-id',
                               to_file=sio, verbose=False, full=False)
        self.assertEqualDiff('1            joe@foo | first\n'
                             '1.1.1        barry@f | third\n'
                             '1.1.1.1.1    jerry@f | fourth\n'
                             '1.1.1.1.1.1> george@ | fifth\n'
                             '                     | sixth\n',
                             sio.getvalue())

    def test_annotate_show_ids(self):
        tree1 = self.create_deeply_merged_trees()

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, show_ids=True, full=False)

        # It looks better with real revision ids :)
        self.assertEqualDiff('            rev-1 | first\n'
                             '            rev-2 | second\n'
                             '        rev-1_1_1 | third\n'
                             '    rev-1_1_1_1_1 | fourth\n'
                             'rev-1_1_1_1_1_1_1 | fifth\n'
                             '                  | sixth\n',
                             sio.getvalue())

        sio = StringIO()
        annotate.annotate_file(tree1.branch, 'rev-6', 'a-id',
                               to_file=sio, show_ids=True, full=True)

        self.assertEqualDiff('            rev-1 | first\n'
                             '            rev-2 | second\n'
                             '        rev-1_1_1 | third\n'
                             '    rev-1_1_1_1_1 | fourth\n'
                             'rev-1_1_1_1_1_1_1 | fifth\n'
                             'rev-1_1_1_1_1_1_1 | sixth\n',
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

        # the test passes if the annotate_file() calls below do not raise an
        # exception

        to_file = codecs.EncodedFile(StringIO(), 'utf-8')
        annotate.annotate_file(tree1.branch, 'rev-1', 'a-id', to_file=to_file)

        to_file = codecs.getwriter('ascii')(StringIO())
        to_file.encoding = 'ascii' # codecs does not set it
        annotate.annotate_file(tree1.branch, 'rev-2', 'b-id', to_file=to_file)


class TestReannotate(tests.TestCase):

    def annotateEqual(self, expected, parents, newlines, revision_id):
        annotate_list = list(annotate.reannotate(parents, newlines,
                             revision_id))
        self.assertEqual(len(expected), len(annotate_list))
        for e, a in zip(expected, annotate_list):
            self.assertEqual(e, a)

    def test_reannotate(self):
        self.annotateEqual(parent_1, [parent_1], new_1, 'blahblah')
        self.annotateEqual(expected_2_1, [parent_2], new_1, 'blahblah')
        self.annotateEqual(expected_1_2_2, [parent_1, parent_2], new_2, 
                           'blahblah')
