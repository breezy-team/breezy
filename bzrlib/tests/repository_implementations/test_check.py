# Copyright (C) 2007 Canonical Ltd
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


"""Test operations that check the repository for corruption"""


from bzrlib import (
    inventory,
    revision as _mod_revision,
    )
from bzrlib.tests.repository_implementations import TestCaseWithRepository


class TestFindBadAncestors(TestCaseWithRepository):

    def make_broken_repository(self):
        repo = self.make_repository('.')

        # make rev1a: A well-formed revision, containing 'file1'
        inv = inventory.Inventory(revision_id='rev1a')
        inv.root.revision = 'rev1a'
        self.add_file(repo, inv, 'file1', 'rev1a', [])
        repo.add_inventory('rev1a', inv, [])
        revision = _mod_revision.Revision('rev1a',
            committer='jrandom@example.com', timestamp=0, inventory_sha1='',
            timezone=0, message='foo', parent_ids=[])
        repo.add_revision('rev1a',revision, inv)

        # make rev1b, which has no Revision, but has an Inventory, and file1
        inv = inventory.Inventory(revision_id='rev1b')
        inv.root.revision = 'rev1b'
        self.add_file(repo, inv, 'file1', 'rev1b', [])
        repo.add_inventory('rev1b', inv, [])

        # make rev2, with file1 and file2
        # file2 is sane
        # file1 has 'rev1b' as an ancestor, even though this is not
        # mentioned by 'rev1a', making it an unreferenced ancestor
        inv = inventory.Inventory()
        self.add_file(repo, inv, 'file1', 'rev2', ['rev1a', 'rev1b'])
        self.add_file(repo, inv, 'file2', 'rev2', [])
        self.add_revision(repo, 'rev2', inv, ['rev1a'])

        # make ghost revision rev1c
        inv = inventory.Inventory()
        self.add_file(repo, inv, 'file2', 'rev1c', [])

        # make rev3 with file2
        # file2 refers to 'rev1c', which is a ghost in this repository, so
        # file2 cannot have rev1c as its ancestor.
        inv = inventory.Inventory()
        self.add_file(repo, inv, 'file2', 'rev3', ['rev1c'])
        self.add_revision(repo, 'rev3', inv, ['rev1c'])
        return repo

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = _mod_revision.Revision(revision_id,
            committer='jrandom@example.com', timestamp=0, inventory_sha1='',
            timezone=0, message='foo', parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def add_file(self, repo, inv, filename, revision, parents):
        file_id = filename + '-id'
        entry = inventory.InventoryFile(file_id, filename, 'TREE_ROOT')
        entry.revision = revision
        inv.add(entry)
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, ['line\n'])

    def find_bad_ancestors(self, file_id, revision_ids):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave(file_id, repo.get_transaction())
        return repo.find_bad_ancestors(revision_ids, file_id, vf, {})

    def test_normal_first_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions = {}
        result = repo.find_bad_ancestors(['rev1a'], 'file1-id', vf,
            inventory_versions)
        self.assertSubset(['rev1a'], inventory_versions.keys())
        self.assertEqual('rev1a', inventory_versions['rev1a']['file1-id'])
        self.assertEqual({}, result)

    def test_not_present_in_revision(self):
        # It is not an error to check a revision that does not contain the file
        result = self.find_bad_ancestors('file2-id', ['rev1a'])
        self.assertEqual({}, result)

    def test_second_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions = {}
        result = repo.find_bad_ancestors(['rev2'], 'file1-id', vf,
            inventory_versions)
        self.assertEqual({'rev1b': set(['rev2'])}, result)

    def test_ghost(self):
        result = self.find_bad_ancestors('file2-id', ['rev3'])
        self.assertEqual({'rev1c': set(['rev3'])}, result)
