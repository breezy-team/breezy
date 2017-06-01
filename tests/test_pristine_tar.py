# Copyright (C) 2012 Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for pristine tar extraction code."""

from base64 import standard_b64encode

from ..pristine_tar import (
    get_pristine_tar_tree,
    revision_pristine_tar_data,
    read_git_pristine_tar_data,
    store_git_pristine_tar_data,
    )

from ....revision import Revision
from ....tests import TestCase

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
        rev = Revision("myrevid")
        self.assertRaises(KeyError,
            revision_pristine_tar_data, rev)

    def test_pristine_tar_delta_gz(self):
        rev = Revision("myrevid")
        rev.properties["deb-pristine-delta"] = standard_b64encode("bla")
        self.assertEquals(("bla", "gz"), revision_pristine_tar_data(rev))


class ReadPristineTarData(TestCase):

    def test_read_pristine_tar_data_no_branch(self):
        r = GitMemoryRepo()
        self.assertRaises(KeyError, read_git_pristine_tar_data,
            r, "foo")

    def test_read_pristine_tar_data_no_file(self):
        r = GitMemoryRepo()
        t = Tree()
        b = Blob.from_string("README")
        r.object_store.add_object(b)
        t.add("README", stat.S_IFREG | 0644, b.id)
        r.object_store.add_object(t)
        r.do_commit("Add README", tree=t.id,
                    ref='refs/heads/pristine-tar')
        self.assertRaises(KeyError, read_git_pristine_tar_data,
            r, "foo")

    def test_read_pristine_tar_data(self):
        r = GitMemoryRepo()
        delta = Blob.from_string("some yummy data")
        r.object_store.add_object(delta)
        idfile = Blob.from_string("someid")
        r.object_store.add_object(idfile)
        t = Tree()
        t.add("foo.delta", stat.S_IFREG | 0644, delta.id)
        t.add("foo.id", stat.S_IFREG | 0644, idfile.id)
        r.object_store.add_object(t)
        r.do_commit("pristine tar delta for foo", tree=t.id,
                    ref='refs/heads/pristine-tar')
        self.assertEquals(
            ("some yummy data", "someid"),
            read_git_pristine_tar_data(r, 'foo'))


class StoreGitPristineTarData(TestCase):

    def test_store_new(self):
        r = GitMemoryRepo()
        cid = store_git_pristine_tar_data(r, "foo", "mydelta", "myid")
        tree = get_pristine_tar_tree(r)
        self.assertEquals(
            (stat.S_IFREG | 0644, "7b02de8ac4162e64f402c43487d8a40a505482e1"),
            tree["README"])
        self.assertEquals(r[cid].tree, tree.id)
        self.assertEquals(r[tree["foo.delta"][1]].data, "mydelta")
        self.assertEquals(r[tree["foo.id"][1]].data, "myid")

        self.assertEquals(("mydelta", "myid"),
            read_git_pristine_tar_data(r, "foo"))
