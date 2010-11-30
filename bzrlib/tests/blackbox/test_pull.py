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


"""Black-box tests for bzr pull."""

import os
import sys

from bzrlib import (
    debug,
    remote,
    urlutils,
    )

from bzrlib.branch import Branch
from bzrlib.directory_service import directories
from bzrlib.osutils import pathjoin
from bzrlib.tests import TestCaseWithTransport
from bzrlib.uncommit import uncommit
from bzrlib.workingtree import WorkingTree


class TestPull(TestCaseWithTransport):

    def example_branch(self, path='.'):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents([
            (pathjoin(path, 'hello'),   'foo'),
            (pathjoin(path, 'goodbye'), 'baz')])
        tree.add('hello')
        tree.commit(message='setup')
        tree.add('goodbye')
        tree.commit(message='setup')
        return tree

    def test_pull(self):
        """Pull changes from one branch to another."""
        a_tree = self.example_branch('a')
        os.chdir('a')
        self.run_bzr('pull', retcode=3)
        self.run_bzr('missing', retcode=3)
        self.run_bzr('missing .')
        self.run_bzr('missing')
        # this will work on windows because we check for the same branch
        # in pull - if it fails, it is a regression
        self.run_bzr('pull')
        self.run_bzr('pull /', retcode=3)
        if sys.platform not in ('win32', 'cygwin'):
            self.run_bzr('pull')

        os.chdir('..')
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        os.chdir('b')
        self.run_bzr('pull')
        os.mkdir('subdir')
        b_tree.add('subdir')
        b_tree.commit(message='blah', allow_pointless=True)

        os.chdir('..')
        a = Branch.open('a')
        b = Branch.open('b')
        self.assertEqual(a.revision_history(), b.revision_history()[:-1])

        os.chdir('a')
        self.run_bzr('pull ../b')
        self.assertEqual(a.revision_history(), b.revision_history())
        a_tree.commit(message='blah2', allow_pointless=True)
        b_tree.commit(message='blah3', allow_pointless=True)
        # no overwrite
        os.chdir('../b')
        self.run_bzr('pull ../a', retcode=3)
        os.chdir('..')
        b_tree.bzrdir.sprout('overwriteme')
        os.chdir('overwriteme')
        self.run_bzr('pull --overwrite ../a')
        overwritten = Branch.open('.')
        self.assertEqual(overwritten.revision_history(),
                         a.revision_history())
        a_tree.merge_from_branch(b_tree.branch)
        a_tree.commit(message="blah4", allow_pointless=True)
        os.chdir('../b/subdir')
        self.run_bzr('pull ../../a')
        self.assertEqual(a.revision_history()[-1], b.revision_history()[-1])
        sub_tree = WorkingTree.open_containing('.')[0]
        sub_tree.commit(message="blah5", allow_pointless=True)
        sub_tree.commit(message="blah6", allow_pointless=True)
        os.chdir('..')
        self.run_bzr('pull ../a')
        os.chdir('../a')
        a_tree.commit(message="blah7", allow_pointless=True)
        a_tree.merge_from_branch(b_tree.branch)
        a_tree.commit(message="blah8", allow_pointless=True)
        self.run_bzr('pull ../b')
        self.run_bzr('pull ../b')

    def test_pull_dash_d(self):
        self.example_branch('a')
        self.make_branch_and_tree('b')
        self.make_branch_and_tree('c')
        # pull into that branch
        self.run_bzr('pull -d b a')
        # pull into a branch specified by a url
        c_url = urlutils.local_path_to_url('c')
        self.assertStartsWith(c_url, 'file://')
        self.run_bzr(['pull', '-d', c_url, 'a'])

    def test_pull_revision(self):
        """Pull some changes from one branch to another."""
        a_tree = self.example_branch('a')
        self.build_tree_contents([
            ('a/hello2',   'foo'),
            ('a/goodbye2', 'baz')])
        a_tree.add('hello2')
        a_tree.commit(message="setup")
        a_tree.add('goodbye2')
        a_tree.commit(message="setup")

        b_tree = a_tree.bzrdir.sprout('b',
                   revision_id=a_tree.branch.get_rev_id(1)).open_workingtree()
        os.chdir('b')
        self.run_bzr('pull -r 2')
        a = Branch.open('../a')
        b = Branch.open('.')
        self.assertEqual(a.revno(),4)
        self.assertEqual(b.revno(),2)
        self.run_bzr('pull -r 3')
        self.assertEqual(b.revno(),3)
        self.run_bzr('pull -r 4')
        self.assertEqual(a.revision_history(), b.revision_history())

    def test_overwrite_uptodate(self):
        # Make sure pull --overwrite overwrites
        # even if the target branch has merged
        # everything already.
        a_tree = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/foo', 'original\n')])
        a_tree.add('foo')
        a_tree.commit(message='initial commit')

        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()

        self.build_tree_contents([('a/foo', 'changed\n')])
        a_tree.commit(message='later change')

        self.build_tree_contents([('a/foo', 'a third change')])
        a_tree.commit(message='a third change')

        rev_history_a = a_tree.branch.revision_history()
        self.assertEqual(len(rev_history_a), 3)

        b_tree.merge_from_branch(a_tree.branch)
        b_tree.commit(message='merge')

        self.assertEqual(len(b_tree.branch.revision_history()), 2)

        os.chdir('b')
        self.run_bzr('pull --overwrite ../a')
        rev_history_b = b_tree.branch.revision_history()
        self.assertEqual(len(rev_history_b), 3)

        self.assertEqual(rev_history_b, rev_history_a)

    def test_overwrite_children(self):
        # Make sure pull --overwrite sets the revision-history
        # to be identical to the pull source, even if we have convergence
        a_tree = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/foo', 'original\n')])
        a_tree.add('foo')
        a_tree.commit(message='initial commit')

        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()

        self.build_tree_contents([('a/foo', 'changed\n')])
        a_tree.commit(message='later change')

        self.build_tree_contents([('a/foo', 'a third change')])
        a_tree.commit(message='a third change')

        self.assertEqual(len(a_tree.branch.revision_history()), 3)

        b_tree.merge_from_branch(a_tree.branch)
        b_tree.commit(message='merge')

        self.assertEqual(len(b_tree.branch.revision_history()), 2)

        self.build_tree_contents([('a/foo', 'a fourth change\n')])
        a_tree.commit(message='a fourth change')

        rev_history_a = a_tree.branch.revision_history()
        self.assertEqual(len(rev_history_a), 4)

        # With convergence, we could just pull over the
        # new change, but with --overwrite, we want to switch our history
        os.chdir('b')
        self.run_bzr('pull --overwrite ../a')
        rev_history_b = b_tree.branch.revision_history()
        self.assertEqual(len(rev_history_b), 4)

        self.assertEqual(rev_history_b, rev_history_a)

    def test_pull_remember(self):
        """Pull changes from one branch to another and test parent location."""
        transport = self.get_transport()
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        tree_b = branch_a.bzrdir.sprout('branch_b').open_workingtree()
        branch_b = tree_b.branch
        tree_c = branch_a.bzrdir.sprout('branch_c').open_workingtree()
        branch_c = tree_c.branch
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        # reset parent
        parent = branch_b.get_parent()
        branch_b.set_parent(None)
        self.assertEqual(None, branch_b.get_parent())
        # test pull for failure without parent set
        os.chdir('branch_b')
        out = self.run_bzr('pull', retcode=3)
        self.assertEqual(out,
                ('','bzr: ERROR: No pull location known or specified.\n'))
        # test implicit --remember when no parent set, this pull conflicts
        self.build_tree(['d'])
        tree_b.add('d')
        tree_b.commit('commit d')
        out = self.run_bzr('pull ../branch_a', retcode=3)
        self.assertEqual(out,
                ('','bzr: ERROR: These branches have diverged.'
                    ' Use the missing command to see how.\n'
                    'Use the merge command to reconcile them.\n'))
        self.assertEqual(branch_b.get_parent(), parent)
        # test implicit --remember after resolving previous failure
        uncommit(branch=branch_b, tree=tree_b)
        transport.delete('branch_b/d')
        self.run_bzr('pull')
        self.assertEqual(branch_b.get_parent(), parent)
        # test explicit --remember
        self.run_bzr('pull ../branch_c --remember')
        self.assertEqual(branch_b.get_parent(),
                          branch_c.bzrdir.root_transport.base)

    def test_pull_bundle(self):
        from bzrlib.testament import Testament
        # Build up 2 trees and prepare for a pull
        tree_a = self.make_branch_and_tree('branch_a')
        f = open('branch_a/a', 'wb')
        f.write('hello')
        f.close()
        tree_a.add('a')
        tree_a.commit('message')

        tree_b = tree_a.bzrdir.sprout('branch_b').open_workingtree()

        # Make a change to 'a' that 'b' can pull
        f = open('branch_a/a', 'wb')
        f.write('hey there')
        f.close()
        tree_a.commit('message')

        # Create the bundle for 'b' to pull
        os.chdir('branch_a')
        self.run_bzr('bundle ../branch_b -o ../bundle')

        os.chdir('../branch_b')
        out, err = self.run_bzr('pull ../bundle')
        self.assertEqual(out,
                         'Now on revision 2.\n')
        self.assertEqual(err,
                ' M  a\nAll changes applied successfully.\n')

        self.assertEqualDiff(tree_a.branch.revision_history(),
                             tree_b.branch.revision_history())

        testament_a = Testament.from_revision(tree_a.branch.repository,
                                              tree_a.get_parent_ids()[0])
        testament_b = Testament.from_revision(tree_b.branch.repository,
                                              tree_b.get_parent_ids()[0])
        self.assertEqualDiff(testament_a.as_text(),
                             testament_b.as_text())

        # it is legal to attempt to pull an already-merged bundle
        out, err = self.run_bzr('pull ../bundle')
        self.assertEqual(err, '')
        self.assertEqual(out, 'No revisions to pull.\n')

    def test_pull_verbose_no_files(self):
        """Pull --verbose should not list modified files"""
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree(['tree_a/foo'])
        tree_a.add('foo')
        tree_a.commit('bar')
        tree_b = self.make_branch_and_tree('tree_b')
        out = self.run_bzr('pull --verbose -d tree_b tree_a')[0]
        self.assertContainsRe(out, 'bar')
        self.assertNotContainsRe(out, 'added:')
        self.assertNotContainsRe(out, 'foo')

    def test_pull_quiet(self):
        """Check that bzr pull --quiet does not print anything"""
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree(['tree_a/foo'])
        tree_a.add('foo')
        revision_id = tree_a.commit('bar')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        out, err = self.run_bzr('pull --quiet -d tree_b')
        self.assertEqual(out, '')
        self.assertEqual(err, '')
        self.assertEqual(tree_b.last_revision(), revision_id)
        self.build_tree(['tree_a/moo'])
        tree_a.add('moo')
        revision_id = tree_a.commit('quack')
        out, err = self.run_bzr('pull --quiet -d tree_b')
        self.assertEqual(out, '')
        self.assertEqual(err, '')
        self.assertEqual(tree_b.last_revision(), revision_id)

    def test_pull_from_directory_service(self):
        source = self.make_branch_and_tree('source')
        source.commit('commit 1')
        target = source.bzrdir.sprout('target').open_workingtree()
        source_last = source.commit('commit 2')
        class FooService(object):
            """A directory service that always returns source"""

            def look_up(self, name, url):
                return 'source'
        directories.register('foo:', FooService, 'Testing directory service')
        self.addCleanup(directories.remove, 'foo:')
        self.run_bzr('pull foo:bar -d target')
        self.assertEqual(source_last, target.last_revision())

    def test_pull_verbose_defaults_to_long(self):
        tree = self.example_branch('source')
        target = self.make_branch_and_tree('target')
        out = self.run_bzr('pull -v source -d target')[0]
        self.assertContainsRe(out,
                              r'revno: 1\ncommitter: .*\nbranch nick: source')
        self.assertNotContainsRe(out, r'\n {4}1 .*\n {6}setup\n')

    def test_pull_verbose_uses_default_log(self):
        tree = self.example_branch('source')
        target = self.make_branch_and_tree('target')
        target_config = target.branch.get_config()
        target_config.set_user_option('log_format', 'short')
        out = self.run_bzr('pull -v source -d target')[0]
        self.assertContainsRe(out, r'\n {4}1 .*\n {6}setup\n')
        self.assertNotContainsRe(
            out, r'revno: 1\ncommitter: .*\nbranch nick: source')

    def test_pull_smart_stacked_streaming_acceptance(self):
        """'bzr pull -r 123' works on stacked, smart branches, even when the
        revision specified by the revno is only present in the fallback
        repository.

        See <https://launchpad.net/bugs/380314>
        """
        self.setup_smart_server_with_call_log()
        # Make a stacked-on branch with two commits so that the
        # revision-history can't be determined just by looking at the parent
        # field in the revision in the stacked repo.
        parent = self.make_branch_and_tree('parent', format='1.9')
        parent.commit(message='first commit')
        parent.commit(message='second commit')
        local = parent.bzrdir.sprout('local').open_workingtree()
        local.commit(message='local commit')
        local.branch.create_clone_on_transport(
            self.get_transport('stacked'), stacked_on=self.get_url('parent'))
        empty = self.make_branch_and_tree('empty', format='1.9')
        self.reset_smart_call_log()
        self.run_bzr(['pull', '-r', '1', self.get_url('stacked')],
            working_dir='empty')
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(18, self.hpss_calls)
        remote = Branch.open('stacked')
        self.assertEndsWith(remote.get_stacked_on_url(), '/parent')
    
    def test_pull_cross_format_warning(self):
        """You get a warning for probably slow cross-format pulls.
        """
        # this is assumed to be going through InterDifferingSerializer
        from_tree = self.make_branch_and_tree('from', format='2a')
        to_tree = self.make_branch_and_tree('to', format='1.14-rich-root')
        from_tree.commit(message='first commit')
        out, err = self.run_bzr(['pull', '-d', 'to', 'from'])
        self.assertContainsRe(err,
            "(?m)Doing on-the-fly conversion")

    def test_pull_cross_format_warning_no_IDS(self):
        """You get a warning for probably slow cross-format pulls.
        """
        # this simulates what would happen across the network, where
        # interdifferingserializer is not active

        debug.debug_flags.add('IDS_never')
        # TestCase take care of restoring them

        from_tree = self.make_branch_and_tree('from', format='2a')
        to_tree = self.make_branch_and_tree('to', format='1.14-rich-root')
        from_tree.commit(message='first commit')
        out, err = self.run_bzr(['pull', '-d', 'to', 'from'])
        self.assertContainsRe(err,
            "(?m)Doing on-the-fly conversion")

    def test_pull_cross_format_from_network(self):
        self.setup_smart_server_with_call_log()
        from_tree = self.make_branch_and_tree('from', format='2a')
        to_tree = self.make_branch_and_tree('to', format='1.14-rich-root')
        self.assertIsInstance(from_tree.branch, remote.RemoteBranch)
        from_tree.commit(message='first commit')
        out, err = self.run_bzr(['pull', '-d', 'to',
            from_tree.branch.bzrdir.root_transport.base])
        self.assertContainsRe(err,
            "(?m)Doing on-the-fly conversion")

    def test_pull_to_experimental_format_warning(self):
        """You get a warning for pulling into experimental formats.
        """
        from_tree = self.make_branch_and_tree('from', format='development-subtree')
        to_tree = self.make_branch_and_tree('to', format='development-subtree')
        from_tree.commit(message='first commit')
        out, err = self.run_bzr(['pull', '-d', 'to', 'from'])
        self.assertContainsRe(err,
            "(?m)Fetching into experimental format")

    def test_pull_cross_to_experimental_format_warning(self):
        """You get a warning for pulling into experimental formats.
        """
        from_tree = self.make_branch_and_tree('from', format='2a')
        to_tree = self.make_branch_and_tree('to', format='development-subtree')
        from_tree.commit(message='first commit')
        out, err = self.run_bzr(['pull', '-d', 'to', 'from'])
        self.assertContainsRe(err,
            "(?m)Fetching into experimental format")

    def test_pull_show_base(self):
        """bzr pull supports --show-base

        see https://bugs.launchpad.net/bzr/+bug/202374"""
        # create two trees with conflicts, setup conflict, check that
        # conflicted file looks correct
        a_tree = self.example_branch('a')
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()

        f = open(pathjoin('a', 'hello'),'wt')
        f.write('fee')
        f.close()
        a_tree.commit('fee')

        f = open(pathjoin('b', 'hello'),'wt')
        f.write('fie')
        f.close()

        out,err=self.run_bzr(['pull','-d','b','a','--show-base'])

        # check for message here
        self.assertEqual(err,
                         ' M  hello\nText conflict in hello\n1 conflicts encountered.\n')

        self.assertEqualDiff('<<<<<<< TREE\n'
                             'fie||||||| BASE-REVISION\n'
                             'foo=======\n'
                             'fee>>>>>>> MERGE-SOURCE\n',
                             open(pathjoin('b', 'hello')).read())

    def test_pull_show_base_working_tree_only(self):
        """--show-base only allowed if there's a working tree

        see https://bugs.launchpad.net/bzr/+bug/202374"""
        # create a branch, see that --show-base fails
        self.make_branch('from')
        self.make_branch('to')
        out=self.run_bzr(['pull','-d','to','from','--show-base'],retcode=3)
        self.assertEqual(out,
                         ('','bzr: ERROR: Need working tree for --show-base.\n'))


