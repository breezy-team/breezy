# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# vim: encoding=utf-8
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


"""Tests for ref handling."""

from ... import tests

from ..object_store import BazaarObjectStore
from ..refs import (
    BazaarRefsContainer,
    ref_to_branch_name,
    branch_name_to_ref,
    )


class BranchNameRefConversionTests(tests.TestCase):

    def test_head(self):
        self.assertEqual("", ref_to_branch_name(b"HEAD"))
        self.assertEqual(b"HEAD", branch_name_to_ref(""))

    def test_tag(self):
        self.assertRaises(ValueError, ref_to_branch_name, b"refs/tags/FOO")

    def test_branch(self):
        self.assertEqual("frost", ref_to_branch_name(b"refs/heads/frost"))
        self.assertEqual(b"refs/heads/frost", branch_name_to_ref("frost"))


class BazaarRefsContainerTests(tests.TestCaseWithTransport):

    def test_empty(self):
        tree = self.make_branch_and_tree('.')
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(refs.as_dict(), {})

    def test_some_commit(self):
        tree = self.make_branch_and_tree('.')
        revid = tree.commit('somechange')
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(
            refs.as_dict(),
            {b'HEAD': store._lookup_revision_sha1(revid)})

    def test_some_tag(self):
        tree = self.make_branch_and_tree('.')
        revid = tree.commit('somechange')
        tree.branch.tags.set_tag('sometag', revid)
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(
            refs.as_dict(),
            {b'HEAD': store._lookup_revision_sha1(revid),
             b'refs/tags/sometag': store._lookup_revision_sha1(revid),
             })

    def test_some_branch(self):
        tree = self.make_branch_and_tree('.')
        revid = tree.commit('somechange')
        otherbranch = tree.controldir.create_branch(name='otherbranch')
        otherbranch.generate_revision_history(revid)
        store = BazaarObjectStore(tree.branch.repository)
        refs = BazaarRefsContainer(tree.controldir, store)
        self.assertEqual(
            refs.as_dict(),
            {b'HEAD': store._lookup_revision_sha1(revid),
             b'refs/heads/otherbranch': store._lookup_revision_sha1(revid),
             })
