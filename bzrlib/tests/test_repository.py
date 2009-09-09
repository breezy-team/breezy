# Copyright (C) 2006, 2007, 2008, 2009 Canonical Ltd
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

"""Tests for the Repository facility that are not interface tests.

For interface tests see tests/per_repository/*.py.

For concrete class tests see this file, and for storage formats tests
also see this file.
"""

from stat import S_ISDIR
from StringIO import StringIO

import bzrlib
from bzrlib.errors import (NotBranchError,
                           NoSuchFile,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )
from bzrlib import (
    graph,
    tests,
    )
from bzrlib.branchbuilder import BranchBuilder
from bzrlib.btree_index import BTreeBuilder, BTreeGraphIndex
from bzrlib.index import GraphIndex, InMemoryGraphIndex
from bzrlib.repository import RepositoryFormat
from bzrlib.smart import server
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    TestSkipped,
    test_knit,
    )
from bzrlib.transport import (
    fakenfs,
    get_transport,
    )
from bzrlib.transport.memory import MemoryServer
from bzrlib import (
    bencode,
    bzrdir,
    errors,
    inventory,
    osutils,
    progress,
    repository,
    revision as _mod_revision,
    symbol_versioning,
    upgrade,
    workingtree,
    )
from bzrlib.repofmt import (
    groupcompress_repo,
    knitrepo,
    pack_repo,
    weaverepo,
    )


class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_default = bzrdir.format_registry.get('default')
        private_default = old_default().repository_format.__class__
        old_format = repository.RepositoryFormat.get_default_format()
        self.assertTrue(isinstance(old_format, private_default))
        def make_sample_bzrdir():
            my_bzrdir = bzrdir.BzrDirMetaFormat1()
            my_bzrdir.repository_format = SampleRepositoryFormat()
            return my_bzrdir
        bzrdir.format_registry.remove('default')
        bzrdir.format_registry.register('sample', make_sample_bzrdir, '')
        bzrdir.format_registry.set_default('sample')
        # creating a repository should now create an instrumented dir.
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize('memory:///')
            result = dir.create_repository()
            self.assertEqual(result, 'A bzr repository dir')
        finally:
            bzrdir.format_registry.remove('default')
            bzrdir.format_registry.remove('sample')
            bzrdir.format_registry.register('default', old_default, '')
        self.assertIsInstance(repository.RepositoryFormat.get_default_format(),
                              old_format.__class__)


