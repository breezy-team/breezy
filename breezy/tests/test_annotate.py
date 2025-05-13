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

from .. import annotate, errors, revision, tests
from ..annotate import Annotator
from ..bzr import knit
from .ui_testing import StringIOWithEncoding


def annotation(text):
    return [tuple(l.split(b" ", 1)) for l in text.splitlines(True)]


parent_1 = annotation(
    b"""\
rev1 a
rev2 b
rev3 c
rev4 d
rev5 e
"""
)


parent_2 = annotation(
    b"""\
rev1 a
rev3 c
rev4 d
rev6 f
rev7 e
rev8 h
"""
)


expected_2_1 = annotation(
    b"""\
rev1 a
blahblah b
rev3 c
rev4 d
rev7 e
"""
)


# a: in both, same value, kept
# b: in 1, kept
# c: in both, same value, kept
# d: in both, same value, kept
# e: 1 and 2 disagree, so it goes to blahblah
# f: in 2, but not in new, so ignored
# g: not in 1 or 2, so it goes to blahblah
# h: only in parent 2, so 2 gets it
expected_1_2_2 = annotation(
    b"""\
rev1 a
rev2 b
rev3 c
rev4 d
blahblah e
blahblah g
rev8 h
"""
)


new_1 = b"""\
a
b
c
d
e
""".splitlines(True)

expected_1 = annotation(
    b"""\
blahblah a
blahblah b
blahblah c
blahblah d
blahblah e
"""
)


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
duplicate_base = annotation(
    b"""\
rev-base first
rev-base second
rev-base third
rev-base fourth-base
"""
)

duplicate_a = annotation(
    b"""\
rev-base first
rev-A alt-second
rev-base third
rev-A fourth-A
"""
)

duplicate_b = annotation(
    b"""\
rev-base first
rev-B alt-second
rev-base third
rev-B fourth-B
"""
)

duplicate_c = annotation(
    b"""\
rev-base first
rev-A alt-second
rev-base third
rev-C fourth-C
"""
)

duplicate_d = annotation(
    b"""\
rev-base first
rev-A alt-second
rev-base third
rev-D fourth-D
"""
)

duplicate_e = annotation(
    b"""\
rev-base first
rev-A alt-second
rev-base third
rev-E fourth-E
"""
)


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
        a_text = b"".join(l for r, l in duplicate_a)
        b_text = b"".join(l for r, l in duplicate_b)
        c_text = b"".join(l for r, l in duplicate_c)
        d_text = b"".join(l for r, l in duplicate_d)
        e_text = b"".join(l for r, l in duplicate_e)
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
        self.assertRepoAnnotate(duplicate_a, repo, "file", b"rev-A")
        self.assertRepoAnnotate(duplicate_b, repo, "file", b"rev-B")
        self.assertRepoAnnotate(duplicate_c, repo, "file", b"rev-C")
        self.assertRepoAnnotate(duplicate_d, repo, "file", b"rev-D")
        self.assertRepoAnnotate(duplicate_e, repo, "file", b"rev-E")

    def test_annotate_shows_dotted_revnos(self):
        builder = self.create_merged_trees()

        self.assertBranchAnnotate(
            "1     joe@foo | first\n2     joe@foo | second\n1.1.1 barry@f | third\n",
            builder.get_branch(),
            "a",
            b"rev-3",
        )

    def test_annotate_limits_dotted_revnos(self):
        """Annotate should limit dotted revnos to a depth of 12."""
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


