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

import posixpath

from dulwich.objects import Blob
from dulwich.refs import SymrefLoop
from dulwich.tests.test_object_store import PackBasedObjectStoreTests
from dulwich.tests.test_refs import RefsContainerTests
from dulwich.tests.utils import make_object

from ...tests import TestCaseWithTransport, TestCaseWithMemoryTransport

from ..transportgit import (
    TransportObjectStore,
    TransportRefsContainer,
    )


class TransportObjectStoreTests(PackBasedObjectStoreTests, TestCaseWithTransport):

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
        self.assertEqual(1, len(self.store.packs))
        packname = list(self.store.packs)[0].name()
        self.assertEqual({'pack-%s' % packname.decode('ascii')},
                         set(self.store._pack_names()))
        self.store.transport.put_bytes_non_atomic('info/packs',
                                                  b'P foo-pack.pack\n')
        self.assertEqual({'pack-%s' % packname.decode('ascii')},
                         set(self.store._pack_names()))

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
        self.get_transport().put_bytes_non_atomic('packed-refs',
                                                  b'# pack-refs with: peeled fully-peeled sorted \n'
                                                  b'2001b954f1ec392f84f7cec2f2f96a76ed6ba4ee refs/heads/master')
        self.assertEqual(
            {b'refs/heads/master': b'2001b954f1ec392f84f7cec2f2f96a76ed6ba4ee'},
            self._refs.get_packed_refs())


