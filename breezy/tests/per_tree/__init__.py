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


"""Tree implementation tests for bzr.

These test the conformance of all the tree variations to the expected API.
Specific tests for individual variations are in other places such as:
 - tests/per_workingtree/*.py.
 - tests/test_tree.py
 - tests/test_revision.py
 - tests/test_workingtree.py
"""

import contextlib

from breezy import errors, tests, transform, transport
from breezy.bzr.workingtree_4 import (
    DirStateRevisionTree,
    WorkingTreeFormat4,
    WorkingTreeFormat5,
)
from breezy.git.tree import GitRevisionTree
from breezy.git.workingtree import GitWorkingTreeFormat
from breezy.revisiontree import RevisionTree
from breezy.tests import features
from breezy.tests.per_controldir.test_controldir import TestCaseWithControlDir
from breezy.tests.per_workingtree import make_scenario as wt_make_scenario
from breezy.tests.per_workingtree import make_scenarios as wt_make_scenarios
from breezy.workingtree import format_registry


def return_parameter(testcase, something):
    """A trivial thunk to return its input."""
    return something


def revision_tree_from_workingtree(testcase, tree):
    """Create a revision tree from a working tree."""
    revid = tree.commit("save tree", allow_pointless=True, recursive=None)
    return tree.branch.repository.revision_tree(revid)


def _dirstate_tree_from_workingtree(testcase, tree):
    revid = tree.commit("save tree", allow_pointless=True, recursive=None)
    return tree.basis_tree()


def preview_tree_pre(testcase, tree):
    tt = tree.preview_transform()
    testcase.addCleanup(tt.finalize)
    preview_tree = tt.get_preview_tree()
    preview_tree.set_parent_ids(tree.get_parent_ids())
    return preview_tree


def preview_tree_post(testcase, tree):
    basis = tree.basis_tree()
    tt = basis.preview_transform()
    testcase.addCleanup(tt.finalize)
    tree.lock_read()
    testcase.addCleanup(tree.unlock)
    pp = None
    es = contextlib.ExitStack()
    testcase.addCleanup(es.close)
    transform._prepare_revert_transform(
        es, basis, tree, tt, None, False, None, basis, {}
    )
    preview_tree = tt.get_preview_tree()
    preview_tree.set_parent_ids(tree.get_parent_ids())
    return preview_tree


class TestTreeImplementationSupport(tests.TestCaseWithTransport):
    def test_revision_tree_from_workingtree_bzr(self):
        tree = self.make_branch_and_tree(".", format="bzr")
        tree = revision_tree_from_workingtree(self, tree)
        self.assertIsInstance(tree, RevisionTree)

    def test_revision_tree_from_workingtree(self):
        tree = self.make_branch_and_tree(".", format="git")
        tree = revision_tree_from_workingtree(self, tree)
        self.assertIsInstance(tree, GitRevisionTree)


