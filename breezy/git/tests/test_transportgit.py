# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for bzr-git's object store."""

import os

from dulwich.objects import Blob
from dulwich.tests.test_object_store import PackBasedObjectStoreTests
from dulwich.tests.utils import make_object

from ...tests import TestCaseWithTransport
from ..transportgit import (
    TransportGitFile,
    TransportObjectStore,
    TransportRefsContainer,
)


class TransportGitFileTests(TestCaseWithTransport):
    def test_local_write_takes_the_lock_file(self):
        transport = self.get_transport()
        f = TransportGitFile(transport, "afile", "wb")
        self.addCleanup(f.abort)
        self.assertTrue(transport.has("afile.lock"))

    def test_write_without_the_lock_file(self):
        transport = self.get_transport()
        f = TransportGitFile(transport, "afile", "wb", lock=False)
        self.addCleanup(f.abort)
        self.assertFalse(transport.has("afile.lock"))

    def test_close_without_the_lock_file(self):
        transport = self.get_transport()
        with TransportGitFile(transport, "afile", "wb", lock=False) as f:
            f.write(b"contents")
        self.assertEqual(b"contents", transport.get_bytes("afile"))

    def test_close_without_the_lock_file_sets_the_mode(self):
        self.addCleanup(os.umask, os.umask(0o022))
        transport = self.get_transport()
        with TransportGitFile(transport, "afile", "wb", mask=0o600, lock=False) as f:
            f.write(b"contents")
        self.assertTransportMode(transport, "afile", 0o600)

    def test_abort_without_the_lock_file(self):
        transport = self.get_transport()
        transport.put_bytes("afile", b"old")
        f = TransportGitFile(transport, "afile", "wb", lock=False)
        f.write(b"new")
        f.abort()
        self.assertEqual(b"old", transport.get_bytes("afile"))


class TransportObjectStoreTests(PackBasedObjectStoreTests, TestCaseWithTransport):  # type: ignore
    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.store = TransportObjectStore.init(self.get_transport())

    def tearDown(self):
        PackBasedObjectStoreTests.tearDown(self)
        TestCaseWithTransport.tearDown(self)

    def test_prefers_pack_listdir(self):
        self.store.add_object(make_object(Blob, data=b"data"))
        self.assertEqual(0, len(self.store.packs))
        self.store.pack_loose_objects()
        self.assertEqual(1, len(self.store.packs), self.store.packs)
        packname = list(self.store.packs)[0].name()
        self.assertEqual(
            {"pack-{}".format(packname.decode("ascii"))}, set(self.store._pack_names())
        )
        self.store.transport.put_bytes_non_atomic("info/packs", b"P foo-pack.pack\n")
        self.assertEqual(
            {"pack-{}".format(packname.decode("ascii"))}, set(self.store._pack_names())
        )

    def test_remembers_packs(self):
        self.store.add_object(make_object(Blob, data=b"data"))
        self.assertEqual(0, len(self.store.packs))
        self.store.pack_loose_objects()
        self.assertEqual(1, len(self.store.packs))

        # Packing a second object creates a second pack.
        self.store.add_object(make_object(Blob, data=b"more data"))
        self.store.pack_loose_objects()
        self.assertEqual(2, len(self.store.packs))

        # If we reopen the store, it reloads both packs.
        restore = TransportObjectStore(self.get_transport())
        self.assertEqual(2, len(restore.packs))


# FIXME: Unfortunately RefsContainerTests requires on a specific set of refs existing.


class TransportRefContainerTests(TestCaseWithTransport):
    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self._refs = TransportRefsContainer(self.get_transport())

    def test_packed_refs_missing(self):
        self.assertEqual({}, self._refs.get_packed_refs())

    def test_packed_refs(self):
        self.get_transport().put_bytes_non_atomic(
            "packed-refs",
            b"# pack-refs with: peeled fully-peeled sorted \n"
            b"2001b954f1ec392f84f7cec2f2f96a76ed6ba4ee refs/heads/master",
        )
        self.assertEqual(
            {b"refs/heads/master": b"2001b954f1ec392f84f7cec2f2f96a76ed6ba4ee"},
            self._refs.get_packed_refs(),
        )
