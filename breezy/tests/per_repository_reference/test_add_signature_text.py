# Copyright (C) 2008 Canonical Ltd
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

"""Tests for add_signature_text on a repository with external references."""

from breezy import errors
from breezy.repository import WriteGroup
from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestAddSignatureText(TestCaseWithExternalReferenceRepository):

    def test_add_signature_text_goes_to_repo(self):
        # adding a signature only writes to the repository add_signature_text
        # is called on.
        tree = self.make_branch_and_tree('sample')
        revid = tree.commit('one')
        inv = tree.branch.repository.get_inventory(revid)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        base = self.make_repository('base')
        repo = self.make_referring('referring', base)
        with repo.lock_write(), WriteGroup(repo):
            rev = tree.branch.repository.get_revision(revid)
            repo.texts.add_lines((inv.root.file_id, revid), [], [])
            repo.add_revision(revid, rev, inv=inv)
            repo.add_signature_text(revid, b"text")
        repo.get_signature_text(revid)
        self.assertRaises(errors.NoSuchRevision, base.get_signature_text,
                          revid)
