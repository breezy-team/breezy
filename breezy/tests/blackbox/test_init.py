# Copyright (C) 2006-2011 Canonical Ltd
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


"""Test 'brz init'"""

import os
import re

from breezy import (
    branch as _mod_branch,
    config as _mod_config,
    osutils,
    urlutils,
    )
from breezy.bzr.bzrdir import BzrDirMetaFormat1
from breezy.tests import TestSkipped
from breezy.tests import TestCaseWithTransport
from breezy.tests.test_sftp_transport import TestCaseWithSFTPServer
from breezy.workingtree import WorkingTree


class TestInit(TestCaseWithTransport):

    def setUp(self):
        super(TestInit, self).setUp()
        self._default_label = '2a'

    def test_init_with_format(self):
        # Verify brz init --format constructs something plausible
        t = self.get_transport()
        self.run_bzr('init --format default')
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)

    def test_init_format_2a(self):
        """Smoke test for constructing a format 2a repository."""
        out, err = self.run_bzr('init --format=2a')
        self.assertEqual("""Created a standalone tree (format: 2a)\n""",
                         out)
        self.assertEqual('', err)

    def test_init_format_bzr(self):
        """Smoke test for constructing a format with the 'bzr' alias."""
        out, err = self.run_bzr('init --format=bzr')
        self.assertEqual(
            "Created a standalone tree (format: %s)\n" % self._default_label,
            out)
        self.assertEqual('', err)

    def test_init_colocated(self):
        """Smoke test for constructing a colocated branch."""
        out, err = self.run_bzr(
            'init --format=development-colo file:,branch=abranch')
        self.assertEqual("""Created a standalone tree (format: development-colo)\n""",
                         out)
        self.assertEqual('', err)
        out, err = self.run_bzr('branches')
        self.assertEqual("  abranch\n", out)
        self.assertEqual('', err)

    def test_init_at_repository_root(self):
        # brz init at the root of a repository should create a branch
        # and working tree even when creation of working trees is disabled.
        t = self.get_transport()
        t.mkdir('repo')
        format = BzrDirMetaFormat1()
        newdir = format.initialize(t.abspath('repo'))
        repo = newdir.create_repository(shared=True)
        repo.set_make_working_trees(False)
        out, err = self.run_bzr('init repo')
        self.assertEqual("""Created a repository tree (format: %s)
Using shared repository: %s
""" % (self._default_label, urlutils.local_path_from_url(
            repo.controldir.root_transport.external_url())), out)
        cwd = osutils.getcwd()
        self.assertEndsWith(out, cwd + '/repo/\n')
        self.assertEqual('', err)
        newdir.open_branch()
        newdir.open_workingtree()

    def test_init_branch(self):
        out, err = self.run_bzr('init')
        self.assertEqual("Created a standalone tree (format: %s)\n" % (
            self._default_label,), out)
        self.assertEqual('', err)

        # Can it handle subdirectories of branches too ?
        out, err = self.run_bzr('init subdir1')
        self.assertEqual("Created a standalone tree (format: %s)\n" % (
            self._default_label,), out)
        self.assertEqual('', err)
        WorkingTree.open('subdir1')

        self.run_bzr_error(['Parent directory of subdir2/nothere does not exist'],
                           'init subdir2/nothere')
        out, err = self.run_bzr('init subdir2/nothere', retcode=3)
        self.assertEqual('', out)

        os.mkdir('subdir2')
        out, err = self.run_bzr('init subdir2')
        self.assertEqual("Created a standalone tree (format: %s)\n" % (
            self._default_label,), out)
        self.assertEqual('', err)
        # init an existing branch.
        out, err = self.run_bzr('init subdir2', retcode=3)
        self.assertEqual('', out)
        self.assertTrue(err.startswith('brz: ERROR: Already a branch:'))

    def test_init_branch_quiet(self):
        out, err = self.run_bzr('init -q')
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_init_existing_branch(self):
        self.run_bzr('init')
        out, err = self.run_bzr('init', retcode=3)
        self.assertContainsRe(err, 'Already a branch')
        # don't suggest making a checkout, there's already a working tree
        self.assertFalse(re.search(r'checkout', err))

    def test_init_existing_without_workingtree(self):
        # make a repository
        repo = self.make_repository('.', shared=True)
        repo.set_make_working_trees(False)
        # make a branch; by default without a working tree
        self.run_bzr('init subdir')
        # fail
        out, err = self.run_bzr('init subdir', retcode=3)
        # suggests using checkout
        self.assertContainsRe(err,
                              'ontains a branch.*but no working tree.*checkout')

    def test_no_defaults(self):
        """Init creates no default ignore rules."""
        self.run_bzr('init')
        self.assertFalse(os.path.exists('.bzrignore'))

    def test_init_unicode(self):
        # Make sure getcwd can handle unicode filenames
        try:
            os.mkdir(u'mu-\xb5')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")
        # try to init unicode dir
        self.run_bzr(['init', '-q', u'mu-\xb5'])

    def create_simple_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add(['a'], ids=[b'a-id'])
        tree.commit('one', rev_id=b'r1')
        return tree

    def test_init_create_prefix(self):
        """'brz init --create-prefix; will create leading directories."""
        tree = self.create_simple_tree()

        self.run_bzr_error(['Parent directory of ../new/tree does not exist'],
                           'init ../new/tree', working_dir='tree')
        self.run_bzr('init ../new/tree --create-prefix', working_dir='tree')
        self.assertPathExists('new/tree/.bzr')

    def test_init_default_format_option(self):
        """brz init should read default format from option default_format"""
        g_store = _mod_config.GlobalStore()
        g_store._load_from_string(b'''
[DEFAULT]
default_format = 1.9
''')
        g_store.save()
        out, err = self.run_brz_subprocess('init')
        self.assertContainsRe(out, b'1.9')

    def test_init_no_tree(self):
        """'brz init --no-tree' creates a branch with no working tree."""
        out, err = self.run_bzr('init --no-tree')
        self.assertStartsWith(out, 'Created a standalone branch')


