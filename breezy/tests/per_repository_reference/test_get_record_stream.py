# Copyright (C) 2008, 2009 Canonical Ltd
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

"""Tests that get_record_stream() behaves itself properly when stacked."""

from breezy.bzr import knit
from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
)


class TestGetRecordStream(TestCaseWithExternalReferenceRepository):
    def setUp(self):
        super().setUp()
        builder = self.make_branch_builder("all")
        builder.start_series()
        # Graph of revisions:
        #
        #   A
        #   |\
        #   B C
        #   |/|
        #   D E
        #   |\|
        #   F G
        # These can be split up among the different repos as desired
        #

        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"f-id", "file", b"initial content\n")),
            ],
            revision_id=b"A",
        )
        builder.build_snapshot(
            [b"A"],
            [
                ("modify", ("file", b"initial content\nand B content\n")),
            ],
            revision_id=b"B",
        )
        builder.build_snapshot(
            [b"A"],
            [
                ("modify", ("file", b"initial content\nand C content\n")),
            ],
            revision_id=b"C",
        )
        builder.build_snapshot(
            [b"B", b"C"],
            [
                (
                    "modify",
                    (
                        "file",
                        b"initial content\nand B content\nand C content\n",
                    ),
                ),
            ],
            revision_id=b"D",
        )
        builder.build_snapshot(
            [b"C"],
            [
                (
                    "modify",
                    (
                        "file",
                        b"initial content\nand C content\nand E content\n",
                    ),
                ),
            ],
            revision_id=b"E",
        )
        builder.build_snapshot(
            [b"D"],
            [
                (
                    "modify",
                    (
                        "file",
                        b"initial content\n"
                        b"and B content\n"
                        b"and C content\n"
                        b"and F content\n",
                    ),
                ),
            ],
            revision_id=b"F",
        )
        builder.build_snapshot(
            [b"E", b"D"],
            [
                (
                    "modify",
                    (
                        "file",
                        b"initial content\n"
                        b"and B content\n"
                        b"and C content\n"
                        b"and E content\n",
                    ),
                ),
            ],
            revision_id=b"G",
        )
        builder.finish_series()
        self.all_repo = builder.get_branch().repository
        self.all_repo.lock_read()
        self.addCleanup(self.all_repo.unlock)
        self.base_repo = self.make_repository("base")
        self.stacked_repo = self.make_referring("referring", self.base_repo)

    def make_simple_split(self):
        """Set up the repositories so that everything is in base except F"""
        self.base_repo.fetch(self.all_repo, revision_id=b"G")
        self.stacked_repo.fetch(self.all_repo, revision_id=b"F")

    def make_complex_split(self):
        """Intermix the revisions so that base holds left stacked holds right.

        base will hold
            A B D F (and C because it is a parent of D)
        referring will hold
            C E G (only)
        """
        self.base_repo.fetch(self.all_repo, revision_id=b"B")
        self.stacked_repo.fetch(self.all_repo, revision_id=b"C")
        self.base_repo.fetch(self.all_repo, revision_id=b"F")
        self.stacked_repo.fetch(self.all_repo, revision_id=b"G")

    def test_unordered_fetch_simple_split(self):
        self.make_simple_split()
        keys = [(b"f-id", bytes([r])) for r in bytearray(b"ABCDF")]
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(keys, "unordered", False)
        record_keys = set()
        for record in stream:
            if record.storage_kind == "absent":
                raise ValueError("absent record: {}".format(record.key))
            record_keys.add(record.key)
        # everything should be present, we don't care about the order
        self.assertEqual(keys, sorted(record_keys))

    def test_unordered_fetch_complex_split(self):
        self.make_complex_split()
        keys = [(b"f-id", bytes([r])) for r in bytearray(b"ABCDEG")]
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(keys, "unordered", False)
        record_keys = set()
        for record in stream:
            if record.storage_kind == "absent":
                raise ValueError("absent record: {}".format(record.key))
            record_keys.add(record.key)
        # everything should be present, we don't care about the order
        self.assertEqual(keys, sorted(record_keys))

    def test_ordered_no_closure(self):
        self.make_complex_split()
        # Topological ordering allows B & C and D & E to be returned with
        # either one first, so the required ordering is:
        # [A (B C) (D E) G]
        #
        # or, because E can be returned before B:
        #
        # A C E B D G
        keys = [(b"f-id", bytes([r])) for r in bytearray(b"ABCDEG")]
        alt_1 = [(b"f-id", bytes([r])) for r in bytearray(b"ACBDEG")]
        alt_2 = [(b"f-id", bytes([r])) for r in bytearray(b"ABCEDG")]
        alt_3 = [(b"f-id", bytes([r])) for r in bytearray(b"ACBEDG")]
        alt_4 = [(b"f-id", bytes([r])) for r in bytearray(b"ACEBDG")]
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(keys, "topological", False)
        record_keys = []
        for record in stream:
            if record.storage_kind == "absent":
                raise ValueError("absent record: {}".format(record.key))
            record_keys.append(record.key)
        self.assertIn(record_keys, (keys, alt_1, alt_2, alt_3, alt_4))

    def test_ordered_fulltext_simple(self):
        self.make_simple_split()
        # This is a common case in asking to annotate a file that exists on a
        # stacked branch.
        # See https://bugs.launchpad.net/bzr/+bug/393366
        # Topological ordering allows B & C and D & E to be returned with
        # either one first, so the required ordering is:
        # [A (B C) D F]
        keys = [(b"f-id", bytes([r])) for r in bytearray(b"ABCDF")]
        alt_1 = [(b"f-id", bytes([r])) for r in bytearray(b"ACBDF")]
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(keys, "topological", True)
        record_keys = []
        for record in stream:
            if record.storage_kind == "absent":
                raise ValueError("absent record: {}".format(record.key))
            record_keys.append(record.key)
        self.assertIn(record_keys, (keys, alt_1))

    def test_ordered_fulltext_complex(self):
        self.make_complex_split()
        # Topological ordering allows B & C and D & E to be returned with
        # either one first, so the required ordering is:
        # [A (B C) (D E) G]
        #
        # or, because E can be returned before B:
        #
        # A C E B D G
        keys = [(b"f-id", bytes([r])) for r in bytearray(b"ABCDEG")]
        alt_1 = [(b"f-id", bytes([r])) for r in bytearray(b"ACBDEG")]
        alt_2 = [(b"f-id", bytes([r])) for r in bytearray(b"ABCEDG")]
        alt_3 = [(b"f-id", bytes([r])) for r in bytearray(b"ACBEDG")]
        alt_4 = [(b"f-id", bytes([r])) for r in bytearray(b"ACEBDG")]
        self.stacked_repo.lock_read()
        self.addCleanup(self.stacked_repo.unlock)
        stream = self.stacked_repo.texts.get_record_stream(keys, "topological", True)
        record_keys = []
        for record in stream:
            if record.storage_kind == "absent":
                raise ValueError("absent record: {}".format(record.key))
            record_keys.append(record.key)
        # Note that currently --2a format repositories do this correctly, but
        # KnitPack format repositories do not.
        if isinstance(self.stacked_repo.texts, knit.KnitVersionedFiles):
            # See https://bugs.launchpad.net/bzr/+bug/399884
            self.expectFailure(
                "KVF does not weave fulltexts from fallback"
                " repositories to preserve perfect order",
                self.assertTrue,
                record_keys in (keys, alt_1, alt_2, alt_3, alt_4),
            )
        self.assertIn(record_keys, (keys, alt_1, alt_2, alt_3, alt_4))
