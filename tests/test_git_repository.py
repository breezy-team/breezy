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

"""Tests for interfacing with a Git Repository"""

import subprocess

from bzrlib import (
    inventory,
    repository,
    revision,
    )

from bzrlib.plugins.git import tests
from bzrlib.plugins.git import (
    git_repository,
    ids,
    model,
    )


class TestGitRepository(tests.TestCaseInTempDir):
    """Feature tests for GitRepository."""

    _test_needs_features = [tests.GitCommandFeature]

    def test_open_existing(self):
        tests.run_git('init')

        repo = repository.Repository.open('.')
        self.assertIsInstance(repo, git_repository.GitRepository)

    def test_has_git_model(self):
        tests.run_git('init')

        repo = repository.Repository.open('.')
        self.assertIsInstance(repo._git, model.GitModel)

    def test_revision_graph(self):
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        commit1_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        builder.set_file('a', 'new a\n', False)
        commit2_handle = builder.commit('Joe Foo <joe@foo.com>', u'new a')
        builder.set_file('b', 'text for b\n', False)
        commit3_handle = builder.commit('Jerry Bar <jerry@foo.com>', u'b',
                                        base=commit1_handle)
        commit4_handle = builder.commit('Jerry Bar <jerry@foo.com>', u'merge',
                                        base=commit3_handle,
                                        merge=[commit2_handle],)

        mapping = builder.finish()
        commit1_id = mapping[commit1_handle]
        commit2_id = mapping[commit2_handle]
        commit3_id = mapping[commit3_handle]
        commit4_id = mapping[commit4_handle]

        revisions = tests.run_git('rev-list', '--topo-order',
                                  commit4_id)
        revisions = revisions.splitlines()
        self.assertEqual([commit4_id, commit2_id, commit3_id, commit1_id],
                         revisions)
        bzr_revisions = [ids.convert_revision_id_git_to_bzr(r) for r in revisions]
        graph = {bzr_revisions[0]:[bzr_revisions[2], bzr_revisions[1]],
                 bzr_revisions[1]:[bzr_revisions[3]],
                 bzr_revisions[2]:[bzr_revisions[3]],
                 bzr_revisions[3]:[],
                }

        repo = repository.Repository.open('.')
        self.assertEqual(graph, repo.get_revision_graph(bzr_revisions[0]))
        self.assertEqual({bzr_revisions[3]:[]},
                         repo.get_revision_graph(bzr_revisions[3]))

    def test_get_revision(self):
        # GitRepository.get_revision gives a Revision object.

        # Create a git repository with a revision.
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        mapping = builder.finish()
        commit_id = mapping[commit_handle]

        # Get the corresponding Revision object.
        revid = ids.convert_revision_id_git_to_bzr(commit_id)
        repo = repository.Repository.open('.')
        rev = repo.get_revision(revid)
        self.assertIsInstance(rev, revision.Revision)

    def test_get_inventory(self):
        # GitRepository.get_inventory gives a GitInventory object with
        # plausible entries for typical cases.

        # Create a git repository with some interesting files in a revision.
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('data', 'text\n', False)
        builder.set_file('executable', 'content', True)
        builder.set_link('link', 'broken')
        builder.set_file('subdir/subfile', 'subdir text\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        mapping = builder.finish()
        commit_id = mapping[commit_handle]

        # Get the corresponding Inventory object.
        revid = ids.convert_revision_id_git_to_bzr(commit_id)
        repo = repository.Repository.open('.')
        inv = repo.get_inventory(revid)
        self.assertIsInstance(inv, inventory.Inventory)
        entries = list(inv.iter_entries())
        printed_inv = '\n'.join(
            repr((path, entry.executable, entry))
            for path, entry in inv.iter_entries())
        self.assertEqualDiff(
            printed_inv,
            "('', False, InventoryDirectory('TREE_ROOT', u'', parent_id=None,"
            " revision=None))\n"
            "(u'data', False, InventoryFile('data', u'data',"
            " parent_id='TREE_ROOT',"
            " sha1='8e27be7d6154a1f68ea9160ef0e18691d20560dc', len=None))\n"
            "(u'executable', True, InventoryFile('executable', u'executable',"
            " parent_id='TREE_ROOT',"
            " sha1='6b584e8ece562ebffc15d38808cd6b98fc3d97ea', len=None))\n"
            "(u'link', False, InventoryLink('link', u'link',"
            " parent_id='TREE_ROOT', revision=None))\n"
            "(u'subdir', False, InventoryDirectory('subdir', u'subdir',"
            " parent_id='TREE_ROOT', revision=None))\n"
            "(u'subdir/subfile', False, InventoryFile('subdir/subfile',"
            " u'subfile', parent_id='subdir',"
            " sha1='0ddb53cbe2dd209f550dd8d7f1287a5ed9b1ee8b', len=None))")

    def test_supports_rich_root(self):
        # GitRepository.supports_rich_root is False, at least for now.
        tests.run_git('init')
        repo = repository.Repository.open('.')
        self.assertEqual(repo.supports_rich_root(), False)


class TestGitRepositoryParseRev(tests.TestCase):
    """Unit tests for GitRepository._parse_rev."""

    def test_base_commit(self):
        # GitRepository._parse_rev works for a simple base commit.
        rev = git_repository.GitRepository._parse_rev([
            "873a8ae0d682b0e63e9795bc53056d32ed3de93f\n",
            "tree aaff74984cccd156a469afa7d9ab10e4777beb24\n",
            "author Jane Bar <jane@bar.com> 1198784533 +0200\n",
            "committer Joe Foo <joe@foo.com> 1198784532 +0100\n",
            "\n",
            "    message\n",
            "\x00"])
        self.assertEqual(
            rev.revision_id, 'git1r-873a8ae0d682b0e63e9795bc53056d32ed3de93f')
        self.assertEqual(rev.parent_ids, [])
        self.assertEqual(rev.committer, 'Joe Foo <joe@foo.com>')
        self.assertEqual(repr(rev.timestamp), '1198784532.0')
        self.assertEqual(repr(rev.timezone), '3600')
        self.assertEqual(rev.message, 'message\n')
        self.assertEqual(
            rev.properties,
            {'git-tree-id': 'aaff74984cccd156a469afa7d9ab10e4777beb24',
             'author': 'Jane Bar <jane@bar.com>',
             'git-author-timestamp': '1198784533',
             'git-author-timezone': '+0200'})

    def test_merge_commit(self):
        # Multi-parent commits (merges) are parsed correctly.
        rev = git_repository.GitRepository._parse_rev([
            "873a8ae0d682b0e63e9795bc53056d32ed3de93f\n",
            "tree aaff74984cccd156a469afa7d9ab10e4777beb24\n",
            "parent 263ed20f0d4898be994404ca418bafe8e89abb8a\n",
            "parent 546563eb8f3e94a557f3bb779b6e5a2bd9658752\n",
            "parent 3116d42db7b5c5e69e58f651721e179791479c23\n",
            "author Jane Bar <jane@bar.com> 1198784533 +0200\n",
            "committer Joe Foo <joe@foo.com> 1198784532 +0100\n",
            "\n",
            "    message\n",
            "\x00"])
        # Git records merges in the same way as bzr. The first parent is the
        # commit base, the following parents are the ordered merged revisions.
        self.assertEqual(
            rev.parent_ids,
            ['git1r-263ed20f0d4898be994404ca418bafe8e89abb8a',
             'git1r-546563eb8f3e94a557f3bb779b6e5a2bd9658752',
             'git1r-3116d42db7b5c5e69e58f651721e179791479c23'])

    def test_redundant_spaces(self):
        # Redundant spaces in author and committer are preserved.
        rev = git_repository.GitRepository._parse_rev([
            "873a8ae0d682b0e63e9795bc53056d32ed3de93f\n",
            "tree aaff74984cccd156a469afa7d9ab10e4777beb24\n",
            "author  Jane  Bar  <jane@bar.com>  1198784533 +0200\n",
            "committer  Joe  Foo  <joe@foo.com>  1198784532 +0100\n",
            "\n",
            "    message\n",
            "\x00"])
        self.assertEqual(rev.committer, ' Joe  Foo  <joe@foo.com> ')
        self.assertEqual(
            rev.properties['author'], ' Jane  Bar  <jane@bar.com> ')

    def test_no_committer(self):
        # If committer is not set, then author is used.
        #
        # Folks in #git say that git fsck would likely accept commits that do
        # not set committer, but that author is a mandatory value.
        rev = git_repository.GitRepository._parse_rev([
            "873a8ae0d682b0e63e9795bc53056d32ed3de93f\n",
            "tree aaff74984cccd156a469afa7d9ab10e4777beb24\n",
            "author Jane Bar <jane@bar.com> 1198784533 +0200\n",
            "\n",
            "    message\n",
            "\x00"])
        self.assertEqual(rev.committer, 'Jane Bar <jane@bar.com>')
        self.assertEqual(repr(rev.timestamp), '1198784533.0')
        self.assertEqual(repr(rev.timezone), '7200')
        self.assertEqual(rev.properties['author'], 'Jane Bar <jane@bar.com>')
        self.assertEqual(rev.properties['git-author-timestamp'], '1198784533')
        self.assertEqual(rev.properties['git-author-timezone'], '+0200')

    def test_parse_tz(self):
        # Simple tests for the _parse_tz helper.
        parse_tz = git_repository.GitRepository._parse_tz
        self.assertEqual(repr(parse_tz('+0000')), '0')
        self.assertEqual(repr(parse_tz('+0001')), '60')
        self.assertEqual(repr(parse_tz('-0001')), '-60')
        self.assertEqual(repr(parse_tz('+0100')), '3600')
        self.assertEqual(repr(parse_tz('-0100')), '-3600')
        self.assertEqual(repr(parse_tz('+9959')), '359940')
        self.assertEqual(repr(parse_tz('-9959')), '-359940')

