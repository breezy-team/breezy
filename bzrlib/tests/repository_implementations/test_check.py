from bzrlib import (
    inventory,
    revision as _mod_revision,
    )
from bzrlib.tests.repository_implementations import TestCaseWithRepository

class TestCheckRepository(TestCaseWithRepository):

    def make_broken_repository(self):
        repo = self.make_repository('.')

        # make rev1a
        inv = inventory.Inventory(revision_id='rev1a')
        inv.root.revision = 'rev1a'
        self.add_file(repo, inv, 'file1', 'rev1a', [])
        repo.add_inventory('rev1a', inv, [])
        revision = _mod_revision.Revision('rev1a',
            committer='jrandom@example.com', timestamp=0, inventory_sha1='',
            timezone=0, message='foo', parent_ids=[])
        repo.add_revision('rev1a',revision, inv)

        # make rev1b
        inv = inventory.Inventory(revision_id='rev1b')
        inv.root.revision = 'rev1b'
        self.add_file(repo, inv, 'file1', 'rev1b', [])
        repo.add_inventory('rev1b', inv, [])

        # make rev2
        inv = inventory.Inventory()
        self.add_file(repo, inv, 'file1', 'rev2', ['rev1a', 'rev1b'])
        self.add_file(repo, inv, 'file2', 'rev2', [])
        self.add_revision(repo, 'rev2', inv, ['rev1a'])

        # make ghost revision rev1c
        inv = inventory.Inventory()
        self.add_file(repo, inv, 'file2', 'rev1c', [])

        # make rev3 with reference to ghost rev1c
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

    def check_versionedfile(self, file_id, revision_ids):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave(file_id, repo.get_transaction())
        return repo.check_versionedfile(revision_ids, file_id, vf, {})

    def test_normal_first_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions = {}
        result = repo.check_versionedfile(['rev1a'], 'file1-id', vf,
            inventory_versions)
        self.assertSubset(['rev1a'], inventory_versions.keys())
        self.assertEqual('rev1a', inventory_versions['rev1a']['file1-id'])
        self.assertEqual({}, result)

    def test_not_present_in_revision(self):
        # It is not an error to check a revision that does not contain the file
        result = self.check_versionedfile('file2-id', ['rev1a'])
        self.assertEqual({}, result)

    def test_second_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions = {}
        result = repo.check_versionedfile(['rev2'], 'file1-id', vf,
            inventory_versions)
        self.assertEqual({'rev1b': set(['rev2'])}, result)

    def test_ghost(self):
        result = self.check_versionedfile('file2-id', ['rev3'])
        self.assertEqual({'rev1c': set(['rev3'])}, result)
