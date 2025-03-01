# Copyright (C) 2005-2011, 2016 Canonical Ltd
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


# TODO: tests regarding version names
# TODO: rbc 20050108 test that join does not leave an inconsistent weave
#       if it fails.

"""test suite for weave algorithm."""

from io import BytesIO
from pprint import pformat

from ... import errors
from ...osutils import sha_string
from ..weave import Weave, WeaveFormatError, WeaveInvalidChecksum
from ..weavefile import read_weave, write_weave
from . import TestCase, TestCaseInTempDir

# texts for use in testing
TEXT_0 = [b"Hello world"]
TEXT_1 = [b"Hello world", b"A second line"]


class TestBase(TestCase):
    def check_read_write(self, k):
        """Check the weave k can be written & re-read."""
        from tempfile import TemporaryFile

        tf = TemporaryFile()

        write_weave(k, tf)
        tf.seek(0)
        k2 = read_weave(tf)

        if k != k2:
            tf.seek(0)
            self.log("serialized weave:")
            self.log(tf.read())

            self.log("")
            self.log("parents: %s" % (k._parents == k2._parents))
            self.log("         {!r}".format(k._parents))
            self.log("         {!r}".format(k2._parents))
            self.log("")
            self.fail("read/write check failed")


class WeaveContains(TestBase):
    """Weave __contains__ operator."""

    def runTest(self):
        k = Weave(get_scope=lambda: None)
        self.assertFalse(b"foo" in k)
        k.add_lines(b"foo", [], TEXT_1)
        self.assertTrue(b"foo" in k)


class Easy(TestBase):
    def runTest(self):
        Weave()


class AnnotateOne(TestBase):
    def runTest(self):
        k = Weave()
        k.add_lines(b"text0", [], TEXT_0)
        self.assertEqual(k.annotate(b"text0"), [(b"text0", TEXT_0[0])])


class InvalidAdd(TestBase):
    """Try to use invalid version number during add."""

    def runTest(self):
        k = Weave()

        self.assertRaises(
            errors.RevisionNotPresent, k.add_lines, b"text0", [b"69"], [b"new text!"]
        )


class RepeatedAdd(TestBase):
    """Add the same version twice; harmless."""

    def test_duplicate_add(self):
        k = Weave()
        idx = k.add_lines(b"text0", [], TEXT_0)
        idx2 = k.add_lines(b"text0", [], TEXT_0)
        self.assertEqual(idx, idx2)


class InvalidRepeatedAdd(TestBase):
    def runTest(self):
        k = Weave()
        k.add_lines(b"basis", [], TEXT_0)
        k.add_lines(b"text0", [], TEXT_0)
        self.assertRaises(
            errors.RevisionAlreadyPresent,
            k.add_lines,
            b"text0",
            [],
            [b"not the same text"],
        )
        self.assertRaises(
            errors.RevisionAlreadyPresent,
            k.add_lines,
            b"text0",
            [b"basis"],  # not the right parents
            TEXT_0,
        )


class InsertLines(TestBase):
    """Store a revision that adds one line to the original.

    Look at the annotations to make sure that the first line is matched
    and not stored repeatedly.
    """

    def runTest(self):
        k = Weave()

        k.add_lines(b"text0", [], [b"line 1"])
        k.add_lines(b"text1", [b"text0"], [b"line 1", b"line 2"])

        self.assertEqual(k.annotate(b"text0"), [(b"text0", b"line 1")])

        self.assertEqual(k.get_lines(1), [b"line 1", b"line 2"])

        self.assertEqual(
            k.annotate(b"text1"), [(b"text0", b"line 1"), (b"text1", b"line 2")]
        )

        k.add_lines(b"text2", [b"text0"], [b"line 1", b"diverged line"])

        self.assertEqual(
            k.annotate(b"text2"), [(b"text0", b"line 1"), (b"text2", b"diverged line")]
        )

        text3 = [b"line 1", b"middle line", b"line 2"]
        k.add_lines(b"text3", [b"text0", b"text1"], text3)

        # self.log("changes to text3: " + pformat(list(k._delta(set([0, 1]),
        # text3))))

        self.log("k._weave=" + pformat(k._weave))

        self.assertEqual(
            k.annotate(b"text3"),
            [(b"text0", b"line 1"), (b"text3", b"middle line"), (b"text1", b"line 2")],
        )

        # now multiple insertions at different places
        k.add_lines(
            b"text4",
            [b"text0", b"text1", b"text3"],
            [b"line 1", b"aaa", b"middle line", b"bbb", b"line 2", b"ccc"],
        )

        self.assertEqual(
            k.annotate(b"text4"),
            [
                (b"text0", b"line 1"),
                (b"text4", b"aaa"),
                (b"text3", b"middle line"),
                (b"text4", b"bbb"),
                (b"text1", b"line 2"),
                (b"text4", b"ccc"),
            ],
        )