class TestSFTPInit(TestCaseWithSFTPServer):

    def test_init(self):
        # init on a remote url should succeed.
        out, err = self.run_bzr(['init', '--format=pack-0.92', self.get_url()])
        self.assertEqual(out,
                         """Created a standalone branch (format: pack-0.92)\n""")

    def test_init_existing_branch(self):
        # when there is already a branch present, make mention
        self.make_branch('.')

        # rely on SFTPServer get_url() pointing at '.'
        out, err = self.run_bzr_error(['Already a branch'],
                                      ['init', self.get_url()])

        # make sure using 'brz checkout' is not suggested
        # for remote locations missing a working tree
        self.assertFalse(re.search(r'use brz checkout', err))

    def test_init_existing_branch_with_workingtree(self):
        # don't distinguish between the branch having a working tree or not
        # when the branch itself is remote.
        self.make_branch_and_tree('.')

        # rely on SFTPServer get_url() pointing at '.'
        self.run_bzr_error(['Already a branch'], ['init', self.get_url()])

    def test_init_append_revisions_only(self):
        self.run_bzr('init --format=dirstate-tags normal_branch6')
        branch = _mod_branch.Branch.open('normal_branch6')
        self.assertEqual(None, branch.get_append_revisions_only())
        self.run_bzr(
            'init --append-revisions-only --format=dirstate-tags branch6')
        branch = _mod_branch.Branch.open('branch6')
        self.assertEqual(True, branch.get_append_revisions_only())
        self.run_bzr_error(['cannot be set to append-revisions-only'],
                           'init --append-revisions-only --format=knit knit')

    def test_init_without_username(self):
        """Ensure init works if username is not set.
        """
        # brz makes user specified whoami mandatory for operations
        # like commit as whoami is recorded. init however is not so final
        # and uses whoami only in a lock file. Without whoami the login name
        # is used. This test is to ensure that init passes even when whoami
        # is not available.
        self.overrideEnv('EMAIL', None)
        self.overrideEnv('BRZ_EMAIL', None)
        out, err = self.run_bzr(['init', 'foo'])
        self.assertEqual(err, '')
        self.assertTrue(os.path.exists('foo'))
