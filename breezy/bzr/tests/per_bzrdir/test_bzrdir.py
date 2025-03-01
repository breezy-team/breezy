# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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

"""Tests for bzrdir implementations - tests a bzrdir format."""

import errno
from stat import S_ISDIR

import breezy.branch
from breezy import controldir, errors, repository, transport, workingtree
from breezy import revision as _mod_revision
from breezy.bzr import bzrdir
from breezy.bzr.remote import RemoteBzrDirFormat
from breezy.bzr.tests.per_bzrdir import TestCaseWithBzrDir
from breezy.tests import TestNotApplicable, TestSkipped
from breezy.transport import FileExists
from breezy.transport.local import LocalTransport


class AnonymousTestBranchFormat(breezy.branch.BranchFormat):
    """An anonymous branch format (does not have a format string)"""

    def get_format_string(self):
        raise NotImplementedError(self.get_format_string)


class IdentifiableTestBranchFormat(breezy.branch.BranchFormat):
    """An identifable branch format (has a format string)"""

    def get_format_string(self):
        return b"I have an identity"


class AnonymousTestRepositoryFormat(repository.RepositoryFormat):
    """An anonymous branch format (does not have a format string)"""

    def get_format_string(self):
        raise NotImplementedError(self.get_format_string)


class IdentifiableTestRepositoryFormat(repository.RepositoryFormat):
    """An identifable branch format (has a format string)"""

    def get_format_string(self):
        return b"I have an identity"


class AnonymousTestWorkingTreeFormat(workingtree.WorkingTreeFormat):
    """An anonymous branch format (does not have a format string)"""

    def get_format_string(self):
        raise NotImplementedError(self.get_format_string)


class IdentifiableTestWorkingTreeFormat(workingtree.WorkingTreeFormat):
    """An identifable branch format (has a format string)"""

    def get_format_string(self):
        return b"I have an identity"


