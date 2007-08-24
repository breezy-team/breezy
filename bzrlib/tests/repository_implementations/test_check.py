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
        inv = inventory.Inventory(revision_id='rev2')
        inv.root.revision = 'rev2'
        self.add_file(repo, inv, 'file1', 'rev2', ['rev1a', 'rev1b'])
        repo.add_inventory('rev2', inv, ['rev1a'])
        revision = _mod_revision.Revision('rev2',
            committer='jrandom@example.com', timestamp=0, inventory_sha1='',
            timezone=0, message='foo', parent_ids=['rev1a'])
        repo.add_revision('rev2',revision, inv)
        return repo

    def add_file(self, repo, inv, filename, revision, parents):
        file_id = filename + '-id'
        entry = inventory.InventoryFile(file_id, filename, 'TREE_ROOT')
        entry.revision = revision 
        inv.add(entry)
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, ['line\n'])

    def test_normal_first_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions = {}
        result = repo.check_versionedfile(['rev1a'], 'file1-id', vf,
            inventory_versions)
        self.assertSubset(['rev1a'], inventory_versions.keys())
        self.assertEqual('rev1a', inventory_versions['rev1a']['file1-id'])
        self.assertEqual({}, result)

    def test_second_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions = {}
        result = repo.check_versionedfile(['rev2'], 'file1-id', vf,
            inventory_versions)
        self.assertEqual({('file1-id', 'rev2'): set(['rev1b'])}, result)