class TestCaseWithTree(TestCaseWithControlDir):
    def make_branch_and_tree(self, relpath):
        bzrdir_format = self.workingtree_format.get_controldir_for_branch()
        made_control = self.make_controldir(relpath, format=bzrdir_format)
        made_control.create_repository()
        b = made_control.create_branch()
        if getattr(self, "repo_is_remote", False):
            # If the repo is remote, then we just create a local lightweight
            # checkout
            # XXX: This duplicates a lot of Branch.create_checkout, but we know
            #      we want a) lightweight, and b) a specific WT format. We also
            #      know that nothing should already exist, etc.
            t = transport.get_transport(relpath)
            t.ensure_base()
            wt_dir = bzrdir_format.initialize_on_transport(t)
            branch_ref = wt_dir.set_branch_reference(b)
            wt = wt_dir.create_workingtree(None, from_branch=branch_ref)
        else:
            wt = self.workingtree_format.initialize(made_control)
        return wt

    def workingtree_to_test_tree(self, tree):
        return self._workingtree_to_test_tree(self, tree)

    def _convert_tree(self, tree, converter=None):
        """Helper to convert using the converter or a supplied one."""
        # convert that to the final shape
        if converter is None:
            converter = self.workingtree_to_test_tree
        return converter(tree)

    def get_tree_no_parents_no_content(self, empty_tree, converter=None):
        """Make a tree with no parents and no contents from empty_tree.

        :param empty_tree: A working tree with no content and no parents to
            modify.
        """
        if empty_tree.supports_setting_file_ids():
            empty_tree.set_root_id(b"empty-root-id")
        return self._convert_tree(empty_tree, converter)

    def _make_abc_tree(self, tree):
        """Setup an abc content tree."""
        files = ["a", "b/", "b/c"]
        self.build_tree(
            files, line_endings="binary", transport=tree.controldir.root_transport
        )
        tree.add(files)

    def get_tree_no_parents_abc_content(self, tree, converter=None):
        """Return a test tree with a, b/, b/c contents."""
        self._make_abc_tree(tree)
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_2(self, tree, converter=None):
        """Return a test tree with a, b/, b/c contents.

        This variation changes the content of 'a' to foobar\n.
        """
        self._make_abc_tree(tree)
        with open(tree.basedir + "/a", "wb") as f:
            f.write(b"foobar\n")
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_3(self, tree, converter=None):
        """Return a test tree with a, b/, b/c contents.

        This variation changes the executable flag of b/c to True.
        """
        self._make_abc_tree(tree)
        tt = tree.transform()
        trans_id = tt.trans_id_tree_path("b/c")
        tt.set_executability(True, trans_id)
        tt.apply()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_4(self, tree, converter=None):
        """Return a test tree with d, b/, b/c contents.

        This variation renames a to d.
        """
        self._make_abc_tree(tree)
        tree.rename_one("a", "d")
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_5(self, tree, converter=None):
        """Return a test tree with d, b/, b/c contents.

        This variation renames a to d and alters its content to 'bar\n'.
        """
        self._make_abc_tree(tree)
        tree.rename_one("a", "d")
        with open(tree.basedir + "/d", "wb") as f:
            f.write(b"bar\n")
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_6(self, tree, converter=None):
        """Return a test tree with a, b/, e contents.

        This variation renames b/c to e, and makes it executable.
        """
        self._make_abc_tree(tree)
        tt = tree.transform()
        trans_id = tt.trans_id_tree_path("b/c")
        parent_trans_id = tt.trans_id_tree_path("")
        tt.adjust_path("e", parent_trans_id, trans_id)
        tt.set_executability(True, trans_id)
        tt.apply()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_7(self, tree, converter=None):
        """Return a test tree with a, b/, d/e contents.

        This variation adds a dir 'd' (b'd-id'), renames b to d/e.
        """
        self._make_abc_tree(tree)
        self.build_tree(["d/"], transport=tree.controldir.root_transport)
        tree.add(["d"])
        tt = tree.transform()
        trans_id = tt.trans_id_tree_path("b")
        parent_trans_id = tt.trans_id_tree_path("d")
        tt.adjust_path("e", parent_trans_id, trans_id)
        tt.apply()
        return self._convert_tree(tree, converter)

    def get_tree_with_subdirs_and_all_content_types(self):
        """Return a test tree with subdirs and all content types.
        See get_tree_with_subdirs_and_all_supported_content_types for details.
        """
        return self.get_tree_with_subdirs_and_all_supported_content_types(True)

    def get_tree_with_subdirs_and_all_supported_content_types(self, symlinks):
        """Return a test tree with subdirs and all supported content types.
        Some content types may not be created on some platforms
        (like symlinks on native win32)

        :param  symlinks:   control is symlink should be created in the tree.
                            Note: if you wish to automatically set this
                            parameters depending on underlying system,
                            please use value returned
                            by breezy.osutils.supports_symlinks() function.

        The returned tree has the following inventory:
            ['',
             '0file',
             '1top-dir',
             u'2utf\u1234file',
             'symlink',            # only if symlinks arg is True
             '1top-dir/0file-in-1topdir',
             '1top-dir/1dir-in-1topdir']
        where each component has the type of its name -
        i.e. '1file..' is afile.

        note that the order of the paths and fileids is deliberately
        mismatched to ensure that the result order is path based.
        """
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        paths = [
            "0file",
            "1top-dir/",
            "2utf\u1234file",
            "1top-dir/0file-in-1topdir",
            "1top-dir/1dir-in-1topdir/",
        ]
        self.build_tree(paths)
        tree.add(paths)
        tt = tree.transform()
        if symlinks:
            root_transaction_id = tt.trans_id_tree_path("")
            tt.new_symlink("symlink", root_transaction_id, "link-target", b"symlink")
        tt.apply()
        return self.workingtree_to_test_tree(tree)