class DeleteLines(TestBase):
    """Deletion of lines from existing text.

    Try various texts all based on a common ancestor.
    """

    def runTest(self):
        k = Weave()

        base_text = [b"one", b"two", b"three", b"four"]

        k.add_lines(b"text0", [], base_text)

        texts = [
            [b"one", b"two", b"three"],
            [b"two", b"three", b"four"],
            [b"one", b"four"],
            [b"one", b"two", b"three", b"four"],
        ]

        i = 1
        for t in texts:
            k.add_lines(b"text%d" % i, [b"text0"], t)
            i += 1

        self.log("final weave:")
        self.log("k._weave=" + pformat(k._weave))

        for i in range(len(texts)):
            self.assertEqual(k.get_lines(i + 1), texts[i])


class SuicideDelete(TestBase):
    """Invalid weave which tries to add and delete simultaneously."""

    def runTest(self):
        k = Weave()

        k._parents = [
            (),
        ]
        k._weave = [
            (b"{", 0),
            b"first line",
            (b"[", 0),
            b"deleted in 0",
            (b"]", 0),
            (b"}", 0),
        ]
        # SKIPPED
        # Weave.get doesn't trap this anymore
        return

        self.assertRaises(WeaveFormatError, k.get_lines, 0)


class CannedDelete(TestBase):
    """Unpack canned weave with deleted lines."""

    def runTest(self):
        k = Weave()

        k._parents = [
            (),
            frozenset([0]),
        ]
        k._weave = [
            (b"{", 0),
            b"first line",
            (b"[", 1),
            b"line to be deleted",
            (b"]", 1),
            b"last line",
            (b"}", 0),
        ]
        k._sha1s = [
            sha_string(b"first lineline to be deletedlast line"),
            sha_string(b"first linelast line"),
        ]

        self.assertEqual(
            k.get_lines(0),
            [
                b"first line",
                b"line to be deleted",
                b"last line",
            ],
        )

        self.assertEqual(
            k.get_lines(1),
            [
                b"first line",
                b"last line",
            ],
        )


class CannedReplacement(TestBase):
    """Unpack canned weave with deleted lines."""

    def runTest(self):
        k = Weave()

        k._parents = [
            frozenset(),
            frozenset([0]),
        ]
        k._weave = [
            (b"{", 0),
            b"first line",
            (b"[", 1),
            b"line to be deleted",
            (b"]", 1),
            (b"{", 1),
            b"replacement line",
            (b"}", 1),
            b"last line",
            (b"}", 0),
        ]
        k._sha1s = [
            sha_string(b"first lineline to be deletedlast line"),
            sha_string(b"first linereplacement linelast line"),
        ]

        self.assertEqual(
            k.get_lines(0),
            [
                b"first line",
                b"line to be deleted",
                b"last line",
            ],
        )

        self.assertEqual(
            k.get_lines(1),
            [
                b"first line",
                b"replacement line",
                b"last line",
            ],
        )


class BadWeave(TestBase):
    """Test that we trap an insert which should not occur."""

    def runTest(self):
        k = Weave()

        k._parents = [
            frozenset(),
        ]
        k._weave = [
            b"bad line",
            (b"{", 0),
            b"foo {",
            (b"{", 1),
            b"  added in version 1",
            (b"{", 2),
            b"  added in v2",
            (b"}", 2),
            b"  also from v1",
            (b"}", 1),
            b"}",
            (b"}", 0),
        ]

        # SKIPPED
        # Weave.get doesn't trap this anymore
        return

        self.assertRaises(WeaveFormatError, k.get, 0)


