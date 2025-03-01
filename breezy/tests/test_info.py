# Copyright (C) 2007-2012 Canonical Ltd
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

import sys

from .. import branch as _mod_branch
from .. import controldir, info, tests, workingtree
from .. import repository as _mod_repository
from ..bzr import branch as _mod_bzrbranch


class TestInfo(tests.TestCaseWithTransport):
    def test_describe_standalone_layout(self):
        tree = self.make_branch_and_tree("tree")
        self.assertEqual("Empty control directory", info.describe_layout())
        self.assertEqual(
            "Unshared repository with trees and colocated branches",
            info.describe_layout(tree.branch.repository, control=tree.controldir),
        )
        tree.branch.repository.set_make_working_trees(False)
        self.assertEqual(
            "Unshared repository with colocated branches",
            info.describe_layout(tree.branch.repository, control=tree.controldir),
        )
        self.assertEqual(
            "Standalone branch",
            info.describe_layout(
                tree.branch.repository, tree.branch, control=tree.controldir
            ),
        )
        self.assertEqual(
            "Standalone branchless tree",
            info.describe_layout(
                tree.branch.repository, None, tree, control=tree.controldir
            ),
        )
        self.assertEqual(
            "Standalone tree",
            info.describe_layout(
                tree.branch.repository, tree.branch, tree, control=tree.controldir
            ),
        )
        tree.branch.bind(tree.branch)
        self.assertEqual(
            "Bound branch",
            info.describe_layout(
                tree.branch.repository, tree.branch, control=tree.controldir
            ),
        )
        self.assertEqual(
            "Checkout",
            info.describe_layout(
                tree.branch.repository, tree.branch, tree, control=tree.controldir
            ),
        )
        checkout = tree.branch.create_checkout("checkout", lightweight=True)
        self.assertEqual(
            "Lightweight checkout",
            info.describe_layout(
                checkout.branch.repository,
                checkout.branch,
                checkout,
                control=tree.controldir,
            ),
        )

    def test_describe_repository_layout(self):
        repository = self.make_repository(".", shared=True)
        tree = controldir.ControlDir.create_branch_convenience(
            "tree", force_new_tree=True
        ).controldir.open_workingtree()
        self.assertEqual(
            "Shared repository with trees and colocated branches",
            info.describe_layout(tree.branch.repository, control=tree.controldir),
        )
        repository.set_make_working_trees(False)
        self.assertEqual(
            "Shared repository with colocated branches",
            info.describe_layout(tree.branch.repository, control=tree.controldir),
        )
        self.assertEqual(
            "Repository branch",
            info.describe_layout(
                tree.branch.repository, tree.branch, control=tree.controldir
            ),
        )
        self.assertEqual(
            "Repository branchless tree",
            info.describe_layout(
                tree.branch.repository, None, tree, control=tree.controldir
            ),
        )
        self.assertEqual(
            "Repository tree",
            info.describe_layout(
                tree.branch.repository, tree.branch, tree, control=tree.controldir
            ),
        )
        tree.branch.bind(tree.branch)
        self.assertEqual(
            "Repository checkout",
            info.describe_layout(
                tree.branch.repository, tree.branch, tree, control=tree.controldir
            ),
        )
        checkout = tree.branch.create_checkout("checkout", lightweight=True)
        self.assertEqual(
            "Lightweight checkout",
            info.describe_layout(
                checkout.branch.repository,
                checkout.branch,
                checkout,
                control=tree.controldir,
            ),
        )

    def assertTreeDescription(self, format):
        """Assert a tree's format description matches expectations."""
        self.make_branch_and_tree("{}_tree".format(format), format=format)
        tree = workingtree.WorkingTree.open("{}_tree".format(format))
        self.assertEqual(
            format,
            info.describe_format(
                tree.controldir, tree.branch.repository, tree.branch, tree
            ),
        )

    def assertCheckoutDescription(self, format, expected=None):
        """Assert a checkout's format description matches expectations."""
        if expected is None:
            expected = format
        branch = self.make_branch("{}_cobranch".format(format), format=format)
        # this ought to be easier...
        branch.create_checkout(
            "{}_co".format(format), lightweight=True
        ).controldir.destroy_workingtree()
        control = controldir.ControlDir.open("{}_co".format(format))
        old_format = control._format.workingtree_format
        try:
            control._format.workingtree_format = (
                controldir.format_registry.make_controldir(format).workingtree_format
            )
            control.create_workingtree()
            tree = workingtree.WorkingTree.open("{}_co".format(format))
            format_description = info.describe_format(
                tree.controldir, tree.branch.repository, tree.branch, tree
            )
            self.assertEqual(
                expected,
                format_description,
                "checkout of format called {!r} was described as {!r}".format(expected, format_description),
            )
        finally:
            control._format.workingtree_format = old_format

    def assertBranchDescription(self, format, expected=None):
        """Assert branch's format description matches expectations."""
        if expected is None:
            expected = format
        self.make_branch("{}_branch".format(format), format=format)
        branch = _mod_branch.Branch.open("{}_branch".format(format))
        self.assertEqual(
            expected,
            info.describe_format(branch.controldir, branch.repository, branch, None),
        )

    def assertRepoDescription(self, format, expected=None):
        """Assert repository's format description matches expectations."""
        if expected is None:
            expected = format
        self.make_repository("{}_repo".format(format), format=format)
        repo = _mod_repository.Repository.open("{}_repo".format(format))
        self.assertEqual(
            expected, info.describe_format(repo.controldir, repo, None, None)
        )

    def test_describe_tree_format(self):
        for key, format in controldir.format_registry.iteritems():
            if key in controldir.format_registry.aliases():
                continue
            if not format().supports_workingtrees:
                continue
            self.assertTreeDescription(key)

    def test_describe_checkout_format(self):
        for key in controldir.format_registry.keys():
            if key in controldir.format_registry.aliases():
                # Aliases will not describe correctly in the UI because the
                # real format is found.
                continue
            # legacy: weave does not support checkouts
            if key == "weave":
                continue
            # foreign: git checkouts can actually be bzr controldirs
            if key in ("git", "git-bare"):
                continue
            if controldir.format_registry.get_info(key).experimental:
                # We don't require that experimental formats support checkouts
                # or describe correctly in the UI.
                continue
            if controldir.format_registry.get_info(key).hidden:
                continue
            expected = None
            if key in ("pack-0.92",):
                expected = "pack-0.92"
            elif key in ("knit", "metaweave"):
                if "metaweave" in controldir.format_registry:
                    expected = "knit or metaweave"
                else:
                    expected = "knit"
            elif key in ("1.14", "1.14-rich-root"):
                expected = "1.14 or 1.14-rich-root"
            self.assertCheckoutDescription(key, expected)

    def test_describe_branch_format(self):
        for key in controldir.format_registry.keys():
            if key in controldir.format_registry.aliases():
                continue
            if controldir.format_registry.get_info(key).hidden:
                continue
            expected = None
            if key in ("dirstate", "knit"):
                expected = "dirstate or knit"
            elif key in ("1.14",):
                expected = "1.14"
            elif key in ("1.14-rich-root",):
                expected = "1.14-rich-root"
            self.assertBranchDescription(key, expected)

    def test_describe_repo_format(self):
        for key in controldir.format_registry.keys():
            if key in controldir.format_registry.aliases():
                continue
            if controldir.format_registry.get_info(key).hidden:
                continue
            expected = None
            if key in ("dirstate", "knit", "dirstate-tags"):
                expected = "dirstate or dirstate-tags or knit"
            elif key in ("1.14",):
                expected = "1.14"
            elif key in ("1.14-rich-root",):
                expected = "1.14-rich-root"
            self.assertRepoDescription(key, expected)

        format = controldir.format_registry.make_controldir("knit")
        format.set_branch_format(_mod_bzrbranch.BzrBranchFormat6())
        tree = self.make_branch_and_tree("unknown", format=format)
        self.assertEqual(
            "unnamed",
            info.describe_format(
                tree.controldir, tree.branch.repository, tree.branch, tree
            ),
        )

    def test_gather_location_controldir_only(self):
        bzrdir = self.make_controldir(".")
        self.assertEqual(
            [("control directory", bzrdir.user_url)],
            info.gather_location_info(control=bzrdir),
        )

    def test_gather_location_standalone(self):
        tree = self.make_branch_and_tree("tree")
        self.assertEqual(
            [("branch root", tree.controldir.root_transport.base)],
            info.gather_location_info(
                tree.branch.repository, tree.branch, tree, control=tree.controldir
            ),
        )
        self.assertEqual(
            [("branch root", tree.controldir.root_transport.base)],
            info.gather_location_info(
                tree.branch.repository, tree.branch, control=tree.controldir
            ),
        )
        return tree

    def test_gather_location_repo(self):
        srepo = self.make_repository("shared", shared=True)
        self.assertEqual(
            [("shared repository", srepo.controldir.root_transport.base)],
            info.gather_location_info(srepo, control=srepo.controldir),
        )
        urepo = self.make_repository("unshared")
        self.assertEqual(
            [("repository", urepo.controldir.root_transport.base)],
            info.gather_location_info(urepo, control=urepo.controldir),
        )

    def test_gather_location_repo_branch(self):
        srepo = self.make_repository("shared", shared=True)
        self.assertEqual(
            [("shared repository", srepo.controldir.root_transport.base)],
            info.gather_location_info(srepo, control=srepo.controldir),
        )
        tree = self.make_branch_and_tree("shared/tree")
        self.assertEqual(
            [
                ("shared repository", srepo.controldir.root_transport.base),
                ("repository branch", tree.branch.base),
            ],
            info.gather_location_info(srepo, tree.branch, tree, srepo.controldir),
        )

    def test_gather_location_light_checkout(self):
        tree = self.make_branch_and_tree("tree")
        lcheckout = tree.branch.create_checkout("lcheckout", lightweight=True)
        self.assertEqual(
            [
                ("light checkout root", lcheckout.controldir.root_transport.base),
                ("checkout of branch", tree.controldir.root_transport.base),
            ],
            self.gather_tree_location_info(lcheckout),
        )

    def test_gather_location_heavy_checkout(self):
        tree = self.make_branch_and_tree("tree")
        checkout = tree.branch.create_checkout("checkout")
        self.assertEqual(
            [
                ("checkout root", checkout.controldir.root_transport.base),
                ("checkout of branch", tree.controldir.root_transport.base),
            ],
            self.gather_tree_location_info(checkout),
        )
        light_checkout = checkout.branch.create_checkout(
            "light_checkout", lightweight=True
        )
        self.assertEqual(
            [
                ("light checkout root", light_checkout.controldir.root_transport.base),
                ("checkout root", checkout.controldir.root_transport.base),
                ("checkout of branch", tree.controldir.root_transport.base),
            ],
            self.gather_tree_location_info(light_checkout),
        )

    def test_gather_location_shared_repo_checkout(self):
        tree = self.make_branch_and_tree("tree")
        srepo = self.make_repository("shared", shared=True)
        shared_checkout = tree.branch.create_checkout("shared/checkout")
        self.assertEqual(
            [
                (
                    "repository checkout root",
                    shared_checkout.controldir.root_transport.base,
                ),
                ("checkout of branch", tree.controldir.root_transport.base),
                ("shared repository", srepo.controldir.root_transport.base),
            ],
            self.gather_tree_location_info(shared_checkout),
        )

    def gather_tree_location_info(self, tree):
        return info.gather_location_info(
            tree.branch.repository, tree.branch, tree, tree.controldir
        )

    def test_gather_location_bound(self):
        branch = self.make_branch("branch")
        bound_branch = self.make_branch("bound_branch")
        bound_branch.bind(branch)
        self.assertEqual(
            [
                ("branch root", bound_branch.controldir.root_transport.base),
                ("bound to branch", branch.controldir.root_transport.base),
            ],
            info.gather_location_info(
                bound_branch.repository, bound_branch, control=bound_branch.controldir
            ),
        )

    def test_gather_location_bound_in_repository(self):
        repo = self.make_repository("repo", shared=True)
        repo.set_make_working_trees(False)
        branch = self.make_branch("branch")
        bound_branch = controldir.ControlDir.create_branch_convenience(
            "repo/bound_branch"
        )
        try:
            bound_branch.bind(branch)
        except _mod_branch.BindingUnsupported:
            raise tests.TestNotApplicable("format does not support bound branches")
        self.assertEqual(
            [
                ("shared repository", bound_branch.repository.controldir.user_url),
                ("repository branch", bound_branch.controldir.user_url),
                ("bound to branch", branch.controldir.user_url),
            ],
            info.gather_location_info(bound_branch.repository, bound_branch),
        )

    def test_location_list(self):
        if sys.platform == "win32":
            raise tests.TestSkipped("Windows-unfriendly test")
        locs = info.LocationList("/home/foo")
        locs.add_url("a", "file:///home/foo/")
        locs.add_url("b", "file:///home/foo/bar/")
        locs.add_url("c", "file:///home/bar/bar")
        locs.add_url("d", "http://example.com/example/")
        locs.add_url("e", None)
        self.assertEqual(
            locs.locs,
            [
                ("a", "."),
                ("b", "bar"),
                ("c", "/home/bar/bar"),
                ("d", "http://example.com/example/"),
            ],
        )
        self.assertEqualDiff(
            "  a: .\n  b: bar\n  c: /home/bar/bar\n  d: http://example.com/example/\n",
            "".join(locs.get_lines()),
        )

    def test_gather_related_braches(self):
        branch = self.make_branch(".")
        branch.lock_write()
        try:
            branch.set_public_branch("baz")
            branch.set_push_location("bar")
            branch.set_parent("foo")
            branch.set_submit_branch("qux")
        finally:
            branch.unlock()
        self.assertEqual(
            [
                ("public branch", "baz"),
                ("push branch", "bar"),
                ("parent branch", "foo"),
                ("submit branch", "qux"),
            ],
            info._gather_related_branches(branch).locs,
        )
