# Copyright (C) 2006-2010 Canonical Ltd
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

"""Tests for weave repositories.

For interface tests see tests/per_repository/*.py.

"""

from stat import S_ISDIR
import sys

from bzrlib.bzrdir import (
    BzrDirMetaFormat1,
    )
from bzrlib.errors import (
    IllegalPath,
    NoSuchFile,
    )
from bzrlib.repository import (
    InterRepository,
    Repository,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    )

from bzrlib.plugins.weave_fmt.bzrdir import (
    BzrDirFormat6,
    )
from bzrlib.plugins.weave_fmt.repository import (
    InterWeaveRepo,
    RepositoryFormat4,
    RepositoryFormat5,
    RepositoryFormat6,
    RepositoryFormat7,
    )


class TestFormat6(TestCaseWithTransport):

    def test_attribute__fetch_order(self):
        """Weaves need topological data insertion."""
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertEqual('topological', repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Weaves do not reuse deltas."""
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertEqual(False, repo._format._fetch_uses_deltas)

    def test_attribute__fetch_reconcile(self):
        """Weave repositories need a reconcile after fetch."""
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertEqual(True, repo._format._fetch_reconcile)

    def test_no_ancestry_weave(self):
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        # We no longer need to create the ancestry.weave file
        # since it is *never* used.
        self.assertRaises(NoSuchFile,
                          control.transport.get,
                          'ancestry.weave')

    def test_supports_external_lookups(self):
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertFalse(repo._format.supports_external_lookups)




class TestFormat7(TestCaseWithTransport):

    def test_attribute__fetch_order(self):
        """Weaves need topological data insertion."""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertEqual('topological', repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Weaves do not reuse deltas."""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertEqual(False, repo._format._fetch_uses_deltas)

    def test_attribute__fetch_reconcile(self):
        """Weave repositories need a reconcile after fetch."""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertEqual(True, repo._format._fetch_reconcile)

    def test_disk_layout(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        # we want:
        # format 'Bazaar-NG Repository format 7'
        # lock ''
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        t = control.get_repository_transport(None)
        self.assertEqualDiff('Bazaar-NG Repository format 7',
                             t.get('format').read())
        self.assertTrue(S_ISDIR(t.stat('revision-store').st_mode))
        self.assertTrue(S_ISDIR(t.stat('weaves').st_mode))
        self.assertEqualDiff('# bzr weave file v5\n'
                             'w\n'
                             'W\n',
                             t.get('inventory.weave').read())
        # Creating a file with id Foo:Bar results in a non-escaped file name on
        # disk.
        control.create_branch()
        tree = control.create_workingtree()
        tree.add(['foo'], ['Foo:Bar'], ['file'])
        tree.put_file_bytes_non_atomic('Foo:Bar', 'content\n')
        try:
            tree.commit('first post', rev_id='first')
        except IllegalPath:
            if sys.platform != 'win32':
                raise
            self.knownFailure('Foo:Bar cannot be used as a file-id on windows'
                              ' in repo format 7')
            return
        self.assertEqualDiff(
            '# bzr weave file v5\n'
            'i\n'
            '1 7fe70820e08a1aac0ef224d9c66ab66831cc4ab1\n'
            'n first\n'
            '\n'
            'w\n'
            '{ 0\n'
            '. content\n'
            '}\n'
            'W\n',
            t.get('weaves/74/Foo%3ABar.weave').read())

    def test_shared_disk_layout(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control, shared=True)
        # we want:
        # format 'Bazaar-NG Repository format 7'
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        # lock is not present when unlocked
        t = control.get_repository_transport(None)
        self.assertEqualDiff('Bazaar-NG Repository format 7',
                             t.get('format').read())
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.assertTrue(S_ISDIR(t.stat('revision-store').st_mode))
        self.assertTrue(S_ISDIR(t.stat('weaves').st_mode))
        self.assertEqualDiff('# bzr weave file v5\n'
                             'w\n'
                             'W\n',
                             t.get('inventory.weave').read())
        self.assertFalse(t.has('branch-lock'))

    def test_creates_lockdir(self):
        """Make sure it appears to be controlled by a LockDir existence"""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control, shared=True)
        t = control.get_repository_transport(None)
        # TODO: Should check there is a 'lock' toplevel directory,
        # regardless of contents
        self.assertFalse(t.has('lock/held/info'))
        repo.lock_write()
        try:
            self.assertTrue(t.has('lock/held/info'))
        finally:
            # unlock so we don't get a warning about failing to do so
            repo.unlock()

    def test_uses_lockdir(self):
        """repo format 7 actually locks on lockdir"""
        base_url = self.get_url()
        control = BzrDirMetaFormat1().initialize(base_url)
        repo = RepositoryFormat7().initialize(control, shared=True)
        t = control.get_repository_transport(None)
        repo.lock_write()
        repo.unlock()
        del repo
        # make sure the same lock is created by opening it
        repo = Repository.open(base_url)
        repo.lock_write()
        self.assertTrue(t.has('lock/held/info'))
        repo.unlock()
        self.assertFalse(t.has('lock/held/info'))

    def test_shared_no_tree_disk_layout(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control, shared=True)
        repo.set_make_working_trees(False)
        # we want:
        # format 'Bazaar-NG Repository format 7'
        # lock ''
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = control.get_repository_transport(None)
        self.assertEqualDiff('Bazaar-NG Repository format 7',
                             t.get('format').read())
        ## self.assertEqualDiff('', t.get('lock').read())
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.assertEqualDiff('', t.get('no-working-trees').read())
        repo.set_make_working_trees(True)
        self.assertFalse(t.has('no-working-trees'))
        self.assertTrue(S_ISDIR(t.stat('revision-store').st_mode))
        self.assertTrue(S_ISDIR(t.stat('weaves').st_mode))
        self.assertEqualDiff('# bzr weave file v5\n'
                             'w\n'
                             'W\n',
                             t.get('inventory.weave').read())

    def test_supports_external_lookups(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertFalse(repo._format.supports_external_lookups)


class TestInterWeaveRepo(TestCaseWithTransport):

    def test_is_compatible_and_registered(self):
        # InterWeaveRepo is compatible when either side
        # is a format 5/6/7 branch
        from bzrlib.repofmt import knitrepo
        formats = [RepositoryFormat5(),
                   RepositoryFormat6(),
                   RepositoryFormat7()]
        incompatible_formats = [RepositoryFormat4(),
                                knitrepo.RepositoryFormatKnit1(),
                                ]
        repo_a = self.make_repository('a')
        repo_b = self.make_repository('b')
        is_compatible = InterWeaveRepo.is_compatible
        for source in incompatible_formats:
            # force incompatible left then right
            repo_a._format = source
            repo_b._format = formats[0]
            self.assertFalse(is_compatible(repo_a, repo_b))
            self.assertFalse(is_compatible(repo_b, repo_a))
        for source in formats:
            repo_a._format = source
            for target in formats:
                repo_b._format = target
                self.assertTrue(is_compatible(repo_a, repo_b))
        self.assertEqual(InterWeaveRepo,
                         InterRepository.get(repo_a, repo_b).__class__)


def load_tests(basic_tests, module, loader):
    from bzrlib import tests
    from bzrlib.tests.per_repository import (
        formats_to_scenarios,
        per_repository_tests,
        )
    legacy_formats = [RepositoryFormat4(), RepositoryFormat5(), RepositoryFormat6()]
    scenarios = formats_to_scenarios([('', format) for format in legacy_formats],
        tests.default_transport, None)
    tests.multiply_tests(per_repository_tests(loader), scenarios, basic_tests)
    return basic_tests
