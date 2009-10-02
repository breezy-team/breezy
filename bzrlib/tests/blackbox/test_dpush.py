# Copyright (C) 2005, 2007, 2008, 2009 Canonical Ltd
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


"""Black-box tests for bzr dpush."""


import os

from bzrlib import (
    branch,
    bzrdir,
    foreign,
    tests,
    workingtree,
    )
from bzrlib.tests import (
    blackbox,
    test_foreign,
    )


def load_tests(standard_tests, module, loader):
    """Multiply tests for the dpush command."""
    result = loader.suiteClass()

    # one for each king of change
    changes_tests, remaining_tests = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance((
                TestDpushStrictWithChanges,
                )))
    changes_scenarios = [
        ('uncommitted',
         dict(_changes_type= '_uncommitted_changes')),
        ('pending-merges',
         dict(_changes_type= '_pending_merges')),
        ('out-of-sync-trees',
         dict(_changes_type= '_out_of_sync_trees')),
        ]
    tests.multiply_tests(changes_tests, changes_scenarios, result)
    # No parametrization for the remaining tests
    result.addTests(remaining_tests)

    return result


class TestDpush(blackbox.ExternalBase):

    def setUp(self):
        bzrdir.BzrDirFormat.register_control_format(
            test_foreign.DummyForeignVcsDirFormat)
        branch.InterBranch.register_optimiser(
            test_foreign.InterToDummyVcsBranch)
        self.addCleanup(self.unregister_format)
        super(TestDpush, self).setUp()

    def unregister_format(self):
        try:
            bzrdir.BzrDirFormat.unregister_control_format(
                test_foreign.DummyForeignVcsDirFormat)
        except ValueError:
            pass
        branch.InterBranch.unregister_optimiser(
            test_foreign.InterToDummyVcsBranch)

    def make_dummy_builder(self, relpath):
        builder = self.make_branch_builder(
            relpath, format=test_foreign.DummyForeignVcsDirFormat())
        builder.build_snapshot('revid', None,
            [('add', ('', 'TREE_ROOT', 'directory', None)),
             ('add', ('foo', 'fooid', 'file', 'bar'))])
        return builder

    def test_dpush_native(self):
        target_tree = self.make_branch_and_tree("dp")
        source_tree = self.make_branch_and_tree("dc")
        output, error = self.run_bzr("dpush -d dc dp", retcode=3)
        self.assertEquals("", output)
        self.assertContainsRe(error, 'in the same VCS, lossy push not necessary. Please use regular push.')

    def test_dpush(self):
        branch = self.make_dummy_builder('d').get_branch()

        dc = branch.bzrdir.sprout('dc', force_new_repo=True)
        self.build_tree(("dc/foo", "blaaaa"))
        dc.open_workingtree().commit('msg')

        output, error = self.run_bzr("dpush -d dc d")
        self.assertEquals(error, "Pushed up to revision 2.\n")
        self.check_output("", "status dc")

    def test_dpush_new(self):
        b = self.make_dummy_builder('d').get_branch()

        dc = b.bzrdir.sprout('dc', force_new_repo=True)
        self.build_tree_contents([("dc/foofile", "blaaaa")])
        dc_tree = dc.open_workingtree()
        dc_tree.add("foofile")
        dc_tree.commit("msg")

        self.check_output("", "dpush -d dc d")
        self.check_output("2\n", "revno dc")
        self.check_output("", "status dc")

    def test_dpush_wt_diff(self):
        b = self.make_dummy_builder('d').get_branch()

        dc = b.bzrdir.sprout('dc', force_new_repo=True)
        self.build_tree_contents([("dc/foofile", "blaaaa")])
        dc_tree = dc.open_workingtree()
        dc_tree.add("foofile")
        newrevid = dc_tree.commit('msg')

        self.build_tree_contents([("dc/foofile", "blaaaal")])
        self.check_output("", "dpush -d dc d")
        self.assertFileEqual("blaaaal", "dc/foofile")
        self.check_output('modified:\n  foofile\n', "status dc")

    def test_diverged(self):
        builder = self.make_dummy_builder('d')

        b = builder.get_branch()

        dc = b.bzrdir.sprout('dc', force_new_repo=True)
        dc_tree = dc.open_workingtree()

        self.build_tree_contents([("dc/foo", "bar")])
        dc_tree.commit('msg1')

        builder.build_snapshot('revid2', None,
          [('modify', ('fooid', 'blie'))])

        output, error = self.run_bzr("dpush -d dc d", retcode=3)
        self.assertEquals(output, "")
        self.assertContainsRe(error, "have diverged")


