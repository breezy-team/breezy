# Copyright (C) 2006-2012, 2016 Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
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


# TODO: might be nice to create a versionedfile with some type of corruption
# considered typical and check that it can be detected/corrected.

import itertools
from gzip import GzipFile
from io import BytesIO

from ... import errors, osutils, progress, transport, ui
from ... import graph as _mod_graph
from ...errors import RevisionAlreadyPresent, RevisionNotPresent
from ...tests import (
    TestCase,
    TestCaseWithMemoryTransport,
    TestNotApplicable,
    TestSkipped,
)
from ...tests.http_utils import TestCaseWithWebserver
from ...tests.scenarios import load_tests_apply_scenarios
from ...transport.memory import MemoryTransport
from .. import groupcompress
from .. import knit as _mod_knit
from .. import versionedfile as versionedfile
from ..knit import cleanup_pack_knit, make_file_factory, make_pack_factory
from ..versionedfile import (
    ChunkedContentFactory,
    ConstantMapper,
    ExistingContent,
    HashEscapedPrefixMapper,
    PrefixMapper,
    UnavailableRepresentation,
    VirtualVersionedFiles,
    make_versioned_files_factory,
)
from ..weave import WeaveFile, WeaveInvalidChecksum
from ..weavefile import write_weave

load_tests = load_tests_apply_scenarios


def get_diamond_vf(f, trailing_eol=True, left_only=False):
    r"""Get a diamond graph to exercise deltas and merges.

    :param trailing_eol: If True end the last line with \n.
    """
    parents = {
        b"origin": (),
        b"base": ((b"origin",),),
        b"left": ((b"base",),),
        b"right": ((b"base",),),
        b"merged": ((b"left",), (b"right",)),
    }
    # insert a diamond graph to exercise deltas and merges.
    if trailing_eol:
        last_char = b"\n"
    else:
        last_char = b""
    f.add_lines(b"origin", [], [b"origin" + last_char])
    f.add_lines(b"base", [b"origin"], [b"base" + last_char])
    f.add_lines(b"left", [b"base"], [b"base\n", b"left" + last_char])
    if not left_only:
        f.add_lines(b"right", [b"base"], [b"base\n", b"right" + last_char])
        f.add_lines(
            b"merged",
            [b"left", b"right"],
            [b"base\n", b"left\n", b"right\n", b"merged" + last_char],
        )
    return f, parents


def get_diamond_files(
    files, key_length, trailing_eol=True, left_only=False, nograph=False, nokeys=False
):
    r"""Get a diamond graph to exercise deltas and merges.

    This creates a 5-node graph in files. If files supports 2-length keys two
    graphs are made to exercise the support for multiple ids.

    :param trailing_eol: If True end the last line with \n.
    :param key_length: The length of keys in files. Currently supports length 1
        and 2 keys.
    :param left_only: If True do not add the right and merged nodes.
    :param nograph: If True, do not provide parents to the add_lines calls;
        this is useful for tests that need inserted data but have graphless
        stores.
    :param nokeys: If True, pass None is as the key for all insertions.
        Currently implies nograph.
    :return: The results of the add_lines calls.
    """
    if nokeys:
        nograph = True
    if key_length == 1:
        prefixes = [()]
    else:
        prefixes = [(b"FileA",), (b"FileB",)]
    # insert a diamond graph to exercise deltas and merges.
    if trailing_eol:
        last_char = b"\n"
    else:
        last_char = b""
    result = []

    def get_parents(suffix_list):
        if nograph:
            return ()
        else:
            result = [prefix + suffix for suffix in suffix_list]
            return result

    def get_key(suffix):
        if nokeys:
            return (None,)
        else:
            return (suffix,)

    # we loop over each key because that spreads the inserts across prefixes,
    # which is how commit operates.
    for prefix in prefixes:
        result.append(
            files.add_lines(prefix + get_key(b"origin"), (), [b"origin" + last_char])
        )
    for prefix in prefixes:
        result.append(
            files.add_lines(
                prefix + get_key(b"base"),
                get_parents([(b"origin",)]),
                [b"base" + last_char],
            )
        )
    for prefix in prefixes:
        result.append(
            files.add_lines(
                prefix + get_key(b"left"),
                get_parents([(b"base",)]),
                [b"base\n", b"left" + last_char],
            )
        )
    if not left_only:
        for prefix in prefixes:
            result.append(
                files.add_lines(
                    prefix + get_key(b"right"),
                    get_parents([(b"base",)]),
                    [b"base\n", b"right" + last_char],
                )
            )
        for prefix in prefixes:
            result.append(
                files.add_lines(
                    prefix + get_key(b"merged"),
                    get_parents([(b"left",), (b"right",)]),
                    [b"base\n", b"left\n", b"right\n", b"merged" + last_char],
                )
            )
    return result


