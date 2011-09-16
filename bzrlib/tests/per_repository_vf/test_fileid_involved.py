# Copyright (C) 2005-2010 Canonical Ltd
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

import time

from bzrlib import (
    inventory,
    remote,
    revision as _mod_revision,
    tests,
    )
from bzrlib.tests.scenarios import load_tests_apply_scenarios
from bzrlib.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
    )


load_tests = load_tests_apply_scenarios


class FileIdInvolvedWGhosts(TestCaseWithRepository):

    scenarios = all_repository_vf_format_scenarios()

    def create_branch_with_ghost_text(self):
        builder = self.make_branch_builder('ghost')
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('a', 'a-file-id', 'file', 'some content\n'))])
        b = builder.get_branch()
        old_rt = b.repository.revision_tree('A-id')
        new_inv = inventory.mutable_inventory_from_tree(old_rt)
        new_inv.revision_id = 'B-id'
        new_inv['a-file-id'].revision = 'ghost-id'
        new_rev = _mod_revision.Revision('B-id',
            timestamp=time.time(),
            timezone=0,
            message='Committing against a ghost',
            committer='Joe Foo <joe@foo.com>',
            properties={},
            parent_ids=('A-id', 'ghost-id'),
            )
        b.lock_write()
        self.addCleanup(b.unlock)
        b.repository.start_write_group()
        b.repository.add_revision('B-id', new_rev, new_inv)
        self.disable_commit_write_group_paranoia(b.repository)
        b.repository.commit_write_group()
        return b

    def disable_commit_write_group_paranoia(self, repo):
        if isinstance(repo, remote.RemoteRepository):
            # We can't easily disable the checks in a remote repo.
            repo.abort_write_group()
            raise tests.TestSkipped(
                "repository format does not support storing revisions with "
                "missing texts.")
        pack_coll = getattr(repo, '_pack_collection', None)
        if pack_coll is not None:
            # Monkey-patch the pack collection instance to allow storing
            # incomplete revisions.
            pack_coll._check_new_inventories = lambda: []

    def test_file_ids_include_ghosts(self):
        b = self.create_branch_with_ghost_text()
        repo = b.repository
        self.assertEqual(
            {'a-file-id':set(['ghost-id'])},
            repo.fileids_altered_by_revision_ids(['B-id']))

    def test_file_ids_uses_fallbacks(self):
        builder = self.make_branch_builder('source',
                                           format=self.bzrdir_format)
        repo = builder.get_branch().repository
        if not repo._format.supports_external_lookups:
            raise tests.TestNotApplicable('format does not support stacking')
        builder.start_series()
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'contents\n'))])
        builder.build_snapshot('B-id', ['A-id'], [
            ('modify', ('file-id', 'new-content\n'))])
        builder.build_snapshot('C-id', ['B-id'], [
            ('modify', ('file-id', 'yet more content\n'))])
        builder.finish_series()
        source_b = builder.get_branch()
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        base = self.make_branch('base')
        base.pull(source_b, stop_revision='B-id')
        stacked = self.make_branch('stacked')
        stacked.set_stacked_on_url('../base')
        stacked.pull(source_b, stop_revision='C-id')

        stacked.lock_read()
        self.addCleanup(stacked.unlock)
        repo = stacked.repository
        keys = {'file-id': set(['A-id'])}
        if stacked.repository.supports_rich_root():
            keys['root-id'] = set(['A-id'])
        self.assertEqual(keys, repo.fileids_altered_by_revision_ids(['A-id']))
