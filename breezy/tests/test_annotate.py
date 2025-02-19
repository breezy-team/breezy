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
from io import BytesIO, StringIO

from .. import annotate, tests
from .ui_testing import StringIOWithEncoding


def annotation(text):
    return [tuple(l.split(b" ", 1)) for l in text.splitlines(True)]


parent_1 = annotation(b"""\
rev1 a
rev2 b
rev3 c
rev4 d
rev5 e
""")


parent_2 = annotation(b"""\
rev1 a
rev3 c
rev4 d
rev6 f
rev7 e
rev8 h
""")


expected_2_1 = annotation(b"""\
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
expected_1_2_2 = annotation(b"""\
rev1 a
rev2 b
rev3 c
rev4 d
blahblah e
blahblah g
rev8 h
""")


new_1 = b"""\
a
b
c
d
e
""".splitlines(True)

expected_1 = annotation(b"""\
blahblah a
blahblah b
blahblah c
blahblah d
blahblah e
""")


new_2 = b"""\
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
duplicate_base = annotation(b"""\
rev-base first
rev-base second
rev-base third
rev-base fourth-base
""")

duplicate_A = annotation(b"""\
rev-base first
rev-A alt-second
rev-base third
rev-A fourth-A
""")

duplicate_B = annotation(b"""\
rev-base first
rev-B alt-second
rev-base third
rev-B fourth-B
""")

duplicate_C = annotation(b"""\
rev-base first
rev-A alt-second
rev-base third
rev-C fourth-C
""")

duplicate_D = annotation(b"""\
rev-base first
rev-A alt-second
rev-base third
rev-D fourth-D
""")

duplicate_E = annotation(b"""\
rev-base first
rev-A alt-second
rev-base third
rev-E fourth-E
""")


class TestAnnotate(tests.TestCaseWithTransport):
    def create_merged_trees(self):
        """Create 2 trees with merges between them.

        rev-1 --+
         |      |
        rev-2  rev-1_1_1
         |      |
         +------+
         |
        rev-3
        """
        builder = self.make_branch_builder("branch")
        builder.start_series()
        self.addCleanup(builder.finish_series)
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("a", b"a-id", "file", b"first\n")),
            ],
            timestamp=1166046000.00,
            timezone=0,
            committer="joe@foo.com",
            revision_id=b"rev-1",
        )
        builder.build_snapshot(
            [b"rev-1"],
            [
                ("modify", ("a", b"first\nsecond\n")),
            ],
            timestamp=1166046001.00,
            timezone=0,
            committer="joe@foo.com",
            revision_id=b"rev-2",
        )
        builder.build_snapshot(
            [b"rev-1"],
            [
                ("modify", ("a", b"first\nthird\n")),
            ],
            timestamp=1166046002.00,
            timezone=0,
            committer="barry@foo.com",
            revision_id=b"rev-1_1_1",
        )
        builder.build_snapshot(
            [b"rev-2", b"rev-1_1_1"],
            [
                ("modify", ("a", b"first\nsecond\nthird\n")),
            ],
            timestamp=1166046003.00,
            timezone=0,
            committer="sal@foo.com",
            revision_id=b"rev-3",
        )
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
        builder.build_snapshot([b"rev-1_1_1"], [], revision_id=b"rev-1_1_2")
        builder.build_snapshot([b"rev-3", b"rev-1_1_2"], [], revision_id=b"rev-4")
        builder.build_snapshot(
            [b"rev-1_1_1"],
            [
                ("modify", ("a", b"first\nthird\nfourth\n")),
            ],
            timestamp=1166046003.00,
            timezone=0,
            committer="jerry@foo.com",
            revision_id=b"rev-1_2_1",
        )
        builder.build_snapshot(
            [b"rev-1_2_1"],
            [],
            timestamp=1166046004.00,
            timezone=0,
            committer="jerry@foo.com",
            revision_id=b"rev-1_2_2",
        )
        builder.build_snapshot(
            [b"rev-4", b"rev-1_2_2"],
            [
                ("modify", ("a", b"first\nsecond\nthird\nfourth\n")),
            ],
            timestamp=1166046004.00,
            timezone=0,
            committer="jerry@foo.com",
            revision_id=b"rev-5",
        )
        builder.build_snapshot(
            [b"rev-1_2_1"],
            [
                ("modify", ("a", b"first\nthird\nfourth\nfifth\nsixth\n")),
            ],
            timestamp=1166046005.00,
            timezone=0,
            committer="george@foo.com",
            revision_id=b"rev-1_3_1",
        )
        builder.build_snapshot(
            [b"rev-5", b"rev-1_3_1"],
            [
                ("modify", ("a", b"first\nsecond\nthird\nfourth\nfifth\nsixth\n")),
            ],
            revision_id=b"rev-6",
        )
        return builder

    def create_duplicate_lines_tree(self):
        builder = self.make_branch_builder("branch")
        builder.start_series()
        self.addCleanup(builder.finish_series)
        base_text = b"".join(l for r, l in duplicate_base)
        a_text = b"".join(l for r, l in duplicate_A)
        b_text = b"".join(l for r, l in duplicate_B)
        c_text = b"".join(l for r, l in duplicate_C)
        d_text = b"".join(l for r, l in duplicate_D)
        e_text = b"".join(l for r, l in duplicate_E)
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", base_text)),
            ],
            revision_id=b"rev-base",
        )
        builder.build_snapshot(
            [b"rev-base"], [("modify", ("file", a_text))], revision_id=b"rev-A"
        )
        builder.build_snapshot(
            [b"rev-base"], [("modify", ("file", b_text))], revision_id=b"rev-B"
        )
        builder.build_snapshot(
            [b"rev-A"], [("modify", ("file", c_text))], revision_id=b"rev-C"
        )
        builder.build_snapshot(
            [b"rev-B", b"rev-A"], [("modify", ("file", d_text))], revision_id=b"rev-D"
        )
        builder.build_snapshot(
            [b"rev-C", b"rev-D"], [("modify", ("file", e_text))], revision_id=b"rev-E"
        )
        return builder

    def assertAnnotateEqualDiff(self, actual, expected):
        if actual != expected:
            # Create an easier to understand diff when the lines don't actually
            # match
            self.assertEqualDiff(
                "".join("\t".join(l) for l in expected),
                "".join("\t".join(l) for l in actual),
            )

    def assertBranchAnnotate(
        self,
        expected,
        branch,
        path,
        revision_id,
        verbose=False,
        full=False,
        show_ids=False,
    ):
        tree = branch.repository.revision_tree(revision_id)
        to_file = StringIO()
        annotate.annotate_file_tree(
            tree,
            path,
            to_file,
            verbose=verbose,
            full=full,
            show_ids=show_ids,
            branch=branch,
        )
        self.assertAnnotateEqualDiff(to_file.getvalue(), expected)

    def assertRepoAnnotate(self, expected, repo, path, revision_id):
        """Assert that the revision is properly annotated."""
        actual = list(repo.revision_tree(revision_id).annotate_iter(path))
        self.assertAnnotateEqualDiff(actual, expected)

    def test_annotate_duplicate_lines(self):
        # XXX: Should this be a per_repository test?
        builder = self.create_duplicate_lines_tree()
        repo = builder.get_branch().repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertRepoAnnotate(duplicate_base, repo, "file", b"rev-base")
        self.assertRepoAnnotate(duplicate_A, repo, "file", b"rev-A")
        self.assertRepoAnnotate(duplicate_B, repo, "file", b"rev-B")
        self.assertRepoAnnotate(duplicate_C, repo, "file", b"rev-C")
        self.assertRepoAnnotate(duplicate_D, repo, "file", b"rev-D")
        self.assertRepoAnnotate(duplicate_E, repo, "file", b"rev-E")

    def test_annotate_shows_dotted_revnos(self):
        builder = self.create_merged_trees()

        self.assertBranchAnnotate(
            "1     joe@foo | first\n2     joe@foo | second\n1.1.1 barry@f | third\n",
            builder.get_branch(),
            "a",
            b"rev-3",
        )

    def test_annotate_limits_dotted_revnos(self):
        """Annotate should limit dotted revnos to a depth of 12"""
        builder = self.create_deeply_merged_trees()

        self.assertBranchAnnotate(
            "1     joe@foo | first\n"
            "2     joe@foo | second\n"
            "1.1.1 barry@f | third\n"
            "1.2.1 jerry@f | fourth\n"
            "1.3.1 george@ | fifth\n"
            "              | sixth\n",
            builder.get_branch(),
            "a",
            b"rev-6",
            verbose=False,
            full=False,
        )

        self.assertBranchAnnotate(
            "1     joe@foo | first\n"
            "2     joe@foo | second\n"
            "1.1.1 barry@f | third\n"
            "1.2.1 jerry@f | fourth\n"
            "1.3.1 george@ | fifth\n"
            "1.3.1 george@ | sixth\n",
            builder.get_branch(),
            "a",
            b"rev-6",
            verbose=False,
            full=True,
        )

        # verbose=True shows everything, the full revno, user id, and date
        self.assertBranchAnnotate(
            "1     joe@foo.com    20061213 | first\n"
            "2     joe@foo.com    20061213 | second\n"
            "1.1.1 barry@foo.com  20061213 | third\n"
            "1.2.1 jerry@foo.com  20061213 | fourth\n"
            "1.3.1 george@foo.com 20061213 | fifth\n"
            "                              | sixth\n",
            builder.get_branch(),
            "a",
            b"rev-6",
            verbose=True,
            full=False,
        )

        self.assertBranchAnnotate(
            "1     joe@foo.com    20061213 | first\n"
            "2     joe@foo.com    20061213 | second\n"
            "1.1.1 barry@foo.com  20061213 | third\n"
            "1.2.1 jerry@foo.com  20061213 | fourth\n"
            "1.3.1 george@foo.com 20061213 | fifth\n"
            "1.3.1 george@foo.com 20061213 | sixth\n",
            builder.get_branch(),
            "a",
            b"rev-6",
            verbose=True,
            full=True,
        )

    def test_annotate_uses_branch_context(self):
        """Dotted revnos should use the Branch context.

        When annotating a non-mainline revision, the annotation should still
        use dotted revnos from the mainline.
        """
        builder = self.create_deeply_merged_trees()

        self.assertBranchAnnotate(
            "1     joe@foo | first\n"
            "1.1.1 barry@f | third\n"
            "1.2.1 jerry@f | fourth\n"
            "1.3.1 george@ | fifth\n"
            "              | sixth\n",
            builder.get_branch(),
            "a",
            b"rev-1_3_1",
            verbose=False,
            full=False,
        )

    def test_annotate_show_ids(self):
        builder = self.create_deeply_merged_trees()

        # It looks better with real revision ids :)
        self.assertBranchAnnotate(
            "    rev-1 | first\n"
            "    rev-2 | second\n"
            "rev-1_1_1 | third\n"
            "rev-1_2_1 | fourth\n"
            "rev-1_3_1 | fifth\n"
            "          | sixth\n",
            builder.get_branch(),
            "a",
            b"rev-6",
            show_ids=True,
            full=False,
        )

        self.assertBranchAnnotate(
            "    rev-1 | first\n"
            "    rev-2 | second\n"
            "rev-1_1_1 | third\n"
            "rev-1_2_1 | fourth\n"
            "rev-1_3_1 | fifth\n"
            "rev-1_3_1 | sixth\n",
            builder.get_branch(),
            "a",
            b"rev-6",
            show_ids=True,
            full=True,
        )

    def test_annotate_unicode_author(self):
        tree1 = self.make_branch_and_tree("tree1")

        self.build_tree_contents([("tree1/a", b"adi\xc3\xb3s")])
        tree1.add(["a"], ids=[b"a-id"])
        tree1.commit(
            "a",
            rev_id=b"rev-1",
            committer="Pepe P\xe9rez <pperez@ejemplo.com>",
            timestamp=1166046000.00,
            timezone=0,
        )

        self.build_tree_contents([("tree1/b", b"bye")])
        tree1.add(["b"], ids=[b"b-id"])
        tree1.commit(
            "b",
            rev_id=b"rev-2",
            committer="p\xe9rez",
            timestamp=1166046000.00,
            timezone=0,
        )

        tree1.lock_read()
        self.addCleanup(tree1.unlock)

        revtree_1 = tree1.branch.repository.revision_tree(b"rev-1")
        revtree_2 = tree1.branch.repository.revision_tree(b"rev-2")

        # this passes if no exception is raised
        to_file = StringIO()
        annotate.annotate_file_tree(
            revtree_1, "a", to_file=to_file, branch=tree1.branch
        )

        sio = BytesIO()
        to_file = codecs.getwriter("ascii")(sio, "replace")
        annotate.annotate_file_tree(
            revtree_2, "b", to_file=to_file, branch=tree1.branch
        )
        self.assertEqualDiff(b"2   p?rez   | bye\n", sio.getvalue())

        # test now with unicode file-like
        to_file = StringIOWithEncoding()
        annotate.annotate_file_tree(
            revtree_2, "b", to_file=to_file, branch=tree1.branch
        )
        self.assertContainsRe("2   p\xe9rez   | bye\n", to_file.getvalue())

    def test_annotate_author_or_committer(self):
        tree1 = self.make_branch_and_tree("tree1")

        self.build_tree_contents([("tree1/a", b"hello")])
        tree1.add(["a"], ids=[b"a-id"])
        tree1.commit(
            "a",
            rev_id=b"rev-1",
            committer="Committer <committer@example.com>",
            timestamp=1166046000.00,
            timezone=0,
        )

        self.build_tree_contents([("tree1/b", b"bye")])
        tree1.add(["b"], ids=[b"b-id"])
        tree1.commit(
            "b",
            rev_id=b"rev-2",
            committer="Committer <committer@example.com>",
            authors=["Author <author@example.com>"],
            timestamp=1166046000.00,
            timezone=0,
        )

        tree1.lock_read()
        self.addCleanup(tree1.unlock)

        self.assertBranchAnnotate("1   committ | hello\n", tree1.branch, "a", b"rev-1")

        self.assertBranchAnnotate("2   author@ | bye\n", tree1.branch, "b", b"rev-2")