class VersionedFileTestMixIn:
    """A mixin test class for testing VersionedFiles.

    This is not an adaptor-style test at this point because
    theres no dynamic substitution of versioned file implementations,
    they are strictly controlled by their owning repositories.
    """

    def get_transaction(self):
        if not hasattr(self, "_transaction"):
            self._transaction = None
        return self._transaction

    def test_add(self):
        f = self.get_file()
        f.add_lines(b"r0", [], [b"a\n", b"b\n"])
        f.add_lines(b"r1", [b"r0"], [b"b\n", b"c\n"])

        def verify_file(f):
            versions = f.versions()
            self.assertTrue(b"r0" in versions)
            self.assertTrue(b"r1" in versions)
            self.assertEqual(f.get_lines(b"r0"), [b"a\n", b"b\n"])
            self.assertEqual(f.get_text(b"r0"), b"a\nb\n")
            self.assertEqual(f.get_lines(b"r1"), [b"b\n", b"c\n"])
            self.assertEqual(2, len(f))
            self.assertEqual(2, f.num_versions())

            self.assertRaises(RevisionNotPresent, f.add_lines, b"r2", [b"foo"], [])
            self.assertRaises(RevisionAlreadyPresent, f.add_lines, b"r1", [], [])

        verify_file(f)
        # this checks that reopen with create=True does not break anything.
        f = self.reopen_file(create=True)
        verify_file(f)

    def test_adds_with_parent_texts(self):
        f = self.get_file()
        parent_texts = {}
        _, _, parent_texts[b"r0"] = f.add_lines(b"r0", [], [b"a\n", b"b\n"])
        try:
            _, _, parent_texts[b"r1"] = f.add_lines_with_ghosts(
                b"r1", [b"r0", b"ghost"], [b"b\n", b"c\n"], parent_texts=parent_texts
            )
        except NotImplementedError:
            # if the format doesn't support ghosts, just add normally.
            _, _, parent_texts[b"r1"] = f.add_lines(
                b"r1", [b"r0"], [b"b\n", b"c\n"], parent_texts=parent_texts
            )
        f.add_lines(b"r2", [b"r1"], [b"c\n", b"d\n"], parent_texts=parent_texts)
        self.assertNotEqual(None, parent_texts[b"r0"])
        self.assertNotEqual(None, parent_texts[b"r1"])

        def verify_file(f):
            versions = f.versions()
            self.assertTrue(b"r0" in versions)
            self.assertTrue(b"r1" in versions)
            self.assertTrue(b"r2" in versions)
            self.assertEqual(f.get_lines(b"r0"), [b"a\n", b"b\n"])
            self.assertEqual(f.get_lines(b"r1"), [b"b\n", b"c\n"])
            self.assertEqual(f.get_lines(b"r2"), [b"c\n", b"d\n"])
            self.assertEqual(3, f.num_versions())
            origins = f.annotate(b"r1")
            self.assertEqual(origins[0][0], b"r0")
            self.assertEqual(origins[1][0], b"r1")
            origins = f.annotate(b"r2")
            self.assertEqual(origins[0][0], b"r1")
            self.assertEqual(origins[1][0], b"r2")

        verify_file(f)
        f = self.reopen_file()
        verify_file(f)

    def test_add_unicode_content(self):
        # unicode content is not permitted in versioned files.
        # versioned files version sequences of bytes only.
        vf = self.get_file()
        self.assertRaises(
            errors.BzrBadParameterUnicode,
            vf.add_lines,
            b"a",
            [],
            [b"a\n", "b\n", b"c\n"],
        )
        self.assertRaises(
            (errors.BzrBadParameterUnicode, NotImplementedError),
            vf.add_lines_with_ghosts,
            b"a",
            [],
            [b"a\n", "b\n", b"c\n"],
        )

    def test_add_follows_left_matching_blocks(self):
        """If we change left_matching_blocks, delta changes.

        Note: There are multiple correct deltas in this case, because
        we start with 1 "a" and we get 3.
        """
        vf = self.get_file()
        if isinstance(vf, WeaveFile):
            raise TestSkipped("WeaveFile ignores left_matching_blocks")
        vf.add_lines(b"1", [], [b"a\n"])
        vf.add_lines(
            b"2",
            [b"1"],
            [b"a\n", b"a\n", b"a\n"],
            left_matching_blocks=[(0, 0, 1), (1, 3, 0)],
        )
        self.assertEqual([b"a\n", b"a\n", b"a\n"], vf.get_lines(b"2"))
        vf.add_lines(
            b"3",
            [b"1"],
            [b"a\n", b"a\n", b"a\n"],
            left_matching_blocks=[(0, 2, 1), (1, 3, 0)],
        )
        self.assertEqual([b"a\n", b"a\n", b"a\n"], vf.get_lines(b"3"))

    def test_inline_newline_throws(self):
        # \r characters are not permitted in lines being added
        vf = self.get_file()
        self.assertRaises(
            errors.BzrBadParameterContainsNewline, vf.add_lines, b"a", [], [b"a\n\n"]
        )
        self.assertRaises(
            (errors.BzrBadParameterContainsNewline, NotImplementedError),
            vf.add_lines_with_ghosts,
            b"a",
            [],
            [b"a\n\n"],
        )
        # but inline CR's are allowed
        vf.add_lines(b"a", [], [b"a\r\n"])
        try:
            vf.add_lines_with_ghosts(b"b", [], [b"a\r\n"])
        except NotImplementedError:
            pass

    def test_add_reserved(self):
        vf = self.get_file()
        self.assertRaises(
            errors.ReservedId, vf.add_lines, b"a:", [], [b"a\n", b"b\n", b"c\n"]
        )

    def test_add_lines_nostoresha(self):
        """When nostore_sha is supplied using old content raises."""
        vf = self.get_file()
        empty_text = (b"a", [])
        sample_text_nl = (b"b", [b"foo\n", b"bar\n"])
        sample_text_no_nl = (b"c", [b"foo\n", b"bar"])
        shas = []
        for version, lines in (empty_text, sample_text_nl, sample_text_no_nl):
            sha, _, _ = vf.add_lines(version, [], lines)
            shas.append(sha)
        # we now have a copy of all the lines in the vf.
        for sha, (version, lines) in zip(
            shas, (empty_text, sample_text_nl, sample_text_no_nl)
        ):
            self.assertRaises(
                ExistingContent,
                vf.add_lines,
                version + b"2",
                [],
                lines,
                nostore_sha=sha,
            )
            # and no new version should have been added.
            self.assertRaises(errors.RevisionNotPresent, vf.get_lines, version + b"2")

    def test_add_lines_with_ghosts_nostoresha(self):
        """When nostore_sha is supplied using old content raises."""
        vf = self.get_file()
        empty_text = (b"a", [])
        sample_text_nl = (b"b", [b"foo\n", b"bar\n"])
        sample_text_no_nl = (b"c", [b"foo\n", b"bar"])
        shas = []
        for version, lines in (empty_text, sample_text_nl, sample_text_no_nl):
            sha, _, _ = vf.add_lines(version, [], lines)
            shas.append(sha)
        # we now have a copy of all the lines in the vf.
        # is the test applicable to this vf implementation?
        try:
            vf.add_lines_with_ghosts(b"d", [], [])
        except NotImplementedError as e:
            raise TestSkipped("add_lines_with_ghosts is optional") from e
        for sha, (version, lines) in zip(
            shas, (empty_text, sample_text_nl, sample_text_no_nl)
        ):
            self.assertRaises(
                ExistingContent,
                vf.add_lines_with_ghosts,
                version + b"2",
                [],
                lines,
                nostore_sha=sha,
            )
            # and no new version should have been added.
            self.assertRaises(errors.RevisionNotPresent, vf.get_lines, version + b"2")

    def test_add_lines_return_value(self):
        # add_lines should return the sha1 and the text size.
        vf = self.get_file()
        empty_text = (b"a", [])
        sample_text_nl = (b"b", [b"foo\n", b"bar\n"])
        sample_text_no_nl = (b"c", [b"foo\n", b"bar"])
        # check results for the three cases:
        for version, lines in (empty_text, sample_text_nl, sample_text_no_nl):
            # the first two elements are the same for all versioned files:
            # - the digest and the size of the text. For some versioned files
            #   additional data is returned in additional tuple elements.
            result = vf.add_lines(version, [], lines)
            self.assertEqual(3, len(result))
            self.assertEqual(
                (osutils.sha_strings(lines), sum(map(len, lines))), result[0:2]
            )
        # parents should not affect the result:
        lines = sample_text_nl[1]
        self.assertEqual(
            (osutils.sha_strings(lines), sum(map(len, lines))),
            vf.add_lines(b"d", [b"b", b"c"], lines)[0:2],
        )

    def test_get_reserved(self):
        vf = self.get_file()
        self.assertRaises(errors.ReservedId, vf.get_texts, [b"b:"])
        self.assertRaises(errors.ReservedId, vf.get_lines, b"b:")
        self.assertRaises(errors.ReservedId, vf.get_text, b"b:")

    def test_add_unchanged_last_line_noeol_snapshot(self):
        """Add a text with an unchanged last line with no eol should work."""
        # Test adding this in a number of chain lengths; because the interface
        # for VersionedFile does not allow forcing a specific chain length, we
        # just use a small base to get the first snapshot, then a much longer
        # first line for the next add (which will make the third add snapshot)
        # and so on. 20 has been chosen as an aribtrary figure - knits use 200
        # as a capped delta length, but ideally we would have some way of
        # tuning the test to the store (e.g. keep going until a snapshot
        # happens).
        for length in range(20):
            version_lines = {}
            vf = self.get_file(f"case-%{length}")
            prefix = b"step-%d"
            parents = []
            for step in range(length):
                version = prefix % step
                lines = ([b"prelude \n"] * step) + [b"line"]
                vf.add_lines(version, parents, lines)
                version_lines[version] = lines
                parents = [version]
            vf.add_lines(b"no-eol", parents, [b"line"])
            vf.get_texts(version_lines.keys())
            self.assertEqualDiff(b"line", vf.get_text(b"no-eol"))

    def test_get_texts_eol_variation(self):
        # similar to the failure in <http://bugs.launchpad.net/234748>
        vf = self.get_file()
        sample_text_nl = [b"line\n"]
        sample_text_no_nl = [b"line"]
        versions = []
        version_lines = {}
        parents = []
        for i in range(4):
            version = b"v%d" % i
            if i % 2:
                lines = sample_text_nl
            else:
                lines = sample_text_no_nl
            # left_matching blocks is an internal api; it operates on the
            # *internal* representation for a knit, which is with *all* lines
            # being normalised to end with \n - even the final line in a no_nl
            # file. Using it here ensures that a broken internal implementation
            # (which is what this test tests) will generate a correct line
            # delta (which is to say, an empty delta).
            vf.add_lines(version, parents, lines, left_matching_blocks=[(0, 0, 1)])
            parents = [version]
            versions.append(version)
            version_lines[version] = lines
        vf.check()
        vf.get_texts(versions)
        vf.get_texts(reversed(versions))

    def test_add_lines_with_matching_blocks_noeol_last_line(self):
        """Add a text with an unchanged last line with no eol should work."""
        # Hand verified sha1 of the text we're adding.
        # Create a mpdiff which adds a new line before the trailing line, and
        # reuse the last line unaltered (which can cause annotation reuse).
        # Test adding this in two situations:
        # On top of a new insertion
        vf = self.get_file("fulltext")
        vf.add_lines(b"noeol", [], [b"line"])
        vf.add_lines(
            b"noeol2",
            [b"noeol"],
            [b"newline\n", b"line"],
            left_matching_blocks=[(0, 1, 1)],
        )
        self.assertEqualDiff(b"newline\nline", vf.get_text(b"noeol2"))
        # On top of a delta
        vf = self.get_file("delta")
        vf.add_lines(b"base", [], [b"line"])
        vf.add_lines(b"noeol", [b"base"], [b"prelude\n", b"line"])
        vf.add_lines(
            b"noeol2",
            [b"noeol"],
            [b"newline\n", b"line"],
            left_matching_blocks=[(1, 1, 1)],
        )
        self.assertEqualDiff(b"newline\nline", vf.get_text(b"noeol2"))

    def test_make_mpdiffs(self):
        from breezy import multiparent

        vf = self.get_file("foo")
        self._setup_for_deltas(vf)
        new_vf = self.get_file("bar")
        for version in multiparent.topo_iter(vf):
            mpdiff = vf.make_mpdiffs([version])[0]
            new_vf.add_mpdiffs(
                [
                    (
                        version,
                        vf.get_parent_map([version])[version],
                        vf.get_sha1s([version])[version],
                        mpdiff,
                    )
                ]
            )
            self.assertEqualDiff(vf.get_text(version), new_vf.get_text(version))

    def test_make_mpdiffs_with_ghosts(self):
        vf = self.get_file("foo")
        try:
            vf.add_lines_with_ghosts(b"text", [b"ghost"], [b"line\n"])
        except NotImplementedError:
            # old Weave formats do not allow ghosts
            return
        self.assertRaises(errors.RevisionNotPresent, vf.make_mpdiffs, [b"ghost"])

    def _setup_for_deltas(self, f):
        self.assertFalse(f.has_version("base"))
        # add texts that should trip the knit maximum delta chain threshold
        # as well as doing parallel chains of data in knits.
        # this is done by two chains of 25 insertions
        f.add_lines(b"base", [], [b"line\n"])
        f.add_lines(b"noeol", [b"base"], [b"line"])
        # detailed eol tests:
        # shared last line with parent no-eol
        f.add_lines(b"noeolsecond", [b"noeol"], [b"line\n", b"line"])
        # differing last line with parent, both no-eol
        f.add_lines(b"noeolnotshared", [b"noeolsecond"], [b"line\n", b"phone"])
        # add eol following a noneol parent, change content
        f.add_lines(b"eol", [b"noeol"], [b"phone\n"])
        # add eol following a noneol parent, no change content
        f.add_lines(b"eolline", [b"noeol"], [b"line\n"])
        # noeol with no parents:
        f.add_lines(b"noeolbase", [], [b"line"])
        # noeol preceeding its leftmost parent in the output:
        # this is done by making it a merge of two parents with no common
        # anestry: noeolbase and noeol with the
        # later-inserted parent the leftmost.
        f.add_lines(b"eolbeforefirstparent", [b"noeolbase", b"noeol"], [b"line"])
        # two identical eol texts
        f.add_lines(b"noeoldup", [b"noeol"], [b"line"])
        next_parent = b"base"
        text_name = b"chain1-"
        text = [b"line\n"]
        sha1s = {
            0: b"da6d3141cb4a5e6f464bf6e0518042ddc7bfd079",
            1: b"45e21ea146a81ea44a821737acdb4f9791c8abe7",
            2: b"e1f11570edf3e2a070052366c582837a4fe4e9fa",
            3: b"26b4b8626da827088c514b8f9bbe4ebf181edda1",
            4: b"e28a5510be25ba84d31121cff00956f9970ae6f6",
            5: b"d63ec0ce22e11dcf65a931b69255d3ac747a318d",
            6: b"2c2888d288cb5e1d98009d822fedfe6019c6a4ea",
            7: b"95c14da9cafbf828e3e74a6f016d87926ba234ab",
            8: b"779e9a0b28f9f832528d4b21e17e168c67697272",
            9: b"1f8ff4e5c6ff78ac106fcfe6b1e8cb8740ff9a8f",
            10: b"131a2ae712cf51ed62f143e3fbac3d4206c25a05",
            11: b"c5a9d6f520d2515e1ec401a8f8a67e6c3c89f199",
            12: b"31a2286267f24d8bedaa43355f8ad7129509ea85",
            13: b"dc2a7fe80e8ec5cae920973973a8ee28b2da5e0a",
            14: b"2c4b1736566b8ca6051e668de68650686a3922f2",
            15: b"5912e4ecd9b0c07be4d013e7e2bdcf9323276cde",
            16: b"b0d2e18d3559a00580f6b49804c23fea500feab3",
            17: b"8e1d43ad72f7562d7cb8f57ee584e20eb1a69fc7",
            18: b"5cf64a3459ae28efa60239e44b20312d25b253f3",
            19: b"1ebed371807ba5935958ad0884595126e8c4e823",
            20: b"2aa62a8b06fb3b3b892a3292a068ade69d5ee0d3",
            21: b"01edc447978004f6e4e962b417a4ae1955b6fe5d",
            22: b"d8d8dc49c4bf0bab401e0298bb5ad827768618bb",
            23: b"c21f62b1c482862983a8ffb2b0c64b3451876e3f",
            24: b"c0593fe795e00dff6b3c0fe857a074364d5f04fc",
            25: b"dd1a1cf2ba9cc225c3aff729953e6364bf1d1855",
        }
        for depth in range(26):
            new_version = text_name + b"%d" % depth
            text = text + [b"line\n"]
            f.add_lines(new_version, [next_parent], text)
            next_parent = new_version
        next_parent = b"base"
        text_name = b"chain2-"
        text = [b"line\n"]
        for depth in range(26):
            new_version = text_name + b"%d" % depth
            text = text + [b"line\n"]
            f.add_lines(new_version, [next_parent], text)
            next_parent = new_version
        return sha1s

    def test_ancestry(self):
        f = self.get_file()
        self.assertEqual(set(), f.get_ancestry([]))
        f.add_lines(b"r0", [], [b"a\n", b"b\n"])
        f.add_lines(b"r1", [b"r0"], [b"b\n", b"c\n"])
        f.add_lines(b"r2", [b"r0"], [b"b\n", b"c\n"])
        f.add_lines(b"r3", [b"r2"], [b"b\n", b"c\n"])
        f.add_lines(b"rM", [b"r1", b"r2"], [b"b\n", b"c\n"])
        self.assertEqual(set(), f.get_ancestry([]))
        f.get_ancestry([b"rM"])

        self.assertRaises(RevisionNotPresent, f.get_ancestry, [b"rM", b"rX"])

        self.assertEqual(set(f.get_ancestry(b"rM")), set(f.get_ancestry(b"rM")))

    def test_mutate_after_finish(self):
        self._transaction = "before"
        f = self.get_file()
        self._transaction = "after"
        self.assertRaises(errors.OutSideTransaction, f.add_lines, b"", [], [])
        self.assertRaises(
            errors.OutSideTransaction, f.add_lines_with_ghosts, b"", [], []
        )

    def test_copy_to(self):
        f = self.get_file()
        f.add_lines(b"0", [], [b"a\n"])
        t = MemoryTransport()
        f.copy_to("foo", t)
        for suffix in self.get_factory().get_suffixes():
            self.assertTrue(t.has("foo" + suffix))

    def test_get_suffixes(self):
        self.get_file()
        # and should be a list
        self.assertTrue(isinstance(self.get_factory().get_suffixes(), list))

    def test_get_parent_map(self):
        f = self.get_file()
        f.add_lines(b"r0", [], [b"a\n", b"b\n"])
        self.assertEqual({b"r0": ()}, f.get_parent_map([b"r0"]))
        f.add_lines(b"r1", [b"r0"], [b"a\n", b"b\n"])
        self.assertEqual({b"r1": (b"r0",)}, f.get_parent_map([b"r1"]))
        self.assertEqual({b"r0": (), b"r1": (b"r0",)}, f.get_parent_map([b"r0", b"r1"]))
        f.add_lines(b"r2", [], [b"a\n", b"b\n"])
        f.add_lines(b"r3", [], [b"a\n", b"b\n"])
        f.add_lines(b"m", [b"r0", b"r1", b"r2", b"r3"], [b"a\n", b"b\n"])
        self.assertEqual({b"m": (b"r0", b"r1", b"r2", b"r3")}, f.get_parent_map([b"m"]))
        self.assertEqual({}, f.get_parent_map(b"y"))
        self.assertEqual(
            {b"r0": (), b"r1": (b"r0",)}, f.get_parent_map([b"r0", b"y", b"r1"])
        )

    def test_annotate(self):
        f = self.get_file()
        f.add_lines(b"r0", [], [b"a\n", b"b\n"])
        f.add_lines(b"r1", [b"r0"], [b"c\n", b"b\n"])
        origins = f.annotate(b"r1")
        self.assertEqual(origins[0][0], b"r1")
        self.assertEqual(origins[1][0], b"r0")

        self.assertRaises(RevisionNotPresent, f.annotate, b"foo")

    def test_detection(self):
        # Test weaves detect corruption.
        #
        # Weaves contain a checksum of their texts.
        # When a text is extracted, this checksum should be
        # verified.

        w = self.get_file_corrupted_text()

        self.assertEqual(b"hello\n", w.get_text(b"v1"))
        self.assertRaises(WeaveInvalidChecksum, w.get_text, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.get_lines, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.check)

        w = self.get_file_corrupted_checksum()

        self.assertEqual(b"hello\n", w.get_text(b"v1"))
        self.assertRaises(WeaveInvalidChecksum, w.get_text, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.get_lines, b"v2")
        self.assertRaises(WeaveInvalidChecksum, w.check)

    def get_file_corrupted_text(self):
        """Return a versioned file with corrupt text but valid metadata."""
        raise NotImplementedError(self.get_file_corrupted_text)

    def reopen_file(self, name="foo"):
        """Open the versioned file from disk again."""
        raise NotImplementedError(self.reopen_file)

    def test_iter_lines_added_or_present_in_versions(self):
        # test that we get at least an equalset of the lines added by
        # versions in the weave
        # the ordering here is to make a tree so that dumb searches have
        # more changes to muck up.

        class InstrumentedProgress(progress.ProgressTask):
            def __init__(self):
                progress.ProgressTask.__init__(self)
                self.updates = []

            def update(self, msg=None, current=None, total=None):
                self.updates.append((msg, current, total))

        vf = self.get_file()
        # add a base to get included
        vf.add_lines(b"base", [], [b"base\n"])
        # add a ancestor to be included on one side
        vf.add_lines(b"lancestor", [], [b"lancestor\n"])
        # add a ancestor to be included on the other side
        vf.add_lines(b"rancestor", [b"base"], [b"rancestor\n"])
        # add a child of rancestor with no eofile-nl
        vf.add_lines(b"child", [b"rancestor"], [b"base\n", b"child\n"])
        # add a child of lancestor and base to join the two roots
        vf.add_lines(
            b"otherchild",
            [b"lancestor", b"base"],
            [b"base\n", b"lancestor\n", b"otherchild\n"],
        )

        def iter_with_versions(versions, expected):
            # now we need to see what lines are returned, and how often.
            lines = {}
            progress = InstrumentedProgress()
            # iterate over the lines
            for line in vf.iter_lines_added_or_present_in_versions(
                versions, pb=progress
            ):
                lines.setdefault(line, 0)
                lines[line] += 1
            if progress.updates != []:
                self.assertEqual(expected, progress.updates)
            return lines

        lines = iter_with_versions(
            [b"child", b"otherchild"],
            [
                ("Walking content", 0, 2),
                ("Walking content", 1, 2),
                ("Walking content", 2, 2),
            ],
        )
        # we must see child and otherchild
        self.assertTrue(lines[(b"child\n", b"child")] > 0)
        self.assertTrue(lines[(b"otherchild\n", b"otherchild")] > 0)
        # we dont care if we got more than that.

        # test all lines
        lines = iter_with_versions(
            None,
            [
                ("Walking content", 0, 5),
                ("Walking content", 1, 5),
                ("Walking content", 2, 5),
                ("Walking content", 3, 5),
                ("Walking content", 4, 5),
                ("Walking content", 5, 5),
            ],
        )
        # all lines must be seen at least once
        self.assertTrue(lines[(b"base\n", b"base")] > 0)
        self.assertTrue(lines[(b"lancestor\n", b"lancestor")] > 0)
        self.assertTrue(lines[(b"rancestor\n", b"rancestor")] > 0)
        self.assertTrue(lines[(b"child\n", b"child")] > 0)
        self.assertTrue(lines[(b"otherchild\n", b"otherchild")] > 0)

    def test_add_lines_with_ghosts(self):
        # some versioned file formats allow lines to be added with parent
        # information that is > than that in the format. Formats that do
        # not support this need to raise NotImplementedError on the
        # add_lines_with_ghosts api.
        vf = self.get_file()
        # add a revision with ghost parents
        # The preferred form is utf8, but we should translate when needed
        parent_id_unicode = "b\xbfse"
        parent_id_utf8 = parent_id_unicode.encode("utf8")
        try:
            vf.add_lines_with_ghosts(b"notbxbfse", [parent_id_utf8], [])
        except NotImplementedError:
            # check the other ghost apis are also not implemented
            self.assertRaises(
                NotImplementedError, vf.get_ancestry_with_ghosts, [b"foo"]
            )
            self.assertRaises(NotImplementedError, vf.get_parents_with_ghosts, b"foo")
            return
        vf = self.reopen_file()
        # test key graph related apis: getncestry, _graph, get_parents
        # has_version
        # - these are ghost unaware and must not be reflect ghosts
        self.assertEqual({b"notbxbfse"}, vf.get_ancestry(b"notbxbfse"))
        self.assertFalse(vf.has_version(parent_id_utf8))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual(
            {parent_id_utf8, b"notbxbfse"}, vf.get_ancestry_with_ghosts([b"notbxbfse"])
        )
        self.assertEqual([parent_id_utf8], vf.get_parents_with_ghosts(b"notbxbfse"))
        # if we add something that is a ghost of another, it should correct the
        # results of the prior apis
        vf.add_lines(parent_id_utf8, [], [])
        self.assertEqual(
            {parent_id_utf8, b"notbxbfse"}, vf.get_ancestry([b"notbxbfse"])
        )
        self.assertEqual(
            {b"notbxbfse": (parent_id_utf8,)}, vf.get_parent_map([b"notbxbfse"])
        )
        self.assertTrue(vf.has_version(parent_id_utf8))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual(
            {parent_id_utf8, b"notbxbfse"}, vf.get_ancestry_with_ghosts([b"notbxbfse"])
        )
        self.assertEqual([parent_id_utf8], vf.get_parents_with_ghosts(b"notbxbfse"))

    def test_add_lines_with_ghosts_after_normal_revs(self):
        # some versioned file formats allow lines to be added with parent
        # information that is > than that in the format. Formats that do
        # not support this need to raise NotImplementedError on the
        # add_lines_with_ghosts api.
        vf = self.get_file()
        # probe for ghost support
        try:
            vf.add_lines_with_ghosts(b"base", [], [b"line\n", b"line_b\n"])
        except NotImplementedError:
            return
        vf.add_lines_with_ghosts(
            b"references_ghost",
            [b"base", b"a_ghost"],
            [b"line\n", b"line_b\n", b"line_c\n"],
        )
        origins = vf.annotate(b"references_ghost")
        self.assertEqual((b"base", b"line\n"), origins[0])
        self.assertEqual((b"base", b"line_b\n"), origins[1])
        self.assertEqual((b"references_ghost", b"line_c\n"), origins[2])

    def test_readonly_mode(self):
        t = self.get_transport()
        factory = self.get_factory()
        vf = factory("id", t, 0o777, create=True, access_mode="w")
        vf = factory("id", t, access_mode="r")
        self.assertRaises(errors.ReadOnlyError, vf.add_lines, b"base", [], [])
        self.assertRaises(
            errors.ReadOnlyError, vf.add_lines_with_ghosts, b"base", [], []
        )

    def test_get_sha1s(self):
        # check the sha1 data is available
        vf = self.get_file()
        # a simple file
        vf.add_lines(b"a", [], [b"a\n"])
        # the same file, different metadata
        vf.add_lines(b"b", [b"a"], [b"a\n"])
        # a file differing only in last newline.
        vf.add_lines(b"c", [], [b"a"])
        self.assertEqual(
            {
                b"a": b"3f786850e387550fdab836ed7e6dc881de23001b",
                b"c": b"86f7e437faa5a7fce15d1ddcb9eaeaea377667b8",
                b"b": b"3f786850e387550fdab836ed7e6dc881de23001b",
            },
            vf.get_sha1s([b"a", b"c", b"b"]),
        )