class TestBzrDir(TestCaseWithBzrDir):
    # Many of these tests test for disk equality rather than checking
    # for semantic equivalence. This works well for some tests but
    # is not good at handling changes in representation or the addition
    # or removal of control data. It would be nice to for instance:
    # sprout a new branch, check that the nickname has been reset by hand
    # and then set the nickname to match the source branch, at which point
    # a semantic equivalence should pass

    def assertDirectoriesEqual(self, source, target, ignore_list=[]):
        """Assert that the content of source and target are identical.

        paths in ignore list will be completely ignored.

        We ignore paths that represent data which is allowed to change during
        a clone or sprout: for instance, inventory.knit contains gzip fragements
        which have timestamps in them, and as we have read the inventory from
        the source knit, the already-read data is recompressed rather than
        reading it again, which leads to changed timestamps. This is ok though,
        because the inventory.kndx file is not ignored, and the integrity of
        knit joins is tested by test_knit and test_versionedfile.

        :seealso: Additionally, assertRepositoryHasSameItems provides value
            rather than representation checking of repositories for
            equivalence.
        """
        files = []
        directories = ["."]
        while directories:
            dir = directories.pop()
            for path in set(source.list_dir(dir) + target.list_dir(dir)):
                path = dir + "/" + path
                if path in ignore_list:
                    continue
                try:
                    stat = source.stat(path)
                except transport.NoSuchFile:
                    self.fail("%s not in source" % path)
                if S_ISDIR(stat.st_mode):
                    self.assertTrue(S_ISDIR(target.stat(path).st_mode))
                    directories.append(path)
                else:
                    self.assertEqualDiff(
                        source.get_bytes(path),
                        target.get_bytes(path),
                        "text for file %r differs:\n" % path,
                    )

    def assertRepositoryHasSameItems(self, left_repo, right_repo):
        """Require left_repo and right_repo to contain the same data."""
        # XXX: TODO: Doesn't work yet, because we need to be able to compare
        # local repositories to remote ones...  but this is an as-yet unsolved
        # aspect of format management and the Remote protocols...
        # self.assertEqual(left_repo._format.__class__,
        #     right_repo._format.__class__)
        with left_repo.lock_read(), right_repo.lock_read():
            # revs
            all_revs = left_repo.all_revision_ids()
            self.assertEqual(
                left_repo.all_revision_ids(), right_repo.all_revision_ids()
            )
            for rev_id in left_repo.all_revision_ids():
                self.assertEqual(
                    left_repo.get_revision(rev_id), right_repo.get_revision(rev_id)
                )
            # Assert the revision trees (and thus the inventories) are equal

            def sort_key(rev_tree):
                return rev_tree.get_revision_id()

            rev_trees_a = sorted(left_repo.revision_trees(all_revs), key=sort_key)
            rev_trees_b = sorted(right_repo.revision_trees(all_revs), key=sort_key)
            for tree_a, tree_b in zip(rev_trees_a, rev_trees_b):
                self.assertEqual([], list(tree_a.iter_changes(tree_b)))
            # texts
            text_index = left_repo._generate_text_key_index()
            self.assertEqual(text_index, right_repo._generate_text_key_index())
            desired_files = []
            for file_id, revision_id in text_index:
                desired_files.append((file_id, revision_id, (file_id, revision_id)))
            left_texts = [
                (identifier, b"".join(bytes_iterator))
                for (identifier, bytes_iterator) in left_repo.iter_files_bytes(
                    desired_files
                )
            ]
            right_texts = [
                (identifier, b"".join(bytes_iterator))
                for (identifier, bytes_iterator) in right_repo.iter_files_bytes(
                    desired_files
                )
            ]
            left_texts.sort()
            right_texts.sort()
            self.assertEqual(left_texts, right_texts)
            # signatures
            for rev_id in all_revs:
                try:
                    left_text = left_repo.get_signature_text(rev_id)
                except errors.NoSuchRevision:
                    continue
                right_text = right_repo.get_signature_text(rev_id)
                self.assertEqual(left_text, right_text)

    def sproutOrSkip(
        self,
        from_bzrdir,
        to_url,
        revision_id=None,
        force_new_repo=False,
        accelerator_tree=None,
        create_tree_if_local=True,
    ):
        """Sprout from_bzrdir into to_url, or raise TestSkipped.

        A simple wrapper for from_bzrdir.sprout that translates NotLocalUrl into
        TestSkipped.  Returns the newly sprouted bzrdir.
        """
        to_transport = transport.get_transport(to_url)
        if not isinstance(to_transport, LocalTransport):
            raise TestSkipped("Cannot sprout to remote bzrdirs.")
        target = from_bzrdir.sprout(
            to_url,
            revision_id=revision_id,
            force_new_repo=force_new_repo,
            possible_transports=[to_transport],
            accelerator_tree=accelerator_tree,
            create_tree_if_local=create_tree_if_local,
        )
        return target

    def skipIfNoWorkingTree(self, a_controldir):
        """Raises TestSkipped if a_controldir doesn't have a working tree.

        If the bzrdir does have a workingtree, this is a no-op.
        """
        try:
            a_controldir.open_workingtree()
        except (errors.NotLocalUrl, errors.NoWorkingTree):
            raise TestSkipped(
                "bzrdir on transport %r has no working tree" % a_controldir.transport
            )

    def createWorkingTreeOrSkip(self, a_controldir):
        """Create a working tree on a_controldir, or raise TestSkipped.

        A simple wrapper for create_workingtree that translates NotLocalUrl into
        TestSkipped.  Returns the newly created working tree.
        """
        try:
            # This passes in many named options to make sure they're
            # understood by subclasses: see
            # <https://bugs.launchpad.net/bzr/+bug/524627>.
            return a_controldir.create_workingtree(
                revision_id=None,
                from_branch=None,
                accelerator_tree=None,
                hardlink=False,
            )
        except errors.NotLocalUrl:
            raise TestSkipped(
                "cannot make working tree with transport %r" % a_controldir.transport
            )

    def test_clone_bzrdir_repository_under_shared_force_new_repo(self):
        tree = self.make_branch_and_tree("commit_tree")
        self.build_tree(["commit_tree/foo"])
        tree.add("foo")
        tree.commit("revision 1", rev_id=b"1")
        dir = self.make_controldir("source")
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision(b"1"))
        try:
            self.make_repository("target", shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.clone(self.get_url("target/child"), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/repository",
            ],
        )
        self.assertRepositoryHasSameItems(tree.branch.repository, repo)

    def test_clone_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree("commit_tree")
        self.build_tree(["commit_tree/foo"])
        tree.add("foo")
        tree.commit("revision 1")
        source = self.make_branch("source")
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        dir = source.controldir
        target = dir.clone(self.get_url("target"))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/basis-inventory-cache",
                "./.bzr/checkout/stat-cache",
                "./.bzr/merge-hashes",
                "./.bzr/repository",
                "./.bzr/stat-cache",
            ],
        )
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_repository()
        )

    def test_clone_on_transport(self):
        a_dir = self.make_controldir("source")
        target_transport = a_dir.root_transport.clone("..").clone("target")
        target = a_dir.clone_on_transport(target_transport)
        self.assertNotEqual(a_dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            a_dir.root_transport, target.root_transport, ["./.bzr/merge-hashes"]
        )

    def test_clone_bzrdir_empty(self):
        dir = self.make_controldir("source")
        target = dir.clone(self.get_url("target"))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport, target.root_transport, ["./.bzr/merge-hashes"]
        )

    def test_clone_bzrdir_empty_force_new_ignored(self):
        # the force_new_repo parameter should have no effect on an empty
        # bzrdir's clone logic
        dir = self.make_controldir("source")
        target = dir.clone(self.get_url("target"), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport, target.root_transport, ["./.bzr/merge-hashes"]
        )

    def test_clone_bzrdir_repository(self):
        tree = self.make_branch_and_tree("commit_tree")
        self.build_tree(["foo"], transport=tree.controldir.transport.clone(".."))
        tree.add("foo")
        tree.commit("revision 1", rev_id=b"1")
        dir = self.make_controldir("source")
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision(b"1"))
        target = dir.clone(self.get_url("target"))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/merge-hashes",
                "./.bzr/repository",
            ],
        )
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_repository()
        )

    def test_clone_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree("source")
        self.build_tree(["source/foo"])
        tree.add("foo")
        tree.commit("revision 1")
        dir = tree.controldir
        target = dir.clone(self.get_url("target"))
        self.skipIfNoWorkingTree(target)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/stat-cache",
                "./.bzr/checkout/dirstate",
                "./.bzr/checkout/stat-cache",
                "./.bzr/checkout/merge-hashes",
                "./.bzr/merge-hashes",
                "./.bzr/repository",
            ],
        )
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_branch().repository
        )
        target.open_workingtree().revert()

    def test_revert_inventory(self):
        tree = self.make_branch_and_tree("source")
        self.build_tree(["source/foo"])
        tree.add("foo")
        tree.commit("revision 1")
        dir = tree.controldir
        target = dir.clone(self.get_url("target"))
        self.skipIfNoWorkingTree(target)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/stat-cache",
                "./.bzr/checkout/dirstate",
                "./.bzr/checkout/stat-cache",
                "./.bzr/checkout/merge-hashes",
                "./.bzr/merge-hashes",
                "./.bzr/repository",
            ],
        )
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_branch().repository
        )

        target.open_workingtree().revert()
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/stat-cache",
                "./.bzr/checkout/dirstate",
                "./.bzr/checkout/stat-cache",
                "./.bzr/checkout/merge-hashes",
                "./.bzr/merge-hashes",
                "./.bzr/repository",
            ],
        )
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_branch().repository
        )

    def test_clone_bzrdir_tree_branch_reference(self):
        # a tree with a branch reference (aka a checkout)
        # should stay a checkout on clone.
        referenced_branch = self.make_branch("referencced")
        dir = self.make_controldir("source")
        try:
            dir.set_branch_reference(referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.createWorkingTreeOrSkip(dir)
        target = dir.clone(self.get_url("target"))
        self.skipIfNoWorkingTree(target)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/stat-cache",
                "./.bzr/checkout/stat-cache",
                "./.bzr/checkout/merge-hashes",
                "./.bzr/merge-hashes",
                "./.bzr/repository/inventory.knit",
            ],
        )

    def test_clone_bzrdir_branch_and_repo_into_shared_repo_force_new_repo(self):
        # by default cloning into a shared repo uses the shared repo.
        tree = self.make_branch_and_tree("commit_tree")
        self.build_tree(["commit_tree/foo"])
        tree.add("foo")
        tree.commit("revision 1")
        source = self.make_branch("source")
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        try:
            self.make_repository("target", shared=True)
        except errors.IncompatibleFormat:
            return
        dir = source.controldir
        target = dir.clone(self.get_url("target/child"), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        repo = target.open_repository()
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/repository",
            ],
        )
        self.assertRepositoryHasSameItems(tree.branch.repository, repo)

    def test_clone_bzrdir_branch_reference(self):
        # cloning should preserve the reference status of the branch in a bzrdir
        referenced_branch = self.make_branch("referencced")
        dir = self.make_controldir("source")
        try:
            dir.set_branch_reference(referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        target = dir.clone(self.get_url("target"))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_sprout_bzrdir_repository(self):
        tree = self.make_branch_and_tree("commit_tree")
        self.build_tree(["foo"], transport=tree.controldir.transport.clone(".."))
        tree.add("foo")
        tree.commit("revision 1", rev_id=b"1")
        dir = self.make_controldir("source")
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision(b"1"))
        try:
            self.assertTrue(_mod_revision.is_null(dir.open_branch().last_revision()))
        except errors.NotBranchError:
            pass
        target = dir.sprout(self.get_url("target"))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # testing inventory isn't reasonable for repositories
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/branch",
                "./.bzr/checkout",
                "./.bzr/inventory",
                "./.bzr/parent",
                "./.bzr/repository/inventory.knit",
            ],
        )
        try:
            local_inventory = dir.transport.local_abspath("inventory")
        except errors.NotLocalUrl:
            return
        try:
            # If we happen to have a tree, we'll guarantee everything
            # except for the tree root is the same.
            with open(local_inventory, "rb") as inventory_f:
                self.assertContainsRe(
                    inventory_f.read(), b'<inventory format="5">\n</inventory>\n'
                )
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def test_sprout_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree("commit_tree")
        self.build_tree(["commit_tree/foo"])
        tree.add("foo")
        tree.commit("revision 1")
        source = self.make_branch("source")
        tree.branch.repository.copy_content_into(source.repository)
        tree.controldir.open_branch().copy_content_into(source)
        dir = source.controldir
        target = dir.sprout(self.get_url("target"))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        target_repo = target.open_repository()
        self.assertRepositoryHasSameItems(source.repository, target_repo)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/basis-inventory-cache",
                "./.bzr/branch/branch.conf",
                "./.bzr/branch/parent",
                "./.bzr/checkout",
                "./.bzr/checkout/inventory",
                "./.bzr/checkout/stat-cache",
                "./.bzr/inventory",
                "./.bzr/parent",
                "./.bzr/repository",
                "./.bzr/stat-cache",
                "./foo",
            ],
        )

    def test_sprout_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree("source")
        self.build_tree(["foo"], transport=tree.controldir.transport.clone(".."))
        tree.add("foo")
        tree.commit("revision 1")
        dir = tree.controldir
        target = self.sproutOrSkip(dir, self.get_url("target"))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(
            dir.root_transport,
            target.root_transport,
            [
                "./.bzr/branch",
                "./.bzr/checkout/dirstate",
                "./.bzr/checkout/stat-cache",
                "./.bzr/checkout/inventory",
                "./.bzr/inventory",
                "./.bzr/parent",
                "./.bzr/repository",
                "./.bzr/stat-cache",
            ],
        )
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_repository()
        )

    def test_sprout_branch_no_source_branch(self):
        try:
            repo = self.make_repository("source", shared=True)
        except errors.IncompatibleFormat:
            return
        if isinstance(self.bzrdir_format, RemoteBzrDirFormat):
            self.skipTest("remote formats not supported")
        branch = controldir.ControlDir.create_branch_convenience("source/trunk")
        tree = branch.controldir.open_workingtree()
        self.build_tree(["source/trunk/foo"])
        tree.add("foo")
        tree.commit("revision 1")
        rev2 = tree.commit("revision 2", allow_pointless=True)
        target = self.sproutOrSkip(
            repo.controldir, self.get_url("target"), revision_id=rev2
        )
        self.assertEqual([rev2], target.open_workingtree().get_parent_ids())

    def test_retire_bzrdir(self):
        bd = self.make_controldir(".")
        transport = bd.root_transport
        # must not overwrite existing directories
        self.build_tree(
            [
                ".bzr.retired.0/",
                ".bzr.retired.0/junk",
            ],
            transport=transport,
        )
        self.assertTrue(transport.has(".bzr"))
        bd.retire_bzrdir()
        self.assertFalse(transport.has(".bzr"))
        self.assertTrue(transport.has(".bzr.retired.1"))

    def test_retire_bzrdir_limited(self):
        bd = self.make_controldir(".")
        transport = bd.root_transport
        # must not overwrite existing directories
        self.build_tree(
            [
                ".bzr.retired.0/",
                ".bzr.retired.0/junk",
            ],
            transport=transport,
        )
        self.assertTrue(transport.has(".bzr"))
        self.assertRaises(
            (FileExists, errors.DirectoryNotEmpty), bd.retire_bzrdir, limit=0
        )

    def test_get_branch_transport(self):
        dir = self.make_controldir(".")
        # without a format, get_branch_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(isinstance(dir.get_branch_transport(None), transport.Transport))
        # with a given format, either the bzr dir supports identifiable
        # branches, or it supports anonymous branch formats, but not both.
        anonymous_format = AnonymousTestBranchFormat()
        identifiable_format = IdentifiableTestBranchFormat()
        try:
            found_transport = dir.get_branch_transport(anonymous_format)
            self.assertRaises(
                errors.IncompatibleFormat, dir.get_branch_transport, identifiable_format
            )
        except errors.IncompatibleFormat:
            found_transport = dir.get_branch_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must exist.
        found_transport.list_dir(".")

    def test_get_repository_transport(self):
        dir = self.make_controldir(".")
        # without a format, get_repository_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(
            isinstance(dir.get_repository_transport(None), transport.Transport)
        )
        # with a given format, either the bzr dir supports identifiable
        # repositories, or it supports anonymous repository formats, but not both.
        anonymous_format = AnonymousTestRepositoryFormat()
        identifiable_format = IdentifiableTestRepositoryFormat()
        try:
            found_transport = dir.get_repository_transport(anonymous_format)
            self.assertRaises(
                errors.IncompatibleFormat,
                dir.get_repository_transport,
                identifiable_format,
            )
        except errors.IncompatibleFormat:
            found_transport = dir.get_repository_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must exist.
        found_transport.list_dir(".")

    def test_get_workingtree_transport(self):
        dir = self.make_controldir(".")
        # without a format, get_workingtree_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(
            isinstance(dir.get_workingtree_transport(None), transport.Transport)
        )
        # with a given format, either the bzr dir supports identifiable
        # trees, or it supports anonymous tree formats, but not both.
        anonymous_format = AnonymousTestWorkingTreeFormat()
        identifiable_format = IdentifiableTestWorkingTreeFormat()
        try:
            found_transport = dir.get_workingtree_transport(anonymous_format)
            self.assertRaises(
                errors.IncompatibleFormat,
                dir.get_workingtree_transport,
                identifiable_format,
            )
        except errors.IncompatibleFormat:
            found_transport = dir.get_workingtree_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must exist.
        found_transport.list_dir(".")

    def assertInitializeEx(self, t, need_meta=False, **kwargs):
        """Execute initialize_on_transport_ex and check it succeeded correctly.

        This involves checking that the disk objects were created, open with
        the same format returned, and had the expected disk format.

        :param t: The transport to initialize on.
        :param **kwargs: Additional arguments to pass to
            initialize_on_transport_ex.
        :return: the resulting repo, control dir tuple.
        """
        if not self.bzrdir_format.is_initializable():
            raise TestNotApplicable("control dir format is not initializable")
        repo, control, require_stacking, repo_policy = (
            self.bzrdir_format.initialize_on_transport_ex(t, **kwargs)
        )
        if repo is not None:
            # Repositories are open write-locked
            self.assertTrue(repo.is_write_locked())
            self.addCleanup(repo.unlock)
        self.assertIsInstance(control, bzrdir.BzrDir)
        opened = bzrdir.BzrDir.open(t.base)
        expected_format = self.bzrdir_format
        if need_meta and expected_format.fixed_components:
            # Pre-metadir formats change when we are making something that
            # needs a metaformat, because clone is used for push.
            expected_format = bzrdir.BzrDirMetaFormat1()
        if not isinstance(expected_format, RemoteBzrDirFormat):
            self.assertEqual(
                control._format.network_name(), expected_format.network_name()
            )
            self.assertEqual(
                control._format.network_name(), opened._format.network_name()
            )
        self.assertEqual(control.__class__, opened.__class__)
        return repo, control

    def test_format_initialize_on_transport_ex_default_stack_on(self):
        # When initialize_on_transport_ex uses a stacked-on branch because of
        # a stacking policy on the target, the location of the fallback
        # repository is the same as the external location of the stacked-on
        # branch.
        balloon = self.make_controldir("balloon")
        if isinstance(balloon._format, bzrdir.BzrDirMetaFormat1):
            stack_on = self.make_branch("stack-on", format="1.9")
        else:
            stack_on = self.make_branch("stack-on")
        if not stack_on.repository._format.supports_nesting_repositories:
            raise TestNotApplicable("requires nesting repositories")
        config = self.make_controldir(".").get_config()
        try:
            config.set_default_stack_on("stack-on")
        except errors.BzrError:
            raise TestNotApplicable("Only relevant for stackable formats.")
        # Initialize a bzrdir subject to the policy.
        t = self.get_transport("stacked")
        repo_fmt = controldir.format_registry.make_controldir("1.9")
        repo_name = repo_fmt.repository_format.network_name()
        repo, control = self.assertInitializeEx(
            t, need_meta=True, repo_format_name=repo_name, stacked_on=None
        )
        # self.addCleanup(repo.unlock)
        # There's one fallback repo, with a public location.
        self.assertLength(1, repo._fallback_repositories)
        fallback_repo = repo._fallback_repositories[0]
        self.assertEqual(stack_on.base, fallback_repo.controldir.root_transport.base)
        # The bzrdir creates a branch in stacking-capable format.
        new_branch = control.create_branch()
        self.assertTrue(new_branch._format.supports_stacking())

    def test_no_leftover_dirs(self):
        # bug 886196: development-colo uses a branch-lock directory
        # in the user directory rather than the control directory.
        if not self.bzrdir_format.colocated_branches:
            raise TestNotApplicable("format does not support colocated branches")
        branch = self.make_branch(".", format="development-colo")
        branch.controldir.create_branch(name="another-colocated-branch")
        self.assertEqual(branch.controldir.user_transport.list_dir("."), [".bzr"])

    def test_get_branches(self):
        repo = self.make_repository("branch-1")
        if not repo.controldir._format.colocated_branches:
            raise TestNotApplicable("Format does not support colocation")
        target_branch = repo.controldir.create_branch(name="foo")
        repo.controldir.set_branch_reference(target_branch)
        self.assertEqual({"", "foo"}, set(repo.controldir.branch_names()))