class BadInsert(TestBase):
    """Test that we trap an insert which should not occur."""

    def runTest(self):
        k = Weave()

        k._parents = [
            frozenset(),
            frozenset([0]),
            frozenset([0]),
            frozenset([0, 1, 2]),
        ]
        k._weave = [
            (b"{", 0),
            b"foo {",
            (b"{", 1),
            b"  added in version 1",
            (b"{", 1),
            b"  more in 1",
            (b"}", 1),
            (b"}", 1),
            (b"}", 0),
        ]

        # this is not currently enforced by get
        return

        self.assertRaises(WeaveFormatError, k.get, 0)

        self.assertRaises(WeaveFormatError, k.get, 1)


class InsertNested(TestBase):
    """Insertion with nested instructions."""

    def runTest(self):
        k = Weave()

        k._parents = [
            frozenset(),
            frozenset([0]),
            frozenset([0]),
            frozenset([0, 1, 2]),
        ]
        k._weave = [
            (b"{", 0),
            b"foo {",
            (b"{", 1),
            b"  added in version 1",
            (b"{", 2),
            b"  added in v2",
            (b"}", 2),
            b"  also from v1",
            (b"}", 1),
            b"}",
            (b"}", 0),
        ]

        k._sha1s = [
            sha_string(b"foo {}"),
            sha_string(b"foo {  added in version 1  also from v1}"),
            sha_string(b"foo {  added in v2}"),
            sha_string(b"foo {  added in version 1  added in v2  also from v1}"),
        ]

        self.assertEqual(k.get_lines(0), [b"foo {", b"}"])

        self.assertEqual(
            k.get_lines(1), [b"foo {", b"  added in version 1", b"  also from v1", b"}"]
        )

        self.assertEqual(k.get_lines(2), [b"foo {", b"  added in v2", b"}"])

        self.assertEqual(
            k.get_lines(3),
            [
                b"foo {",
                b"  added in version 1",
                b"  added in v2",
                b"  also from v1",
                b"}",
            ],
        )


class DeleteLines2(TestBase):
    """Test recording revisions that delete lines.

    This relies on the weave having a way to represent lines knocked
    out by a later revision.
    """

    def runTest(self):
        k = Weave()

        k.add_lines(b"text0", [], [b"line the first", b"line 2", b"line 3", b"fine"])

        self.assertEqual(len(k.get_lines(0)), 4)

        k.add_lines(b"text1", [b"text0"], [b"line the first", b"fine"])

        self.assertEqual(k.get_lines(1), [b"line the first", b"fine"])

        self.assertEqual(
            k.annotate(b"text1"), [(b"text0", b"line the first"), (b"text0", b"fine")]
        )


class IncludeVersions(TestBase):
    """Check texts that are stored across multiple revisions.

    Here we manually create a weave with particular encoding and make
    sure it unpacks properly.

    Text 0 includes nothing; text 1 includes text 0 and adds some
    lines.
    """

    def runTest(self):
        k = Weave()

        k._parents = [frozenset(), frozenset([0])]
        k._weave = [
            (b"{", 0),
            b"first line",
            (b"}", 0),
            (b"{", 1),
            b"second line",
            (b"}", 1),
        ]

        k._sha1s = [sha_string(b"first line"), sha_string(b"first linesecond line")]

        self.assertEqual(k.get_lines(1), [b"first line", b"second line"])

        self.assertEqual(k.get_lines(0), [b"first line"])


class DivergedIncludes(TestBase):
    """Weave with two diverged texts based on version 0."""

    def runTest(self):
        # FIXME make the weave, dont poke at it.
        k = Weave()

        k._names = [b"0", b"1", b"2"]
        k._name_map = {b"0": 0, b"1": 1, b"2": 2}
        k._parents = [
            frozenset(),
            frozenset([0]),
            frozenset([0]),
        ]
        k._weave = [
            (b"{", 0),
            b"first line",
            (b"}", 0),
            (b"{", 1),
            b"second line",
            (b"}", 1),
            (b"{", 2),
            b"alternative second line",
            (b"}", 2),
        ]

        k._sha1s = [
            sha_string(b"first line"),
            sha_string(b"first linesecond line"),
            sha_string(b"first linealternative second line"),
        ]

        self.assertEqual(k.get_lines(0), [b"first line"])

        self.assertEqual(k.get_lines(1), [b"first line", b"second line"])

        self.assertEqual(k.get_lines(b"2"), [b"first line", b"alternative second line"])

        self.assertEqual(set(k.get_ancestry([b"2"])), {b"0", b"2"})