class TestWeave(TestCaseWithMemoryTransport, VersionedFileTestMixIn):
    def get_file(self, name="foo"):
        return WeaveFile(
            name, self.get_transport(), create=True, get_scope=self.get_transaction
        )

    def get_file_corrupted_text(self):
        w = WeaveFile(
            "foo", self.get_transport(), create=True, get_scope=self.get_transaction
        )
        w.add_lines(b"v1", [], [b"hello\n"])
        w.add_lines(b"v2", [b"v1"], [b"hello\n", b"there\n"])

        # We are going to invasively corrupt the text
        # Make sure the internals of weave are the same
        self.assertEqual(
            [(b"{", 0), b"hello\n", (b"}", None), (b"{", 1), b"there\n", (b"}", None)],
            w._weave,
        )

        self.assertEqual(
            [
                b"f572d396fae9206628714fb2ce00f72e94f2258f",
                b"90f265c6e75f1c8f9ab76dcf85528352c5f215ef",
            ],
            w._sha1s,
        )
        w.check()

        # Corrupted
        w._weave[4] = b"There\n"
        return w

    def get_file_corrupted_checksum(self):
        w = self.get_file_corrupted_text()
        # Corrected
        w._weave[4] = b"there\n"
        self.assertEqual(b"hello\nthere\n", w.get_text(b"v2"))

        # Invalid checksum, first digit changed
        w._sha1s[1] = b"f0f265c6e75f1c8f9ab76dcf85528352c5f215ef"
        return w

    def reopen_file(self, name="foo", create=False):
        return WeaveFile(
            name, self.get_transport(), create=create, get_scope=self.get_transaction
        )

    def test_no_implicit_create(self):
        self.assertRaises(
            transport.NoSuchFile,
            WeaveFile,
            "foo",
            self.get_transport(),
            get_scope=self.get_transaction,
        )

    def get_factory(self):
        return WeaveFile


class TestPlanMergeVersionedFile(TestCaseWithMemoryTransport):
    def setUp(self):
        super().setUp()
        mapper = PrefixMapper()
        factory = make_file_factory(True, mapper)
        self.vf1 = factory(self.get_transport("root-1"))
        self.vf2 = factory(self.get_transport("root-2"))
        self.plan_merge_vf = versionedfile._PlanMergeVersionedFile("root")
        self.plan_merge_vf.fallback_versionedfiles.extend([self.vf1, self.vf2])

    def test_add_lines(self):
        self.plan_merge_vf.add_lines((b"root", b"a:"), [], [])
        self.assertRaises(
            ValueError, self.plan_merge_vf.add_lines, (b"root", b"a"), [], []
        )
        self.assertRaises(
            ValueError, self.plan_merge_vf.add_lines, (b"root", b"a:"), None, []
        )
        self.assertRaises(
            ValueError, self.plan_merge_vf.add_lines, (b"root", b"a:"), [], None
        )

    def setup_abcde(self):
        self.vf1.add_lines((b"root", b"A"), [], [b"a"])
        self.vf1.add_lines((b"root", b"B"), [(b"root", b"A")], [b"b"])
        self.vf2.add_lines((b"root", b"C"), [], [b"c"])
        self.vf2.add_lines((b"root", b"D"), [(b"root", b"C")], [b"d"])
        self.plan_merge_vf.add_lines(
            (b"root", b"E:"), [(b"root", b"B"), (b"root", b"D")], [b"e"]
        )

    def test_get_parents(self):
        self.setup_abcde()
        self.assertEqual(
            {(b"root", b"B"): ((b"root", b"A"),)},
            self.plan_merge_vf.get_parent_map([(b"root", b"B")]),
        )
        self.assertEqual(
            {(b"root", b"D"): ((b"root", b"C"),)},
            self.plan_merge_vf.get_parent_map([(b"root", b"D")]),
        )
        self.assertEqual(
            {(b"root", b"E:"): ((b"root", b"B"), (b"root", b"D"))},
            self.plan_merge_vf.get_parent_map([(b"root", b"E:")]),
        )
        self.assertEqual({}, self.plan_merge_vf.get_parent_map([(b"root", b"F")]))
        self.assertEqual(
            {
                (b"root", b"B"): ((b"root", b"A"),),
                (b"root", b"D"): ((b"root", b"C"),),
                (b"root", b"E:"): ((b"root", b"B"), (b"root", b"D")),
            },
            self.plan_merge_vf.get_parent_map(
                [(b"root", b"B"), (b"root", b"D"), (b"root", b"E:"), (b"root", b"F")]
            ),
        )

    def test_get_record_stream(self):
        self.setup_abcde()

        def get_record(suffix):
            return next(
                self.plan_merge_vf.get_record_stream(
                    [(b"root", suffix)], "unordered", True
                )
            )

        self.assertEqual(b"a", get_record(b"A").get_bytes_as("fulltext"))
        self.assertEqual(b"a", b"".join(get_record(b"A").iter_bytes_as("chunked")))
        self.assertEqual(b"c", get_record(b"C").get_bytes_as("fulltext"))
        self.assertEqual(b"e", get_record(b"E:").get_bytes_as("fulltext"))
        self.assertEqual("absent", get_record("F").storage_kind)


class TestReadonlyHttpMixin:
    def get_transaction(self):
        return 1

    def test_readonly_http_works(self):
        # we should be able to read from http with a versioned file.
        self.get_file()
        # try an empty file access
        readonly_vf = self.get_factory()(
            "foo", transport.get_transport_from_url(self.get_readonly_url("."))
        )
        self.assertEqual([], readonly_vf.versions())

    def test_readonly_http_works_with_feeling(self):
        # we should be able to read from http with a versioned file.
        vf = self.get_file()
        # now with feeling.
        vf.add_lines(b"1", [], [b"a\n"])
        vf.add_lines(b"2", [b"1"], [b"b\n", b"a\n"])
        readonly_vf = self.get_factory()(
            "foo", transport.get_transport_from_url(self.get_readonly_url("."))
        )
        self.assertEqual([b"1", b"2"], vf.versions())
        self.assertEqual([b"1", b"2"], readonly_vf.versions())
        for version in readonly_vf.versions():
            readonly_vf.get_lines(version)


class TestWeaveHTTP(TestCaseWithWebserver, TestReadonlyHttpMixin):
    def get_file(self):
        return WeaveFile(
            "foo", self.get_transport(), create=True, get_scope=self.get_transaction
        )

    def get_factory(self):
        return WeaveFile


class MergeCasesMixin:
    def doMerge(self, base, a, b, mp):

        def addcrlf(x):
            return x + b"\n"

        w = self.get_file()
        w.add_lines(b"text0", [], list(map(addcrlf, base)))
        w.add_lines(b"text1", [b"text0"], list(map(addcrlf, a)))
        w.add_lines(b"text2", [b"text0"], list(map(addcrlf, b)))

        self.log_contents(w)

        self.log("merge plan:")
        p = list(w.plan_merge(b"text1", b"text2"))
        for state, line in p:
            if line:
                self.log("%12s | %s" % (state, line[:-1]))

        self.log("merge:")
        mt = BytesIO()
        mt.writelines(w.weave_merge(p))
        mt.seek(0)
        self.log(mt.getvalue())

        mp = list(map(addcrlf, mp))
        self.assertEqual(mt.readlines(), mp)

    def testOneInsert(self):
        self.doMerge([], [b"aa"], [], [b"aa"])

    def testSeparateInserts(self):
        self.doMerge(
            [b"aaa", b"bbb", b"ccc"],
            [b"aaa", b"xxx", b"bbb", b"ccc"],
            [b"aaa", b"bbb", b"yyy", b"ccc"],
            [b"aaa", b"xxx", b"bbb", b"yyy", b"ccc"],
        )

    def testSameInsert(self):
        self.doMerge(
            [b"aaa", b"bbb", b"ccc"],
            [b"aaa", b"xxx", b"bbb", b"ccc"],
            [b"aaa", b"xxx", b"bbb", b"yyy", b"ccc"],
            [b"aaa", b"xxx", b"bbb", b"yyy", b"ccc"],
        )

    overlappedInsertExpected = [b"aaa", b"xxx", b"yyy", b"bbb"]

    def testOverlappedInsert(self):
        self.doMerge(
            [b"aaa", b"bbb"],
            [b"aaa", b"xxx", b"yyy", b"bbb"],
            [b"aaa", b"xxx", b"bbb"],
            self.overlappedInsertExpected,
        )

        # really it ought to reduce this to
        # [b'aaa', b'xxx', b'yyy', b'bbb']

    def testClashReplace(self):
        self.doMerge(
            [b"aaa"],
            [b"xxx"],
            [b"yyy", b"zzz"],
            [b"<<<<<<< ", b"xxx", b"=======", b"yyy", b"zzz", b">>>>>>> "],
        )

    def testNonClashInsert1(self):
        self.doMerge(
            [b"aaa"],
            [b"xxx", b"aaa"],
            [b"yyy", b"zzz"],
            [b"<<<<<<< ", b"xxx", b"aaa", b"=======", b"yyy", b"zzz", b">>>>>>> "],
        )

    def testNonClashInsert2(self):
        self.doMerge([b"aaa"], [b"aaa"], [b"yyy", b"zzz"], [b"yyy", b"zzz"])

    def testDeleteAndModify(self):
        """Clashing delete and modification.

        If one side modifies a region and the other deletes it then
        there should be a conflict with one side blank.
        """
        #######################################
        # skippd, not working yet
        return

        self.doMerge(
            [b"aaa", b"bbb", b"ccc"],
            [b"aaa", b"ddd", b"ccc"],
            [b"aaa", b"ccc"],
            [b"<<<<<<<< ", b"aaa", b"=======", b">>>>>>> ", b"ccc"],
        )

    def _test_merge_from_strings(self, base, a, b, expected):
        w = self.get_file()
        w.add_lines(b"text0", [], base.splitlines(True))
        w.add_lines(b"text1", [b"text0"], a.splitlines(True))
        w.add_lines(b"text2", [b"text0"], b.splitlines(True))
        self.log("merge plan:")
        p = list(w.plan_merge(b"text1", b"text2"))
        for state, line in p:
            if line:
                self.log("%12s | %s" % (state, line[:-1]))
        self.log("merge result:")
        result_text = b"".join(w.weave_merge(p))
        self.log(result_text)
        self.assertEqualDiff(result_text, expected)

    def test_weave_merge_conflicts(self):
        # does weave merge properly handle plans that end with unchanged?
        result = b"".join(self.get_file().weave_merge([("new-a", b"hello\n")]))
        self.assertEqual(result, b"hello\n")

    def test_deletion_extended(self):
        """One side deletes, the other deletes more."""
        base = b"""\
            line 1
            line 2
            line 3
            """
        a = b"""\
            line 1
            line 2
            """
        b = b"""\
            line 1
            """
        result = b"""\
            line 1
<<<<<<<\x20
            line 2
=======
>>>>>>>\x20
            """
        self._test_merge_from_strings(base, a, b, result)

    def test_deletion_overlap(self):
        """Delete overlapping regions with no other conflict.

        Arguably it'd be better to treat these as agreement, rather than
        conflict, but for now conflict is safer.
        """
        base = b"""\
            start context
            int a() {}
            int b() {}
            int c() {}
            end context
            """
        a = b"""\
            start context
            int a() {}
            end context
            """
        b = b"""\
            start context
            int c() {}
            end context
            """
        result = b"""\
            start context
<<<<<<<\x20
            int a() {}
=======
            int c() {}
>>>>>>>\x20
            end context
            """
        self._test_merge_from_strings(base, a, b, result)

    def test_agreement_deletion(self):
        """Agree to delete some lines, without conflicts."""
        base = b"""\
            start context
            base line 1
            base line 2
            end context
            """
        a = b"""\
            start context
            base line 1
            end context
            """
        b = b"""\
            start context
            base line 1
            end context
            """
        result = b"""\
            start context
            base line 1
            end context
            """
        self._test_merge_from_strings(base, a, b, result)

    def test_sync_on_deletion(self):
        """Specific case of merge where we can synchronize incorrectly.

        A previous version of the weave merge concluded that the two versions
        agreed on deleting line 2, and this could be a synchronization point.
        Line 1 was then considered in isolation, and thought to be deleted on
        both sides.

        It's better to consider the whole thing as a disagreement region.
        """
        base = b"""\
            start context
            base line 1
            base line 2
            end context
            """
        a = b"""\
            start context
            base line 1
            a's replacement line 2
            end context
            """
        b = b"""\
            start context
            b replaces
            both lines
            end context
            """
        result = b"""\
            start context
<<<<<<<\x20
            base line 1
            a's replacement line 2
=======
            b replaces
            both lines
>>>>>>>\x20
            end context
            """
        self._test_merge_from_strings(base, a, b, result)


