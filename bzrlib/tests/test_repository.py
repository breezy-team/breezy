# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for the Repository facility that are not interface tests.

For interface tests see tests/repository_implementations/*.py.

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
from bzrlib.index import GraphIndex, InMemoryGraphIndex
from bzrlib.repository import RepositoryFormat
from bzrlib.smart import server
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    test_knit,
    )
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryServer
from bzrlib.util import bencode
from bzrlib import (
    bzrdir,
    errors,
    inventory,
    osutils,
    repository,
    revision as _mod_revision,
    symbol_versioning,
    upgrade,
    workingtree,
    )
from bzrlib.repofmt import knitrepo, weaverepo, pack_repo


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

    def test_no_ancestry_weave(self):
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat6().initialize(control)
        # We no longer need to create the ancestry.weave file
        # since it is *never* used.
        self.assertRaises(NoSuchFile,
                          control.transport.get,
                          'ancestry.weave')

    def test_exposed_versioned_files_are_marked_dirty(self):
        control = bzrdir.BzrDirFormat6().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat6().initialize(control)
        repo.lock_write()
        inv = repo.get_inventory_weave()
        repo.unlock()
        self.assertRaises(errors.OutSideTransaction,
            inv.add_lines, 'foo', [], [])


class TestFormat7(TestCaseWithTransport):
    
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

    def test_exposed_versioned_files_are_marked_dirty(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = weaverepo.RepositoryFormat7().initialize(control)
        repo.lock_write()
        inv = repo.get_inventory_weave()
        repo.unlock()
        self.assertRaises(errors.OutSideTransaction,
            inv.add_lines, 'foo', [], [])


class TestFormatKnit1(TestCaseWithTransport):
    
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

    def assertHasKnit(self, t, knit_name):
        """Assert that knit_name exists on t."""
        self.assertEqualDiff('# bzr knit index 8\n',
                             t.get(knit_name + '.kndx').read())
        # no default content
        self.assertTrue(t.has(knit_name + '.knit'))

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

    def test_exposed_versioned_files_are_marked_dirty(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        repo = self.make_repository('.', format=format)
        repo.lock_write()
        inv = repo.get_inventory_weave()
        repo.unlock()
        self.assertRaises(errors.OutSideTransaction,
            inv.add_lines, 'foo', [], [])

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
        inv = repo.deserialise_inventory('test-rev-id', inv_xml)
        self.assertEqual('other-rev-id', inv.root.revision)


class KnitRepositoryStreamTests(test_knit.KnitTests):
    """Tests for knitrepo._get_stream_as_bytes."""

    def test_get_stream_as_bytes(self):
        # Make a simple knit
        k1 = self.make_test_knit()
        k1.add_lines('text-a', [], test_knit.split_lines(test_knit.TEXT_1))
        
        # Serialise it, check the output.
        bytes = knitrepo._get_stream_as_bytes(k1, ['text-a'])
        data = bencode.bdecode(bytes)
        format, record = data
        self.assertEqual('knit-plain', format)
        self.assertEqual(['text-a', ['fulltext'], []], record[:3])
        self.assertRecordContentEqual(k1, 'text-a', record[3])

    def test_get_stream_as_bytes_all(self):
        """Get a serialised data stream for all the records in a knit.

        Much like test_get_stream_all, except for get_stream_as_bytes.
        """
        k1 = self.make_test_knit()
        # Insert the same data as BasicKnitTests.test_knit_join, as they seem
        # to cover a range of cases (no parents, one parent, multiple parents).
        test_data = [
            ('text-a', [], test_knit.TEXT_1),
            ('text-b', ['text-a'], test_knit.TEXT_1),
            ('text-c', [], test_knit.TEXT_1),
            ('text-d', ['text-c'], test_knit.TEXT_1),
            ('text-m', ['text-b', 'text-d'], test_knit.TEXT_1),
           ]
        # This test is actually a bit strict as the order in which they're
        # returned is not defined.  This matches the current (deterministic)
        # behaviour.
        expected_data_list = [
            # version, options, parents
            ('text-a', ['fulltext'], []),
            ('text-b', ['line-delta'], ['text-a']),
            ('text-m', ['line-delta'], ['text-b', 'text-d']),
            ('text-c', ['fulltext'], []),
            ('text-d', ['line-delta'], ['text-c']),
            ]
        for version_id, parents, lines in test_data:
            k1.add_lines(version_id, parents, test_knit.split_lines(lines))

        bytes = knitrepo._get_stream_as_bytes(
            k1, ['text-a', 'text-b', 'text-m', 'text-c', 'text-d', ])

        data = bencode.bdecode(bytes)
        format = data.pop(0)
        self.assertEqual('knit-plain', format)

        for expected, actual in zip(expected_data_list, data):
            expected_version = expected[0]
            expected_options = expected[1]
            expected_parents = expected[2]
            version, options, parents, bytes = actual
            self.assertEqual(expected_version, version)
            self.assertEqual(expected_options, options)
            self.assertEqual(expected_parents, parents)
            self.assertRecordContentEqual(k1, version, bytes)


class DummyRepository(object):
    """A dummy repository for testing."""

    _serializer = None

    def supports_rich_root(self):
        return False


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
        dummy_b = DummyRepository()
        repo = self.make_repository('.')
        # hack dummies to look like repo somewhat.
        dummy_a._serializer = repo._serializer
        dummy_b._serializer = repo._serializer
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


class TestInterRemoteToOther(TestCaseWithTransport):

    def make_remote_repository(self, path, backing_format=None):
        """Make a RemoteRepository object backed by a real repository that will
        be created at the given path."""
        self.make_repository(path, format=backing_format)
        smart_server = server.SmartTCPServer_for_testing()
        smart_server.setUp()
        remote_transport = get_transport(smart_server.get_url()).clone(path)
        self.addCleanup(smart_server.tearDown)
        remote_bzrdir = bzrdir.BzrDir.open_from_transport(remote_transport)
        remote_repo = remote_bzrdir.open_repository()
        return remote_repo

    def test_is_compatible_same_format(self):
        """InterRemoteToOther is compatible with a remote repository and a
        second repository that have the same format."""
        local_repo = self.make_repository('local')
        remote_repo = self.make_remote_repository('remote')
        is_compatible = repository.InterRemoteToOther.is_compatible
        self.assertTrue(
            is_compatible(remote_repo, local_repo),
            "InterRemoteToOther(%r, %r) is false" % (remote_repo, local_repo))
          
    def test_is_incompatible_different_format(self):
        local_repo = self.make_repository('local', 'dirstate')
        remote_repo = self.make_remote_repository('a', 'dirstate-with-subtree')
        is_compatible = repository.InterRemoteToOther.is_compatible
        self.assertFalse(
            is_compatible(remote_repo, local_repo),
            "InterRemoteToOther(%r, %r) is true" % (local_repo, remote_repo))

    def test_is_incompatible_different_format_both_remote(self):
        remote_repo_a = self.make_remote_repository(
            'a', 'dirstate-with-subtree')
        remote_repo_b = self.make_remote_repository('b', 'dirstate')
        is_compatible = repository.InterRemoteToOther.is_compatible
        self.assertFalse(
            is_compatible(remote_repo_a, remote_repo_b),
            "InterRemoteToOther(%r, %r) is true"
            % (remote_repo_a, remote_repo_b))


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

    def test_convert(self):
        """Ensure the upgrade adds weaves for roots"""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        tree = self.make_branch_and_tree('.', format)
        tree.commit("Dull commit", rev_id="dull")
        revision_tree = tree.branch.repository.revision_tree('dull')
        self.assertRaises(errors.NoSuchFile, revision_tree.get_file_lines,
            revision_tree.inventory.root.file_id)
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        upgrade.Convert('.', format)
        tree = workingtree.WorkingTree.open('.')
        revision_tree = tree.branch.repository.revision_tree('dull')
        revision_tree.get_file_lines(revision_tree.inventory.root.file_id)
        tree.commit("Another dull commit", rev_id='dull2')
        revision_tree = tree.branch.repository.revision_tree('dull2')
        self.assertEqual('dull', revision_tree.inventory.root.revision)

    def test_exposed_versioned_files_are_marked_dirty(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        repo = self.make_repository('.', format=format)
        repo.lock_write()
        inv = repo.get_inventory_weave()
        repo.unlock()
        self.assertRaises(errors.OutSideTransaction,
            inv.add_lines, 'foo', [], [])


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
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, ['line\n'])

    def test_insert_from_broken_repo(self):
        """Inserting a data stream from a broken repository won't silently
        corrupt the target repository.
        """
        broken_repo = self.make_broken_repository()
        empty_repo = self.make_repository('empty-repo')
        stream = broken_repo.get_data_stream(['rev1a', 'rev2', 'rev3'])
        empty_repo.lock_write()
        self.addCleanup(empty_repo.unlock)
        empty_repo.start_write_group()
        try:
            self.assertRaises(
                errors.KnitCorrupt, empty_repo.insert_data_stream, stream)
        finally:
            empty_repo.abort_write_group()


class TestKnitPackNoSubtrees(TestCaseWithTransport):

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir('pack-0.92')

    def test_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.check_databases(t)

    def check_format(self, t):
        self.assertEqualDiff(
            "Bazaar pack repository format 1 (needs bzr 0.92)\n",
                             t.get('format').read())

    def assertHasKndx(self, t, knit_name):
        """Assert that knit_name exists on t."""
        self.assertEqualDiff('# bzr knit index 8\n',
                             t.get(knit_name + '.kndx').read())

    def assertHasNoKndx(self, t, knit_name):
        """Assert that knit_name has no index on t."""
        self.assertFalse(t.has(knit_name + '.kndx'))

    def assertHasNoKnit(self, t, knit_name):
        """Assert that knit_name exists on t."""
        # no default content
        self.assertFalse(t.has(knit_name + '.knit'))

    def check_databases(self, t):
        """check knit content for a repository."""
        # check conversion worked
        self.assertHasNoKndx(t, 'inventory')
        self.assertHasNoKnit(t, 'inventory')
        self.assertHasNoKndx(t, 'revisions')
        self.assertHasNoKnit(t, 'revisions')
        self.assertHasNoKndx(t, 'signatures')
        self.assertHasNoKnit(t, 'signatures')
        self.assertFalse(t.has('knits'))
        # revision-indexes file-container directory
        self.assertEqual([],
            list(GraphIndex(t, 'pack-names', None).iter_all_entries()))
        self.assertTrue(S_ISDIR(t.stat('packs').st_mode))
        self.assertTrue(S_ISDIR(t.stat('upload').st_mode))
        self.assertTrue(S_ISDIR(t.stat('indices').st_mode))
        self.assertTrue(S_ISDIR(t.stat('obsolete_packs').st_mode))

    def test_shared_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', shared=True, format=format)
        # we want:
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        # We should have a 'shared-storage' marker file.
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.check_databases(t)

    def test_shared_no_tree_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', shared=True, format=format)
        repo.set_make_working_trees(False)
        # we want:
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        # We should have a 'shared-storage' marker file.
        self.assertEqualDiff('', t.get('shared-storage').read())
        # We should have a marker for the no-working-trees flag.
        self.assertEqualDiff('', t.get('no-working-trees').read())
        # The marker should go when we toggle the setting.
        repo.set_make_working_trees(True)
        self.assertFalse(t.has('no-working-trees'))
        self.check_databases(t)

    def test_adding_revision_creates_pack_indices(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        self.assertEqual([],
            list(GraphIndex(trans, 'pack-names', None).iter_all_entries()))
        tree.commit('foobarbaz')
        index = GraphIndex(trans, 'pack-names', None)
        index_nodes = list(index.iter_all_entries())
        self.assertEqual(1, len(index_nodes))
        node = index_nodes[0]
        name = node[1][0]
        # the pack sizes should be listed in the index
        pack_value = node[2]
        sizes = [int(digits) for digits in pack_value.split(' ')]
        for size, suffix in zip(sizes, ['.rix', '.iix', '.tix', '.six']):
            stat = trans.stat('indices/%s%s' % (name, suffix))
            self.assertEqual(size, stat.st_size)

    def test_pulling_nothing_leads_to_no_new_names(self):
        format = self.get_format()
        tree1 = self.make_branch_and_tree('1', format=format)
        tree2 = self.make_branch_and_tree('2', format=format)
        tree1.branch.repository.fetch(tree2.branch.repository)
        trans = tree1.branch.repository.bzrdir.get_repository_transport(None)
        self.assertEqual([],
            list(GraphIndex(trans, 'pack-names', None).iter_all_entries()))

    def test_commit_across_pack_shape_boundary_autopacks(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        # This test could be a little cheaper by replacing the packs
        # attribute on the repository to allow a different pack distribution
        # and max packs policy - so we are checking the policy is honoured
        # in the test. But for now 11 commits is not a big deal in a single
        # test.
        for x in range(9):
            tree.commit('commit %s' % x)
        # there should be 9 packs:
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(9, len(list(index.iter_all_entries())))
        # insert some files in obsolete_packs which should be removed by pack.
        trans.put_bytes('obsolete_packs/foo', '123')
        trans.put_bytes('obsolete_packs/bar', '321')
        # committing one more should coalesce to 1 of 10.
        tree.commit('commit triggering pack')
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        # packing should not damage data
        tree = tree.bzrdir.open_workingtree()
        check_result = tree.branch.repository.check(
            [tree.branch.last_revision()])
        # We should have 50 (10x5) files in the obsolete_packs directory.
        obsolete_files = list(trans.list_dir('obsolete_packs'))
        self.assertFalse('foo' in obsolete_files)
        self.assertFalse('bar' in obsolete_files)
        self.assertEqual(50, len(obsolete_files))
        # XXX: Todo check packs obsoleted correctly - old packs and indices
        # in the obsolete_packs directory.
        large_pack_name = list(index.iter_all_entries())[0][1][0]
        # finally, committing again should not touch the large pack.
        tree.commit('commit not triggering pack')
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(2, len(list(index.iter_all_entries())))
        pack_names = [node[1][0] for node in index.iter_all_entries()]
        self.assertTrue(large_pack_name in pack_names)

    def test_pack_after_two_commits_packs_everything(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        tree.commit('start')
        tree.commit('more work')
        tree.branch.repository.pack()
        # there should be 1 pack:
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        self.assertEqual(2, len(tree.branch.repository.all_revision_ids()))

    def test_pack_repositories_support_multiple_write_locks(self):
        format = self.get_format()
        self.make_repository('.', shared=True, format=format)
        r1 = repository.Repository.open('.')
        r2 = repository.Repository.open('.')
        r1.lock_write()
        self.addCleanup(r1.unlock)
        r2.lock_write()
        r2.unlock()

    def _add_text(self, repo, fileid):
        """Add a text to the repository within a write group."""
        vf =repo.weave_store.get_weave(fileid, repo.get_transaction())
        vf.add_lines('samplerev+' + fileid, [], [])

    def test_concurrent_writers_merge_new_packs(self):
        format = self.get_format()
        self.make_repository('.', shared=True, format=format)
        r1 = repository.Repository.open('.')
        r2 = repository.Repository.open('.')
        r1.lock_write()
        try:
            # access enough data to load the names list
            list(r1.all_revision_ids())
            r2.lock_write()
            try:
                # access enough data to load the names list
                list(r2.all_revision_ids())
                r1.start_write_group()
                try:
                    r2.start_write_group()
                    try:
                        self._add_text(r1, 'fileidr1')
                        self._add_text(r2, 'fileidr2')
                    except:
                        r2.abort_write_group()
                        raise
                except:
                    r1.abort_write_group()
                    raise
                # both r1 and r2 have open write groups with data in them
                # created while the other's write group was open.
                # Commit both which requires a merge to the pack-names.
                try:
                    r1.commit_write_group()
                except:
                    r1.abort_write_group()
                    r2.abort_write_group()
                    raise
                r2.commit_write_group()
                # tell r1 to reload from disk
                r1._pack_collection.reset()
                # Now both repositories should know about both names
                r1._pack_collection.ensure_loaded()
                r2._pack_collection.ensure_loaded()
                self.assertEqual(r1._pack_collection.names(), r2._pack_collection.names())
                self.assertEqual(2, len(r1._pack_collection.names()))
            finally:
                r2.unlock()
        finally:
            r1.unlock()

    def test_concurrent_writer_second_preserves_dropping_a_pack(self):
        format = self.get_format()
        self.make_repository('.', shared=True, format=format)
        r1 = repository.Repository.open('.')
        r2 = repository.Repository.open('.')
        # add a pack to drop
        r1.lock_write()
        try:
            r1.start_write_group()
            try:
                self._add_text(r1, 'fileidr1')
            except:
                r1.abort_write_group()
                raise
            else:
                r1.commit_write_group()
            r1._pack_collection.ensure_loaded()
            name_to_drop = r1._pack_collection.all_packs()[0].name
        finally:
            r1.unlock()
        r1.lock_write()
        try:
            # access enough data to load the names list
            list(r1.all_revision_ids())
            r2.lock_write()
            try:
                # access enough data to load the names list
                list(r2.all_revision_ids())
                r1._pack_collection.ensure_loaded()
                try:
                    r2.start_write_group()
                    try:
                        # in r1, drop the pack
                        r1._pack_collection._remove_pack_from_memory(
                            r1._pack_collection.get_pack_by_name(name_to_drop))
                        # in r2, add a pack
                        self._add_text(r2, 'fileidr2')
                    except:
                        r2.abort_write_group()
                        raise
                except:
                    r1._pack_collection.reset()
                    raise
                # r1 has a changed names list, and r2 an open write groups with
                # changes.
                # save r1, and then commit the r2 write group, which requires a
                # merge to the pack-names, which should not reinstate
                # name_to_drop
                try:
                    r1._pack_collection._save_pack_names()
                    r1._pack_collection.reset()
                except:
                    r2.abort_write_group()
                    raise
                try:
                    r2.commit_write_group()
                except:
                    r2.abort_write_group()
                    raise
                # Now both repositories should now about just one name.
                r1._pack_collection.ensure_loaded()
                r2._pack_collection.ensure_loaded()
                self.assertEqual(r1._pack_collection.names(), r2._pack_collection.names())
                self.assertEqual(1, len(r1._pack_collection.names()))
                self.assertFalse(name_to_drop in r1._pack_collection.names())
            finally:
                r2.unlock()
        finally:
            r1.unlock()

    def test_lock_write_does_not_physically_lock(self):
        repo = self.make_repository('.', format=self.get_format())
        repo.lock_write()
        self.addCleanup(repo.unlock)
        self.assertFalse(repo.get_physical_lock_status())

    def prepare_for_break_lock(self):
        # Setup the global ui factory state so that a break-lock method call
        # will find usable input in the input stream.
        old_factory = bzrlib.ui.ui_factory
        def restoreFactory():
            bzrlib.ui.ui_factory = old_factory
        self.addCleanup(restoreFactory)
        bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()
        bzrlib.ui.ui_factory.stdin = StringIO("y\n")

    def test_break_lock_breaks_physical_lock(self):
        repo = self.make_repository('.', format=self.get_format())
        repo._pack_collection.lock_names()
        repo2 = repository.Repository.open('.')
        self.assertTrue(repo.get_physical_lock_status())
        self.prepare_for_break_lock()
        repo2.break_lock()
        self.assertFalse(repo.get_physical_lock_status())

    def test_broken_physical_locks_error_on__unlock_names_lock(self):
        repo = self.make_repository('.', format=self.get_format())
        repo._pack_collection.lock_names()
        self.assertTrue(repo.get_physical_lock_status())
        repo2 = repository.Repository.open('.')
        self.prepare_for_break_lock()
        repo2.break_lock()
        self.assertRaises(errors.LockBroken, repo._pack_collection._unlock_names)

    def test_fetch_without_find_ghosts_ignores_ghosts(self):
        # we want two repositories at this point:
        # one with a revision that is a ghost in the other
        # repository.
        # 'ghost' is present in has_ghost, 'ghost' is absent in 'missing_ghost'.
        # 'references' is present in both repositories, and 'tip' is present
        # just in has_ghost.
        # has_ghost       missing_ghost
        #------------------------------
        # 'ghost'             -
        # 'references'    'references'
        # 'tip'               -
        # In this test we fetch 'tip' which should not fetch 'ghost'
        has_ghost = self.make_repository('has_ghost', format=self.get_format())
        missing_ghost = self.make_repository('missing_ghost',
            format=self.get_format())

        def add_commit(repo, revision_id, parent_ids):
            repo.lock_write()
            repo.start_write_group()
            inv = inventory.Inventory(revision_id=revision_id)
            inv.root.revision = revision_id
            root_id = inv.root.file_id
            sha1 = repo.add_inventory(revision_id, inv, [])
            vf = repo.weave_store.get_weave_or_empty(root_id,
                repo.get_transaction())
            vf.add_lines(revision_id, [], [])
            rev = bzrlib.revision.Revision(timestamp=0,
                                           timezone=None,
                                           committer="Foo Bar <foo@example.com>",
                                           message="Message",
                                           inventory_sha1=sha1,
                                           revision_id=revision_id)
            rev.parent_ids = parent_ids
            repo.add_revision(revision_id, rev)
            repo.commit_write_group()
            repo.unlock()
        add_commit(has_ghost, 'ghost', [])
        add_commit(has_ghost, 'references', ['ghost'])
        add_commit(missing_ghost, 'references', ['ghost'])
        add_commit(has_ghost, 'tip', ['references'])
        missing_ghost.fetch(has_ghost, 'tip')
        # missing ghost now has tip and not ghost.
        rev = missing_ghost.get_revision('tip')
        inv = missing_ghost.get_inventory('tip')
        self.assertRaises(errors.NoSuchRevision,
            missing_ghost.get_revision, 'ghost')
        self.assertRaises(errors.RevisionNotPresent,
            missing_ghost.get_inventory, 'ghost')


class TestKnitPackSubtrees(TestKnitPackNoSubtrees):

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir(
            'pack-0.92-subtree')

    def check_format(self, t):
        self.assertEqualDiff(
            "Bazaar pack repository format 1 with subtree support (needs bzr 0.92)\n",
            t.get('format').read())


class TestRepositoryPackCollection(TestCaseWithTransport):

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir('pack-0.92')

    def test__max_pack_count(self):
        """The maximum pack count is a function of the number of revisions."""
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        packs = repo._pack_collection
        # no revisions - one pack, so that we can have a revision free repo
        # without it blowing up
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
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        packs = repo._pack_collection
        self.assertEqual([0], packs.pack_distribution(0))

    def test_ensure_loaded_unlocked(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        self.assertRaises(errors.ObjectNotLocked,
                          repo._pack_collection.ensure_loaded)

    def test_pack_distribution_one_to_nine(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        packs = repo._pack_collection
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
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        packs = repo._pack_collection
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
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        packs = repo._pack_collection
        existing_packs = [(2000, "big"), (9, "medium")]
        # rev count - 2009 -> 2x1000 + 9x1
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 1, 1, 1, 1, 1, 1, 1, 1, 1])
        self.assertEqual([], pack_operations)

    def test_plan_pack_operations_2010_revisions_skip_all_packs(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        packs = repo._pack_collection
        existing_packs = [(2000, "big"), (9, "medium"), (1, "single")]
        # rev count - 2010 -> 2x1000 + 1x10
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 10])
        self.assertEqual([], pack_operations)

    def test_plan_pack_operations_2010_combines_smallest_two(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        packs = repo._pack_collection
        existing_packs = [(1999, "big"), (9, "medium"), (1, "single2"),
            (1, "single1")]
        # rev count - 2010 -> 2x1000 + 1x10 (3)
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 10])
        self.assertEqual([[2, ["single2", "single1"]], [0, []]], pack_operations)

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
        packs.ensure_loaded()
        name = packs.names()[0]
        pack_1 = packs.get_pack_by_name(name)
        # the pack should be correctly initialised
        rev_index = GraphIndex(packs._index_transport, name + '.rix',
            packs._names[name][0])
        inv_index = GraphIndex(packs._index_transport, name + '.iix',
            packs._names[name][1])
        txt_index = GraphIndex(packs._index_transport, name + '.tix',
            packs._names[name][2])
        sig_index = GraphIndex(packs._index_transport, name + '.six',
            packs._names[name][3])
        self.assertEqual(pack_repo.ExistingPack(packs._pack_transport,
            name, rev_index, inv_index, txt_index, sig_index), pack_1)
        # and the same instance should be returned on successive calls.
        self.assertTrue(pack_1 is packs.get_pack_by_name(name))


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
        pack = pack_repo.NewPack(upload_transport, index_transport,
            pack_transport)
        self.assertIsInstance(pack.revision_index, InMemoryGraphIndex)
        self.assertIsInstance(pack.inventory_index, InMemoryGraphIndex)
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

    # To date, this class has been factored out and nothing new added to it;
    # thus there are not yet any tests.
