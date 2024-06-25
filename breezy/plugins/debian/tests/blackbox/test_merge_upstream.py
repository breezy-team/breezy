#    test_merge_upstream.py -- Blackbox tests for merge-upstream.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os.path

from ..... import export
from ...import_dsc import (
    DistributionBranch,
    DistributionBranchSet,
)
from ...util import (
    md5sum_filename,
)
from .. import (
    BuilddebTestCase,
    SourcePackageBuilder,
)


class Fixture:
    """A test fixture."""

    def __init__(self):
        pass

    def setUp(self, test_case):
        test_case.addCleanup(self.tearDown)

    def tearDown(self):
        pass


class Upstream(Fixture):
    """An upstream.

    :ivar tree: The tree of the upstream.
    """

    def setUp(self, test_case):
        Fixture.setUp(self, test_case)
        treename = test_case.getUniqueString()
        tree = test_case.make_branch_and_tree(treename)
        filename = test_case.getUniqueString()
        test_case.build_tree([f"{treename}/{filename}"])
        tree.add([filename])
        tree.commit(test_case.getUniqueString())
        self.tree = tree


class ExportedTarball(Fixture):
    """An exported tarball 'release'."""

    def __init__(self, upstream, version):
        self.upstream = upstream
        self.version = version

    def setUp(self, test_case):
        filename = "project-{}.tar.gz".format(self.version)
        tree = self.upstream.tree.branch.repository.revision_tree(
            self.upstream.tree.branch.last_revision()
        )
        export.export(tree, filename)
        self.tarball = filename


class DHMadePackage(Fixture):
    """A package made via dh-make."""

    def __init__(self, tar, upstream):
        self.tar = tar
        self.upstream = upstream

    def setUp(self, test_case):
        branchpath = test_case.getUniqueString()
        tree = self.upstream.tree.controldir.sprout(branchpath).open_workingtree()
        db = DistributionBranch(
            tree.branch, tree.branch, tree=tree, pristine_upstream_tree=tree
        )
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        db.import_upstream_tarballs(
            [(self.tar.tarball, None, md5sum_filename(self.tar.tarball))],
            "foo",
            str(self.tar.version),
            {None: [(tree.branch.last_revision(), "")]},
        )
        package_builder = SourcePackageBuilder("foo", str(self.tar.version) + "-1")
        package_builder.add_default_control()
        package_builder.write_debian_files(branchpath)
        tree.smart_add([tree.basedir])
        tree.commit("debianised.")
        self.tree = tree


class FileMovedReplacedUpstream(Fixture):
    """An upstream that has been changed by moving and replacing a file."""

    def __init__(self, upstream):
        self.upstream = upstream

    def setUp(self, test_case):
        branchpath = test_case.getUniqueString()
        tree = self.upstream.tree.controldir.sprout(branchpath).open_workingtree()
        self.tree = tree
        with tree.lock_write():
            newpath = test_case.getUniqueString()
            for child in tree.iter_child_entries(""):
                if child.kind == "file":
                    oldpath = child.name
            tree.rename_one(oldpath, newpath)
            test_case.build_tree([f"{os.path.basename(tree.basedir)}/{oldpath}"])
            tree.add([oldpath])
            tree.commit("yo, renaming and replacing")