class TestWeaveMerge(TestCaseWithMemoryTransport, MergeCasesMixin):
    def get_file(self, name="foo"):
        return WeaveFile(name, self.get_transport(), create=True)

    def log_contents(self, w):
        self.log("weave is:")
        tmpf = BytesIO()
        write_weave(w, tmpf)
        self.log(tmpf.getvalue())

    overlappedInsertExpected = [
        b"aaa",
        b"<<<<<<< ",
        b"xxx",
        b"yyy",
        b"=======",
        b"xxx",
        b">>>>>>> ",
        b"bbb",
    ]


class TestContentFactoryAdaption(TestCaseWithMemoryTransport):
    def test_select_adaptor(self):
        """Test expected adapters exist."""
        # One scenario for each lookup combination we expect to use.
        # Each is source_kind, requested_kind, adapter class
        scenarios = [
            ("knit-delta-gz", "fulltext", _mod_knit.DeltaPlainToFullText),
            ("knit-delta-gz", "lines", _mod_knit.DeltaPlainToFullText),
            ("knit-delta-gz", "chunked", _mod_knit.DeltaPlainToFullText),
            ("knit-ft-gz", "fulltext", _mod_knit.FTPlainToFullText),
            ("knit-ft-gz", "lines", _mod_knit.FTPlainToFullText),
            ("knit-ft-gz", "chunked", _mod_knit.FTPlainToFullText),
            (
                "knit-annotated-delta-gz",
                "knit-delta-gz",
                _mod_knit.DeltaAnnotatedToUnannotated,
            ),
            ("knit-annotated-delta-gz", "fulltext", _mod_knit.DeltaAnnotatedToFullText),
            ("knit-annotated-ft-gz", "knit-ft-gz", _mod_knit.FTAnnotatedToUnannotated),
            ("knit-annotated-ft-gz", "fulltext", _mod_knit.FTAnnotatedToFullText),
            ("knit-annotated-ft-gz", "lines", _mod_knit.FTAnnotatedToFullText),
            ("knit-annotated-ft-gz", "chunked", _mod_knit.FTAnnotatedToFullText),
        ]
        for source, requested, klass in scenarios:
            adapter_factory = versionedfile.adapter_registry.get((source, requested))
            adapter = adapter_factory(None)
            self.assertIsInstance(adapter, klass)

    def get_knit(self, annotated=True):
        mapper = ConstantMapper("knit")
        transport = self.get_transport()
        return make_file_factory(annotated, mapper)(transport)

    def helpGetBytes(self, f, ft_name, ft_adapter, delta_name, delta_adapter):
        """Grab the interested adapted texts for tests."""
        # origin is a fulltext
        entries = f.get_record_stream([(b"origin",)], "unordered", False)
        base = next(entries)
        ft_data = ft_adapter.get_bytes(base, ft_name)
        # merged is both a delta and multiple parents.
        entries = f.get_record_stream([(b"merged",)], "unordered", False)
        merged = next(entries)
        delta_data = delta_adapter.get_bytes(merged, delta_name)
        return ft_data, delta_data

    def test_deannotation_noeol(self):
        """Test converting annotated knits to unannotated knits."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1, trailing_eol=False)
        ft_data, delta_data = self.helpGetBytes(
            f,
            "knit-ft-gz",
            _mod_knit.FTAnnotatedToUnannotated(None),
            "knit-delta-gz",
            _mod_knit.DeltaAnnotatedToUnannotated(None),
        )
        self.assertEqual(
            b"version origin 1 b284f94827db1fa2970d9e2014f080413b547a7e\n"
            b"origin\n"
            b"end origin\n",
            GzipFile(mode="rb", fileobj=BytesIO(ft_data)).read(),
        )
        self.assertEqual(
            b"version merged 4 32c2e79763b3f90e8ccde37f9710b6629c25a796\n"
            b"1,2,3\nleft\nright\nmerged\nend merged\n",
            GzipFile(mode="rb", fileobj=BytesIO(delta_data)).read(),
        )

    def test_deannotation(self):
        """Test converting annotated knits to unannotated knits."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1)
        ft_data, delta_data = self.helpGetBytes(
            f,
            "knit-ft-gz",
            _mod_knit.FTAnnotatedToUnannotated(None),
            "knit-delta-gz",
            _mod_knit.DeltaAnnotatedToUnannotated(None),
        )
        self.assertEqual(
            b"version origin 1 00e364d235126be43292ab09cb4686cf703ddc17\n"
            b"origin\n"
            b"end origin\n",
            GzipFile(mode="rb", fileobj=BytesIO(ft_data)).read(),
        )
        self.assertEqual(
            b"version merged 3 ed8bce375198ea62444dc71952b22cfc2b09226d\n"
            b"2,2,2\nright\nmerged\nend merged\n",
            GzipFile(mode="rb", fileobj=BytesIO(delta_data)).read(),
        )

    def test_annotated_to_fulltext_no_eol(self):
        """Test adapting annotated knits to full texts (for -> weaves)."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1, trailing_eol=False)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(
            f,
            "fulltext",
            _mod_knit.FTAnnotatedToFullText(None),
            "fulltext",
            _mod_knit.DeltaAnnotatedToFullText(logged_vf),
        )
        self.assertEqual(b"origin", ft_data)
        self.assertEqual(b"base\nleft\nright\nmerged", delta_data)
        self.assertEqual(
            [("get_record_stream", [(b"left",)], "unordered", True)], logged_vf.calls
        )

    def test_annotated_to_fulltext(self):
        """Test adapting annotated knits to full texts (for -> weaves)."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(
            f,
            "fulltext",
            _mod_knit.FTAnnotatedToFullText(None),
            "fulltext",
            _mod_knit.DeltaAnnotatedToFullText(logged_vf),
        )
        self.assertEqual(b"origin\n", ft_data)
        self.assertEqual(b"base\nleft\nright\nmerged\n", delta_data)
        self.assertEqual(
            [("get_record_stream", [(b"left",)], "unordered", True)], logged_vf.calls
        )

    def test_unannotated_to_fulltext(self):
        """Test adapting unannotated knits to full texts.

        This is used for -> weaves, and for -> annotated knits.
        """
        # we need a full text, and a delta
        f = self.get_knit(annotated=False)
        get_diamond_files(f, 1)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(
            f,
            "fulltext",
            _mod_knit.FTPlainToFullText(None),
            "fulltext",
            _mod_knit.DeltaPlainToFullText(logged_vf),
        )
        self.assertEqual(b"origin\n", ft_data)
        self.assertEqual(b"base\nleft\nright\nmerged\n", delta_data)
        self.assertEqual(
            [("get_record_stream", [(b"left",)], "unordered", True)], logged_vf.calls
        )

    def test_unannotated_to_fulltext_no_eol(self):
        """Test adapting unannotated knits to full texts.

        This is used for -> weaves, and for -> annotated knits.
        """
        # we need a full text, and a delta
        f = self.get_knit(annotated=False)
        get_diamond_files(f, 1, trailing_eol=False)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(
            f,
            "fulltext",
            _mod_knit.FTPlainToFullText(None),
            "fulltext",
            _mod_knit.DeltaPlainToFullText(logged_vf),
        )
        self.assertEqual(b"origin", ft_data)
        self.assertEqual(b"base\nleft\nright\nmerged", delta_data)
        self.assertEqual(
            [("get_record_stream", [(b"left",)], "unordered", True)], logged_vf.calls
        )


class TestKeyMapper(TestCaseWithMemoryTransport):
    """Tests for various key mapping logic."""

    def test_identity_mapper(self):
        mapper = versionedfile.ConstantMapper("inventory")
        self.assertEqual("inventory", mapper.map((b"foo@ar",)))
        self.assertEqual("inventory", mapper.map((b"quux",)))

    def test_prefix_mapper(self):
        # format5: plain
        mapper = versionedfile.PrefixMapper()
        self.assertEqual("file-id", mapper.map((b"file-id", b"revision-id")))
        self.assertEqual("new-id", mapper.map((b"new-id", b"revision-id")))
        self.assertEqual((b"file-id",), mapper.unmap("file-id"))
        self.assertEqual((b"new-id",), mapper.unmap("new-id"))

    def test_hash_prefix_mapper(self):
        # format6: hash + plain
        mapper = versionedfile.HashPrefixMapper()
        self.assertEqual("9b/file-id", mapper.map((b"file-id", b"revision-id")))
        self.assertEqual("45/new-id", mapper.map((b"new-id", b"revision-id")))
        self.assertEqual((b"file-id",), mapper.unmap("9b/file-id"))
        self.assertEqual((b"new-id",), mapper.unmap("45/new-id"))

    def test_hash_escaped_mapper(self):
        # knit1: hash + escaped
        mapper = versionedfile.HashEscapedPrefixMapper()
        self.assertEqual("88/%2520", mapper.map((b" ", b"revision-id")))
        self.assertEqual("ed/fil%2545-%2549d", mapper.map((b"filE-Id", b"revision-id")))
        self.assertEqual("88/ne%2557-%2549d", mapper.map((b"neW-Id", b"revision-id")))
        self.assertEqual((b"filE-Id",), mapper.unmap("ed/fil%2545-%2549d"))
        self.assertEqual((b"neW-Id",), mapper.unmap("88/ne%2557-%2549d"))


