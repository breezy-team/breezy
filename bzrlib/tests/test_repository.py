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

from bzrlib import symbol_versioning
import bzrlib
import bzrlib.bzrdir as bzrdir
import bzrlib.errors as errors
from bzrlib.errors import (NotBranchError,
                           NoSuchFile,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )
from bzrlib.file_names import FileNames
from bzrlib.repository import RepositoryFormat
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryServer
from bzrlib import (
    repository,
    upgrade,
    workingtree,
    )
from bzrlib.repofmt import knitrepo, weaverepo


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


class DummyRepository(object):
    """A dummy repository for testing."""

    _serializer = None

    def supports_rich_root(self):
        return False


class InterDummy(repository.InterRepository):
    """An inter-repository optimised code path for DummyRepository.

    This is for use during testing where we use DummyRepository as repositories
    so that none of the default regsitered inter-repository classes will
    match.
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


class TestExperimentalNoSubtrees(TestCaseWithTransport):

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir('experimental')

    def test_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        # we want:
        # format 'Bazaar Experimental'
        # lock: is a directory
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.assertTrue(S_ISDIR(t.stat('knits').st_mode))
        self.check_databases(t)

    def check_format(self, t):
        self.assertEqualDiff('Bazaar Experimental no-subtrees\n',
                             t.get('format').read())

    def assertHasKndx(self, t, knit_name):
        """Assert that knit_name exists on t."""
        self.assertEqualDiff('# bzr knit index 8\n',
                             t.get(knit_name + '.kndx').read())

    def assertHasNoKndx(self, t, knit_name):
        """Assert that knit_name has no index on t."""
        self.assertFalse(t.has(knit_name + '.kndx'))

    def assertHasKnit(self, t, knit_name):
        """Assert that knit_name exists on t."""
        # no default content
        self.assertTrue(t.has(knit_name + '.knit'))

    def check_databases(self, t):
        """check knit content for a repository."""
        self.assertHasKndx(t, 'inventory')
        self.assertHasKnit(t, 'inventory')
        self.assertHasNoKndx(t, 'revisions')
        self.assertHasKnit(t, 'revisions')
        self.assertHasNoKndx(t, 'signatures')
        self.assertHasKnit(t, 'signatures')
        # revision-indexes file-container directory
        names = FileNames(t.clone('indices'), 'index')
        names.load()
        self.assertEqual(set(), names.names())

    def test_shared_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', shared=True, format=format)
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock: is a directory
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.assertTrue(S_ISDIR(t.stat('knits').st_mode))
        self.check_databases(t)

    def test_shared_no_tree_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', shared=True, format=format)
        repo.set_make_working_trees(False)
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock ''
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.assertEqualDiff('', t.get('no-working-trees').read())
        repo.set_make_working_trees(True)
        self.assertFalse(t.has('no-working-trees'))
        self.assertTrue(S_ISDIR(t.stat('knits').st_mode))
        self.check_databases(t)

    def test_add_revision_creates_zero_dot_rix(self):
        """Adding a revision makes a 0.rix (Revision IndeX) file."""
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        self.assertFalse(trans.has('indices/0.rix'))
        tree.commit('foobarbaz')
        self.assertTrue(trans.has('indices/0.rix'))

    def test_add_revision_creates_zero_dot_six(self):
        """Adding a revision makes a 0.six (Signature IndeX) file."""
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        self.assertFalse(trans.has('indices/0.six'))
        tree.commit('foobarbaz')
        self.assertTrue(trans.has('indices/0.six'))

    def test_add_revision_creates_zero_dot_tix(self):
        """Adding a revision makes a 0.tix (Text IndeX) file."""
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        self.assertFalse(trans.has('indices/0.tix'))
        tree.commit('foobarbaz')
        self.assertTrue(trans.has('indices/0.tix'))

    def test_pulling_nothing_leads_to_no_new_names(self):
        format = self.get_format()
        tree1 = self.make_branch_and_tree('1', format=format)
        tree2 = self.make_branch_and_tree('2', format=format)
        tree1.branch.repository.fetch(tree2.branch.repository)
        trans = tree1.branch.repository.bzrdir.get_repository_transport(None)
        self.assertFalse(trans.has('indices/0.rix'))
        self.assertFalse(trans.has('indices/0.six'))
        self.assertFalse(trans.has('indices/0.tix'))
        names = FileNames(trans.clone('indices'), 'index')
        names.load()
        self.assertEqual(set(), names.names())


class TestExperimentalSubtrees(TestExperimentalNoSubtrees):

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir('experimental-subtree')

    def check_format(self, t):
        self.assertEqualDiff('Bazaar Experimental subtrees\n',
                             t.get('format').read())