class TestMergeUpstream(BuilddebTestCase):
    def test_merge_upstream_available(self):
        self.run_bzr("merge-upstream --help")

    def make_upstream(self):
        result = Upstream()
        result.setUp(self)
        return result

    def release_upstream(self, upstream):
        version = str(self.getUniqueInteger())
        upstream.tree.branch.tags.set_tag(version, upstream.tree.branch.last_revision())
        tar = ExportedTarball(upstream, version=version)
        tar.setUp(self)
        return tar

    def import_upstream(self, tar, upstream):
        packaging = DHMadePackage(tar, upstream)
        packaging.setUp(self)
        return packaging

    def file_moved_replaced_upstream(self, upstream):
        result = FileMovedReplacedUpstream(upstream)
        result.setUp(self)
        return result

    def test_smoke_renamed_file(self):
        # When a file is renamed by upstream, it should still import ok.
        upstream = self.make_upstream()
        rel1 = self.release_upstream(upstream)
        package = self.import_upstream(rel1, upstream)
        changed_upstream = self.file_moved_replaced_upstream(upstream)
        rel2 = self.release_upstream(changed_upstream)
        (out, err) = self.run_bzr(
            [
                "merge-upstream",
                "--version",
                str(rel2.version),
                os.path.abspath(rel2.tarball),
            ],
            working_dir=package.tree.basedir,
        )
        self.assertEqual(out, "")
        self.assertEqual(
            err,
            "Using distribution unstable\n"
            "Using version string 8.\n"
            "All changes applied successfully.\n"
            "The new upstream version has been imported.\n"
            "You should now review the changes and then commit.\n",
        )

    def test_upstream_branch_revision_guessed(self):
        # When an upstream branch is specified but does not have the
        # upstream version, 'bzr merge-upstream' should guess.
        upstream = self.make_upstream()
        rel1 = self.release_upstream(upstream)
        package = self.import_upstream(rel1, upstream)
        changed_upstream = self.file_moved_replaced_upstream(upstream)
        rel2 = self.release_upstream(changed_upstream)
        (out, err) = self.run_bzr(
            [
                "merge-upstream",
                "--version",
                str(rel2.version),
                os.path.abspath(rel2.tarball),
                changed_upstream.tree.basedir,
            ],
            working_dir=package.tree.basedir,
        )
        self.assertEqual(out, "")
        self.knownFailure("conflicts introduced by rename detection")
        self.assertEqual(
            err,
            "Using distribution unstable\n"
            "Using version string 8.\n"
            "No upstream upstream-revision format specified, trying tag:8\n"
            "All changes applied successfully.\n"
            "The new upstream version has been imported.\n"
            "You should now review the changes and then commit.\n",
        )

    def test_upstream_branch_revision_not_found(self):
        # When an upstream branch is specified but does not have the
        # upstream version, 'bzr merge-upstream' should complain.
        upstream = self.make_upstream()
        rel1 = self.release_upstream(upstream)
        package = self.import_upstream(rel1, upstream)
        changed_upstream = self.file_moved_replaced_upstream(upstream)
        rel2 = self.release_upstream(changed_upstream)
        changed_upstream.tree.branch.tags.delete_tag("8")
        self.run_bzr_error(
            [
                "Using version string 8.",
                "brz: ERROR: Version 8 can not be found in upstream branch "
                "<UpstreamBranchSource for '.*'>. Specify the revision "
                "manually using --revision or adjust "
                "'export-upstream-revision' in the configuration.",
            ],
            [
                "merge-upstream",
                "--version",
                str(rel2.version),
                os.path.abspath(rel2.tarball),
                changed_upstream.tree.basedir,
            ],
            working_dir=package.tree.basedir,
        )

    def test_upstream_branch_revision(self):
        # It is sufficient to just specify an upstream revision
        upstream = self.make_upstream()
        rel1 = self.release_upstream(upstream)
        package = self.import_upstream(rel1, upstream)
        changed_upstream = self.file_moved_replaced_upstream(upstream)
        self.release_upstream(changed_upstream)
        package_path = package.tree.basedir
        os.mkdir(os.path.join(package_path, ".bzr-builddeb/"))
        with open(os.path.join(package_path, ".bzr-builddeb/local.conf"), "w") as f:
            f.write(
                "[BUILDDEB]\n" "upstream-branch = {}\n".format(changed_upstream.tree.basedir)
            )

        (out, err) = self.run_bzr(
            [
                "merge-upstream",
                "-rrevid:{}".format(changed_upstream.tree.last_revision().decode("utf-8")),
            ],
            working_dir=package.tree.basedir,
        )
        self.assertEqual(out, "")
        self.assertContainsRe(err, "Using version string 8.")

    def test_upstream_branch_revision_requires_upstream(self):
        # --revision requires a valid upstreambranch
        upstream = self.make_upstream()
        rel1 = self.release_upstream(upstream)
        package = self.import_upstream(rel1, upstream)
        changed_upstream = self.file_moved_replaced_upstream(upstream)
        self.release_upstream(changed_upstream)
        with open(package.tree.abspath("debian/watch"), "w") as f:
            f.write("version=4\nhttp://example.com/ bar-\\d.tar.gz\n")
        (out, err) = self.run_bzr(
            ["merge-upstream", "-r8"], working_dir=package.tree.basedir, retcode=3
        )
        self.assertEqual(out, "")
        self.assertEqual(
            err,
            "Using distribution unstable\n"
            "brz: ERROR: --revision can only be used with a "
            "valid upstream branch\n",
        )

    def test_hooks(self):
        upstream = self.make_upstream()
        rel1 = self.release_upstream(upstream)
        package = self.import_upstream(rel1, upstream)
        package_path = package.tree.basedir
        os.mkdir(os.path.join(package_path, ".bzr-builddeb/"))
        with open(os.path.join(package_path, ".bzr-builddeb/local.conf"), "w") as f:
            f.write("[HOOKS]\nmerge-upstream = touch muhook\n")
        changed_upstream = self.file_moved_replaced_upstream(upstream)
        rel2 = self.release_upstream(changed_upstream)
        self.run_bzr(
            [
                "merge-upstream",
                "--version",
                str(rel2.version),
                os.path.abspath(rel2.tarball),
            ],
            working_dir=package.tree.basedir,
        )
        self.assertPathExists(os.path.join(package.tree.basedir, "muhook"))

    def test_new_package(self):
        upstream = self.make_upstream()
        tree = upstream.tree.controldir.sprout("package").open_workingtree()
        rel1 = self.release_upstream(upstream)
        self.run_bzr(
            [
                "merge-upstream",
                "--version",
                str(rel1.version),
                "--package",
                "bar",
                os.path.abspath(rel1.tarball),
            ],
            working_dir=tree.basedir,
        )

    def test_new_package_from_empty_branch(self):
        upstream = self.make_upstream()
        tree = self.make_branch_and_tree("package")
        rel1 = self.release_upstream(upstream)
        self.run_bzr(
            [
                "merge-upstream",
                "--version",
                str(rel1.version),
                "--package",
                "bar",
                os.path.abspath(rel1.tarball),
            ],
            working_dir=tree.basedir,
        )


# vim: ts=4 sts=4 sw=4