class TestVersionedFiles(TestCaseWithMemoryTransport):
    """Tests for the multiple-file variant of VersionedFile."""

    # We want to be sure of behaviour for:
    # weaves prefix layout (weave texts)
    # individually named weaves (weave inventories)
    # annotated knits - prefix|hash|hash-escape layout, we test the third only
    #                   as it is the most complex mapper.
    # individually named knits
    # individual no-graph knits in packs (signatures)
    # individual graph knits in packs (inventories)
    # individual graph nocompression knits in packs (revisions)
    # plain text knits in packs (texts)
    len_one_scenarios = [
        (
            "weave-named",
            {
                "cleanup": None,
                "factory": make_versioned_files_factory(
                    WeaveFile, ConstantMapper("inventory")
                ),
                "graph": True,
                "key_length": 1,
                "support_partial_insertion": False,
            },
        ),
        (
            "named-knit",
            {
                "cleanup": None,
                "factory": make_file_factory(False, ConstantMapper("revisions")),
                "graph": True,
                "key_length": 1,
                "support_partial_insertion": False,
            },
        ),
        (
            "named-nograph-nodelta-knit-pack",
            {
                "cleanup": cleanup_pack_knit,
                "factory": make_pack_factory(False, False, 1),
                "graph": False,
                "key_length": 1,
                "support_partial_insertion": False,
            },
        ),
        (
            "named-graph-knit-pack",
            {
                "cleanup": cleanup_pack_knit,
                "factory": make_pack_factory(True, True, 1),
                "graph": True,
                "key_length": 1,
                "support_partial_insertion": True,
            },
        ),
        (
            "named-graph-nodelta-knit-pack",
            {
                "cleanup": cleanup_pack_knit,
                "factory": make_pack_factory(True, False, 1),
                "graph": True,
                "key_length": 1,
                "support_partial_insertion": False,
            },
        ),
        (
            "groupcompress-nograph",
            {
                "cleanup": groupcompress.cleanup_pack_group,
                "factory": groupcompress.make_pack_factory(False, False, 1),
                "graph": False,
                "key_length": 1,
                "support_partial_insertion": False,
            },
        ),
    ]
    len_two_scenarios = [
        (
            "weave-prefix",
            {
                "cleanup": None,
                "factory": make_versioned_files_factory(WeaveFile, PrefixMapper()),
                "graph": True,
                "key_length": 2,
                "support_partial_insertion": False,
            },
        ),
        (
            "annotated-knit-escape",
            {
                "cleanup": None,
                "factory": make_file_factory(True, HashEscapedPrefixMapper()),
                "graph": True,
                "key_length": 2,
                "support_partial_insertion": False,
            },
        ),
        (
            "plain-knit-pack",
            {
                "cleanup": cleanup_pack_knit,
                "factory": make_pack_factory(True, True, 2),
                "graph": True,
                "key_length": 2,
                "support_partial_insertion": True,
            },
        ),
        (
            "groupcompress",
            {
                "cleanup": groupcompress.cleanup_pack_group,
                "factory": groupcompress.make_pack_factory(True, False, 1),
                "graph": True,
                "key_length": 1,
                "support_partial_insertion": False,
            },
        ),
    ]

    scenarios = len_one_scenarios + len_two_scenarios

    def get_versionedfiles(self, relpath="files"):
        transport = self.get_transport(relpath)
        if relpath != ".":
            transport.mkdir(".")
        files = self.factory(transport)
        if self.cleanup is not None:
            self.addCleanup(self.cleanup, files)
        return files

    def get_simple_key(self, suffix):
        """Return a key for the object under test."""
        if self.key_length == 1:
            return (suffix,)
        else:
            return (b"FileA",) + (suffix,)

    def test_add_fallback_implies_without_fallbacks(self):
        f = self.get_versionedfiles("files")
        if getattr(f, "add_fallback_versioned_files", None) is None:
            raise TestNotApplicable(
                "{} doesn't support fallbacks".format(f.__class__.__name__)
            )
        g = self.get_versionedfiles("fallback")
        key_a = self.get_simple_key(b"a")
        g.add_lines(key_a, [], [b"\n"])
        f.add_fallback_versioned_files(g)
        self.assertTrue(key_a in f.get_parent_map([key_a]))
        self.assertFalse(key_a in f.without_fallbacks().get_parent_map([key_a]))

    def test_add_lines(self):
        f = self.get_versionedfiles()
        key0 = self.get_simple_key(b"r0")
        key1 = self.get_simple_key(b"r1")
        self.get_simple_key(b"r2")
        self.get_simple_key(b"foo")
        f.add_lines(key0, [], [b"a\n", b"b\n"])
        if self.graph:
            f.add_lines(key1, [key0], [b"b\n", b"c\n"])
        else:
            f.add_lines(key1, [], [b"b\n", b"c\n"])
        keys = f.keys()
        self.assertTrue(key0 in keys)
        self.assertTrue(key1 in keys)
        records = []
        for record in f.get_record_stream([key0, key1], "unordered", True):
            records.append((record.key, record.get_bytes_as("fulltext")))
        records.sort()
        self.assertEqual([(key0, b"a\nb\n"), (key1, b"b\nc\n")], records)

    def test_add_chunks(self):
        f = self.get_versionedfiles()
        key0 = self.get_simple_key(b"r0")
        key1 = self.get_simple_key(b"r1")
        self.get_simple_key(b"r2")
        self.get_simple_key(b"foo")

        def add_chunks(key, parents, chunks):
            factory = ChunkedContentFactory(
                key, parents, osutils.sha_strings(chunks), chunks
            )
            return f.add_content(factory)

        add_chunks(key0, [], [b"a", b"\nb\n"])
        if self.graph:
            add_chunks(key1, [key0], [b"b", b"\n", b"c\n"])
        else:
            add_chunks(key1, [], [b"b\n", b"c\n"])
        keys = f.keys()
        self.assertIn(key0, keys)
        self.assertIn(key1, keys)
        records = []
        for record in f.get_record_stream([key0, key1], "unordered", True):
            records.append((record.key, record.get_bytes_as("fulltext")))
        records.sort()
        self.assertEqual([(key0, b"a\nb\n"), (key1, b"b\nc\n")], records)

    def test_annotate(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            prefix = ()
        else:
            prefix = (b"FileA",)
        # introduced full text
        origins = files.annotate(prefix + (b"origin",))
        self.assertEqual([(prefix + (b"origin",), b"origin\n")], origins)
        # a delta
        origins = files.annotate(prefix + (b"base",))
        self.assertEqual([(prefix + (b"base",), b"base\n")], origins)
        # a merge
        origins = files.annotate(prefix + (b"merged",))
        if self.graph:
            self.assertEqual(
                [
                    (prefix + (b"base",), b"base\n"),
                    (prefix + (b"left",), b"left\n"),
                    (prefix + (b"right",), b"right\n"),
                    (prefix + (b"merged",), b"merged\n"),
                ],
                origins,
            )
        else:
            # Without a graph everything is new.
            self.assertEqual(
                [
                    (prefix + (b"merged",), b"base\n"),
                    (prefix + (b"merged",), b"left\n"),
                    (prefix + (b"merged",), b"right\n"),
                    (prefix + (b"merged",), b"merged\n"),
                ],
                origins,
            )
        self.assertRaises(RevisionNotPresent, files.annotate, prefix + ("missing-key",))

    def test_check_no_parameters(self):
        self.get_versionedfiles()

    def test_check_progressbar_parameter(self):
        """A progress bar can be supplied because check can be a generator."""
        pb = ui.ui_factory.nested_progress_bar()
        self.addCleanup(pb.finished)
        files = self.get_versionedfiles()
        files.check(progress_bar=pb)

    def test_check_with_keys_becomes_generator(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys = files.keys()
        entries = files.check(keys=keys)
        seen = set()
        # Texts output should be fulltexts.
        self.capture_stream(
            files, entries, seen.add, files.get_parent_map(keys), require_fulltext=True
        )
        # All texts should be output.
        self.assertEqual(set(keys), seen)

    def test_clear_cache(self):
        files = self.get_versionedfiles()
        files.clear_cache()

    def test_construct(self):
        """Each parameterised test can be constructed on a transport."""
        self.get_versionedfiles()

    def get_diamond_files(
        self, files, trailing_eol=True, left_only=False, nokeys=False
    ):
        return get_diamond_files(
            files,
            self.key_length,
            trailing_eol=trailing_eol,
            nograph=not self.graph,
            left_only=left_only,
            nokeys=nokeys,
        )

    def _add_content_nostoresha(self, add_lines):
        """When nostore_sha is supplied using old content raises."""
        vf = self.get_versionedfiles()
        empty_text = (b"a", [])
        sample_text_nl = (b"b", [b"foo\n", b"bar\n"])
        sample_text_no_nl = (b"c", [b"foo\n", b"bar"])
        shas = []
        for version, lines in (empty_text, sample_text_nl, sample_text_no_nl):
            if add_lines:
                sha, _, _ = vf.add_lines(self.get_simple_key(version), [], lines)
            else:
                sha, _, _ = vf.add_lines(self.get_simple_key(version), [], lines)
            shas.append(sha)
        # we now have a copy of all the lines in the vf.
        for sha, (version, lines) in zip(
            shas, (empty_text, sample_text_nl, sample_text_no_nl)
        ):
            new_key = self.get_simple_key(version + b"2")
            self.assertRaises(
                ExistingContent, vf.add_lines, new_key, [], lines, nostore_sha=sha
            )
            self.assertRaises(
                ExistingContent, vf.add_lines, new_key, [], lines, nostore_sha=sha
            )
            # and no new version should have been added.
            record = next(vf.get_record_stream([new_key], "unordered", True))
            self.assertEqual("absent", record.storage_kind)

    def test_add_lines_nostoresha(self):
        self._add_content_nostoresha(add_lines=True)

    def test_add_lines_return(self):
        files = self.get_versionedfiles()
        # save code by using the stock data insertion helper.
        adds = self.get_diamond_files(files)
        results = []
        # We can only validate the first 2 elements returned from add_lines.
        for add in adds:
            self.assertEqual(3, len(add))
            results.append(add[:2])
        if self.key_length == 1:
            self.assertEqual(
                [
                    (b"00e364d235126be43292ab09cb4686cf703ddc17", 7),
                    (b"51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44", 5),
                    (b"a8478686da38e370e32e42e8a0c220e33ee9132f", 10),
                    (b"9ef09dfa9d86780bdec9219a22560c6ece8e0ef1", 11),
                    (b"ed8bce375198ea62444dc71952b22cfc2b09226d", 23),
                ],
                results,
            )
        elif self.key_length == 2:
            self.assertEqual(
                [
                    (b"00e364d235126be43292ab09cb4686cf703ddc17", 7),
                    (b"00e364d235126be43292ab09cb4686cf703ddc17", 7),
                    (b"51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44", 5),
                    (b"51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44", 5),
                    (b"a8478686da38e370e32e42e8a0c220e33ee9132f", 10),
                    (b"a8478686da38e370e32e42e8a0c220e33ee9132f", 10),
                    (b"9ef09dfa9d86780bdec9219a22560c6ece8e0ef1", 11),
                    (b"9ef09dfa9d86780bdec9219a22560c6ece8e0ef1", 11),
                    (b"ed8bce375198ea62444dc71952b22cfc2b09226d", 23),
                    (b"ed8bce375198ea62444dc71952b22cfc2b09226d", 23),
                ],
                results,
            )

    def test_add_lines_no_key_generates_chk_key(self):
        files = self.get_versionedfiles()
        # save code by using the stock data insertion helper.
        adds = self.get_diamond_files(files, nokeys=True)
        results = []
        # We can only validate the first 2 elements returned from add_lines.
        for add in adds:
            self.assertEqual(3, len(add))
            results.append(add[:2])
        if self.key_length == 1:
            self.assertEqual(
                [
                    (b"00e364d235126be43292ab09cb4686cf703ddc17", 7),
                    (b"51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44", 5),
                    (b"a8478686da38e370e32e42e8a0c220e33ee9132f", 10),
                    (b"9ef09dfa9d86780bdec9219a22560c6ece8e0ef1", 11),
                    (b"ed8bce375198ea62444dc71952b22cfc2b09226d", 23),
                ],
                results,
            )
            # Check the added items got CHK keys.
            self.assertEqual(
                {
                    (b"sha1:00e364d235126be43292ab09cb4686cf703ddc17",),
                    (b"sha1:51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44",),
                    (b"sha1:9ef09dfa9d86780bdec9219a22560c6ece8e0ef1",),
                    (b"sha1:a8478686da38e370e32e42e8a0c220e33ee9132f",),
                    (b"sha1:ed8bce375198ea62444dc71952b22cfc2b09226d",),
                },
                files.keys(),
            )
        elif self.key_length == 2:
            self.assertEqual(
                [
                    (b"00e364d235126be43292ab09cb4686cf703ddc17", 7),
                    (b"00e364d235126be43292ab09cb4686cf703ddc17", 7),
                    (b"51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44", 5),
                    (b"51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44", 5),
                    (b"a8478686da38e370e32e42e8a0c220e33ee9132f", 10),
                    (b"a8478686da38e370e32e42e8a0c220e33ee9132f", 10),
                    (b"9ef09dfa9d86780bdec9219a22560c6ece8e0ef1", 11),
                    (b"9ef09dfa9d86780bdec9219a22560c6ece8e0ef1", 11),
                    (b"ed8bce375198ea62444dc71952b22cfc2b09226d", 23),
                    (b"ed8bce375198ea62444dc71952b22cfc2b09226d", 23),
                ],
                results,
            )
            # Check the added items got CHK keys.
            self.assertEqual(
                {
                    (b"FileA", b"sha1:00e364d235126be43292ab09cb4686cf703ddc17"),
                    (b"FileA", b"sha1:51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44"),
                    (b"FileA", b"sha1:9ef09dfa9d86780bdec9219a22560c6ece8e0ef1"),
                    (b"FileA", b"sha1:a8478686da38e370e32e42e8a0c220e33ee9132f"),
                    (b"FileA", b"sha1:ed8bce375198ea62444dc71952b22cfc2b09226d"),
                    (b"FileB", b"sha1:00e364d235126be43292ab09cb4686cf703ddc17"),
                    (b"FileB", b"sha1:51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44"),
                    (b"FileB", b"sha1:9ef09dfa9d86780bdec9219a22560c6ece8e0ef1"),
                    (b"FileB", b"sha1:a8478686da38e370e32e42e8a0c220e33ee9132f"),
                    (b"FileB", b"sha1:ed8bce375198ea62444dc71952b22cfc2b09226d"),
                },
                files.keys(),
            )

    def test_empty_lines(self):
        """Empty files can be stored."""
        f = self.get_versionedfiles()
        key_a = self.get_simple_key(b"a")
        f.add_lines(key_a, [], [])
        self.assertEqual(
            b"",
            next(f.get_record_stream([key_a], "unordered", True)).get_bytes_as(
                "fulltext"
            ),
        )
        key_b = self.get_simple_key(b"b")
        f.add_lines(key_b, self.get_parents([key_a]), [])
        self.assertEqual(
            b"",
            next(f.get_record_stream([key_b], "unordered", True)).get_bytes_as(
                "fulltext"
            ),
        )

    def test_newline_only(self):
        f = self.get_versionedfiles()
        key_a = self.get_simple_key(b"a")
        f.add_lines(key_a, [], [b"\n"])
        self.assertEqual(
            b"\n",
            next(f.get_record_stream([key_a], "unordered", True)).get_bytes_as(
                "fulltext"
            ),
        )
        key_b = self.get_simple_key(b"b")
        f.add_lines(key_b, self.get_parents([key_a]), [b"\n"])
        self.assertEqual(
            b"\n",
            next(f.get_record_stream([key_b], "unordered", True)).get_bytes_as(
                "fulltext"
            ),
        )

    def test_get_known_graph_ancestry(self):
        f = self.get_versionedfiles()
        if not self.graph:
            raise TestNotApplicable("ancestry info only relevant with graph.")
        key_a = self.get_simple_key(b"a")
        key_b = self.get_simple_key(b"b")
        key_c = self.get_simple_key(b"c")
        # A
        # |\
        # | B
        # |/
        # C
        f.add_lines(key_a, [], [b"\n"])
        f.add_lines(key_b, [key_a], [b"\n"])
        f.add_lines(key_c, [key_a, key_b], [b"\n"])
        kg = f.get_known_graph_ancestry([key_c])
        self.assertIsInstance(kg, _mod_graph.KnownGraph)
        self.assertEqual([key_a, key_b, key_c], list(kg.topo_sort()))

    def test_known_graph_with_fallbacks(self):
        f = self.get_versionedfiles("files")
        if not self.graph:
            raise TestNotApplicable("ancestry info only relevant with graph.")
        if getattr(f, "add_fallback_versioned_files", None) is None:
            raise TestNotApplicable(
                "{} doesn't support fallbacks".format(f.__class__.__name__)
            )
        key_a = self.get_simple_key(b"a")
        key_b = self.get_simple_key(b"b")
        key_c = self.get_simple_key(b"c")
        # A     only in fallback
        # |\
        # | B
        # |/
        # C
        g = self.get_versionedfiles("fallback")
        g.add_lines(key_a, [], [b"\n"])
        f.add_fallback_versioned_files(g)
        f.add_lines(key_b, [key_a], [b"\n"])
        f.add_lines(key_c, [key_a, key_b], [b"\n"])
        kg = f.get_known_graph_ancestry([key_c])
        self.assertEqual([key_a, key_b, key_c], list(kg.topo_sort()))

    def test_get_record_stream_empty(self):
        """An empty stream can be requested without error."""
        f = self.get_versionedfiles()
        entries = f.get_record_stream([], "unordered", False)
        self.assertEqual([], list(entries))

    def assertValidStorageKind(self, storage_kind):
        """Assert that storage_kind is a valid storage_kind."""
        self.assertSubset(
            [storage_kind],
            [
                "mpdiff",
                "knit-annotated-ft",
                "knit-annotated-delta",
                "knit-ft",
                "knit-delta",
                "chunked",
                "fulltext",
                "knit-annotated-ft-gz",
                "knit-annotated-delta-gz",
                "knit-ft-gz",
                "knit-delta-gz",
                "knit-delta-closure",
                "knit-delta-closure-ref",
                "groupcompress-block",
                "groupcompress-block-ref",
            ],
        )

    def capture_stream(self, f, entries, on_seen, parents, require_fulltext=False):
        """Capture a stream for testing."""
        for factory in entries:
            on_seen(factory.key)
            self.assertValidStorageKind(factory.storage_kind)
            if factory.sha1 is not None:
                self.assertEqual(f.get_sha1s([factory.key])[factory.key], factory.sha1)
            self.assertEqual(parents[factory.key], factory.parents)
            self.assertIsInstance(factory.get_bytes_as(factory.storage_kind), bytes)
            if require_fulltext:
                factory.get_bytes_as("fulltext")

    def test_get_record_stream_interface(self):
        """Each item in a stream has to provide a regular interface."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, _ = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, "unordered", False)
        seen = set()
        self.capture_stream(files, entries, seen.add, parent_map)
        self.assertEqual(set(keys), seen)

    def get_keys_and_sort_order(self):
        """Get diamond test keys list, and their sort ordering."""
        if self.key_length == 1:
            keys = [(b"merged",), (b"left",), (b"right",), (b"base",)]
            sort_order = {(b"merged",): 2, (b"left",): 1, (b"right",): 1, (b"base",): 0}
        else:
            keys = [
                (b"FileA", b"merged"),
                (b"FileA", b"left"),
                (b"FileA", b"right"),
                (b"FileA", b"base"),
                (b"FileB", b"merged"),
                (b"FileB", b"left"),
                (b"FileB", b"right"),
                (b"FileB", b"base"),
            ]
            sort_order = {
                (b"FileA", b"merged"): 2,
                (b"FileA", b"left"): 1,
                (b"FileA", b"right"): 1,
                (b"FileA", b"base"): 0,
                (b"FileB", b"merged"): 2,
                (b"FileB", b"left"): 1,
                (b"FileB", b"right"): 1,
                (b"FileB", b"base"): 0,
            }
        return keys, sort_order

    def get_keys_and_groupcompress_sort_order(self):
        """Get diamond test keys list, and their groupcompress sort ordering."""
        if self.key_length == 1:
            keys = [(b"merged",), (b"left",), (b"right",), (b"base",)]
            sort_order = {(b"merged",): 0, (b"left",): 1, (b"right",): 1, (b"base",): 2}
        else:
            keys = [
                (b"FileA", b"merged"),
                (b"FileA", b"left"),
                (b"FileA", b"right"),
                (b"FileA", b"base"),
                (b"FileB", b"merged"),
                (b"FileB", b"left"),
                (b"FileB", b"right"),
                (b"FileB", b"base"),
            ]
            sort_order = {
                (b"FileA", b"merged"): 0,
                (b"FileA", b"left"): 1,
                (b"FileA", b"right"): 1,
                (b"FileA", b"base"): 2,
                (b"FileB", b"merged"): 3,
                (b"FileB", b"left"): 4,
                (b"FileB", b"right"): 4,
                (b"FileB", b"base"): 5,
            }
        return keys, sort_order

    def test_get_record_stream_interface_ordered(self):
        """Each item in a stream has to provide a regular interface."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, sort_order = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, "topological", False)
        seen = []
        self.capture_stream(files, entries, seen.append, parent_map)
        self.assertStreamOrder(sort_order, seen, keys)

    def test_get_record_stream_interface_ordered_with_delta_closure(self):
        """Each item must be accessible as a fulltext."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, sort_order = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, "topological", True)
        seen = []
        for factory in entries:
            seen.append(factory.key)
            self.assertValidStorageKind(factory.storage_kind)
            self.assertSubset(
                [factory.sha1], [None, files.get_sha1s([factory.key])[factory.key]]
            )
            self.assertEqual(parent_map[factory.key], factory.parents)
            # self.assertEqual(files.get_text(factory.key),
            ft_bytes = factory.get_bytes_as("fulltext")
            self.assertIsInstance(ft_bytes, bytes)
            chunked_bytes = factory.get_bytes_as("chunked")
            self.assertEqualDiff(ft_bytes, b"".join(chunked_bytes))
            chunked_bytes = factory.iter_bytes_as("chunked")
            self.assertEqualDiff(ft_bytes, b"".join(chunked_bytes))

        self.assertStreamOrder(sort_order, seen, keys)

    def test_get_record_stream_interface_groupcompress(self):
        """Each item in a stream has to provide a regular interface."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, sort_order = self.get_keys_and_groupcompress_sort_order()
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, "groupcompress", False)
        seen = []
        self.capture_stream(files, entries, seen.append, parent_map)
        self.assertStreamOrder(sort_order, seen, keys)

    def assertStreamOrder(self, sort_order, seen, keys):
        self.assertEqual(len(set(seen)), len(keys))
        if self.key_length == 1:
            lows = {(): 0}
        else:
            lows = {(b"FileA",): 0, (b"FileB",): 0}
        if not self.graph:
            self.assertEqual(set(keys), set(seen))
        else:
            for key in seen:
                sort_pos = sort_order[key]
                self.assertTrue(
                    sort_pos >= lows[key[:-1]],
                    "Out of order in sorted stream: {!r}, {!r}".format(key, seen),
                )
                lows[key[:-1]] = sort_pos

    def test_get_record_stream_unknown_storage_kind_raises(self):
        """Asking for a storage kind that the stream cannot supply raises."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            keys = [(b"merged",), (b"left",), (b"right",), (b"base",)]
        else:
            keys = [
                (b"FileA", b"merged"),
                (b"FileA", b"left"),
                (b"FileA", b"right"),
                (b"FileA", b"base"),
                (b"FileB", b"merged"),
                (b"FileB", b"left"),
                (b"FileB", b"right"),
                (b"FileB", b"base"),
            ]
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, "unordered", False)
        # We track the contents because we should be able to try, fail a
        # particular kind and then ask for one that works and continue.
        seen = set()
        for factory in entries:
            seen.add(factory.key)
            self.assertValidStorageKind(factory.storage_kind)
            if factory.sha1 is not None:
                self.assertEqual(
                    files.get_sha1s([factory.key])[factory.key], factory.sha1
                )
            self.assertEqual(parent_map[factory.key], factory.parents)
            # currently no stream emits mpdiff
            self.assertRaises(UnavailableRepresentation, factory.get_bytes_as, "mpdiff")
            self.assertIsInstance(factory.get_bytes_as(factory.storage_kind), bytes)
        self.assertEqual(set(keys), seen)

    def test_get_record_stream_missing_records_are_absent(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            keys = [(b"merged",), (b"left",), (b"right",), (b"absent",), (b"base",)]
        else:
            keys = [
                (b"FileA", b"merged"),
                (b"FileA", b"left"),
                (b"FileA", b"right"),
                (b"FileA", b"absent"),
                (b"FileA", b"base"),
                (b"FileB", b"merged"),
                (b"FileB", b"left"),
                (b"FileB", b"right"),
                (b"FileB", b"absent"),
                (b"FileB", b"base"),
                (b"absent", b"absent"),
            ]
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, "unordered", False)
        self.assertAbsentRecord(files, keys, parent_map, entries)
        entries = files.get_record_stream(keys, "topological", False)
        self.assertAbsentRecord(files, keys, parent_map, entries)

    def assertRecordHasContent(self, record, bytes):
        """Assert that record has the bytes bytes."""
        self.assertEqual(bytes, record.get_bytes_as("fulltext"))
        self.assertEqual(bytes, b"".join(record.get_bytes_as("chunked")))

    def test_get_record_stream_native_formats_are_wire_ready_one_ft(self):
        files = self.get_versionedfiles()
        key = self.get_simple_key(b"foo")
        files.add_lines(key, (), [b"my text\n", b"content"])
        stream = files.get_record_stream([key], "unordered", False)
        record = next(stream)
        if record.storage_kind in ("chunked", "fulltext"):
            # chunked and fulltext representations are for direct use not wire
            # serialisation: check they are able to be used directly. To send
            # such records over the wire translation will be needed.
            self.assertRecordHasContent(record, b"my text\ncontent")
        else:
            bytes = [record.get_bytes_as(record.storage_kind)]
            network_stream = versionedfile.NetworkRecordStream(bytes).read()
            source_record = record
            records = []
            for record in network_stream:
                records.append(record)
                self.assertEqual(source_record.storage_kind, record.storage_kind)
                self.assertEqual(source_record.parents, record.parents)
                self.assertEqual(
                    source_record.get_bytes_as(source_record.storage_kind),
                    record.get_bytes_as(record.storage_kind),
                )
            self.assertEqual(1, len(records))

    def assertStreamMetaEqual(self, records, expected, stream):
        """Assert that streams expected and stream have the same records.

        :param records: A list to collect the seen records.
        :return: A generator of the records in stream.
        """
        # We make assertions during copying to catch things early for easier
        # debugging. This must use the iterating zip() from the future.
        for record, ref_record in zip(stream, expected):
            records.append(record)
            self.assertEqual(ref_record.key, record.key)
            self.assertEqual(ref_record.storage_kind, record.storage_kind)
            self.assertEqual(ref_record.parents, record.parents)
            yield record

    def stream_to_bytes_or_skip_counter(self, skipped_records, full_texts, stream):
        """Convert a stream to a bytes iterator.

        :param skipped_records: A list with one element to increment when a
            record is skipped.
        :param full_texts: A dict from key->fulltext representation, for
            checking chunked or fulltext stored records.
        :param stream: A record_stream.
        :return: An iterator over the bytes of each record.
        """
        for record in stream:
            if record.storage_kind in ("chunked", "fulltext"):
                skipped_records[0] += 1
                # check the content is correct for direct use.
                self.assertRecordHasContent(record, full_texts[record.key])
            else:
                yield record.get_bytes_as(record.storage_kind)

    def test_get_record_stream_native_formats_are_wire_ready_ft_delta(self):
        files = self.get_versionedfiles()
        target_files = self.get_versionedfiles("target")
        key = self.get_simple_key(b"ft")
        key_delta = self.get_simple_key(b"delta")
        files.add_lines(key, (), [b"my text\n", b"content"])
        if self.graph:
            delta_parents = (key,)
        else:
            delta_parents = ()
        files.add_lines(key_delta, delta_parents, [b"different\n", b"content\n"])
        local = files.get_record_stream([key, key_delta], "unordered", False)
        ref = files.get_record_stream([key, key_delta], "unordered", False)
        skipped_records = [0]
        full_texts = {
            key: b"my text\ncontent",
            key_delta: b"different\ncontent\n",
        }
        byte_stream = self.stream_to_bytes_or_skip_counter(
            skipped_records, full_texts, local
        )
        network_stream = versionedfile.NetworkRecordStream(byte_stream).read()
        records = []
        # insert the stream from the network into a versioned files object so we can
        # check the content was carried across correctly without doing delta
        # inspection.
        target_files.insert_record_stream(
            self.assertStreamMetaEqual(records, ref, network_stream)
        )
        # No duplicates on the wire thank you!
        self.assertEqual(2, len(records) + skipped_records[0])
        if len(records):
            # if any content was copied it all must have all been.
            self.assertIdenticalVersionedFile(files, target_files)

    def test_get_record_stream_native_formats_are_wire_ready_delta(self):
        # copy a delta over the wire
        files = self.get_versionedfiles()
        target_files = self.get_versionedfiles("target")
        key = self.get_simple_key(b"ft")
        key_delta = self.get_simple_key(b"delta")
        files.add_lines(key, (), [b"my text\n", b"content"])
        if self.graph:
            delta_parents = (key,)
        else:
            delta_parents = ()
        files.add_lines(key_delta, delta_parents, [b"different\n", b"content\n"])
        # Copy the basis text across so we can reconstruct the delta during
        # insertion into target.
        target_files.insert_record_stream(
            files.get_record_stream([key], "unordered", False)
        )
        local = files.get_record_stream([key_delta], "unordered", False)
        ref = files.get_record_stream([key_delta], "unordered", False)
        skipped_records = [0]
        full_texts = {
            key_delta: b"different\ncontent\n",
        }
        byte_stream = self.stream_to_bytes_or_skip_counter(
            skipped_records, full_texts, local
        )
        network_stream = versionedfile.NetworkRecordStream(byte_stream).read()
        records = []
        # insert the stream from the network into a versioned files object so we can
        # check the content was carried across correctly without doing delta
        # inspection during check_stream.
        target_files.insert_record_stream(
            self.assertStreamMetaEqual(records, ref, network_stream)
        )
        # No duplicates on the wire thank you!
        self.assertEqual(1, len(records) + skipped_records[0])
        if len(records):
            # if any content was copied it all must have all been
            self.assertIdenticalVersionedFile(files, target_files)

    def test_get_record_stream_wire_ready_delta_closure_included(self):
        # copy a delta over the wire with the ability to get its full text.
        files = self.get_versionedfiles()
        key = self.get_simple_key(b"ft")
        key_delta = self.get_simple_key(b"delta")
        files.add_lines(key, (), [b"my text\n", b"content"])
        if self.graph:
            delta_parents = (key,)
        else:
            delta_parents = ()
        files.add_lines(key_delta, delta_parents, [b"different\n", b"content\n"])
        local = files.get_record_stream([key_delta], "unordered", True)
        ref = files.get_record_stream([key_delta], "unordered", True)
        skipped_records = [0]
        full_texts = {
            key_delta: b"different\ncontent\n",
        }
        byte_stream = self.stream_to_bytes_or_skip_counter(
            skipped_records, full_texts, local
        )
        network_stream = versionedfile.NetworkRecordStream(byte_stream).read()
        records = []
        # insert the stream from the network into a versioned files object so we can
        # check the content was carried across correctly without doing delta
        # inspection during check_stream.
        for record in self.assertStreamMetaEqual(records, ref, network_stream):
            # we have to be able to get the full text out:
            self.assertRecordHasContent(record, full_texts[record.key])
        # No duplicates on the wire thank you!
        self.assertEqual(1, len(records) + skipped_records[0])

    def assertAbsentRecord(self, files, keys, parents, entries):
        """Helper for test_get_record_stream_missing_records_are_absent."""
        seen = set()
        for factory in entries:
            seen.add(factory.key)
            if factory.key[-1] == b"absent":
                self.assertEqual("absent", factory.storage_kind)
                self.assertEqual(None, factory.sha1)
                self.assertEqual(None, factory.parents)
            else:
                self.assertValidStorageKind(factory.storage_kind)
                if factory.sha1 is not None:
                    sha1 = files.get_sha1s([factory.key])[factory.key]
                    self.assertEqual(sha1, factory.sha1)
                self.assertEqual(parents[factory.key], factory.parents)
                self.assertIsInstance(factory.get_bytes_as(factory.storage_kind), bytes)
        self.assertEqual(set(keys), seen)

    def test_filter_absent_records(self):
        """Requested missing records can be filter trivially."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, _ = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        # Add an absent record in the middle of the present keys. (We don't ask
        # for just absent keys to ensure that content before and after the
        # absent keys is still delivered).
        present_keys = list(keys)
        if self.key_length == 1:
            keys.insert(2, (b"extra",))
        else:
            keys.insert(2, (b"extra", b"extra"))
        entries = files.get_record_stream(keys, "unordered", False)
        seen = set()
        self.capture_stream(
            files, versionedfile.filter_absent(entries), seen.add, parent_map
        )
        self.assertEqual(set(present_keys), seen)

    def get_mapper(self):
        """Get a mapper suitable for the key length of the test interface."""
        if self.key_length == 1:
            return ConstantMapper("source")
        else:
            return HashEscapedPrefixMapper()

    def get_parents(self, parents):
        """Get parents, taking self.graph into consideration."""
        if self.graph:
            return parents
        else:
            return None

    def test_get_annotator(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        origin_key = self.get_simple_key(b"origin")
        base_key = self.get_simple_key(b"base")
        left_key = self.get_simple_key(b"left")
        right_key = self.get_simple_key(b"right")
        merged_key = self.get_simple_key(b"merged")
        # annotator = files.get_annotator()
        # introduced full text
        origins, lines = files.get_annotator().annotate(origin_key)
        self.assertEqual([(origin_key,)], origins)
        self.assertEqual([b"origin\n"], lines)
        # a delta
        origins, lines = files.get_annotator().annotate(base_key)
        self.assertEqual([(base_key,)], origins)
        # a merge
        origins, lines = files.get_annotator().annotate(merged_key)
        if self.graph:
            self.assertEqual(
                [
                    (base_key,),
                    (left_key,),
                    (right_key,),
                    (merged_key,),
                ],
                origins,
            )
        else:
            # Without a graph everything is new.
            self.assertEqual(
                [
                    (merged_key,),
                    (merged_key,),
                    (merged_key,),
                    (merged_key,),
                ],
                origins,
            )
        self.assertRaises(
            RevisionNotPresent,
            files.get_annotator().annotate,
            self.get_simple_key(b"missing-key"),
        )

    def test_get_parent_map(self):
        files = self.get_versionedfiles()
        if self.key_length == 1:
            parent_details = [
                ((b"r0",), self.get_parents(())),
                ((b"r1",), self.get_parents(((b"r0",),))),
                ((b"r2",), self.get_parents(())),
                ((b"r3",), self.get_parents(())),
                ((b"m",), self.get_parents(((b"r0",), (b"r1",), (b"r2",), (b"r3",)))),
            ]
        else:
            parent_details = [
                ((b"FileA", b"r0"), self.get_parents(())),
                ((b"FileA", b"r1"), self.get_parents(((b"FileA", b"r0"),))),
                ((b"FileA", b"r2"), self.get_parents(())),
                ((b"FileA", b"r3"), self.get_parents(())),
                (
                    (b"FileA", b"m"),
                    self.get_parents(
                        (
                            (b"FileA", b"r0"),
                            (b"FileA", b"r1"),
                            (b"FileA", b"r2"),
                            (b"FileA", b"r3"),
                        )
                    ),
                ),
            ]
        for key, parents in parent_details:
            files.add_lines(key, parents, [])
            # immediately after adding it should be queryable.
            self.assertEqual({key: parents}, files.get_parent_map([key]))
        # We can ask for an empty set
        self.assertEqual({}, files.get_parent_map([]))
        # We can ask for many keys
        all_parents = dict(parent_details)
        self.assertEqual(all_parents, files.get_parent_map(all_parents.keys()))
        # Absent keys are just not included in the result.
        keys = list(all_parents.keys())
        if self.key_length == 1:
            keys.insert(1, (b"missing",))
        else:
            keys.insert(1, (b"missing", b"missing"))
        # Absent keys are just ignored
        self.assertEqual(all_parents, files.get_parent_map(keys))

    def test_get_sha1s(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            keys = [(b"base",), (b"origin",), (b"left",), (b"merged",), (b"right",)]
        else:
            # ask for shas from different prefixes.
            keys = [
                (b"FileA", b"base"),
                (b"FileB", b"origin"),
                (b"FileA", b"left"),
                (b"FileA", b"merged"),
                (b"FileB", b"right"),
            ]
        self.assertEqual(
            {
                keys[0]: b"51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44",
                keys[1]: b"00e364d235126be43292ab09cb4686cf703ddc17",
                keys[2]: b"a8478686da38e370e32e42e8a0c220e33ee9132f",
                keys[3]: b"ed8bce375198ea62444dc71952b22cfc2b09226d",
                keys[4]: b"9ef09dfa9d86780bdec9219a22560c6ece8e0ef1",
            },
            files.get_sha1s(keys),
        )

    def test_insert_record_stream_empty(self):
        """Inserting an empty record stream should work."""
        files = self.get_versionedfiles()
        files.insert_record_stream([])

    def assertIdenticalVersionedFile(self, expected, actual):
        """Assert that left and right have the same contents."""
        self.assertEqual(set(actual.keys()), set(expected.keys()))
        actual_parents = actual.get_parent_map(actual.keys())
        if self.graph:
            self.assertEqual(actual_parents, expected.get_parent_map(expected.keys()))
        else:
            for _key, parents in actual_parents.items():
                self.assertEqual(None, parents)
        for key in actual.keys():
            actual_text = next(
                actual.get_record_stream([key], "unordered", True)
            ).get_bytes_as("fulltext")
            expected_text = next(
                expected.get_record_stream([key], "unordered", True)
            ).get_bytes_as("fulltext")
            self.assertEqual(actual_text, expected_text)

    def test_insert_record_stream_fulltexts(self):
        """Any file should accept a stream of fulltexts."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport("source")
        source_transport.mkdir(".")
        # weaves always output fulltexts.
        source = make_versioned_files_factory(WeaveFile, mapper)(source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), "topological", False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_fulltexts_noeol(self):
        """Any file should accept a stream of fulltexts."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport("source")
        source_transport.mkdir(".")
        # weaves always output fulltexts.
        source = make_versioned_files_factory(WeaveFile, mapper)(source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), "topological", False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_annotated_knits(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport("source")
        source_transport.mkdir(".")
        source = make_file_factory(True, mapper)(source_transport)
        self.get_diamond_files(source)
        stream = source.get_record_stream(source.keys(), "topological", False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_annotated_knits_noeol(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport("source")
        source_transport.mkdir(".")
        source = make_file_factory(True, mapper)(source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), "topological", False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_plain_knits(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport("source")
        source_transport.mkdir(".")
        source = make_file_factory(False, mapper)(source_transport)
        self.get_diamond_files(source)
        stream = source.get_record_stream(source.keys(), "topological", False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_plain_knits_noeol(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport("source")
        source_transport.mkdir(".")
        source = make_file_factory(False, mapper)(source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), "topological", False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_existing_keys(self):
        """Inserting keys already in a file should not error."""
        files = self.get_versionedfiles()
        source = self.get_versionedfiles("source")
        self.get_diamond_files(source)
        # insert some keys into f.
        self.get_diamond_files(files, left_only=True)
        stream = source.get_record_stream(source.keys(), "topological", False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_missing_keys(self):
        """Inserting a stream with absent keys should raise an error."""
        files = self.get_versionedfiles()
        source = self.get_versionedfiles("source")
        stream = source.get_record_stream(
            [(b"missing",) * self.key_length], "topological", False
        )
        self.assertRaises(errors.RevisionNotPresent, files.insert_record_stream, stream)

    def test_insert_record_stream_out_of_order(self):
        """An out of order stream can either error or work."""
        files = self.get_versionedfiles()
        source = self.get_versionedfiles("source")
        self.get_diamond_files(source)
        if self.key_length == 1:
            origin_keys = [(b"origin",)]
            end_keys = [(b"merged",), (b"left",)]
            start_keys = [(b"right",), (b"base",)]
        else:
            origin_keys = [(b"FileA", b"origin"), (b"FileB", b"origin")]
            end_keys = [
                (
                    b"FileA",
                    b"merged",
                ),
                (
                    b"FileA",
                    b"left",
                ),
                (
                    b"FileB",
                    b"merged",
                ),
                (
                    b"FileB",
                    b"left",
                ),
            ]
            start_keys = [
                (
                    b"FileA",
                    b"right",
                ),
                (
                    b"FileA",
                    b"base",
                ),
                (
                    b"FileB",
                    b"right",
                ),
                (
                    b"FileB",
                    b"base",
                ),
            ]
        origin_entries = source.get_record_stream(origin_keys, "unordered", False)
        end_entries = source.get_record_stream(end_keys, "topological", False)
        start_entries = source.get_record_stream(start_keys, "topological", False)
        entries = itertools.chain(origin_entries, end_entries, start_entries)
        try:
            files.insert_record_stream(entries)
        except RevisionNotPresent:
            # Must not have corrupted the file.
            files.check()
        else:
            self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_long_parent_chain_out_of_order(self):
        """An out of order stream can either error or work."""
        if not self.graph:
            raise TestNotApplicable("ancestry info only relevant with graph.")
        # Create a reasonably long chain of records based on each other, where
        # most will be deltas.
        source = self.get_versionedfiles("source")
        parents = ()
        keys = []
        content = [(b"same same %d\n" % n) for n in range(500)]
        letters = b"abcdefghijklmnopqrstuvwxyz"
        for i in range(len(letters)):
            letter = letters[i : i + 1]
            key = (b"key-" + letter,)
            if self.key_length == 2:
                key = (b"prefix",) + key
            content.append(b"content for " + letter + b"\n")
            source.add_lines(key, parents, content)
            keys.append(key)
            parents = (key,)
        # Create a stream of these records, excluding the first record that the
        # rest ultimately depend upon, and insert it into a new vf.
        streams = []
        for key in reversed(keys):
            streams.append(source.get_record_stream([key], "unordered", False))
        deltas = itertools.chain.from_iterable(streams[:-1])
        files = self.get_versionedfiles()
        try:
            files.insert_record_stream(deltas)
        except RevisionNotPresent:
            # Must not have corrupted the file.
            files.check()
        else:
            # Must only report either just the first key as a missing parent,
            # no key as missing (for nodelta scenarios).
            missing = set(files.get_missing_compression_parent_keys())
            missing.discard(keys[0])
            self.assertEqual(set(), missing)

    def get_knit_delta_source(self):
        """Get a source that can produce a stream with knit delta records,
        regardless of this test's scenario.
        """
        mapper = self.get_mapper()
        source_transport = self.get_transport("source")
        source_transport.mkdir(".")
        source = make_file_factory(False, mapper)(source_transport)
        get_diamond_files(
            source, self.key_length, trailing_eol=True, nograph=False, left_only=False
        )
        return source

    def test_insert_record_stream_delta_missing_basis_no_corruption(self):
        """Insertion where a needed basis is not included notifies the caller
        of the missing basis.  In the meantime a record missing its basis is
        not added.
        """
        source = self.get_knit_delta_source()
        keys = [self.get_simple_key(b"origin"), self.get_simple_key(b"merged")]
        entries = source.get_record_stream(keys, "unordered", False)
        files = self.get_versionedfiles()
        if self.support_partial_insertion:
            self.assertEqual([], list(files.get_missing_compression_parent_keys()))
            files.insert_record_stream(entries)
            missing_bases = files.get_missing_compression_parent_keys()
            self.assertEqual({self.get_simple_key(b"left")}, set(missing_bases))
            self.assertEqual(set(keys), set(files.get_parent_map(keys)))
        else:
            self.assertRaises(
                errors.RevisionNotPresent, files.insert_record_stream, entries
            )
            files.check()

    def test_insert_record_stream_delta_missing_basis_can_be_added_later(self):
        """Insertion where a needed basis is not included notifies the caller
        of the missing basis.  That basis can be added in a second
        insert_record_stream call that does not need to repeat records present
        in the previous stream.  The record(s) that required that basis are
        fully inserted once their basis is no longer missing.
        """
        if not self.support_partial_insertion:
            raise TestNotApplicable(
                "versioned file scenario does not support partial insertion"
            )
        source = self.get_knit_delta_source()
        entries = source.get_record_stream(
            [self.get_simple_key(b"origin"), self.get_simple_key(b"merged")],
            "unordered",
            False,
        )
        files = self.get_versionedfiles()
        files.insert_record_stream(entries)
        missing_bases = files.get_missing_compression_parent_keys()
        self.assertEqual({self.get_simple_key(b"left")}, set(missing_bases))
        # 'merged' is inserted (although a commit of a write group involving
        # this versionedfiles would fail).
        merged_key = self.get_simple_key(b"merged")
        self.assertEqual([merged_key], list(files.get_parent_map([merged_key]).keys()))
        # Add the full delta closure of the missing records
        missing_entries = source.get_record_stream(missing_bases, "unordered", True)
        files.insert_record_stream(missing_entries)
        # Now 'merged' is fully inserted (and a commit would succeed).
        self.assertEqual([], list(files.get_missing_compression_parent_keys()))
        self.assertEqual([merged_key], list(files.get_parent_map([merged_key]).keys()))
        files.check()

    def test_iter_lines_added_or_present_in_keys(self):
        # test that we get at least an equalset of the lines added by
        # versions in the store.
        # the ordering here is to make a tree so that dumb searches have
        # more changes to muck up.

        class InstrumentedProgress(progress.ProgressTask):
            def __init__(self):
                progress.ProgressTask.__init__(self)
                self.updates = []

            def update(self, msg=None, current=None, total=None):
                self.updates.append((msg, current, total))

        files = self.get_versionedfiles()
        # add a base to get included
        files.add_lines(self.get_simple_key(b"base"), (), [b"base\n"])
        # add a ancestor to be included on one side
        files.add_lines(self.get_simple_key(b"lancestor"), (), [b"lancestor\n"])
        # add a ancestor to be included on the other side
        files.add_lines(
            self.get_simple_key(b"rancestor"),
            self.get_parents([self.get_simple_key(b"base")]),
            [b"rancestor\n"],
        )
        # add a child of rancestor with no eofile-nl
        files.add_lines(
            self.get_simple_key(b"child"),
            self.get_parents([self.get_simple_key(b"rancestor")]),
            [b"base\n", b"child\n"],
        )
        # add a child of lancestor and base to join the two roots
        files.add_lines(
            self.get_simple_key(b"otherchild"),
            self.get_parents(
                [self.get_simple_key(b"lancestor"), self.get_simple_key(b"base")]
            ),
            [b"base\n", b"lancestor\n", b"otherchild\n"],
        )

        def iter_with_keys(keys, expected):
            # now we need to see what lines are returned, and how often.
            lines = {}
            progress = InstrumentedProgress()
            # iterate over the lines
            for line in files.iter_lines_added_or_present_in_keys(keys, pb=progress):
                lines.setdefault(line, 0)
                lines[line] += 1
            if progress.updates != []:
                self.assertEqual(expected, progress.updates)
            return lines

        lines = iter_with_keys(
            [self.get_simple_key(b"child"), self.get_simple_key(b"otherchild")],
            [
                ("Walking content", 0, 2),
                ("Walking content", 1, 2),
                ("Walking content", 2, 2),
            ],
        )
        # we must see child and otherchild
        self.assertTrue(lines[(b"child\n", self.get_simple_key(b"child"))] > 0)
        self.assertTrue(
            lines[(b"otherchild\n", self.get_simple_key(b"otherchild"))] > 0
        )
        # we dont care if we got more than that.

        # test all lines
        lines = iter_with_keys(
            files.keys(),
            [
                ("Walking content", 0, 5),
                ("Walking content", 1, 5),
                ("Walking content", 2, 5),
                ("Walking content", 3, 5),
                ("Walking content", 4, 5),
                ("Walking content", 5, 5),
            ],
        )
        # all lines must be seen at least once
        self.assertTrue(lines[(b"base\n", self.get_simple_key(b"base"))] > 0)
        self.assertTrue(lines[(b"lancestor\n", self.get_simple_key(b"lancestor"))] > 0)
        self.assertTrue(lines[(b"rancestor\n", self.get_simple_key(b"rancestor"))] > 0)
        self.assertTrue(lines[(b"child\n", self.get_simple_key(b"child"))] > 0)
        self.assertTrue(
            lines[(b"otherchild\n", self.get_simple_key(b"otherchild"))] > 0
        )

    def test_make_mpdiffs(self):
        from breezy import multiparent

        files = self.get_versionedfiles("source")
        # add texts that should trip the knit maximum delta chain threshold
        # as well as doing parallel chains of data in knits.
        # this is done by two chains of 25 insertions
        files.add_lines(self.get_simple_key(b"base"), [], [b"line\n"])
        files.add_lines(
            self.get_simple_key(b"noeol"),
            self.get_parents([self.get_simple_key(b"base")]),
            [b"line"],
        )
        # detailed eol tests:
        # shared last line with parent no-eol
        files.add_lines(
            self.get_simple_key(b"noeolsecond"),
            self.get_parents([self.get_simple_key(b"noeol")]),
            [b"line\n", b"line"],
        )
        # differing last line with parent, both no-eol
        files.add_lines(
            self.get_simple_key(b"noeolnotshared"),
            self.get_parents([self.get_simple_key(b"noeolsecond")]),
            [b"line\n", b"phone"],
        )
        # add eol following a noneol parent, change content
        files.add_lines(
            self.get_simple_key(b"eol"),
            self.get_parents([self.get_simple_key(b"noeol")]),
            [b"phone\n"],
        )
        # add eol following a noneol parent, no change content
        files.add_lines(
            self.get_simple_key(b"eolline"),
            self.get_parents([self.get_simple_key(b"noeol")]),
            [b"line\n"],
        )
        # noeol with no parents:
        files.add_lines(self.get_simple_key(b"noeolbase"), [], [b"line"])
        # noeol preceeding its leftmost parent in the output:
        # this is done by making it a merge of two parents with no common
        # anestry: noeolbase and noeol with the
        # later-inserted parent the leftmost.
        files.add_lines(
            self.get_simple_key(b"eolbeforefirstparent"),
            self.get_parents(
                [self.get_simple_key(b"noeolbase"), self.get_simple_key(b"noeol")]
            ),
            [b"line"],
        )
        # two identical eol texts
        files.add_lines(
            self.get_simple_key(b"noeoldup"),
            self.get_parents([self.get_simple_key(b"noeol")]),
            [b"line"],
        )
        next_parent = self.get_simple_key(b"base")
        text_name = b"chain1-"
        text = [b"line\n"]
        for depth in range(26):
            new_version = self.get_simple_key(text_name + b"%d" % depth)
            text = text + [b"line\n"]
            files.add_lines(new_version, self.get_parents([next_parent]), text)
            next_parent = new_version
        next_parent = self.get_simple_key(b"base")
        text_name = b"chain2-"
        text = [b"line\n"]
        for depth in range(26):
            new_version = self.get_simple_key(text_name + b"%d" % depth)
            text = text + [b"line\n"]
            files.add_lines(new_version, self.get_parents([next_parent]), text)
            next_parent = new_version
        target = self.get_versionedfiles("target")
        for key in multiparent.topo_iter_keys(files, files.keys()):
            mpdiff = files.make_mpdiffs([key])[0]
            parents = files.get_parent_map([key])[key] or []
            target.add_mpdiffs([(key, parents, files.get_sha1s([key])[key], mpdiff)])
            self.assertEqualDiff(
                next(files.get_record_stream([key], "unordered", True)).get_bytes_as(
                    "fulltext"
                ),
                next(target.get_record_stream([key], "unordered", True)).get_bytes_as(
                    "fulltext"
                ),
            )

    def test_keys(self):
        # While use is discouraged, versions() is still needed by aspects of
        # bzr.
        files = self.get_versionedfiles()
        self.assertEqual(set(), set(files.keys()))
        if self.key_length == 1:
            key = (b"foo",)
        else:
            key = (
                b"foo",
                b"bar",
            )
        files.add_lines(key, (), [])
        self.assertEqual({key}, set(files.keys()))


class VirtualVersionedFilesTests(TestCase):
    """Basic tests for the VirtualVersionedFiles implementations."""

    def _get_parent_map(self, keys):
        ret = {}
        for k in keys:
            if k in self._parent_map:
                ret[k] = self._parent_map[k]
        return ret

    def setUp(self):
        super().setUp()
        self._lines = {}
        self._parent_map = {}
        self.texts = VirtualVersionedFiles(self._get_parent_map, self._lines.get)

    def test_add_lines(self):
        self.assertRaises(NotImplementedError, self.texts.add_lines, b"foo", [], [])

    def test_add_mpdiffs(self):
        self.assertRaises(NotImplementedError, self.texts.add_mpdiffs, [])

    def test_check_noerrors(self):
        self.texts.check()

    def test_insert_record_stream(self):
        self.assertRaises(NotImplementedError, self.texts.insert_record_stream, [])

    def test_get_sha1s_nonexistent(self):
        self.assertEqual({}, self.texts.get_sha1s([(b"NONEXISTENT",)]))

    def test_get_sha1s(self):
        self._lines[b"key"] = [b"dataline1", b"dataline2"]
        self.assertEqual(
            {(b"key",): osutils.sha_strings(self._lines[b"key"])},
            self.texts.get_sha1s([(b"key",)]),
        )

    def test_get_parent_map(self):
        self._parent_map = {b"G": (b"A", b"B")}
        self.assertEqual(
            {(b"G",): ((b"A",), (b"B",))}, self.texts.get_parent_map([(b"G",), (b"L",)])
        )

    def test_get_record_stream(self):
        self._lines[b"A"] = [b"FOO", b"BAR"]
        it = self.texts.get_record_stream([(b"A",)], "unordered", True)
        record = next(it)
        self.assertEqual("chunked", record.storage_kind)
        self.assertEqual(b"FOOBAR", record.get_bytes_as("fulltext"))
        self.assertEqual([b"FOO", b"BAR"], record.get_bytes_as("chunked"))

    def test_get_record_stream_absent(self):
        it = self.texts.get_record_stream([(b"A",)], "unordered", True)
        record = next(it)
        self.assertEqual("absent", record.storage_kind)

    def test_iter_lines_added_or_present_in_keys(self):
        self._lines[b"A"] = [b"FOO", b"BAR"]
        self._lines[b"B"] = [b"HEY"]
        self._lines[b"C"] = [b"Alberta"]
        it = self.texts.iter_lines_added_or_present_in_keys([(b"A",), (b"B",)])
        self.assertEqual(
            sorted([(b"FOO", b"A"), (b"BAR", b"A"), (b"HEY", b"B")]), sorted(it)
        )


class TestOrderingVersionedFilesDecorator(TestCaseWithMemoryTransport):
    def get_ordering_vf(self, key_priority):
        builder = self.make_branch_builder("test")
        builder.start_series()
        builder.build_snapshot(
            None, [("add", ("", b"TREE_ROOT", "directory", None))], revision_id=b"A"
        )
        builder.build_snapshot([b"A"], [], revision_id=b"B")
        builder.build_snapshot([b"B"], [], revision_id=b"C")
        builder.build_snapshot([b"C"], [], revision_id=b"D")
        builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        vf = b.repository.inventories
        return versionedfile.OrderingVersionedFilesDecorator(vf, key_priority)

    def test_get_empty(self):
        vf = self.get_ordering_vf({})
        self.assertEqual([], vf.calls)

    def test_get_record_stream_topological(self):
        vf = self.get_ordering_vf({(b"A",): 3, (b"B",): 2, (b"C",): 4, (b"D",): 1})
        request_keys = [(b"B",), (b"C",), (b"D",), (b"A",)]
        keys = [r.key for r in vf.get_record_stream(request_keys, "topological", False)]
        # We should have gotten the keys in topological order
        self.assertEqual([(b"A",), (b"B",), (b"C",), (b"D",)], keys)
        # And recorded that the request was made
        self.assertEqual(
            [("get_record_stream", request_keys, "topological", False)], vf.calls
        )

    def test_get_record_stream_ordered(self):
        vf = self.get_ordering_vf({(b"A",): 3, (b"B",): 2, (b"C",): 4, (b"D",): 1})
        request_keys = [(b"B",), (b"C",), (b"D",), (b"A",)]
        keys = [r.key for r in vf.get_record_stream(request_keys, "unordered", False)]
        # They should be returned based on their priority
        self.assertEqual([(b"D",), (b"B",), (b"A",), (b"C",)], keys)
        # And the request recorded
        self.assertEqual(
            [("get_record_stream", request_keys, "unordered", False)], vf.calls
        )

    def test_get_record_stream_implicit_order(self):
        vf = self.get_ordering_vf({(b"B",): 2, (b"D",): 1})
        request_keys = [(b"B",), (b"C",), (b"D",), (b"A",)]
        keys = [r.key for r in vf.get_record_stream(request_keys, "unordered", False)]
        # A and C are not in the map, so they get sorted to the front. A comes
        # before C alphabetically, so it comes back first
        self.assertEqual([(b"A",), (b"C",), (b"D",), (b"B",)], keys)
        # And the request recorded
        self.assertEqual(
            [("get_record_stream", request_keys, "unordered", False)], vf.calls
        )