class TestDpushStrictMixin(object):

    # FIXME: setUp and unregister_format needs to be dedupe from TestDpush
    # (made into functions in test_foreign ?).
    def setUp(self):
        bzrdir.BzrDirFormat.register_control_format(
            test_foreign.DummyForeignVcsDirFormat)
        branch.InterBranch.register_optimiser(
            test_foreign.InterToDummyVcsBranch)
        self.addCleanup(self.unregister_format)

    def unregister_format(self):
        try:
            bzrdir.BzrDirFormat.unregister_control_format(
                test_foreign.DummyForeignVcsDirFormat)
        except ValueError:
            pass
        branch.InterBranch.unregister_optimiser(
            test_foreign.InterToDummyVcsBranch)

    def make_local_branch_and_tree(self):
        self.tree = self.make_branch_and_tree('local')
        self.build_tree_contents([('local/file', 'initial')])
        self.tree.add('file')
        self.tree.commit('adding file', rev_id='added')
        self.build_tree_contents([('local/file', 'modified')])
        self.tree.commit('modify file', rev_id='modified')

    def make_foreign_branch(self, relpath='to'):
        # Create an empty branch where we will be able to push
        self.foreign = self.make_branch(
            relpath, format=test_foreign.DummyForeignVcsDirFormat())

    def set_config_dpush_strict(self, value):
        # set config var (any of bazaar.conf, locations.conf, branch.conf
        # should do)
        conf = self.tree.branch.get_config()
        conf.set_user_option('dpush_strict', value)

    _default_command = ['dpush', '../to']
    _default_wd = 'local'
    _default_errors = ['Working tree ".*/local/" has uncommitted '
                       'changes \(See bzr status\)\.',]
    _default_dpushed_revid = 'modified'

    def assertDpushFails(self, args):
        self.run_bzr_error(self._default_errors, self._default_command + args,
                           working_dir=self._default_wd, retcode=3)

    def assertDpushSucceeds(self, args, pushed_revid=None):
        self.run_bzr(self._default_command + args,
                     working_dir=self._default_wd)
        if pushed_revid is None:
            # dpush change the revids, so we need to get back to it
            branch_from = branch.Branch.open(self._default_wd)
            pushed_revid = branch_from.last_revision()
        branch_to = branch.Branch.open('to')
        repo_to = branch_to.repository
        self.assertTrue(repo_to.has_revision(pushed_revid))
        self.assertEqual(branch_to.last_revision(), pushed_revid)



class TestDpushStrictWithoutChanges(tests.TestCaseWithTransport,
                                    TestDpushStrictMixin):

    def setUp(self):
        super(TestDpushStrictWithoutChanges, self).setUp()
        TestDpushStrictMixin.setUp(self)
        self.make_local_branch_and_tree()
        self.make_foreign_branch()

    def test_dpush_default(self):
        self.assertDpushSucceeds([])

    def test_dpush_strict(self):
        self.assertDpushSucceeds(['--strict'])

    def test_dpush_no_strict(self):
        self.assertDpushSucceeds(['--no-strict'])

    def test_dpush_config_var_strict(self):
        self.set_config_dpush_strict('true')
        self.assertDpushSucceeds([])

    def test_dpush_config_var_no_strict(self):
        self.set_config_dpush_strict('false')
        self.assertDpushSucceeds([])


class TestDpushStrictWithChanges(tests.TestCaseWithTransport,
                                 TestDpushStrictMixin):

    _changes_type = None # Set by load_tests

    def setUp(self):
        super(TestDpushStrictWithChanges, self).setUp()
        TestDpushStrictMixin.setUp(self)
        # Apply the changes defined in load_tests: one of _uncommitted_changes,
        # _pending_merges or _out_of_sync_trees
        getattr(self, self._changes_type)()
        self.make_foreign_branch()

    def _uncommitted_changes(self):
        self.make_local_branch_and_tree()
        # Make a change without committing it
        self.build_tree_contents([('local/file', 'in progress')])

    def _pending_merges(self):
        self.make_local_branch_and_tree()
        # Create 'other' branch containing a new file
        other_bzrdir = self.tree.bzrdir.sprout('other')
        other_tree = other_bzrdir.open_workingtree()
        self.build_tree_contents([('other/other-file', 'other')])
        other_tree.add('other-file')
        other_tree.commit('other commit', rev_id='other')
        # Merge and revert, leaving a pending merge
        self.tree.merge_from_branch(other_tree.branch)
        self.tree.revert(filenames=['other-file'], backups=False)

    def _out_of_sync_trees(self):
        self.make_local_branch_and_tree()
        self.run_bzr(['checkout', '--lightweight', 'local', 'checkout'])
        # Make a change and commit it
        self.build_tree_contents([('local/file', 'modified in local')])
        self.tree.commit('modify file', rev_id='modified-in-local')
        # Exercise commands from the checkout directory
        self._default_wd = 'checkout'
        self._default_errors = ["Working tree is out of date, please run"
                                " 'bzr update'\.",]
        self._default_dpushed_revid = 'modified-in-local'

    def test_dpush_default(self):
        self.assertDpushFails([])

    def test_dpush_no_strict(self):
        self.assertDpushSucceeds(['--no-strict'])

    def test_dpush_strict_with_changes(self):
        self.assertDpushFails(['--strict'])

    def test_dpush_respect_config_var_strict(self):
        self.set_config_dpush_strict('true')
        self.assertDpushFails([])

    def test_dpush_bogus_config_var_ignored(self):
        self.set_config_dpush_strict("I don't want you to be strict")
        self.assertDpushFails([])

    def test_dpush_no_strict_command_line_override_config(self):
        self.set_config_dpush_strict('yES')
        self.assertDpushFails([])
        self.assertDpushSucceeds(['--no-strict'])

    def test_dpush_strict_command_line_override_config(self):
        self.set_config_dpush_strict('oFF')
        self.assertDpushFails(['--strict'])
        self.assertDpushSucceeds([])