class ReplaceLine(TestBase):
    def runTest(self):
        k = Weave()

        text0 = [b"cheddar", b"stilton", b"gruyere"]
        text1 = [b"cheddar", b"blue vein", b"neufchatel", b"chevre"]

        k.add_lines(b"text0", [], text0)
        k.add_lines(b"text1", [b"text0"], text1)

        self.log("k._weave=" + pformat(k._weave))

        self.assertEqual(k.get_lines(0), text0)
        self.assertEqual(k.get_lines(1), text1)


class Merge(TestBase):
    """Storage of versions that merge diverged parents."""

    def runTest(self):
        k = Weave()

        texts = [
            [b"header"],
            [b"header", b"", b"line from 1"],
            [b"header", b"", b"line from 2", b"more from 2"],
            [b"header", b"", b"line from 1", b"fixup line", b"line from 2"],
        ]

        k.add_lines(b"text0", [], texts[0])
        k.add_lines(b"text1", [b"text0"], texts[1])
        k.add_lines(b"text2", [b"text0"], texts[2])
        k.add_lines(b"merge", [b"text0", b"text1", b"text2"], texts[3])

        for i, t in enumerate(texts):
            self.assertEqual(k.get_lines(i), t)

        self.assertEqual(
            k.annotate(b"merge"),
            [
                (b"text0", b"header"),
                (b"text1", b""),
                (b"text1", b"line from 1"),
                (b"merge", b"fixup line"),
                (b"text2", b"line from 2"),
            ],
        )

        self.assertEqual(
            set(k.get_ancestry([b"merge"])), {b"text0", b"text1", b"text2", b"merge"}
        )

        self.log("k._weave=" + pformat(k._weave))

        self.check_read_write(k)


class Conflicts(TestBase):
    """Test detection of conflicting regions during a merge.

    A base version is inserted, then two descendents try to
    insert different lines in the same place.  These should be
    reported as a possible conflict and forwarded to the user.
    """

    def runTest(self):
        return  # NOT RUN
        k = Weave()

        k.add_lines([], [b"aaa", b"bbb"])
        k.add_lines([0], [b"aaa", b"111", b"bbb"])
        k.add_lines([1], [b"aaa", b"222", b"bbb"])

        k.merge([1, 2])

        self.assertEqual([[[b"aaa"]], [[b"111"], [b"222"]], [[b"bbb"]]])


class NonConflict(TestBase):
    """Two descendants insert compatible changes.

    No conflict should be reported.
    """

    def runTest(self):
        return  # NOT RUN
        k = Weave()

        k.add_lines([], [b"aaa", b"bbb"])
        k.add_lines([0], [b"111", b"aaa", b"ccc", b"bbb"])
        k.add_lines([1], [b"aaa", b"ccc", b"bbb", b"222"])


class Khayyam(TestBase):
    """Test changes to multi-line texts, and read/write."""

    def test_multi_line_merge(self):
        rawtexts = [
            b"""A Book of Verses underneath the Bough,
            A Jug of Wine, a Loaf of Bread, -- and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise enow!""",
            b"""A Book of Verses underneath the Bough,
            A Jug of Wine, a Loaf of Bread, -- and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise now!""",
            b"""A Book of poems underneath the tree,
            A Jug of Wine, a Loaf of Bread,
            and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise now!

            -- O. Khayyam""",
            b"""A Book of Verses underneath the Bough,
            A Jug of Wine, a Loaf of Bread,
            and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise now!""",
        ]
        texts = [[l.strip() for l in t.split(b"\n")] for t in rawtexts]

        k = Weave()
        parents = set()
        i = 0
        for t in texts:
            k.add_lines(b"text%d" % i, list(parents), t)
            parents.add(b"text%d" % i)
            i += 1

        self.log("k._weave=" + pformat(k._weave))

        for i, t in enumerate(texts):
            self.assertEqual(k.get_lines(i), t)

        self.check_read_write(k)


