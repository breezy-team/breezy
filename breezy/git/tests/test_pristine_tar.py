# Copyright (C) 2012-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for pristine tar extraction code."""

from base64 import standard_b64encode

from ..pristine_tar import (
    get_pristine_tar_tree,
    revision_pristine_tar_data,
    read_git_pristine_tar_data,
    store_git_pristine_tar_data,
    )

from ...revision import Revision
from ...tests import TestCase

from dulwich.objects import (
    Blob,
    Tree,
    )
from dulwich.repo import (
    MemoryRepo as GitMemoryRepo,
    )
import stat


class RevisionPristineTarDataTests(TestCase):

    def test_pristine_tar_delta_unknown(self):
        rev = Revision(b"myrevid")
        self.assertRaises(KeyError,
                          revision_pristine_tar_data, rev)

    def test_pristine_tar_delta_gz(self):
        rev = Revision(b"myrevid")
        rev.properties[u"deb-pristine-delta"] = standard_b64encode(b"bla")
        self.assertEqual((b"bla", "gz"), revision_pristine_tar_data(rev))


class ReadPristineTarData(TestCase):

    def test_read_pristine_tar_data_no_branch(self):
        r = GitMemoryRepo()
        self.assertRaises(KeyError, read_git_pristine_tar_data,
                          r, b"foo")

    def test_read_pristine_tar_data_no_file(self):
        r = GitMemoryRepo()
        t = Tree()
        b = Blob.from_string(b"README")
        r.object_store.add_object(b)
        t.add(b"README", stat.S_IFREG | 0o644, b.id)
        r.object_store.add_object(t)
        r.do_commit(b"Add README", tree=t.id,
                    ref=b'refs/heads/pristine-tar')
        self.assertRaises(KeyError, read_git_pristine_tar_data,
                          r, b"foo")

    def test_read_pristine_tar_data(self):
        r = GitMemoryRepo()
        delta = Blob.from_string(b"some yummy data")
        r.object_store.add_object(delta)
        idfile = Blob.from_string(b"someid")
        r.object_store.add_object(idfile)
        t = Tree()
        t.add(b"foo.delta", stat.S_IFREG | 0o644, delta.id)
        t.add(b"foo.id", stat.S_IFREG | 0o644, idfile.id)
        r.object_store.add_object(t)
        r.do_commit(b"pristine tar delta for foo", tree=t.id,
                    ref=b'refs/heads/pristine-tar')
        self.assertEqual(
            (b"some yummy data", b"someid"),
            read_git_pristine_tar_data(r, b'foo'))


class StoreGitPristineTarData(TestCase):

    def test_store_new(self):
        r = GitMemoryRepo()
        cid = store_git_pristine_tar_data(r, b"foo", b"mydelta", b"myid")
        tree = get_pristine_tar_tree(r)
        self.assertEqual(
            (stat.S_IFREG | 0o644, b"7b02de8ac4162e64f402c43487d8a40a505482e1"),
            tree[b"README"])
        self.assertEqual(r[cid].tree, tree.id)
        self.assertEqual(r[tree[b"foo.delta"][1]].data, b"mydelta")
        self.assertEqual(r[tree[b"foo.id"][1]].data, b"myid")

        self.assertEqual((b"mydelta", b"myid"),
                         read_git_pristine_tar_data(r, b"foo"))