class TransportRefsContainerTests(RefsContainerTests, TestCaseWithMemoryTransport):
    def setUp(self):
        super(TransportRefsContainerTests, self).setUp()
        t = self.get_transport()
        t.put_bytes('HEAD', b'ref: refs/heads/master')
        t.mkdir('refs')
        t.mkdir('refs/heads')
        t.mkdir('refs/tags')
        t.put_bytes('refs/heads/40-char-ref-aaaaaaaaaaaaaaaaaa',
                    b'42d06bd4b77fed026b154d16493e5deab78f02ec')
        t.put_bytes('refs/heads/loop', b'')
        t.put_bytes('refs/heads/master', b'42d06bd4b77fed026b154d16493e5deab78f02ec')
        t.put_bytes('refs/heads/packed', b'42d06bd4b77fed026b154d16493e5deab78f02ec')
        t.put_bytes('refs/tags/refs-0.1', b'df6800012397fb85c56e7418dd4eb9405dee075c')
        t.put_bytes('refs/tags/refs-0.2', b'3ec9c43c84ff242e3ef4a9fc5bc111fd780a76a8')

        self._refs = TransportRefsContainer(t)

    def test_get_packed_refs(self):
        self.assertEqual(
            {
                b"refs/heads/packed": b"42d06bd4b77fed026b154d16493e5deab78f02ec",
                b"refs/tags/refs-0.1": b"df6800012397fb85c56e7418dd4eb9405dee075c",
            },
            self._refs.get_packed_refs(),
        )

    def test_get_peeled_not_packed(self):
        # not packed
        self.assertEqual(None, self._refs.get_peeled(b"refs/tags/refs-0.2"))
        self.assertEqual(
            b"3ec9c43c84ff242e3ef4a9fc5bc111fd780a76a8",
            self._refs[b"refs/tags/refs-0.2"],
        )

        # packed, known not peelable
        self.assertEqual(
            self._refs[b"refs/heads/packed"],
            self._refs.get_peeled(b"refs/heads/packed"),
        )

        # packed, peeled
        self.assertEqual(
            b"42d06bd4b77fed026b154d16493e5deab78f02ec",
            self._refs.get_peeled(b"refs/tags/refs-0.1"),
        )

    def test_setitem(self):
        RefsContainerTests.test_setitem(self)
        t = self.get_transport()
        with t.get('refs/some/ref') as f:
            self.assertEqual(b"42d06bd4b77fed026b154d16493e5deab78f02ec", f.read()[:40])

        self.assertRaises(
            OSError,
            self._refs.__setitem__,
            b"refs/some/ref/sub",
            b"42d06bd4b77fed026b154d16493e5deab78f02ec",
        )

    def test_delete_refs_container(self):
        # We shouldn't delete the refs directory
        t = self.get_transport()
        self._refs[b'refs/heads/blah'] = b"42d06bd4b77fed026b154d16493e5deab78f02ec"
        for ref in self._refs.allkeys():
            del self._refs[ref]
        self.assertTrue(t.has('refs'))

    def test_setitem_packed(self):
        self.get_transport().put_bytes("packed-refs", b"""\
# pack-refs with: peeled fully-peeled sorted
42d06bd4b77fed026b154d16493e5deab78f02ec refs/heads/packed
""")

        # It's allowed to set a new ref on a packed ref, the new ref will be
        # placed outside on refs/
        self._refs[b"refs/heads/packed"] = b"3ec9c43c84ff242e3ef4a9fc5bc111fd780a76a8"
        with self.get_transport().get('refs/heads/packed') as f:
            self.assertEqual(b"3ec9c43c84ff242e3ef4a9fc5bc111fd780a76a8", f.read()[:40])

        self.assertRaises(
            OSError,
            self._refs.__setitem__,
            b"refs/heads/packed/sub",
            b"42d06bd4b77fed026b154d16493e5deab78f02ec",
        )

    def test_setitem_symbolic(self):
        ones = b"1" * 40
        self._refs[b"HEAD"] = ones
        self.assertEqual(ones, self._refs[b"HEAD"])

        t = self.get_transport()

        # ensure HEAD was not modified
        with t.get("HEAD") as f:
            v = next(iter(f)).rstrip(b"\n\r")
        self.assertEqual(b"ref: refs/heads/master", v)

        # ensure the symbolic link was written through
        with t.get("refs/heads/master") as f:
            self.assertEqual(ones, f.read()[:40])

    def test_set_if_equals(self):
        RefsContainerTests.test_set_if_equals(self)

        t = self.get_transport()

        # ensure symref was followed
        self.assertEqual(b"9" * 40, self._refs[b"refs/heads/master"])

        # ensure lockfile was deleted
        self.assertFalse(t.has(posixpath.join("refs", "heads", "master.lock")))
        self.assertFalse(t.has("HEAD.lock"))

    def test_add_if_new_packed(self):
        # don't overwrite packed ref
        self.assertFalse(self._refs.add_if_new(b"refs/tags/refs-0.1", b"9" * 40))
        self.assertEqual(
            b"df6800012397fb85c56e7418dd4eb9405dee075c",
            self._refs[b"refs/tags/refs-0.1"],
        )

    def test_add_if_new_symbolic(self):
        # Use an empty repo instead of the default.
        repo_dir = os.path.join(tempfile.mkdtemp(), "test")
        os.makedirs(repo_dir)
        repo = Repo.init(repo_dir)
        self.addCleanup(tear_down_repo, repo)
        refs = repo.refs

        nines = b"9" * 40
        self.assertEqual(b"ref: refs/heads/master", refs.read_ref(b"HEAD"))
        self.assertNotIn(b"refs/heads/master", refs)
        self.assertTrue(refs.add_if_new(b"HEAD", nines))
        self.assertEqual(b"ref: refs/heads/master", refs.read_ref(b"HEAD"))
        self.assertEqual(nines, refs[b"HEAD"])
        self.assertEqual(nines, refs[b"refs/heads/master"])
        self.assertFalse(refs.add_if_new(b"HEAD", b"1" * 40))
        self.assertEqual(nines, refs[b"HEAD"])
        self.assertEqual(nines, refs[b"refs/heads/master"])

    def test_follow(self):
        self.assertEqual(
            (
                [b"HEAD", b"refs/heads/master"],
                b"42d06bd4b77fed026b154d16493e5deab78f02ec",
            ),
            self._refs.follow(b"HEAD"),
        )
        self.assertEqual(
            (
                [b"refs/heads/master"],
                b"42d06bd4b77fed026b154d16493e5deab78f02ec",
            ),
            self._refs.follow(b"refs/heads/master"),
        )
        self.assertRaises(SymrefLoop, self._refs.follow, b"refs/heads/loop")

    def test_set_overwrite_loop(self):
        self.assertRaises(SymrefLoop, self._refs.follow, b"refs/heads/loop")
        self._refs[b'refs/heads/loop'] = (
            b"42d06bd4b77fed026b154d16493e5deab78f02ec")
        self.assertEqual(
            ([b'refs/heads/loop'], b'42d06bd4b77fed026b154d16493e5deab78f02ec'),
            self._refs.follow(b"refs/heads/loop"))

    def test_delitem(self):
        t = self.get_transport()
        RefsContainerTests.test_delitem(self)
        ref_file = posixpath.join("refs", "heads", "master")
        self.assertFalse(t.has(ref_file))
        self.assertNotIn(b"refs/heads/master", self._refs.get_packed_refs())

    def test_delitem_symbolic(self):
        t = self.get_transport()
        self.assertEqual(b"ref: refs/heads/master", self._refs.read_loose_ref(b"HEAD"))
        del self._refs[b"HEAD"]
        self.assertRaises(KeyError, lambda: self._refs[b"HEAD"])
        self.assertEqual(
            b"42d06bd4b77fed026b154d16493e5deab78f02ec",
            self._refs[b"refs/heads/master"],
        )
        self.assertFalse(t.has("HEAD"))

    def test_remove_if_equals_symref(self):
        # HEAD is a symref, so shouldn't equal its dereferenced value
        self.assertFalse(
            self._refs.remove_if_equals(
                b"HEAD", b"42d06bd4b77fed026b154d16493e5deab78f02ec"
            )
        )
        self.assertTrue(
            self._refs.remove_if_equals(
                b"refs/heads/master",
                b"42d06bd4b77fed026b154d16493e5deab78f02ec",
            )
        )
        self.assertRaises(KeyError, lambda: self._refs[b"refs/heads/master"])

        # HEAD is now a broken symref
        self.assertRaises(KeyError, lambda: self._refs[b"HEAD"])
        self.assertEqual(b"ref: refs/heads/master", self._refs.read_loose_ref(b"HEAD"))

        self.assertFalse(t.has("refs/heads/master.lock"))
        self.assertFalse(t.has("HEAD.lock"))

    def test_remove_packed_without_peeled(self):
        t = self.get_transport()
        with t.get('packed-refs') as f:
            refs_data = f.read()
        t.put_bytes('packed-refs', b"\n".join(
                line
                for line in refs_data.split(b"\n")
                if not line or line[0] not in b"#^"
            ))
        self._repo = Repo(self._repo.path)
        refs = self._repo.refs
        self.assertTrue(
            refs.remove_if_equals(
                b"refs/heads/packed",
                b"42d06bd4b77fed026b154d16493e5deab78f02ec",
            )
        )

    def test_remove_if_equals_packed(self):
        # test removing ref that is only packed
        self.assertEqual(
            b"df6800012397fb85c56e7418dd4eb9405dee075c",
            self._refs[b"refs/tags/refs-0.1"],
        )
        self.assertTrue(
            self._refs.remove_if_equals(
                b"refs/tags/refs-0.1",
                b"df6800012397fb85c56e7418dd4eb9405dee075c",
            )
        )
        self.assertRaises(KeyError, lambda: self._refs[b"refs/tags/refs-0.1"])

    def test_remove_parent(self):
        t = self.get_transport()
        self._refs[b"refs/heads/foo/bar"] = b"df6800012397fb85c56e7418dd4eb9405dee075c"
        del self._refs[b"refs/heads/foo/bar"]
        ref_file = posixpath.join("refs", "heads", "foo", "bar")
        self.assertFalse(t.has(ref_file))
        ref_file = posixpath.join("refs", "heads", "foo")
        self.assertFalse(t.has(ref_file))
        ref_file = posixpath.join("refs", "heads")
        self.assertTrue(t.has(ref_file))
        self._refs[b"refs/heads/foo"] = b"df6800012397fb85c56e7418dd4eb9405dee075c"

    def test_read_ref(self):
        self.assertEqual(b"ref: refs/heads/master", self._refs.read_ref(b"HEAD"))
        self.assertEqual(
            b"42d06bd4b77fed026b154d16493e5deab78f02ec",
            self._refs.read_ref(b"refs/heads/packed"),
        )
        self.assertEqual(None, self._refs.read_ref(b"nonexistent"))

    def test_read_loose_ref(self):
        self._refs[b"refs/heads/foo"] = b"df6800012397fb85c56e7418dd4eb9405dee075c"

        self.assertEqual(None, self._refs.read_ref(b"refs/heads/foo/bar"))

    def test_non_ascii(self):
        t = self.get_transport()
        t.put_bytes(u"refs/tags/schön", b"00" * 20)

        expected_refs = dict(_TEST_REFS)
        expected_refs[encoded_ref] = b"00" * 20
        del expected_refs[b"refs/heads/loop"]

        self.assertEqual(expected_refs, self._repo.get_refs())

    def test_cyrillic(self):
        # reported in https://github.com/dulwich/dulwich/issues/608
        name = b"\xcd\xee\xe2\xe0\xff\xe2\xe5\xf2\xea\xe01".decode('utf-8')
        ref = "refs/heads/" + name

        t = self.get_transport()
        t.put_bytes(ref, b"00" * 20)

        expected_refs = set(_TEST_REFS.keys())
        expected_refs.add(encoded_ref)

        self.assertEqual(expected_refs, set(self._repo.refs.allkeys()))
        self.assertEqual(
            {r[len(b"refs/"):] for r in expected_refs if r.startswith(b"refs/")},
            set(self._repo.refs.subkeys(b"refs/")),
        )
        expected_refs.remove(b"refs/heads/loop")
        expected_refs.add(b"HEAD")
        self.assertEqual(expected_refs, set(self._repo.get_refs().keys()))