def make_scenarios(transport_server, transport_readonly_server, formats):
    """Generate test suites for each Tree implementation in breezy.

    Currently this covers all working tree formats, and RevisionTree and
    DirStateRevisionTree by committing a working tree to create the revision
    tree.
    """
    # TODO(jelmer): Test MemoryTree here
    # TODO(jelmer): Test GitMemoryTree here
    scenarios = wt_make_scenarios(transport_server, transport_readonly_server, formats)
    # now adjust the scenarios and add the non-working-tree tree scenarios.
    for scenario in scenarios:
        # for working tree format tests, preserve the tree
        scenario[1]["_workingtree_to_test_tree"] = return_parameter
    # add RevisionTree scenario
    workingtree_format = format_registry.get_default()
    scenarios.append(
        (
            RevisionTree.__name__,
            create_tree_scenario(
                transport_server,
                transport_readonly_server,
                workingtree_format,
                revision_tree_from_workingtree,
            ),
        )
    )
    scenarios.append(
        (
            GitRevisionTree.__name__,
            create_tree_scenario(
                transport_server,
                transport_readonly_server,
                GitWorkingTreeFormat(),
                revision_tree_from_workingtree,
            ),
        )
    )

    # also test WorkingTree4/5's RevisionTree implementation which is
    # specialised.
    # XXX: Ask igc if WT5 revision tree actually is different.
    scenarios.append(
        (
            DirStateRevisionTree.__name__ + ",WT4",
            create_tree_scenario(
                transport_server,
                transport_readonly_server,
                WorkingTreeFormat4(),
                _dirstate_tree_from_workingtree,
            ),
        )
    )
    scenarios.append(
        (
            DirStateRevisionTree.__name__ + ",WT5",
            create_tree_scenario(
                transport_server,
                transport_readonly_server,
                WorkingTreeFormat5(),
                _dirstate_tree_from_workingtree,
            ),
        )
    )
    scenarios.append(
        (
            "PreviewTree",
            create_tree_scenario(
                transport_server,
                transport_readonly_server,
                workingtree_format,
                preview_tree_pre,
            ),
        )
    )
    scenarios.append(
        (
            "PreviewTreePost",
            create_tree_scenario(
                transport_server,
                transport_readonly_server,
                workingtree_format,
                preview_tree_post,
            ),
        )
    )
    return scenarios


def create_tree_scenario(
    transport_server, transport_readonly_server, workingtree_format, converter
):
    """Create a scenario for the specified converter

    :param converter: A function that converts a workingtree into the
        desired format.
    :param workingtree_format: The particular workingtree format to
        convert from.
    :return: a (name, options) tuple, where options is a dict of values
        to be used as members of the TestCase.
    """
    scenario_options = wt_make_scenario(
        transport_server, transport_readonly_server, workingtree_format
    )
    scenario_options["_workingtree_to_test_tree"] = converter
    return scenario_options


def load_tests(loader, standard_tests, pattern):
    per_tree_mod_names = [
        "archive",
        "annotate_iter",
        "export",
        "get_file_mtime",
        "get_file_with_stat",
        "get_root_id",
        "get_symlink_target",
        "ids",
        "iter_search_rules",
        "is_executable",
        "list_files",
        "locking",
        "path_content_summary",
        "revision_tree",
        "symlinks",
        "test_trees",
        "transform",
        "tree",
        "walkdirs",
    ]
    submod_tests = loader.loadTestsFromModuleNames(
        [__name__ + ".test_" + name for name in per_tree_mod_names]
    )
    scenarios = make_scenarios(
        tests.default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        format_registry._get_all(),
    )
    # add the tests for the sub modules
    return tests.multiply_tests(submod_tests, scenarios, standard_tests)