class SampleRepositoryFormat(repository.RepositoryFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the
    open and open(unsupported=True) routines.
    """

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Sample .bzr repository format."

    def initialize(self, a_bzrdir, shared=False):
        """Initialize a repository in a BzrDir"""
        t = a_bzrdir.get_repository_transport(self)
        t.put_bytes('format', self.get_format_string())
        return 'A bzr repository dir'

    def is_supported(self):
        return False

    def open(self, a_bzrdir, _found=False):
        return "opened repository."


class TestRepositoryFormat(TestCaseWithTransport):
    """Tests for the Repository format detection used by the bzr meta dir facility.BzrBranchFormat facility."""

    def test_find_format(self):
        # is the right format object found for a repository?
        # create a branch with a few known format objects.
        # this is not quite the same as
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            format.initialize(dir)
            t = get_transport(url)
            found_format = repository.RepositoryFormat.find_format(dir)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(weaverepo.RepositoryFormat7(), "bar")

    def test_find_format_no_repository(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        self.assertRaises(errors.NoRepositoryPresent,
                          repository.RepositoryFormat.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        SampleRepositoryFormat().initialize(dir)
        self.assertRaises(UnknownFormatError,
                          repository.RepositoryFormat.find_format,
                          dir)

    def test_register_unregister_format(self):
        format = SampleRepositoryFormat()
        # make a control dir
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        # make a repo
        format.initialize(dir)
        # register a format for it.
        repository.RepositoryFormat.register_format(format)
        # which repository.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, repository.Repository.open, self.get_url())
        # but open(unsupported) will work
        self.assertEqual(format.open(dir), "opened repository.")
        # unregister the format
        repository.RepositoryFormat.unregister_format(format)


class TestFormat6(TestCaseWithTransport):

    def test_attribute__fetch_order(self):
        """Weaves need topological data insertion."""
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat6().initialize(control)
        self.assertEqual('topological', repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Weaves do not reuse deltas."""
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat6().initialize(control)
        self.assertEqual(False, repo._format._fetch_uses_deltas)

    def test_attribute__fetch_reconcile(self):
        """Weave repositories need a reconcile after fetch."""
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat6().initialize(control)
        self.assertEqual(True, repo._format._fetch_reconcile)

    def test_no_ancestry_weave(self):
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat6().initialize(control)
        # We no longer need to create the ancestry.weave file
        # since it is *never* used.
        self.assertRaises(NoSuchFile,
                          control.transport.get,
                          'ancestry.weave')

    def test_supports_external_lookups(self):
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat6().initialize(control)
        self.assertFalse(repo._format.supports_external_lookups)


class TestFormat7(TestCaseWithTransport):

    def test_attribute__fetch_order(self):
        """Weaves need topological data insertion."""
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control)
        self.assertEqual('topological', repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Weaves do not reuse deltas."""
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control)
        self.assertEqual(False, repo._format._fetch_uses_deltas)

    def test_attribute__fetch_reconcile(self):
        """Weave repositories need a reconcile after fetch."""
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control)
        self.assertEqual(True, repo._format._fetch_reconcile)

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control)
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
        tree.commit('first post', rev_id='first')
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
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control, shared=True)
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
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control, shared=True)
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
        control = bzrdir.BzrDirMetaFormat1().initialize(base_url)
        repo = weaverepo.RepositoryFormat7().initialize(control, shared=True)
        t = control.get_repository_transport(None)
        repo.lock_write()
        repo.unlock()
        del repo
        # make sure the same lock is created by opening it
        repo = repository.Repository.open(base_url)
        repo.lock_write()
        self.assertTrue(t.has('lock/held/info'))
        repo.unlock()
        self.assertFalse(t.has('lock/held/info'))

    def test_shared_no_tree_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control, shared=True)
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
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control)
        self.assertFalse(repo._format.supports_external_lookups)


class TestFormatKnit1(TestCaseWithTransport):

    def test_attribute__fetch_order(self):
        """Knits need topological data insertion."""
        repo = self.make_repository('.',
                format=bzrdir.format_registry.get('knit')())
        self.assertEqual('topological', repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Knits reuse deltas."""
        repo = self.make_repository('.',
                format=bzrdir.format_registry.get('knit')())
        self.assertEqual(True, repo._format._fetch_uses_deltas)

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = knitrepo.RepositoryFormatKnit1().initialize(control)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock: is a directory
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        t = control.get_repository_transport(None)
        self.assertEqualDiff('Bazaar-NG Knit Repository Format 1',
                             t.get('format').read())
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.assertTrue(S_ISDIR(t.stat('knits').st_mode))
        self.check_knits(t)
        # Check per-file knits.
        branch = control.create_branch()
        tree = control.create_workingtree()
        tree.add(['foo'], ['Nasty-IdC:'], ['file'])
        tree.put_file_bytes_non_atomic('Nasty-IdC:', '')
        tree.commit('1st post', rev_id='foo')
        self.assertHasKnit(t, 'knits/e8/%254easty-%2549d%2543%253a',
            '\nfoo fulltext 0 81  :')

    def assertHasKnit(self, t, knit_name, extra_content=''):
        """Assert that knit_name exists on t."""
        self.assertEqualDiff('# bzr knit index 8\n' + extra_content,
                             t.get(knit_name + '.kndx').read())

    def check_knits(self, t):
        """check knit content for a repository."""
        self.assertHasKnit(t, 'inventory')
        self.assertHasKnit(t, 'revisions')
        self.assertHasKnit(t, 'signatures')

    def test_shared_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = knitrepo.RepositoryFormatKnit1().initialize(control, shared=True)
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock: is a directory
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = control.get_repository_transport(None)
        self.assertEqualDiff('Bazaar-NG Knit Repository Format 1',
                             t.get('format').read())
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.assertTrue(S_ISDIR(t.stat('knits').st_mode))
        self.check_knits(t)

    def test_shared_no_tree_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = knitrepo.RepositoryFormatKnit1().initialize(control, shared=True)
        repo.set_make_working_trees(False)
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock ''
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = control.get_repository_transport(None)
        self.assertEqualDiff('Bazaar-NG Knit Repository Format 1',
                             t.get('format').read())
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.assertEqualDiff('', t.get('no-working-trees').read())
        repo.set_make_working_trees(True)
        self.assertFalse(t.has('no-working-trees'))
        self.assertTrue(S_ISDIR(t.stat('knits').st_mode))
        self.check_knits(t)

    def test_deserialise_sets_root_revision(self):
        """We must have a inventory.root.revision

        Old versions of the XML5 serializer did not set the revision_id for
        the whole inventory. So we grab the one from the expected text. Which
        is valid when the api is not being abused.
        """
        repo = self.make_repository('.',
                format=bzrdir.format_registry.get('knit')())
        inv_xml = '<inventory format="5">\n</inventory>\n'
        inv = repo.deserialise_inventory('test-rev-id', inv_xml)
        self.assertEqual('test-rev-id', inv.root.revision)

    def test_deserialise_uses_global_revision_id(self):
        """If it is set, then we re-use the global revision id"""
        repo = self.make_repository('.',
                format=bzrdir.format_registry.get('knit')())
        inv_xml = ('<inventory format="5" revision_id="other-rev-id">\n'
                   '</inventory>\n')
        # Arguably, the deserialise_inventory should detect a mismatch, and
        # raise an error, rather than silently using one revision_id over the
        # other.
        self.assertRaises(AssertionError, repo.deserialise_inventory,
            'test-rev-id', inv_xml)
        inv = repo.deserialise_inventory('other-rev-id', inv_xml)
        self.assertEqual('other-rev-id', inv.root.revision)

    def test_supports_external_lookups(self):
        repo = self.make_repository('.',
                format=bzrdir.format_registry.get('knit')())
        self.assertFalse(repo._format.supports_external_lookups)


class DummyRepository(object):
    """A dummy repository for testing."""

    _format = None
    _serializer = None

    def supports_rich_root(self):
        if self._format is not None:
            return self._format.rich_root_data
        return False

    def get_graph(self):
        raise NotImplementedError

    def get_parent_map(self, revision_ids):
        raise NotImplementedError


class InterDummy(repository.InterRepository):
    """An inter-repository optimised code path for DummyRepository.

    This is for use during testing where we use DummyRepository as repositories
    so that none of the default regsitered inter-repository classes will
    MATCH.
    """

    @staticmethod
    def is_compatible(repo_source, repo_target):
        """InterDummy is compatible with DummyRepository."""
        return (isinstance(repo_source, DummyRepository) and
            isinstance(repo_target, DummyRepository))


class TestInterRepository(TestCaseWithTransport):

    def test_get_default_inter_repository(self):
        # test that the InterRepository.get(repo_a, repo_b) probes
        # for a inter_repo class where is_compatible(repo_a, repo_b) returns
        # true and returns a default inter_repo otherwise.
        # This also tests that the default registered optimised interrepository
        # classes do not barf inappropriately when a surprising repository type
        # is handed to them.
        dummy_a = DummyRepository()
        dummy_b = DummyRepository()
        self.assertGetsDefaultInterRepository(dummy_a, dummy_b)

    def assertGetsDefaultInterRepository(self, repo_a, repo_b):
        """Asserts that InterRepository.get(repo_a, repo_b) -> the default.

        The effective default is now InterSameDataRepository because there is
        no actual sane default in the presence of incompatible data models.
        """
        inter_repo = repository.InterRepository.get(repo_a, repo_b)
        self.assertEqual(repository.InterSameDataRepository,
                         inter_repo.__class__)
        self.assertEqual(repo_a, inter_repo.source)
        self.assertEqual(repo_b, inter_repo.target)

    def test_register_inter_repository_class(self):
        # test that a optimised code path provider - a
        # InterRepository subclass can be registered and unregistered
        # and that it is correctly selected when given a repository
        # pair that it returns true on for the is_compatible static method
        # check
        dummy_a = DummyRepository()
        dummy_a._format = RepositoryFormat()
        dummy_b = DummyRepository()
        dummy_b._format = RepositoryFormat()
        repo = self.make_repository('.')
        # hack dummies to look like repo somewhat.
        dummy_a._serializer = repo._serializer
        dummy_a._format.supports_tree_reference = repo._format.supports_tree_reference
        dummy_a._format.rich_root_data = repo._format.rich_root_data
        dummy_b._serializer = repo._serializer
        dummy_b._format.supports_tree_reference = repo._format.supports_tree_reference
        dummy_b._format.rich_root_data = repo._format.rich_root_data
        repository.InterRepository.register_optimiser(InterDummy)
        try:
            # we should get the default for something InterDummy returns False
            # to
            self.assertFalse(InterDummy.is_compatible(dummy_a, repo))
            self.assertGetsDefaultInterRepository(dummy_a, repo)
            # and we should get an InterDummy for a pair it 'likes'
            self.assertTrue(InterDummy.is_compatible(dummy_a, dummy_b))
            inter_repo = repository.InterRepository.get(dummy_a, dummy_b)
            self.assertEqual(InterDummy, inter_repo.__class__)
            self.assertEqual(dummy_a, inter_repo.source)
            self.assertEqual(dummy_b, inter_repo.target)
        finally:
            repository.InterRepository.unregister_optimiser(InterDummy)
        # now we should get the default InterRepository object again.
        self.assertGetsDefaultInterRepository(dummy_a, dummy_b)


class TestInterWeaveRepo(TestCaseWithTransport):

    def test_is_compatible_and_registered(self):
        # InterWeaveRepo is compatible when either side
        # is a format 5/6/7 branch
        from bzrlib.repofmt import knitrepo, weaverepo
        formats = [weaverepo.RepositoryFormat5(),
                   weaverepo.RepositoryFormat6(),
                   weaverepo.RepositoryFormat7()]
        incompatible_formats = [weaverepo.RepositoryFormat4(),
                                knitrepo.RepositoryFormatKnit1(),
                                ]
        repo_a = self.make_repository('a')
        repo_b = self.make_repository('b')
        is_compatible = repository.InterWeaveRepo.is_compatible
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
        self.assertEqual(repository.InterWeaveRepo,
                         repository.InterRepository.get(repo_a,
                                                        repo_b).__class__)


class TestRepositoryConverter(TestCaseWithTransport):

    def test_convert_empty(self):
        t = get_transport(self.get_url('.'))
        t.mkdir('repository')
        repo_dir = bzrdir.BzrDirMetaFormat1().initialize('repository')
        repo = weaverepo.RepositoryFormat7().initialize(repo_dir)
        target_format = knitrepo.RepositoryFormatKnit1()
        converter = repository.CopyConverter(target_format)
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            converter.convert(repo, pb)
        finally:
            pb.finished()
        repo = repo_dir.open_repository()
        self.assertTrue(isinstance(target_format, repo._format.__class__))


class TestMisc(TestCase):

    def test_unescape_xml(self):
        """We get some kind of error when malformed entities are passed"""
        self.assertRaises(KeyError, repository._unescape_xml, 'foo&bar;')


class TestRepositoryFormatKnit3(TestCaseWithTransport):

    def test_attribute__fetch_order(self):
        """Knits need topological data insertion."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        repo = self.make_repository('.', format=format)
        self.assertEqual('topological', repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Knits reuse deltas."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        repo = self.make_repository('.', format=format)
        self.assertEqual(True, repo._format._fetch_uses_deltas)

    def test_convert(self):
        """Ensure the upgrade adds weaves for roots"""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        tree = self.make_branch_and_tree('.', format)
        tree.commit("Dull commit", rev_id="dull")
        revision_tree = tree.branch.repository.revision_tree('dull')
        revision_tree.lock_read()
        try:
            self.assertRaises(errors.NoSuchFile, revision_tree.get_file_lines,
                revision_tree.inventory.root.file_id)
        finally:
            revision_tree.unlock()
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        upgrade.Convert('.', format)
        tree = workingtree.WorkingTree.open('.')
        revision_tree = tree.branch.repository.revision_tree('dull')
        revision_tree.lock_read()
        try:
            revision_tree.get_file_lines(revision_tree.inventory.root.file_id)
        finally:
            revision_tree.unlock()
        tree.commit("Another dull commit", rev_id='dull2')
        revision_tree = tree.branch.repository.revision_tree('dull2')
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        self.assertEqual('dull', revision_tree.inventory.root.revision)

    def test_supports_external_lookups(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        repo = self.make_repository('.', format=format)
        self.assertFalse(repo._format.supports_external_lookups)


class Test2a(TestCaseWithTransport):

    def test_fetch_combines_groups(self):
        builder = self.make_branch_builder('source', format='2a')
        builder.start_series()
        builder.build_snapshot('1', None, [
            ('add', ('', 'root-id', 'directory', '')),
            ('add', ('file', 'file-id', 'file', 'content\n'))])
        builder.build_snapshot('2', ['1'], [
            ('modify', ('file-id', 'content-2\n'))])
        builder.finish_series()
        source = builder.get_branch()
        target = self.make_repository('target', format='2a')
        target.fetch(source.repository)
        target.lock_read()
        self.addCleanup(target.unlock)
        details = target.texts._index.get_build_details(
            [('file-id', '1',), ('file-id', '2',)])
        file_1_details = details[('file-id', '1')]
        file_2_details = details[('file-id', '2')]
        # The index, and what to read off disk, should be the same for both
        # versions of the file.
        self.assertEqual(file_1_details[0][:3], file_2_details[0][:3])

    def test_format_pack_compresses_True(self):
        repo = self.make_repository('repo', format='2a')
        self.assertTrue(repo._format.pack_compresses)

    def test_inventories_use_chk_map_with_parent_base_dict(self):
        tree = self.make_branch_and_tree('repo', format="2a")
        revid = tree.commit("foo")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        inv = tree.branch.repository.get_inventory(revid)
        self.assertNotEqual(None, inv.parent_id_basename_to_file_id)
        inv.parent_id_basename_to_file_id._ensure_root()
        inv.id_to_entry._ensure_root()
        self.assertEqual(65536, inv.id_to_entry._root_node.maximum_size)
        self.assertEqual(65536,
            inv.parent_id_basename_to_file_id._root_node.maximum_size)

    def test_autopack_unchanged_chk_nodes(self):
        # at 20 unchanged commits, chk pages are packed that are split into
        # two groups such that the new pack being made doesn't have all its
        # pages in the source packs (though they are in the repository).
        tree = self.make_branch_and_tree('tree', format='2a')
        for pos in range(20):
            tree.commit(str(pos))

    def test_pack_with_hint(self):
        tree = self.make_branch_and_tree('tree', format='2a')
        # 1 commit to leave untouched
        tree.commit('1')
        to_keep = tree.branch.repository._pack_collection.names()
        # 2 to combine
        tree.commit('2')
        tree.commit('3')
        all = tree.branch.repository._pack_collection.names()
        combine = list(set(all) - set(to_keep))
        self.assertLength(3, all)
        self.assertLength(2, combine)
        tree.branch.repository.pack(hint=combine)
        final = tree.branch.repository._pack_collection.names()
        self.assertLength(2, final)
        self.assertFalse(combine[0] in final)
        self.assertFalse(combine[1] in final)
        self.assertSubset(to_keep, final)

    def test_stream_source_to_gc(self):
        source = self.make_repository('source', format='2a')
        target = self.make_repository('target', format='2a')
        stream = source._get_source(target._format)
        self.assertIsInstance(stream, groupcompress_repo.GroupCHKStreamSource)

    def test_stream_source_to_non_gc(self):
        source = self.make_repository('source', format='2a')
        target = self.make_repository('target', format='rich-root-pack')
        stream = source._get_source(target._format)
        # We don't want the child GroupCHKStreamSource
        self.assertIs(type(stream), repository.StreamSource)

    def test_get_stream_for_missing_keys_includes_all_chk_refs(self):
        source_builder = self.make_branch_builder('source',
                            format='2a')
        # We have to build a fairly large tree, so that we are sure the chk
        # pages will have split into multiple pages.
        entries = [('add', ('', 'a-root-id', 'directory', None))]
        for i in 'abcdefghijklmnopqrstuvwxyz123456789':
            for j in 'abcdefghijklmnopqrstuvwxyz123456789':
                fname = i + j
                fid = fname + '-id'
                content = 'content for %s\n' % (fname,)
                entries.append(('add', (fname, fid, 'file', content)))
        source_builder.start_series()
        source_builder.build_snapshot('rev-1', None, entries)
        # Now change a few of them, so we get a few new pages for the second
        # revision
        source_builder.build_snapshot('rev-2', ['rev-1'], [
            ('modify', ('aa-id', 'new content for aa-id\n')),
            ('modify', ('cc-id', 'new content for cc-id\n')),
            ('modify', ('zz-id', 'new content for zz-id\n')),
            ])
        source_builder.finish_series()
        source_branch = source_builder.get_branch()
        source_branch.lock_read()
        self.addCleanup(source_branch.unlock)
        target = self.make_repository('target', format='2a')
        source = source_branch.repository._get_source(target._format)
        self.assertIsInstance(source, groupcompress_repo.GroupCHKStreamSource)

        # On a regular pass, getting the inventories and chk pages for rev-2
        # would only get the newly created chk pages
        search = graph.SearchResult(set(['rev-2']), set(['rev-1']), 1,
                                    set(['rev-2']))
        simple_chk_records = []
        for vf_name, substream in source.get_stream(search):
            if vf_name == 'chk_bytes':
                for record in substream:
                    simple_chk_records.append(record.key)
            else:
                for _ in substream:
                    continue
        # 3 pages, the root (InternalNode), + 2 pages which actually changed
        self.assertEqual([('sha1:91481f539e802c76542ea5e4c83ad416bf219f73',),
                          ('sha1:4ff91971043668583985aec83f4f0ab10a907d3f',),
                          ('sha1:81e7324507c5ca132eedaf2d8414ee4bb2226187',),
                          ('sha1:b101b7da280596c71a4540e9a1eeba8045985ee0',)],
                         simple_chk_records)
        # Now, when we do a similar call using 'get_stream_for_missing_keys'
        # we should get a much larger set of pages.
        missing = [('inventories', 'rev-2')]
        full_chk_records = []
        for vf_name, substream in source.get_stream_for_missing_keys(missing):
            if vf_name == 'inventories':
                for record in substream:
                    self.assertEqual(('rev-2',), record.key)
            elif vf_name == 'chk_bytes':
                for record in substream:
                    full_chk_records.append(record.key)
            else:
                self.fail('Should not be getting a stream of %s' % (vf_name,))
        # We have 257 records now. This is because we have 1 root page, and 256
        # leaf pages in a complete listing.
        self.assertEqual(257, len(full_chk_records))
        self.assertSubset(simple_chk_records, full_chk_records)

    def test_inconsistency_fatal(self):
        repo = self.make_repository('repo', format='2a')
        self.assertTrue(repo.revisions._index._inconsistency_fatal)
        self.assertFalse(repo.texts._index._inconsistency_fatal)
        self.assertFalse(repo.inventories._index._inconsistency_fatal)
        self.assertFalse(repo.signatures._index._inconsistency_fatal)
        self.assertFalse(repo.chk_bytes._index._inconsistency_fatal)


class TestKnitPackStreamSource(tests.TestCaseWithMemoryTransport):

    def test_source_to_exact_pack_092(self):
        source = self.make_repository('source', format='pack-0.92')
        target = self.make_repository('target', format='pack-0.92')
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, pack_repo.KnitPackStreamSource)

    def test_source_to_exact_pack_rich_root_pack(self):
        source = self.make_repository('source', format='rich-root-pack')
        target = self.make_repository('target', format='rich-root-pack')
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, pack_repo.KnitPackStreamSource)

    def test_source_to_exact_pack_19(self):
        source = self.make_repository('source', format='1.9')
        target = self.make_repository('target', format='1.9')
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, pack_repo.KnitPackStreamSource)

    def test_source_to_exact_pack_19_rich_root(self):
        source = self.make_repository('source', format='1.9-rich-root')
        target = self.make_repository('target', format='1.9-rich-root')
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, pack_repo.KnitPackStreamSource)

    def test_source_to_remote_exact_pack_19(self):
        trans = self.make_smart_server('target')
        trans.ensure_base()
        source = self.make_repository('source', format='1.9')
        target = self.make_repository('target', format='1.9')
        target = repository.Repository.open(trans.base)
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, pack_repo.KnitPackStreamSource)

    def test_stream_source_to_non_exact(self):
        source = self.make_repository('source', format='pack-0.92')
        target = self.make_repository('target', format='1.9')
        stream = source._get_source(target._format)
        self.assertIs(type(stream), repository.StreamSource)

    def test_stream_source_to_non_exact_rich_root(self):
        source = self.make_repository('source', format='1.9')
        target = self.make_repository('target', format='1.9-rich-root')
        stream = source._get_source(target._format)
        self.assertIs(type(stream), repository.StreamSource)

    def test_source_to_remote_non_exact_pack_19(self):
        trans = self.make_smart_server('target')
        trans.ensure_base()
        source = self.make_repository('source', format='1.9')
        target = self.make_repository('target', format='1.6')
        target = repository.Repository.open(trans.base)
        stream_source = source._get_source(target._format)
        self.assertIs(type(stream_source), repository.StreamSource)

    def test_stream_source_to_knit(self):
        source = self.make_repository('source', format='pack-0.92')
        target = self.make_repository('target', format='dirstate')
        stream = source._get_source(target._format)
        self.assertIs(type(stream), repository.StreamSource)


class TestDevelopment6FindParentIdsOfRevisions(TestCaseWithTransport):
    """Tests for _find_parent_ids_of_revisions."""

    def setUp(self):
        super(TestDevelopment6FindParentIdsOfRevisions, self).setUp()
        self.builder = self.make_branch_builder('source',
            format='development6-rich-root')
        self.builder.start_series()
        self.builder.build_snapshot('initial', None,
            [('add', ('', 'tree-root', 'directory', None))])
        self.repo = self.builder.get_branch().repository
        self.addCleanup(self.builder.finish_series)

    def assertParentIds(self, expected_result, rev_set):
        self.assertEqual(sorted(expected_result),
            sorted(self.repo._find_parent_ids_of_revisions(rev_set)))

    def test_simple(self):
        self.builder.build_snapshot('revid1', None, [])
        self.builder.build_snapshot('revid2', ['revid1'], [])
        rev_set = ['revid2']
        self.assertParentIds(['revid1'], rev_set)

    def test_not_first_parent(self):
        self.builder.build_snapshot('revid1', None, [])
        self.builder.build_snapshot('revid2', ['revid1'], [])
        self.builder.build_snapshot('revid3', ['revid2'], [])
        rev_set = ['revid3', 'revid2']
        self.assertParentIds(['revid1'], rev_set)

    def test_not_null(self):
        rev_set = ['initial']
        self.assertParentIds([], rev_set)

    def test_not_null_set(self):
        self.builder.build_snapshot('revid1', None, [])
        rev_set = [_mod_revision.NULL_REVISION]
        self.assertParentIds([], rev_set)

    def test_ghost(self):
        self.builder.build_snapshot('revid1', None, [])
        rev_set = ['ghost', 'revid1']
        self.assertParentIds(['initial'], rev_set)

    def test_ghost_parent(self):
        self.builder.build_snapshot('revid1', None, [])
        self.builder.build_snapshot('revid2', ['revid1', 'ghost'], [])
        rev_set = ['revid2', 'revid1']
        self.assertParentIds(['ghost', 'initial'], rev_set)

    def test_righthand_parent(self):
        self.builder.build_snapshot('revid1', None, [])
        self.builder.build_snapshot('revid2a', ['revid1'], [])
        self.builder.build_snapshot('revid2b', ['revid1'], [])
        self.builder.build_snapshot('revid3', ['revid2a', 'revid2b'], [])
        rev_set = ['revid3', 'revid2a']
        self.assertParentIds(['revid1', 'revid2b'], rev_set)


class TestWithBrokenRepo(TestCaseWithTransport):
    """These tests seem to be more appropriate as interface tests?"""

    def make_broken_repository(self):
        # XXX: This function is borrowed from Aaron's "Reconcile can fix bad
        # parent references" branch which is due to land in bzr.dev soon.  Once
        # it does, this duplication should be removed.
        repo = self.make_repository('broken-repo')
        cleanups = []
        try:
            repo.lock_write()
            cleanups.append(repo.unlock)
            repo.start_write_group()
            cleanups.append(repo.commit_write_group)
            # make rev1a: A well-formed revision, containing 'file1'
            inv = inventory.Inventory(revision_id='rev1a')
            inv.root.revision = 'rev1a'
            self.add_file(repo, inv, 'file1', 'rev1a', [])
            repo.texts.add_lines((inv.root.file_id, 'rev1a'), [], [])
            repo.add_inventory('rev1a', inv, [])
            revision = _mod_revision.Revision('rev1a',
                committer='jrandom@example.com', timestamp=0,
                inventory_sha1='', timezone=0, message='foo', parent_ids=[])
            repo.add_revision('rev1a',revision, inv)

            # make rev1b, which has no Revision, but has an Inventory, and
            # file1
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
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.texts.add_lines((inv.root.file_id, revision_id), [], [])
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = _mod_revision.Revision(revision_id,
            committer='jrandom@example.com', timestamp=0, inventory_sha1='',
            timezone=0, message='foo', parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def add_file(self, repo, inv, filename, revision, parents):
        file_id = filename + '-id'
        entry = inventory.InventoryFile(file_id, filename, 'TREE_ROOT')
        entry.revision = revision
        entry.text_size = 0
        inv.add(entry)
        text_key = (file_id, revision)
        parent_keys = [(file_id, parent) for parent in parents]
        repo.texts.add_lines(text_key, parent_keys, ['line\n'])

    def test_insert_from_broken_repo(self):
        """Inserting a data stream from a broken repository won't silently
        corrupt the target repository.
        """
        broken_repo = self.make_broken_repository()
        empty_repo = self.make_repository('empty-repo')
        try:
            empty_repo.fetch(broken_repo)
        except (errors.RevisionNotPresent, errors.BzrCheckError):
            # Test successful: compression parent not being copied leads to
            # error.
            return
        empty_repo.lock_read()
        self.addCleanup(empty_repo.unlock)
        text = empty_repo.texts.get_record_stream(
            [('file2-id', 'rev3')], 'topological', True).next()
        self.assertEqual('line\n', text.get_bytes_as('fulltext'))


class TestRepositoryPackCollection(TestCaseWithTransport):

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir('pack-0.92')

    def get_packs(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        return repo._pack_collection

    def make_packs_and_alt_repo(self, write_lock=False):
        """Create a pack repo with 3 packs, and access it via a second repo."""
        tree = self.make_branch_and_tree('.', format=self.get_format())
        tree.lock_write()
        self.addCleanup(tree.unlock)
        rev1 = tree.commit('one')
        rev2 = tree.commit('two')
        rev3 = tree.commit('three')
        r = repository.Repository.open('.')
        if write_lock:
            r.lock_write()
        else:
            r.lock_read()
        self.addCleanup(r.unlock)
        packs = r._pack_collection
        packs.ensure_loaded()
        return tree, r, packs, [rev1, rev2, rev3]

    def test__max_pack_count(self):
        """The maximum pack count is a function of the number of revisions."""
        # no revisions - one pack, so that we can have a revision free repo
        # without it blowing up
        packs = self.get_packs()
        self.assertEqual(1, packs._max_pack_count(0))
        # after that the sum of the digits, - check the first 1-9
        self.assertEqual(1, packs._max_pack_count(1))
        self.assertEqual(2, packs._max_pack_count(2))
        self.assertEqual(3, packs._max_pack_count(3))
        self.assertEqual(4, packs._max_pack_count(4))
        self.assertEqual(5, packs._max_pack_count(5))
        self.assertEqual(6, packs._max_pack_count(6))
        self.assertEqual(7, packs._max_pack_count(7))
        self.assertEqual(8, packs._max_pack_count(8))
        self.assertEqual(9, packs._max_pack_count(9))
        # check the boundary cases with two digits for the next decade
        self.assertEqual(1, packs._max_pack_count(10))
        self.assertEqual(2, packs._max_pack_count(11))
        self.assertEqual(10, packs._max_pack_count(19))
        self.assertEqual(2, packs._max_pack_count(20))
        self.assertEqual(3, packs._max_pack_count(21))
        # check some arbitrary big numbers
        self.assertEqual(25, packs._max_pack_count(112894))

    def test_pack_distribution_zero(self):
        packs = self.get_packs()
        self.assertEqual([0], packs.pack_distribution(0))

    def test_ensure_loaded_unlocked(self):
        packs = self.get_packs()
        self.assertRaises(errors.ObjectNotLocked,
                          packs.ensure_loaded)

    def test_pack_distribution_one_to_nine(self):
        packs = self.get_packs()
        self.assertEqual([1],
            packs.pack_distribution(1))
        self.assertEqual([1, 1],
            packs.pack_distribution(2))
        self.assertEqual([1, 1, 1],
            packs.pack_distribution(3))
        self.assertEqual([1, 1, 1, 1],
            packs.pack_distribution(4))
        self.assertEqual([1, 1, 1, 1, 1],
            packs.pack_distribution(5))
        self.assertEqual([1, 1, 1, 1, 1, 1],
            packs.pack_distribution(6))
        self.assertEqual([1, 1, 1, 1, 1, 1, 1],
            packs.pack_distribution(7))
        self.assertEqual([1, 1, 1, 1, 1, 1, 1, 1],
            packs.pack_distribution(8))
        self.assertEqual([1, 1, 1, 1, 1, 1, 1, 1, 1],
            packs.pack_distribution(9))

    def test_pack_distribution_stable_at_boundaries(self):
        """When there are multi-rev packs the counts are stable."""
        packs = self.get_packs()
        # in 10s:
        self.assertEqual([10], packs.pack_distribution(10))
        self.assertEqual([10, 1], packs.pack_distribution(11))
        self.assertEqual([10, 10], packs.pack_distribution(20))
        self.assertEqual([10, 10, 1], packs.pack_distribution(21))
        # 100s
        self.assertEqual([100], packs.pack_distribution(100))
        self.assertEqual([100, 1], packs.pack_distribution(101))
        self.assertEqual([100, 10, 1], packs.pack_distribution(111))
        self.assertEqual([100, 100], packs.pack_distribution(200))
        self.assertEqual([100, 100, 1], packs.pack_distribution(201))
        self.assertEqual([100, 100, 10, 1], packs.pack_distribution(211))

    def test_plan_pack_operations_2009_revisions_skip_all_packs(self):
        packs = self.get_packs()
        existing_packs = [(2000, "big"), (9, "medium")]
        # rev count - 2009 -> 2x1000 + 9x1
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 1, 1, 1, 1, 1, 1, 1, 1, 1])
        self.assertEqual([], pack_operations)

    def test_plan_pack_operations_2010_revisions_skip_all_packs(self):
        packs = self.get_packs()
        existing_packs = [(2000, "big"), (9, "medium"), (1, "single")]
        # rev count - 2010 -> 2x1000 + 1x10
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 10])
        self.assertEqual([], pack_operations)

    def test_plan_pack_operations_2010_combines_smallest_two(self):
        packs = self.get_packs()
        existing_packs = [(1999, "big"), (9, "medium"), (1, "single2"),
            (1, "single1")]
        # rev count - 2010 -> 2x1000 + 1x10 (3)
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 10])
        self.assertEqual([[2, ["single2", "single1"]]], pack_operations)

    def test_plan_pack_operations_creates_a_single_op(self):
        packs = self.get_packs()
        existing_packs = [(50, 'a'), (40, 'b'), (30, 'c'), (10, 'd'),
                          (10, 'e'), (6, 'f'), (4, 'g')]
        # rev count 150 -> 1x100 and 5x10
        # The two size 10 packs do not need to be touched. The 50, 40, 30 would
        # be combined into a single 120 size pack, and the 6 & 4 would
        # becombined into a size 10 pack. However, if we have to rewrite them,
        # we save a pack file with no increased I/O by putting them into the
        # same file.
        distribution = packs.pack_distribution(150)
        pack_operations = packs.plan_autopack_combinations(existing_packs,
                                                           distribution)
        self.assertEqual([[130, ['a', 'b', 'c', 'f', 'g']]], pack_operations)

    def test_all_packs_none(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.ensure_loaded()
        self.assertEqual([], packs.all_packs())

    def test_all_packs_one(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        tree.commit('start')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.ensure_loaded()
        self.assertEqual([
            packs.get_pack_by_name(packs.names()[0])],
            packs.all_packs())

    def test_all_packs_two(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        tree.commit('start')
        tree.commit('continue')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.ensure_loaded()
        self.assertEqual([
            packs.get_pack_by_name(packs.names()[0]),
            packs.get_pack_by_name(packs.names()[1]),
            ], packs.all_packs())

    def test_get_pack_by_name(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        tree.commit('start')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.reset()
        packs.ensure_loaded()
        name = packs.names()[0]
        pack_1 = packs.get_pack_by_name(name)
        # the pack should be correctly initialised
        sizes = packs._names[name]
        rev_index = GraphIndex(packs._index_transport, name + '.rix', sizes[0])
        inv_index = GraphIndex(packs._index_transport, name + '.iix', sizes[1])
        txt_index = GraphIndex(packs._index_transport, name + '.tix', sizes[2])
        sig_index = GraphIndex(packs._index_transport, name + '.six', sizes[3])
        self.assertEqual(pack_repo.ExistingPack(packs._pack_transport,
            name, rev_index, inv_index, txt_index, sig_index), pack_1)
        # and the same instance should be returned on successive calls.
        self.assertTrue(pack_1 is packs.get_pack_by_name(name))

    def test_reload_pack_names_new_entry(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo()
        names = packs.names()
        # Add a new pack file into the repository
        rev4 = tree.commit('four')
        new_names = tree.branch.repository._pack_collection.names()
        new_name = set(new_names).difference(names)
        self.assertEqual(1, len(new_name))
        new_name = new_name.pop()
        # The old collection hasn't noticed yet
        self.assertEqual(names, packs.names())
        self.assertTrue(packs.reload_pack_names())
        self.assertEqual(new_names, packs.names())
        # And the repository can access the new revision
        self.assertEqual({rev4:(revs[-1],)}, r.get_parent_map([rev4]))
        self.assertFalse(packs.reload_pack_names())

    def test_reload_pack_names_added_and_removed(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo()
        names = packs.names()
        # Now repack the whole thing
        tree.branch.repository.pack()
        new_names = tree.branch.repository._pack_collection.names()
        # The other collection hasn't noticed yet
        self.assertEqual(names, packs.names())
        self.assertTrue(packs.reload_pack_names())
        self.assertEqual(new_names, packs.names())
        self.assertEqual({revs[-1]:(revs[-2],)}, r.get_parent_map([revs[-1]]))
        self.assertFalse(packs.reload_pack_names())

    def test_autopack_reloads_and_stops(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        # After we have determined what needs to be autopacked, trigger a
        # full-pack via the other repo which will cause us to re-evaluate and
        # decide we don't need to do anything
        orig_execute = packs._execute_pack_operations
        def _munged_execute_pack_ops(*args, **kwargs):
            tree.branch.repository.pack()
            return orig_execute(*args, **kwargs)
        packs._execute_pack_operations = _munged_execute_pack_ops
        packs._max_pack_count = lambda x: 1
        packs.pack_distribution = lambda x: [10]
        self.assertFalse(packs.autopack())
        self.assertEqual(1, len(packs.names()))
        self.assertEqual(tree.branch.repository._pack_collection.names(),
                         packs.names())


class TestPack(TestCaseWithTransport):
    """Tests for the Pack object."""

    def assertCurrentlyEqual(self, left, right):
        self.assertTrue(left == right)
        self.assertTrue(right == left)
        self.assertFalse(left != right)
        self.assertFalse(right != left)

    def assertCurrentlyNotEqual(self, left, right):
        self.assertFalse(left == right)
        self.assertFalse(right == left)
        self.assertTrue(left != right)
        self.assertTrue(right != left)

    def test___eq____ne__(self):
        left = pack_repo.ExistingPack('', '', '', '', '', '')
        right = pack_repo.ExistingPack('', '', '', '', '', '')
        self.assertCurrentlyEqual(left, right)
        # change all attributes and ensure equality changes as we do.
        left.revision_index = 'a'
        self.assertCurrentlyNotEqual(left, right)
        right.revision_index = 'a'
        self.assertCurrentlyEqual(left, right)
        left.inventory_index = 'a'
        self.assertCurrentlyNotEqual(left, right)
        right.inventory_index = 'a'
        self.assertCurrentlyEqual(left, right)
        left.text_index = 'a'
        self.assertCurrentlyNotEqual(left, right)
        right.text_index = 'a'
        self.assertCurrentlyEqual(left, right)
        left.signature_index = 'a'
        self.assertCurrentlyNotEqual(left, right)
        right.signature_index = 'a'
        self.assertCurrentlyEqual(left, right)
        left.name = 'a'
        self.assertCurrentlyNotEqual(left, right)
        right.name = 'a'
        self.assertCurrentlyEqual(left, right)
        left.transport = 'a'
        self.assertCurrentlyNotEqual(left, right)
        right.transport = 'a'
        self.assertCurrentlyEqual(left, right)

    def test_file_name(self):
        pack = pack_repo.ExistingPack('', 'a_name', '', '', '', '')
        self.assertEqual('a_name.pack', pack.file_name())


class TestNewPack(TestCaseWithTransport):
    """Tests for pack_repo.NewPack."""

    def test_new_instance_attributes(self):
        upload_transport = self.get_transport('upload')
        pack_transport = self.get_transport('pack')
        index_transport = self.get_transport('index')
        upload_transport.mkdir('.')
        collection = pack_repo.RepositoryPackCollection(
            repo=None,
            transport=self.get_transport('.'),
            index_transport=index_transport,
            upload_transport=upload_transport,
            pack_transport=pack_transport,
            index_builder_class=BTreeBuilder,
            index_class=BTreeGraphIndex,
            use_chk_index=False)
        pack = pack_repo.NewPack(collection)
        self.assertIsInstance(pack.revision_index, BTreeBuilder)
        self.assertIsInstance(pack.inventory_index, BTreeBuilder)
        self.assertIsInstance(pack._hash, type(osutils.md5()))
        self.assertTrue(pack.upload_transport is upload_transport)
        self.assertTrue(pack.index_transport is index_transport)
        self.assertTrue(pack.pack_transport is pack_transport)
        self.assertEqual(None, pack.index_sizes)
        self.assertEqual(20, len(pack.random_name))
        self.assertIsInstance(pack.random_name, str)
        self.assertIsInstance(pack.start_time, float)


class TestPacker(TestCaseWithTransport):
    """Tests for the packs repository Packer class."""

    def test_pack_optimizes_pack_order(self):
        builder = self.make_branch_builder('.', format="1.9")
        builder.start_series()
        builder.build_snapshot('A', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('f', 'f-id', 'file', 'content\n'))])
        builder.build_snapshot('B', ['A'],
            [('modify', ('f-id', 'new-content\n'))])
        builder.build_snapshot('C', ['B'],
            [('modify', ('f-id', 'third-content\n'))])
        builder.build_snapshot('D', ['C'],
            [('modify', ('f-id', 'fourth-content\n'))])
        b = builder.get_branch()
        b.lock_read()
        builder.finish_series()
        self.addCleanup(b.unlock)
        # At this point, we should have 4 pack files available
        # Because of how they were built, they correspond to
        # ['D', 'C', 'B', 'A']
        packs = b.repository._pack_collection.packs
        packer = pack_repo.Packer(b.repository._pack_collection,
                                  packs, 'testing',
                                  revision_ids=['B', 'C'])
        # Now, when we are copying the B & C revisions, their pack files should
        # be moved to the front of the stack
        # The new ordering moves B & C to the front of the .packs attribute,
        # and leaves the others in the original order.
        new_packs = [packs[1], packs[2], packs[0], packs[3]]
        new_pack = packer.pack()
        self.assertEqual(new_packs, packer.packs)


class TestOptimisingPacker(TestCaseWithTransport):
    """Tests for the OptimisingPacker class."""

    def get_pack_collection(self):
        repo = self.make_repository('.')
        return repo._pack_collection

    def test_open_pack_will_optimise(self):
        packer = pack_repo.OptimisingPacker(self.get_pack_collection(),
                                            [], '.test')
        new_pack = packer.open_pack()
        self.assertIsInstance(new_pack, pack_repo.NewPack)
        self.assertTrue(new_pack.revision_index._optimize_for_size)
        self.assertTrue(new_pack.inventory_index._optimize_for_size)
        self.assertTrue(new_pack.text_index._optimize_for_size)
        self.assertTrue(new_pack.signature_index._optimize_for_size)


class TestCrossFormatPacks(TestCaseWithTransport):

    def log_pack(self, hint=None):
        self.calls.append(('pack', hint))
        self.orig_pack(hint=hint)
        if self.expect_hint:
            self.assertTrue(hint)

    def run_stream(self, src_fmt, target_fmt, expect_pack_called):
        self.expect_hint = expect_pack_called
        self.calls = []
        source_tree = self.make_branch_and_tree('src', format=src_fmt)
        source_tree.lock_write()
        self.addCleanup(source_tree.unlock)
        tip = source_tree.commit('foo')
        target = self.make_repository('target', format=target_fmt)
        target.lock_write()
        self.addCleanup(target.unlock)
        source = source_tree.branch.repository._get_source(target._format)
        self.orig_pack = target.pack
        target.pack = self.log_pack
        search = target.search_missing_revision_ids(
            source_tree.branch.repository, tip)
        stream = source.get_stream(search)
        from_format = source_tree.branch.repository._format
        sink = target._get_sink()
        sink.insert_stream(stream, from_format, [])
        if expect_pack_called:
            self.assertLength(1, self.calls)
        else:
            self.assertLength(0, self.calls)

    def run_fetch(self, src_fmt, target_fmt, expect_pack_called):
        self.expect_hint = expect_pack_called
        self.calls = []
        source_tree = self.make_branch_and_tree('src', format=src_fmt)
        source_tree.lock_write()
        self.addCleanup(source_tree.unlock)
        tip = source_tree.commit('foo')
        target = self.make_repository('target', format=target_fmt)
        target.lock_write()
        self.addCleanup(target.unlock)
        source = source_tree.branch.repository
        self.orig_pack = target.pack
        target.pack = self.log_pack
        target.fetch(source)
        if expect_pack_called:
            self.assertLength(1, self.calls)
        else:
            self.assertLength(0, self.calls)

    def test_sink_format_hint_no(self):
        # When the target format says packing makes no difference, pack is not
        # called.
        self.run_stream('1.9', 'rich-root-pack', False)

    def test_sink_format_hint_yes(self):
        # When the target format says packing makes a difference, pack is
        # called.
        self.run_stream('1.9', '2a', True)

    def test_sink_format_same_no(self):
        # When the formats are the same, pack is not called.
        self.run_stream('2a', '2a', False)

    def test_IDS_format_hint_no(self):
        # When the target format says packing makes no difference, pack is not
        # called.
        self.run_fetch('1.9', 'rich-root-pack', False)

    def test_IDS_format_hint_yes(self):
        # When the target format says packing makes a difference, pack is
        # called.
        self.run_fetch('1.9', '2a', True)

    def test_IDS_format_same_no(self):
        # When the formats are the same, pack is not called.
        self.run_fetch('2a', '2a', False)
