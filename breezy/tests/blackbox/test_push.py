# Copyright (C) 2006-2012, 2016 Canonical Ltd
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


"""Black-box tests for brz push."""

import re

from breezy import (
    branch,
    controldir,
    directory_service,
    errors,
    osutils,
    tests,
    transport,
    uncommit,
    urlutils,
    workingtree
    )
from breezy.bzr import (
    bzrdir,
    )
from breezy.bzr import knitrepo
from breezy.tests import (
    http_server,
    scenarios,
    script,
    test_foreign,
    )
from breezy.transport import memory


load_tests = scenarios.load_tests_apply_scenarios


class TestPush(tests.TestCaseWithTransport):

    def test_push_error_on_vfs_http(self):
        """ pushing a branch to a HTTP server fails cleanly. """
        # the trunk is published on a web server
        self.transport_readonly_server = http_server.HttpServer
        self.make_branch('source')
        public_url = self.get_readonly_url('target')
        self.run_bzr_error(['http does not support mkdir'],
                           ['push', public_url],
                           working_dir='source')

    def test_push_suggests_parent_alias(self):
        """Push suggests using :parent if there is a known parent branch."""
        tree_a = self.make_branch_and_tree('a')
        tree_a.commit('this is a commit')
        tree_b = self.make_branch_and_tree('b')

        # If there is no parent location set, :parent isn't mentioned.
        out = self.run_bzr('push', working_dir='a', retcode=3)
        self.assertEqual(out,
                         ('', 'brz: ERROR: No push location known or specified.\n'))

        # If there is a parent location set, the error suggests :parent.
        tree_a.branch.set_parent(tree_b.branch.base)
        out = self.run_bzr('push', working_dir='a', retcode=3)
        self.assertEqual(out,
                         ('', 'brz: ERROR: No push location known or specified. '
                          'To push to the parent branch '
                          '(at %s), use \'brz push :parent\'.\n' %
                          urlutils.unescape_for_display(tree_b.branch.base, 'utf-8')))

    def test_push_remember(self):
        """Push changes from one branch to another and test push location."""
        transport = self.get_transport()
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        tree_b = branch_a.controldir.sprout('branch_b').open_workingtree()
        branch_b = tree_b.branch
        tree_c = branch_a.controldir.sprout('branch_c').open_workingtree()
        branch_c = tree_c.branch
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        self.build_tree(['branch_b/c'])
        tree_b.add('c')
        tree_b.commit('commit c')
        # initial push location must be empty
        self.assertEqual(None, branch_b.get_push_location())

        # test push for failure without push location set
        out = self.run_bzr('push', working_dir='branch_a', retcode=3)
        self.assertEqual(out,
                         ('', 'brz: ERROR: No push location known or specified.\n'))

        # test not remembered if cannot actually push
        self.run_bzr('push path/which/doesnt/exist',
                     working_dir='branch_a', retcode=3)
        out = self.run_bzr('push', working_dir='branch_a', retcode=3)
        self.assertEqual(
            ('', 'brz: ERROR: No push location known or specified.\n'),
            out)

        # test implicit --remember when no push location set, push fails
        out = self.run_bzr('push ../branch_b',
                           working_dir='branch_a', retcode=3)
        self.assertEqual(out,
                         ('', 'brz: ERROR: These branches have diverged.  '
                          'See "brz help diverged-branches" for more information.\n'))
        # Refresh the branch as 'push' modified it
        branch_a = branch_a.controldir.open_branch()
        self.assertEqual(osutils.abspath(branch_a.get_push_location()),
                         osutils.abspath(branch_b.controldir.root_transport.base))

        # test implicit --remember after resolving previous failure
        uncommit.uncommit(branch=branch_b, tree=tree_b)
        transport.delete('branch_b/c')
        out, err = self.run_bzr('push', working_dir='branch_a')
        # Refresh the branch as 'push' modified it
        branch_a = branch_a.controldir.open_branch()
        path = branch_a.get_push_location()
        self.assertEqual(err,
                         'Using saved push location: %s\n'
                         'All changes applied successfully.\n'
                         'Pushed up to revision 2.\n'
                         % urlutils.local_path_from_url(path))
        self.assertEqual(path,
                         branch_b.controldir.root_transport.base)
        # test explicit --remember
        self.run_bzr('push ../branch_c --remember', working_dir='branch_a')
        # Refresh the branch as 'push' modified it
        branch_a = branch_a.controldir.open_branch()
        self.assertEqual(branch_a.get_push_location(),
                         branch_c.controldir.root_transport.base)

    def test_push_without_tree(self):
        # brz push from a branch that does not have a checkout should work.
        b = self.make_branch('.')
        out, err = self.run_bzr('push pushed-location')
        self.assertEqual('', out)
        self.assertEqual('Created new branch.\n', err)
        b2 = branch.Branch.open('pushed-location')
        self.assertEndsWith(b2.base, 'pushed-location/')

    def test_push_no_tree(self):
        # brz push --no-tree of a branch with working trees
        b = self.make_branch_and_tree('push-from')
        self.build_tree(['push-from/file'])
        b.add('file')
        b.commit('commit 1')
        out, err = self.run_bzr('push --no-tree -d push-from push-to')
        self.assertEqual('', out)
        self.assertEqual('Created new branch.\n', err)
        self.assertPathDoesNotExist('push-to/file')

    def test_push_new_branch_revision_count(self):
        # brz push of a branch with revisions to a new location
        # should print the number of revisions equal to the length of the
        # local branch.
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        t.add('file')
        t.commit('commit 1')
        out, err = self.run_bzr('push -d tree pushed-to')
        self.assertEqual('', out)
        self.assertEqual('Created new branch.\n', err)

    def test_push_quiet(self):
        # test that using -q makes output quiet
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        t.add('file')
        t.commit('commit 1')
        self.run_bzr('push -d tree pushed-to')
        # Refresh the branch as 'push' modified it and get the push location
        push_loc = t.branch.controldir.open_branch().get_push_location()
        out, err = self.run_bzr('push', working_dir="tree")
        self.assertEqual('Using saved push location: %s\n'
                         'No new revisions or tags to push.\n' %
                         urlutils.local_path_from_url(push_loc), err)
        out, err = self.run_bzr('push -q', working_dir="tree")
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_push_only_pushes_history(self):
        # Knit branches should only push the history for the current revision.
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        shared_repo = self.make_repository('repo', format=format, shared=True)
        shared_repo.set_make_working_trees(True)

        def make_shared_tree(path):
            shared_repo.controldir.root_transport.mkdir(path)
            controldir.ControlDir.create_branch_convenience('repo/' + path)
            return workingtree.WorkingTree.open('repo/' + path)
        tree_a = make_shared_tree('a')
        self.build_tree(['repo/a/file'])
        tree_a.add('file')
        tree_a.commit('commit a-1', rev_id=b'a-1')
        f = open('repo/a/file', 'ab')
        f.write(b'more stuff\n')
        f.close()
        tree_a.commit('commit a-2', rev_id=b'a-2')

        tree_b = make_shared_tree('b')
        self.build_tree(['repo/b/file'])
        tree_b.add('file')
        tree_b.commit('commit b-1', rev_id=b'b-1')

        self.assertTrue(shared_repo.has_revision(b'a-1'))
        self.assertTrue(shared_repo.has_revision(b'a-2'))
        self.assertTrue(shared_repo.has_revision(b'b-1'))

        # Now that we have a repository with shared files, make sure
        # that things aren't copied out by a 'push'
        self.run_bzr('push ../../push-b', working_dir='repo/b')
        pushed_tree = workingtree.WorkingTree.open('push-b')
        pushed_repo = pushed_tree.branch.repository
        self.assertFalse(pushed_repo.has_revision(b'a-1'))
        self.assertFalse(pushed_repo.has_revision(b'a-2'))
        self.assertTrue(pushed_repo.has_revision(b'b-1'))

    def test_push_funky_id(self):
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/filename'])
        t.add('filename', ids=b'funky-chars<>%&;"\'')
        t.commit('commit filename')
        self.run_bzr('push -d tree new-tree')

    def test_push_dash_d(self):
        t = self.make_branch_and_tree('from')
        t.commit(allow_pointless=True,
                 message='first commit')
        self.run_bzr('push -d from to-one')
        self.assertPathExists('to-one')
        self.run_bzr('push -d %s %s'
                     % tuple(map(urlutils.local_path_to_url, ['from', 'to-two'])))
        self.assertPathExists('to-two')

    def test_push_repository_no_branch_doesnt_fetch_all_revs(self):
        # See https://bugs.launchpad.net/bzr/+bug/465517
        target_repo = self.make_repository('target')
        source = self.make_branch_builder('source')
        source.start_series()
        source.build_snapshot(None, [
            ('add', ('', b'root-id', 'directory', None))],
            revision_id=b'A')
        source.build_snapshot([b'A'], [], revision_id=b'B')
        source.build_snapshot([b'A'], [], revision_id=b'C')
        source.finish_series()
        self.run_bzr('push target -d source')
        self.addCleanup(target_repo.lock_read().unlock)
        # We should have pushed 'C', but not 'B', since it isn't in the
        # ancestry
        self.assertEqual([(b'A',), (b'C',)], sorted(
            target_repo.revisions.keys()))

    def test_push_smart_with_default_stacking_url_path_segment(self):
        # If the default stacked-on location is a path element then branches
        # we push there over the smart server are stacked and their
        # stacked_on_url is that exact path segment. Added to nail bug 385132.
        self.setup_smart_server_with_call_log()
        self.make_branch('stack-on', format='1.9')
        self.make_controldir('.').get_config().set_default_stack_on(
            '/stack-on')
        self.make_branch('from', format='1.9')
        out, err = self.run_bzr(['push', '-d', 'from', self.get_url('to')])
        b = branch.Branch.open(self.get_url('to'))
        self.assertEqual('/extra/stack-on', b.get_stacked_on_url())

    def test_push_smart_with_default_stacking_relative_path(self):
        # If the default stacked-on location is a relative path then branches
        # we push there over the smart server are stacked and their
        # stacked_on_url is a relative path. Added to nail bug 385132.
        self.setup_smart_server_with_call_log()
        self.make_branch('stack-on', format='1.9')
        self.make_controldir('.').get_config().set_default_stack_on('stack-on')
        self.make_branch('from', format='1.9')
        out, err = self.run_bzr(['push', '-d', 'from', self.get_url('to')])
        b = branch.Branch.open(self.get_url('to'))
        self.assertEqual('../stack-on', b.get_stacked_on_url())

    def create_simple_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add(['a'], ids=[b'a-id'])
        tree.commit('one', rev_id=b'r1')
        return tree

    def test_push_create_prefix(self):
        """'brz push --create-prefix' will create leading directories."""
        tree = self.create_simple_tree()

        self.run_bzr_error(['Parent directory of ../new/tree does not exist'],
                           'push ../new/tree',
                           working_dir='tree')
        self.run_bzr('push ../new/tree --create-prefix',
                     working_dir='tree')
        new_tree = workingtree.WorkingTree.open('new/tree')
        self.assertEqual(tree.last_revision(), new_tree.last_revision())
        self.assertPathExists('new/tree/a')

    def test_push_use_existing(self):
        """'brz push --use-existing-dir' can push into an existing dir.

        By default, 'brz push' will not use an existing, non-versioned dir.
        """
        tree = self.create_simple_tree()
        self.build_tree(['target/'])

        self.run_bzr_error(['Target directory ../target already exists',
                            'Supply --use-existing-dir',
                            ],
                           'push ../target', working_dir='tree')

        self.run_bzr('push --use-existing-dir ../target',
                     working_dir='tree')

        new_tree = workingtree.WorkingTree.open('target')
        self.assertEqual(tree.last_revision(), new_tree.last_revision())
        # The push should have created target/a
        self.assertPathExists('target/a')

    def test_push_use_existing_into_empty_bzrdir(self):
        """'brz push --use-existing-dir' into a dir with an empty .bzr dir
        fails.
        """
        tree = self.create_simple_tree()
        self.build_tree(['target/', 'target/.bzr/'])
        self.run_bzr_error(
            ['Target directory ../target already contains a .bzr directory, '
             'but it is not valid.'],
            'push ../target --use-existing-dir', working_dir='tree')

    def test_push_onto_repo(self):
        """We should be able to 'brz push' into an existing bzrdir."""
        tree = self.create_simple_tree()
        repo = self.make_repository('repo', shared=True)

        self.run_bzr('push ../repo',
                     working_dir='tree')

        # Pushing onto an existing bzrdir will create a repository and
        # branch as needed, but will only create a working tree if there was
        # no BzrDir before.
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTree.open, 'repo')
        new_branch = branch.Branch.open('repo')
        self.assertEqual(tree.last_revision(), new_branch.last_revision())

    def test_push_onto_just_bzrdir(self):
        """We don't handle when the target is just a bzrdir.

        Because you shouldn't be able to create *just* a bzrdir in the wild.
        """
        # TODO: jam 20070109 Maybe it would be better to create the repository
        #       if at this point
        tree = self.create_simple_tree()
        a_controldir = self.make_controldir('dir')

        self.run_bzr_error(['At ../dir you have a valid .bzr control'],
                           'push ../dir',
                           working_dir='tree')

    def test_push_with_revisionspec(self):
        """We should be able to push a revision older than the tip."""
        tree_from = self.make_branch_and_tree('from')
        tree_from.commit("One.", rev_id=b"from-1")
        tree_from.commit("Two.", rev_id=b"from-2")

        self.run_bzr('push -r1 ../to', working_dir='from')

        tree_to = workingtree.WorkingTree.open('to')
        repo_to = tree_to.branch.repository
        self.assertTrue(repo_to.has_revision(b'from-1'))
        self.assertFalse(repo_to.has_revision(b'from-2'))
        self.assertEqual(tree_to.branch.last_revision_info()[1], b'from-1')
        self.assertFalse(
            tree_to.changes_from(tree_to.basis_tree()).has_changed())

        self.run_bzr_error(
            ['brz: ERROR: brz push --revision '
             'takes exactly one revision identifier\n'],
            'push -r0..2 ../to', working_dir='from')

    def create_trunk_and_feature_branch(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('target',
                                               format='1.9')
        trunk_tree.commit('mainline')
        # and a branch from it
        branch_tree = self.make_branch_and_tree('branch',
                                                format='1.9')
        branch_tree.pull(trunk_tree.branch)
        branch_tree.branch.set_parent(trunk_tree.branch.base)
        # with some work on it
        branch_tree.commit('moar work plz')
        return trunk_tree, branch_tree

    def assertPublished(self, branch_revid, stacked_on):
        """Assert that the branch 'published' has been published correctly."""
        published_branch = branch.Branch.open('published')
        # The published branch refers to the mainline
        self.assertEqual(stacked_on, published_branch.get_stacked_on_url())
        # and the branch's work was pushed
        self.assertTrue(published_branch.repository.has_revision(branch_revid))

    def test_push_new_branch_stacked_on(self):
        """Pushing a new branch with --stacked-on creates a stacked branch."""
        trunk_tree, branch_tree = self.create_trunk_and_feature_branch()
        # we publish branch_tree with a reference to the mainline.
        out, err = self.run_bzr(['push', '--stacked-on', trunk_tree.branch.base,
                                 self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
                         trunk_tree.branch.base, err)
        self.assertPublished(branch_tree.last_revision(),
                             trunk_tree.branch.base)

    def test_push_new_branch_stacked_on(self):
        """Pushing a new branch with --stacked-on can use directory URLs."""
        trunk_tree, branch_tree = self.create_trunk_and_feature_branch()
        class FooDirectory(object):
            def look_up(self, name, url, purpose=None):
                if url == 'foo:':
                    return trunk_tree.branch.base
                return url
        directory_service.directories.register('foo:', FooDirectory, 'Foo directory')
        self.addCleanup(directory_service.directories.remove, 'foo:')
        # we publish branch_tree with a reference to the mainline.
        out, err = self.run_bzr(['push', '--stacked-on', 'foo:',
                                 self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
                         trunk_tree.branch.base, err)
        self.assertPublished(branch_tree.last_revision(),
                             trunk_tree.branch.base)

    def test_push_new_branch_stacked_uses_parent_when_no_public_url(self):
        """When the parent has no public url the parent is used as-is."""
        trunk_tree, branch_tree = self.create_trunk_and_feature_branch()
        # now we do a stacked push, which should determine the public location
        # for us.
        out, err = self.run_bzr(['push', '--stacked',
                                 self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
                         trunk_tree.branch.base, err)
        self.assertPublished(branch_tree.last_revision(),
                             trunk_tree.branch.base)

    def test_push_new_branch_stacked_uses_parent_public(self):
        """Pushing a new branch with --stacked creates a stacked branch."""
        trunk_tree, branch_tree = self.create_trunk_and_feature_branch()
        # the trunk is published on a web server
        self.transport_readonly_server = http_server.HttpServer
        trunk_public = self.make_branch('public_trunk', format='1.9')
        trunk_public.pull(trunk_tree.branch)
        trunk_public_url = self.get_readonly_url('public_trunk')
        br = trunk_tree.branch
        br.set_public_branch(trunk_public_url)
        # now we do a stacked push, which should determine the public location
        # for us.
        out, err = self.run_bzr(['push', '--stacked',
                                 self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
                         trunk_public_url, err)
        self.assertPublished(branch_tree.last_revision(), trunk_public_url)

    def test_push_new_branch_stacked_no_parent(self):
        """Pushing with --stacked and no parent branch errors."""
        branch = self.make_branch_and_tree('branch', format='1.9')
        # now we do a stacked push, which should fail as the place to refer too
        # cannot be determined.
        out, err = self.run_bzr_error(
            ['Could not determine branch to refer to\\.'], ['push', '--stacked',
                                                            self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertFalse(self.get_transport('published').has('.'))

    def test_push_notifies_default_stacking(self):
        self.make_branch('stack_on', format='1.6')
        self.make_controldir('.').get_config().set_default_stack_on('stack_on')
        self.make_branch('from', format='1.6')
        out, err = self.run_bzr('push -d from to')
        self.assertContainsRe(err,
                              'Using default stacking branch stack_on at .*')

    def test_push_stacks_with_default_stacking_if_target_is_stackable(self):
        self.make_branch('stack_on', format='1.6')
        self.make_controldir('.').get_config().set_default_stack_on('stack_on')
        self.make_branch('from', format='pack-0.92')
        out, err = self.run_bzr('push -d from to')
        b = branch.Branch.open('to')
        self.assertEqual('../stack_on', b.get_stacked_on_url())

    def test_push_does_not_change_format_with_default_if_target_cannot(self):
        self.make_branch('stack_on', format='pack-0.92')
        self.make_controldir('.').get_config().set_default_stack_on('stack_on')
        self.make_branch('from', format='pack-0.92')
        out, err = self.run_bzr('push -d from to')
        b = branch.Branch.open('to')
        self.assertRaises(branch.UnstackableBranchFormat, b.get_stacked_on_url)

    def test_push_doesnt_create_broken_branch(self):
        """Pushing a new standalone branch works even when there's a default
        stacking policy at the destination.

        The new branch will preserve the repo format (even if it isn't the
        default for the branch), and will be stacked when the repo format
        allows (which means that the branch format isn't necessarly preserved).
        """
        self.make_repository('repo', shared=True, format='1.6')
        builder = self.make_branch_builder('repo/local', format='pack-0.92')
        builder.start_series()
        builder.build_snapshot(None, [
            ('add', ('', b'root-id', 'directory', '')),
            ('add', ('filename', b'f-id', 'file', b'content\n'))],
            revision_id=b'rev-1')
        builder.build_snapshot([b'rev-1'], [], revision_id=b'rev-2')
        builder.build_snapshot([b'rev-2'],
                               [('modify', ('filename', b'new-content\n'))],
                               revision_id=b'rev-3')
        builder.finish_series()
        branch = builder.get_branch()
        # Push rev-1 to "trunk", so that we can stack on it.
        self.run_bzr('push -d repo/local trunk -r 1')
        # Set a default stacking policy so that new branches will automatically
        # stack on trunk.
        self.make_controldir('.').get_config().set_default_stack_on('trunk')
        # Push rev-2 to a new branch "remote".  It will be stacked on "trunk".
        out, err = self.run_bzr('push -d repo/local remote -r 2')
        self.assertContainsRe(
            err, 'Using default stacking branch trunk at .*')
        # Push rev-3 onto "remote".  If "remote" not stacked and is missing the
        # fulltext record for f-id @ rev-1, then this will fail.
        out, err = self.run_bzr('push -d repo/local remote -r 3')

    def test_push_verbose_shows_log(self):
        tree = self.make_branch_and_tree('source')
        tree.commit('rev1')
        out, err = self.run_bzr('push -v -d source target')
        # initial push contains log
        self.assertContainsRe(out, 'rev1')
        tree.commit('rev2')
        out, err = self.run_bzr('push -v -d source target')
        # subsequent push contains log
        self.assertContainsRe(out, 'rev2')
        # subsequent log is accurate
        self.assertNotContainsRe(out, 'rev1')

    def test_push_from_subdir(self):
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        t.add(['dir', 'dir/file'])
        t.commit('r1')
        out, err = self.run_bzr('push ../../pushloc', working_dir='tree/dir')
        self.assertEqual('', out)
        self.assertEqual('Created new branch.\n', err)

    def test_overwrite_tags(self):
        """--overwrite-tags only overwrites tags, not revisions."""
        from_tree = self.make_branch_and_tree('from')
        from_tree.branch.tags.set_tag("mytag", b"somerevid")
        to_tree = self.make_branch_and_tree('to')
        to_tree.branch.tags.set_tag("mytag", b"anotherrevid")
        revid1 = to_tree.commit('my commit')
        out = self.run_bzr(['push', '-d', 'from', 'to'])
        self.assertEqual(out,
                         ('Conflicting tags:\n    mytag\n', 'No new revisions to push.\n'))
        out = self.run_bzr(['push', '-d', 'from', '--overwrite-tags', 'to'])
        self.assertEqual(out, ('', '1 tag updated.\n'))
        self.assertEqual(to_tree.branch.tags.lookup_tag('mytag'),
                         b'somerevid')
        self.assertEqual(to_tree.branch.last_revision(), revid1)


class RedirectingMemoryTransport(memory.MemoryTransport):

    def mkdir(self, relpath, mode=None):
        if self._cwd == '/source/':
            raise errors.RedirectRequested(self.abspath(relpath),
                                           self.abspath('../target'),
                                           is_permanent=True)
        elif self._cwd == '/infinite-loop/':
            raise errors.RedirectRequested(self.abspath(relpath),
                                           self.abspath('../infinite-loop'),
                                           is_permanent=True)
        else:
            return super(RedirectingMemoryTransport, self).mkdir(
                relpath, mode)

    def get(self, relpath):
        if self.clone(relpath)._cwd == '/infinite-loop/':
            raise errors.RedirectRequested(self.abspath(relpath),
                                           self.abspath('../infinite-loop'),
                                           is_permanent=True)
        else:
            return super(RedirectingMemoryTransport, self).get(relpath)

    def _redirected_to(self, source, target):
        # We do accept redirections
        return transport.get_transport(target)


class RedirectingMemoryServer(memory.MemoryServer):

    def start_server(self):
        self._dirs = {'/': None}
        self._files = {}
        self._locks = {}
        self._scheme = 'redirecting-memory+%s:///' % id(self)
        transport.register_transport(self._scheme, self._memory_factory)

    def _memory_factory(self, url):
        result = RedirectingMemoryTransport(url)
        result._dirs = self._dirs
        result._files = self._files
        result._locks = self._locks
        return result

    def stop_server(self):
        transport.unregister_transport(self._scheme, self._memory_factory)


class TestPushRedirect(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestPushRedirect, self).setUp()
        self.memory_server = RedirectingMemoryServer()
        self.start_server(self.memory_server)
        # Make the branch and tree that we'll be pushing.
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        t.add('file')
        t.commit('commit 1')

    def test_push_redirects_on_mkdir(self):
        """If the push requires a mkdir, push respects redirect requests.

        This is added primarily to handle lp:/ URI support, so that users can
        push to new branches by specifying lp:/ URIs.
        """
        destination_url = self.memory_server.get_url() + 'source'
        self.run_bzr(['push', '-d', 'tree', destination_url])

        local_revision = branch.Branch.open('tree').last_revision()
        remote_revision = branch.Branch.open(
            self.memory_server.get_url() + 'target').last_revision()
        self.assertEqual(remote_revision, local_revision)

    def test_push_gracefully_handles_too_many_redirects(self):
        """Push fails gracefully if the mkdir generates a large number of
        redirects.
        """
        destination_url = self.memory_server.get_url() + 'infinite-loop'
        out, err = self.run_bzr_error(
            ['Too many redirections trying to make %s\\.\n'
             % re.escape(destination_url)],
            ['push', '-d', 'tree', destination_url], retcode=3)
        self.assertEqual('', out)


class TestPushStrictMixin(object):

    def make_local_branch_and_tree(self):
        self.tree = self.make_branch_and_tree('local')
        self.build_tree_contents([('local/file', b'initial')])
        self.tree.add('file')
        self.tree.commit('adding file', rev_id=b'added')
        self.build_tree_contents([('local/file', b'modified')])
        self.tree.commit('modify file', rev_id=b'modified')

    def set_config_push_strict(self, value):
        br = branch.Branch.open('local')
        br.get_config_stack().set('push_strict', value)

    _default_command = ['push', '../to']
    _default_wd = 'local'
    _default_errors = ['Working tree ".*/local/" has uncommitted '
                       'changes \\(See brz status\\)\\.', ]
    _default_additional_error = 'Use --no-strict to force the push.\n'
    _default_additional_warning = 'Uncommitted changes will not be pushed.'

    def assertPushFails(self, args):
        out, err = self.run_bzr_error(self._default_errors,
                                      self._default_command + args,
                                      working_dir=self._default_wd, retcode=3)
        self.assertContainsRe(err, self._default_additional_error)

    def assertPushSucceeds(self, args, with_warning=False, revid_to_push=None):
        if with_warning:
            error_regexes = self._default_errors
        else:
            error_regexes = []
        out, err = self.run_bzr(self._default_command + args,
                                working_dir=self._default_wd,
                                error_regexes=error_regexes)
        if with_warning:
            self.assertContainsRe(err, self._default_additional_warning)
        else:
            self.assertNotContainsRe(err, self._default_additional_warning)
        branch_from = branch.Branch.open(self._default_wd)
        if revid_to_push is None:
            revid_to_push = branch_from.last_revision()
        branch_to = branch.Branch.open('to')
        repo_to = branch_to.repository
        self.assertTrue(repo_to.has_revision(revid_to_push))
        self.assertEqual(revid_to_push, branch_to.last_revision())


class TestPushStrictWithoutChanges(tests.TestCaseWithTransport,
                                   TestPushStrictMixin):

    def setUp(self):
        super(TestPushStrictWithoutChanges, self).setUp()
        self.make_local_branch_and_tree()

    def test_push_default(self):
        self.assertPushSucceeds([])

    def test_push_strict(self):
        self.assertPushSucceeds(['--strict'])

    def test_push_no_strict(self):
        self.assertPushSucceeds(['--no-strict'])

    def test_push_config_var_strict(self):
        self.set_config_push_strict('true')
        self.assertPushSucceeds([])

    def test_push_config_var_no_strict(self):
        self.set_config_push_strict('false')
        self.assertPushSucceeds([])


strict_push_change_scenarios = [
    ('uncommitted',
        dict(_changes_type='_uncommitted_changes')),
    ('pending-merges',
        dict(_changes_type='_pending_merges')),
    ('out-of-sync-trees',
        dict(_changes_type='_out_of_sync_trees')),
    ]


class TestPushStrictWithChanges(tests.TestCaseWithTransport,
                                TestPushStrictMixin):

    scenarios = strict_push_change_scenarios
    _changes_type = None  # Set by load_tests

    def setUp(self):
        super(TestPushStrictWithChanges, self).setUp()
        # Apply the changes defined in load_tests: one of _uncommitted_changes,
        # _pending_merges or _out_of_sync_trees
        getattr(self, self._changes_type)()

    def _uncommitted_changes(self):
        self.make_local_branch_and_tree()
        # Make a change without committing it
        self.build_tree_contents([('local/file', b'in progress')])

    def _pending_merges(self):
        self.make_local_branch_and_tree()
        # Create 'other' branch containing a new file
        other_bzrdir = self.tree.controldir.sprout('other')
        other_tree = other_bzrdir.open_workingtree()
        self.build_tree_contents([('other/other-file', b'other')])
        other_tree.add('other-file')
        other_tree.commit('other commit', rev_id=b'other')
        # Merge and revert, leaving a pending merge
        self.tree.merge_from_branch(other_tree.branch)
        self.tree.revert(filenames=['other-file'], backups=False)

    def _out_of_sync_trees(self):
        self.make_local_branch_and_tree()
        self.run_bzr(['checkout', '--lightweight', 'local', 'checkout'])
        # Make a change and commit it
        self.build_tree_contents([('local/file', b'modified in local')])
        self.tree.commit('modify file', rev_id=b'modified-in-local')
        # Exercise commands from the checkout directory
        self._default_wd = 'checkout'
        self._default_errors = ["Working tree is out of date, please run"
                                " 'brz update'\\.", ]

    def test_push_default(self):
        self.assertPushSucceeds([], with_warning=True)

    def test_push_with_revision(self):
        self.assertPushSucceeds(['-r', 'revid:added'], revid_to_push=b'added')

    def test_push_no_strict(self):
        self.assertPushSucceeds(['--no-strict'])

    def test_push_strict_with_changes(self):
        self.assertPushFails(['--strict'])

    def test_push_respect_config_var_strict(self):
        self.set_config_push_strict('true')
        self.assertPushFails([])

    def test_push_bogus_config_var_ignored(self):
        self.set_config_push_strict("I don't want you to be strict")
        self.assertPushSucceeds([], with_warning=True)

    def test_push_no_strict_command_line_override_config(self):
        self.set_config_push_strict('yES')
        self.assertPushFails([])
        self.assertPushSucceeds(['--no-strict'])

    def test_push_strict_command_line_override_config(self):
        self.set_config_push_strict('oFF')
        self.assertPushFails(['--strict'])
        self.assertPushSucceeds([])


class TestPushForeign(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestPushForeign, self).setUp()
        test_foreign.register_dummy_foreign_for_test(self)

    def make_dummy_builder(self, relpath):
        builder = self.make_branch_builder(
            relpath, format=test_foreign.DummyForeignVcsDirFormat())
        builder.build_snapshot(None,
                               [('add', ('', b'TREE_ROOT', 'directory', None)),
                                ('add', ('foo', b'fooid', 'file', b'bar'))],
                               revision_id=b'revid')
        return builder

    def test_no_roundtripping(self):
        target_branch = self.make_dummy_builder('dp').get_branch()
        source_tree = self.make_branch_and_tree("dc")
        output, error = self.run_bzr("push -d dc dp", retcode=3)
        self.assertEqual("", output)
        self.assertEqual(
            error,
            "brz: ERROR: It is not possible to losslessly"
            " push to dummy. You may want to use --lossy.\n")


class TestPushOutput(script.TestCaseWithTransportAndScript):

    def test_push_log_format(self):
        self.run_script("""
            $ brz init trunk
            Created a standalone tree (format: 2a)
            $ cd trunk
            $ echo foo > file
            $ brz add
            adding file
            $ brz commit -m 'we need some foo'
            2>Committing to:...trunk/
            2>added file
            2>Committed revision 1.
            $ brz init ../feature
            Created a standalone tree (format: 2a)
            $ brz push -v ../feature -Olog_format=line
            Added Revisions:
            1: jrandom@example.com ...we need some foo
            2>All changes applied successfully.
            2>Pushed up to revision 1.
            """)

    def test_push_with_revspec(self):
        self.run_script("""
            $ brz init-shared-repo .
            Shared repository with trees (format: 2a)
            Location:
              shared repository: .
            $ brz init trunk
            Created a repository tree (format: 2a)
            Using shared repository...
            $ cd trunk
            $ brz commit -m 'first rev' --unchanged
            2>Committing to:...trunk/
            2>Committed revision 1.
            $ echo foo > file
            $ brz add
            adding file
            $ brz commit -m 'we need some foo'
            2>Committing to:...trunk/
            2>added file
            2>Committed revision 2.
            $ brz push -r 1 ../other
            2>Created new branch.
            $ brz st ../other # checking that file is not created (#484516)
            """)