class JoinWeavesTests(TestBase):
    def setUp(self):
        super().setUp()
        self.weave1 = Weave()
        self.lines1 = [b"hello\n"]
        self.lines3 = [b"hello\n", b"cruel\n", b"world\n"]
        self.weave1.add_lines(b"v1", [], self.lines1)
        self.weave1.add_lines(b"v2", [b"v1"], [b"hello\n", b"world\n"])
        self.weave1.add_lines(b"v3", [b"v2"], self.lines3)

    def test_written_detection(self):
        # Test detection of weave file corruption.
        #
        # Make sure that we can detect if a weave file has
        # been corrupted. This doesn't test all forms of corruption,
        # but it at least helps verify the data you get, is what you want.

        w = Weave()
        w.add_lines(b"v1", [], [b"hello\n"])
        w.add_lines(b"v2", [b"v1"], [b"hello\n", b"there\n"])

        tmpf = BytesIO()
        write_weave(w, tmpf)

        # Because we are corrupting, we need to make sure we have the exact
        # text
        self.assertEqual(
            b"# bzr weave file v5\n"
            b"i\n1 f572d396fae9206628714fb2ce00f72e94f2258f\nn v1\n\n"
            b"i 0\n1 90f265c6e75f1c8f9ab76dcf85528352c5f215ef\nn v2\n\n"
            b"w\n{ 0\n. hello\n}\n{ 1\n. there\n}\nW\n",
            tmpf.getvalue(),
        )

        # Change a single letter
        tmpf = BytesIO(
            b"# bzr weave file v5\n"
            b"i\n1 f572d396fae9206628714fb2ce00f72e94f2258f\nn v1\n\n"
            b"i 0\n1 90f265c6e75f1c8f9ab76dcf85528352c5f215ef\nn v2\n\n"
            b"w\n{ 0\n. hello\n}\n{ 1\n. There\n}\nW\n"
        )

        w = read_weave(tmpf)

        self.assertEqual(b"hello\n", w.get_text(b"v1"))
        self.assertRaises(WeaveInvalidChecksum, w.get_text, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.get_lines, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.check)

        # Change the sha checksum
        tmpf = BytesIO(
            b"# bzr weave file v5\n"
            b"i\n1 f572d396fae9206628714fb2ce00f72e94f2258f\nn v1\n\n"
            b"i 0\n1 f0f265c6e75f1c8f9ab76dcf85528352c5f215ef\nn v2\n\n"
            b"w\n{ 0\n. hello\n}\n{ 1\n. there\n}\nW\n"
        )

        w = read_weave(tmpf)

        self.assertEqual(b"hello\n", w.get_text(b"v1"))
        self.assertRaises(WeaveInvalidChecksum, w.get_text, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.get_lines, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.check)


class TestWeave(TestCase):
    def test_allow_reserved_false(self):
        w = Weave("name", allow_reserved=False)
        # Add lines is checked at the WeaveFile level, not at the Weave level
        w.add_lines(b"name:", [], TEXT_1)
        # But get_lines is checked at this level
        self.assertRaises(errors.ReservedId, w.get_lines, b"name:")

    def test_allow_reserved_true(self):
        w = Weave("name", allow_reserved=True)
        w.add_lines(b"name:", [], TEXT_1)
        self.assertEqual(TEXT_1, w.get_lines(b"name:"))


class InstrumentedWeave(Weave):
    """Keep track of how many times functions are called."""

    def __init__(self, weave_name=None):
        self._extract_count = 0
        Weave.__init__(self, weave_name=weave_name)

    def _extract(self, versions):
        self._extract_count += 1
        return Weave._extract(self, versions)


class TestNeedsReweave(TestCase):
    """Internal corner cases for when reweave is needed."""

    def test_compatible_parents(self):
        w1 = Weave("a")
        my_parents = {1, 2, 3}
        # subsets are ok
        self.assertTrue(w1._compatible_parents(my_parents, {3}))
        # same sets
        self.assertTrue(w1._compatible_parents(my_parents, set(my_parents)))
        # same empty corner case
        self.assertTrue(w1._compatible_parents(set(), set()))
        # other cannot contain stuff my_parents does not
        self.assertFalse(w1._compatible_parents(set(), {1}))
        self.assertFalse(w1._compatible_parents(my_parents, {1, 2, 3, 4}))
        self.assertFalse(w1._compatible_parents(my_parents, {4}))


class TestWeaveFile(TestCaseInTempDir):
    def test_empty_file(self):
        with open("empty.weave", "wb+") as f:
            self.assertRaises(WeaveFormatError, read_weave, f)