class TestReannotate(tests.TestCase):
    def annotateEqual(self, expected, parents, newlines, revision_id, blocks=None):
        annotate_list = list(
            annotate.reannotate(parents, newlines, revision_id, blocks)
        )
        self.assertEqual(len(expected), len(annotate_list))
        for e, a in zip(expected, annotate_list):
            self.assertEqual(e, a)

    def test_reannotate(self):
        self.annotateEqual(parent_1, [parent_1], new_1, b"blahblah")
        self.annotateEqual(expected_2_1, [parent_2], new_1, b"blahblah")
        self.annotateEqual(expected_1_2_2, [parent_1, parent_2], new_2, b"blahblah")

    def test_reannotate_no_parents(self):
        self.annotateEqual(expected_1, [], new_1, b"blahblah")

    def test_reannotate_left_matching_blocks(self):
        """Ensure that left_matching_blocks has an impact.

        In this case, the annotation is ambiguous, so the hint isn't actually
        lying.
        """
        parent = [(b"rev1", b"a\n")]
        new_text = [b"a\n", b"a\n"]
        blocks = [(0, 0, 1), (1, 2, 0)]
        self.annotateEqual(
            [(b"rev1", b"a\n"), (b"rev2", b"a\n")], [parent], new_text, b"rev2", blocks
        )
        blocks = [(0, 1, 1), (1, 2, 0)]
        self.annotateEqual(
            [(b"rev2", b"a\n"), (b"rev1", b"a\n")], [parent], new_text, b"rev2", blocks
        )