class TestAnnotator(tests.TestCaseWithMemoryTransport):
    fa_key = (b"f-id", b"a-id")
    fb_key = (b"f-id", b"b-id")
    fc_key = (b"f-id", b"c-id")
    fd_key = (b"f-id", b"d-id")
    fe_key = (b"f-id", b"e-id")
    ff_key = (b"f-id", b"f-id")

    def make_no_graph_texts(self):
        factory = knit.make_pack_factory(False, False, 2)
        self.vf = factory(self.get_transport())
        self.ann = Annotator(self.vf)
        self.vf.add_lines(self.fa_key, (), [b"simple\n", b"content\n"])
        self.vf.add_lines(self.fb_key, (), [b"simple\n", b"new content\n"])

    def make_simple_text(self):
        # TODO: all we really need is a VersionedFile instance, we'd like to
        #       avoid creating all the intermediate stuff
        factory = knit.make_pack_factory(True, True, 2)
        self.vf = factory(self.get_transport())
        # This assumes nothing special happens during __init__, which may be
        # valid
        self.ann = Annotator(self.vf)
        #  A    'simple|content|'
        #  |
        #  B    'simple|new content|'
        self.vf.add_lines(self.fa_key, [], [b"simple\n", b"content\n"])
        self.vf.add_lines(self.fb_key, [self.fa_key], [b"simple\n", b"new content\n"])

    def make_merge_text(self):
        self.make_simple_text()
        #  A    'simple|content|'
        #  |\
        #  B |  'simple|new content|'
        #  | |
        #  | C  'simple|from c|content|'
        #  |/
        #  D    'simple|from c|new content|introduced in merge|'
        self.vf.add_lines(
            self.fc_key, [self.fa_key], [b"simple\n", b"from c\n", b"content\n"]
        )
        self.vf.add_lines(
            self.fd_key,
            [self.fb_key, self.fc_key],
            [b"simple\n", b"from c\n", b"new content\n", b"introduced in merge\n"],
        )

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
        self.vf.add_lines(self.fc_key, [self.fa_key], [b"simple\n", b"new content\n"])
        self.vf.add_lines(
            self.fd_key, [self.fb_key, self.fc_key], [b"simple\n", b"new content\n"]
        )

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
        self.vf.add_lines(self.fc_key, [self.fa_key], [b"simple\n", b"new content\n"])
        self.vf.add_lines(
            self.fd_key, [self.fb_key, self.fc_key], [b"simple\n", b"new content\n"]
        )
        self.vf.add_lines(self.fe_key, [self.fa_key], [b"simple\n", b"new content\n"])
        self.vf.add_lines(
            self.ff_key, [self.fd_key, self.fe_key], [b"simple\n", b"new content\n"]
        )

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
        self.vf.add_lines(self.fc_key, [self.fb_key], [b"simple\n", b"content\n"])
        # d merges 'a' and 'c', to find both claim last modified
        self.vf.add_lines(
            self.fd_key, [self.fa_key, self.fc_key], [b"simple\n", b"content\n"]
        )

    def assertAnnotateEqual(self, expected_annotation, key, exp_text=None):
        annotation, lines = self.ann.annotate(key)
        self.assertEqual(expected_annotation, annotation)
        if exp_text is None:
            record = next(self.vf.get_record_stream([key], "unordered", True))
            exp_text = record.get_bytes_as("fulltext")
        self.assertEqualDiff(exp_text, b"".join(lines))

    def test_annotate_missing(self):
        self.make_simple_text()
        self.assertRaises(
            errors.RevisionNotPresent, self.ann.annotate, (b"not", b"present")
        )

    def test_annotate_simple(self):
        self.make_simple_text()
        self.assertAnnotateEqual([(self.fa_key,)] * 2, self.fa_key)
        self.assertAnnotateEqual([(self.fa_key,), (self.fb_key,)], self.fb_key)

    def test_annotate_merge_text(self):
        self.make_merge_text()
        self.assertAnnotateEqual(
            [(self.fa_key,), (self.fc_key,), (self.fb_key,), (self.fd_key,)],
            self.fd_key,
        )

    def test_annotate_common_merge_text(self):
        self.make_common_merge_text()
        self.assertAnnotateEqual(
            [(self.fa_key,), (self.fb_key, self.fc_key)], self.fd_key
        )

    def test_annotate_many_way_common_merge_text(self):
        self.make_many_way_common_merge_text()
        self.assertAnnotateEqual(
            [(self.fa_key,), (self.fb_key, self.fc_key, self.fe_key)], self.ff_key
        )

    def test_annotate_merge_and_restored(self):
        self.make_merge_and_restored_text()
        self.assertAnnotateEqual(
            [(self.fa_key,), (self.fa_key, self.fc_key)], self.fd_key
        )

    def test_annotate_flat_simple(self):
        self.make_simple_text()
        self.assertEqual(
            [
                (self.fa_key, b"simple\n"),
                (self.fa_key, b"content\n"),
            ],
            self.ann.annotate_flat(self.fa_key),
        )
        self.assertEqual(
            [
                (self.fa_key, b"simple\n"),
                (self.fb_key, b"new content\n"),
            ],
            self.ann.annotate_flat(self.fb_key),
        )

    def test_annotate_flat_merge_and_restored_text(self):
        self.make_merge_and_restored_text()
        # fc is a simple dominator of fa
        self.assertEqual(
            [
                (self.fa_key, b"simple\n"),
                (self.fc_key, b"content\n"),
            ],
            self.ann.annotate_flat(self.fd_key),
        )

    def test_annotate_common_merge_text_more(self):
        self.make_common_merge_text()
        # there is no common point, so we just pick the lexicographical lowest
        # and b'b-id' comes before b'c-id'
        self.assertEqual(
            [
                (self.fa_key, b"simple\n"),
                (self.fb_key, b"new content\n"),
            ],
            self.ann.annotate_flat(self.fd_key),
        )

    def test_annotate_many_way_common_merge_text_more(self):
        self.make_many_way_common_merge_text()
        self.assertEqual(
            [(self.fa_key, b"simple\n"), (self.fb_key, b"new content\n")],
            self.ann.annotate_flat(self.ff_key),
        )

    def test_annotate_flat_respects_break_ann_tie(self):
        seen = set()

        def custom_tiebreaker(annotated_lines):
            self.assertEqual(2, len(annotated_lines))
            left = annotated_lines[0]
            self.assertEqual(2, len(left))
            self.assertEqual(b"new content\n", left[1])
            right = annotated_lines[1]
            self.assertEqual(2, len(right))
            self.assertEqual(b"new content\n", right[1])
            seen.update([left[0], right[0]])
            # Our custom tiebreaker takes the *largest* value, rather than
            # the *smallest* value
            if left[0] < right[0]:
                return right
            else:
                return left

        self.overrideAttr(annotate, "_break_annotation_tie", custom_tiebreaker)
        self.make_many_way_common_merge_text()
        self.assertEqual(
            [(self.fa_key, b"simple\n"), (self.fe_key, b"new content\n")],
            self.ann.annotate_flat(self.ff_key),
        )
        # Calls happen in set iteration order but should keys should be seen
        self.assertEqual({self.fb_key, self.fc_key, self.fe_key}, seen)

    def test_needed_keys_simple(self):
        self.make_simple_text()
        keys, ann_keys = self.ann._get_needed_keys(self.fb_key)
        self.assertEqual([self.fa_key, self.fb_key], sorted(keys))
        self.assertEqual(
            {self.fa_key: 1, self.fb_key: 1}, self.ann._num_needed_children
        )
        self.assertEqual(set(), ann_keys)

    def test_needed_keys_many(self):
        self.make_many_way_common_merge_text()
        keys, ann_keys = self.ann._get_needed_keys(self.ff_key)
        self.assertEqual(
            [
                self.fa_key,
                self.fb_key,
                self.fc_key,
                self.fd_key,
                self.fe_key,
                self.ff_key,
            ],
            sorted(keys),
        )
        self.assertEqual(
            {
                self.fa_key: 3,
                self.fb_key: 1,
                self.fc_key: 1,
                self.fd_key: 1,
                self.fe_key: 1,
                self.ff_key: 1,
            },
            self.ann._num_needed_children,
        )
        self.assertEqual(set(), ann_keys)

    def test_needed_keys_with_special_text(self):
        self.make_many_way_common_merge_text()
        spec_key = (b"f-id", revision.CURRENT_REVISION)
        spec_text = b"simple\nnew content\nlocally modified\n"
        self.ann.add_special_text(spec_key, [self.fd_key, self.fe_key], spec_text)
        keys, ann_keys = self.ann._get_needed_keys(spec_key)
        self.assertEqual(
            [
                self.fa_key,
                self.fb_key,
                self.fc_key,
                self.fd_key,
                self.fe_key,
            ],
            sorted(keys),
        )
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
        self.ann._text_cache[self.fd_key] = [b"simple\n", b"new content\n"]
        self.ann._annotations_cache[self.fd_key] = [
            (self.fa_key,),
            (self.fb_key, self.fc_key),
        ]
        self.ann._parent_map[self.fe_key] = (self.fa_key,)
        self.ann._text_cache[self.fe_key] = [b"simple\n", b"new content\n"]
        self.ann._annotations_cache[self.fe_key] = [
            (self.fa_key,),
            (self.fe_key,),
        ]
        keys, ann_keys = self.ann._get_needed_keys(self.ff_key)
        self.assertEqual([self.ff_key], sorted(keys))
        self.assertEqual(
            {
                self.fd_key: 1,
                self.fe_key: 1,
                self.ff_key: 1,
            },
            self.ann._num_needed_children,
        )
        self.assertEqual([], sorted(ann_keys))

    def test_record_annotation_removes_texts(self):
        self.make_many_way_common_merge_text()
        # Populate the caches
        for _x in self.ann._get_needed_texts(self.ff_key):
            continue
        self.assertEqual(
            {
                self.fa_key: 3,
                self.fb_key: 1,
                self.fc_key: 1,
                self.fd_key: 1,
                self.fe_key: 1,
                self.ff_key: 1,
            },
            self.ann._num_needed_children,
        )
        self.assertEqual(
            [
                self.fa_key,
                self.fb_key,
                self.fc_key,
                self.fd_key,
                self.fe_key,
                self.ff_key,
            ],
            sorted(self.ann._text_cache.keys()),
        )
        self.ann._record_annotation(self.fa_key, [], [])
        self.ann._record_annotation(self.fb_key, [self.fa_key], [])
        self.assertEqual(
            {
                self.fa_key: 2,
                self.fb_key: 1,
                self.fc_key: 1,
                self.fd_key: 1,
                self.fe_key: 1,
                self.ff_key: 1,
            },
            self.ann._num_needed_children,
        )
        self.assertIn(self.fa_key, self.ann._text_cache)
        self.assertIn(self.fa_key, self.ann._annotations_cache)
        self.ann._record_annotation(self.fc_key, [self.fa_key], [])
        self.ann._record_annotation(self.fd_key, [self.fb_key, self.fc_key], [])
        self.assertEqual(
            {
                self.fa_key: 1,
                self.fb_key: 0,
                self.fc_key: 0,
                self.fd_key: 1,
                self.fe_key: 1,
                self.ff_key: 1,
            },
            self.ann._num_needed_children,
        )
        self.assertIn(self.fa_key, self.ann._text_cache)
        self.assertIn(self.fa_key, self.ann._annotations_cache)
        self.assertNotIn(self.fb_key, self.ann._text_cache)
        self.assertNotIn(self.fb_key, self.ann._annotations_cache)
        self.assertNotIn(self.fc_key, self.ann._text_cache)
        self.assertNotIn(self.fc_key, self.ann._annotations_cache)

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
        spec_key = (b"f-id", revision.CURRENT_REVISION)
        spec_text = b"simple\nnew content\nlocally modified\n"
        self.ann.add_special_text(spec_key, [self.fd_key, self.fe_key], spec_text)
        self.assertAnnotateEqual(
            [
                (self.fa_key,),
                (self.fb_key, self.fc_key, self.fe_key),
                (spec_key,),
            ],
            spec_key,
            exp_text=spec_text,
        )

    def test_no_graph(self):
        self.make_no_graph_texts()
        self.assertAnnotateEqual(
            [
                (self.fa_key,),
                (self.fa_key,),
            ],
            self.fa_key,
        )
        self.assertAnnotateEqual(
            [
                (self.fb_key,),
                (self.fb_key,),
            ],
            self.fb_key,
        )
