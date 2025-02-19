# Copyright (C) 2008-2012 Canonical Ltd
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

import os
import sys

from .... import (
    bedding,
    controldir,
    errors,
    osutils,
    revisionspec,
    tests,
    transport,
    uncommit,
    workingtree,
)
from ....tests import features, per_branch, per_transport
from .. import cmds


def get_transport_scenarios():
    result = []
    basis = per_transport.transport_test_permutations()
    # Keep only the interesting ones for upload
    usable_classes = set()
    if features.paramiko.available():
        from ....transport import sftp

        usable_classes.add(sftp.SFTPTransport)
    from ....transport import local

    usable_classes.add(local.LocalTransport)
    for name, d in basis:
        t_class = d["transport_class"]
        if t_class in usable_classes:
            result.append((name, d))
    return result


def load_tests(loader, standard_tests, pattern):
    """Multiply tests for tranport implementations."""
    result = loader.suiteClass()

    # one for each transport implementation
    t_tests, remaining_tests = tests.split_suite_by_condition(
        standard_tests,
        tests.condition_isinstance(
            (
                TestFullUpload,
                TestIncrementalUpload,
                TestUploadFromRemoteBranch,
            )
        ),
    )
    tests.multiply_tests(t_tests, get_transport_scenarios(), result)

    # one for each branch format
    b_tests, remaining_tests = tests.split_suite_by_condition(
        remaining_tests, tests.condition_isinstance((TestBranchUploadLocations,))
    )
    tests.multiply_tests(b_tests, per_branch.branch_scenarios(), result)

    # No parametrization for the remaining tests
    result.addTests(remaining_tests)

    return result


class UploadUtilsMixin:
    """Helper class to write upload tests.

    This class provides helpers to simplify test writing. The emphasis is on
    easy test writing, so each tree modification is committed. This doesn't
    preclude writing tests spawning several revisions to upload more complex
    changes.
    """

    upload_dir = "upload"
    branch_dir = "branch"

    def make_branch_and_working_tree(self):
        t = transport.get_transport(self.branch_dir)
        t.ensure_base()
        branch = controldir.ControlDir.create_branch_convenience(
            t.base,
            format=controldir.format_registry.make_controldir("default"),
            force_new_tree=False,
        )
        self.tree = branch.controldir.create_workingtree()
        self.tree.commit("initial empty tree")

    def assertUpFileEqual(self, content, path, base=upload_dir):
        self.assertFileEqual(content, osutils.pathjoin(base, path))

    def assertUpPathModeEqual(self, path, expected_mode, base=upload_dir):
        # FIXME: the tests needing that assertion should depend on the server
        # ability to handle chmod so that they don't fail (or be skipped)
        # against servers that can't. Note that some breezy transports define
        # _can_roundtrip_unix_modebits in a incomplete way, this property
        # should depend on both the client and the server, not the client only.
        # But the client will know or can find if the server support chmod so
        # that's the client that will report it anyway.
        full_path = osutils.pathjoin(base, path)
        st = os.stat(full_path)
        mode = st.st_mode & 0o777
        if expected_mode == mode:
            return
        raise AssertionError(
            "For path %s, mode is %s not %s"
            % (full_path, oct(mode), oct(expected_mode))
        )

    def assertUpPathDoesNotExist(self, path, base=upload_dir):
        self.assertPathDoesNotExist(osutils.pathjoin(base, path))

    def assertUpPathExists(self, path, base=upload_dir):
        self.assertPathExists(osutils.pathjoin(base, path))

    def set_file_content(self, path, content, base=branch_dir):
        with open(osutils.pathjoin(base, path), "wb") as f:
            f.write(content)

    def add_file(self, path, content, base=branch_dir):
        self.set_file_content(path, content, base)
        self.tree.add(path)
        self.tree.commit("add file %s" % path)

    def modify_file(self, path, content, base=branch_dir):
        self.set_file_content(path, content, base)
        self.tree.commit("modify file %s" % path)

    def chmod_file(self, path, mode, base=branch_dir):
        full_path = osutils.pathjoin(base, path)
        os.chmod(full_path, mode)
        self.tree.commit("change file {} mode to {}".format(path, oct(mode)))

    def delete_any(self, path, base=branch_dir):
        self.tree.remove([path], keep_files=False)
        self.tree.commit("delete %s" % path)

    def add_dir(self, path, base=branch_dir):
        os.mkdir(osutils.pathjoin(base, path))
        self.tree.add(path)
        self.tree.commit("add directory %s" % path)

    def rename_any(self, old_path, new_path):
        self.tree.rename_one(old_path, new_path)
        self.tree.commit("rename {} into {}".format(old_path, new_path))

    def transform_dir_into_file(self, path, content, base=branch_dir):
        osutils.delete_any(osutils.pathjoin(base, path))
        self.set_file_content(path, content, base)
        self.tree.commit("change %s from dir to file" % path)

    def transform_file_into_dir(self, path, base=branch_dir):
        # bzr can't handle that kind change in a single commit without an
        # intervening bzr status (see bug #205636).
        self.tree.remove([path], keep_files=False)
        os.mkdir(osutils.pathjoin(base, path))
        self.tree.add(path)
        self.tree.commit("change %s from file to dir" % path)

    def add_symlink(self, path, target, base=branch_dir):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        os.symlink(target, osutils.pathjoin(base, path))
        self.tree.add(path)
        self.tree.commit("add symlink {} -> {}".format(path, target))

    def modify_symlink(self, path, target, base=branch_dir):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        full_path = osutils.pathjoin(base, path)
        os.unlink(full_path)
        os.symlink(target, full_path)
        self.tree.commit("modify symlink {} -> {}".format(path, target))

    def _get_cmd_upload(self):
        cmd = cmds.cmd_upload()
        # We don't want to use run_bzr here because redirected output are a
        # pain to debug. But we need to provides a valid outf.
        # XXX: Should a bug against bzr be filled about that ?

        # Short story: we don't expect any output so we may just use stdout
        cmd.outf = sys.stdout
        return cmd

    def do_full_upload(self, *args, **kwargs):
        upload = self._get_cmd_upload()
        up_url = self.get_url(self.upload_dir)
        if kwargs.get("directory") is None:
            kwargs["directory"] = self.branch_dir
        kwargs["full"] = True
        kwargs["quiet"] = True
        upload.run(up_url, *args, **kwargs)

    def do_incremental_upload(self, *args, **kwargs):
        upload = self._get_cmd_upload()
        up_url = self.get_url(self.upload_dir)
        if kwargs.get("directory") is None:
            kwargs["directory"] = self.branch_dir
        kwargs["quiet"] = True
        upload.run(up_url, *args, **kwargs)


class TestUploadMixin(UploadUtilsMixin):
    """Helper class to share tests between full and incremental uploads."""

    def _test_create_file(self, file_name):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file(file_name, b"foo")

        self.do_upload()

        self.assertUpFileEqual(b"foo", file_name)

    def test_create_file(self):
        self._test_create_file("hello")

    def test_unicode_create_file(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_create_file("hell\u00d8")

    def _test_create_file_in_dir(self, dir_name, file_name):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_dir(dir_name)
        fpath = "{}/{}".format(dir_name, file_name)
        self.add_file(fpath, b"baz")

        self.assertUpPathDoesNotExist(fpath)

        self.do_upload()

        self.assertUpFileEqual(b"baz", fpath)
        self.assertUpPathModeEqual(dir_name, 0o775)

    def test_create_file_in_dir(self):
        self._test_create_file_in_dir("dir", "goodbye")

    def test_unicode_create_file_in_dir(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_create_file_in_dir("dir\u00d8", "goodbye\u00d8")

    def test_modify_file(self):
        self.make_branch_and_working_tree()
        self.add_file("hello", b"foo")
        self.do_full_upload()
        self.modify_file("hello", b"bar")

        self.assertUpFileEqual(b"foo", "hello")

        self.do_upload()

        self.assertUpFileEqual(b"bar", "hello")

    def _test_rename_one_file(self, old_name, new_name):
        self.make_branch_and_working_tree()
        self.add_file(old_name, b"foo")
        self.do_full_upload()
        self.rename_any(old_name, new_name)

        self.assertUpFileEqual(b"foo", old_name)

        self.do_upload()

        self.assertUpFileEqual(b"foo", new_name)

    def test_rename_one_file(self):
        self._test_rename_one_file("hello", "goodbye")

    def test_unicode_rename_one_file(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_rename_one_file("hello\u00d8", "goodbye\u00d8")

    def test_rename_and_change_file(self):
        self.make_branch_and_working_tree()
        self.add_file("hello", b"foo")
        self.do_full_upload()
        self.rename_any("hello", "goodbye")
        self.modify_file("goodbye", b"bar")

        self.assertUpFileEqual(b"foo", "hello")

        self.do_upload()

        self.assertUpFileEqual(b"bar", "goodbye")

    def test_rename_two_files(self):
        self.make_branch_and_working_tree()
        self.add_file("a", b"foo")
        self.add_file("b", b"qux")
        self.do_full_upload()
        # We rely on the assumption that bzr will topologically sort the
        # renames which will cause a -> b to appear *before* b -> c
        self.rename_any("b", "c")
        self.rename_any("a", "b")

        self.assertUpFileEqual(b"foo", "a")
        self.assertUpFileEqual(b"qux", "b")

        self.do_upload()

        self.assertUpFileEqual(b"foo", "b")
        self.assertUpFileEqual(b"qux", "c")

    def test_upload_revision(self):
        self.make_branch_and_working_tree()  # rev1
        self.do_full_upload()
        self.add_file("hello", b"foo")  # rev2
        self.modify_file("hello", b"bar")  # rev3

        self.assertUpPathDoesNotExist("hello")

        revspec = revisionspec.RevisionSpec.from_string("2")
        self.do_upload(revision=[revspec])

        self.assertUpFileEqual(b"foo", "hello")

    def test_no_upload_when_changes(self):
        self.make_branch_and_working_tree()
        self.add_file("a", b"foo")
        self.set_file_content("a", b"bar")

        self.assertRaises(errors.UncommittedChanges, self.do_upload)

    def test_no_upload_when_conflicts(self):
        self.make_branch_and_working_tree()
        self.add_file("a", b"foo")
        self.run_bzr("branch branch other")
        self.modify_file("a", b"bar")
        other_tree = workingtree.WorkingTree.open("other")
        self.set_file_content("a", b"baz", "other/")
        other_tree.commit("modify file a")

        self.run_bzr("merge -d branch other", retcode=1)

        self.assertRaises(errors.UncommittedChanges, self.do_upload)

    def _test_change_file_into_dir(self, file_name):
        self.make_branch_and_working_tree()
        self.add_file(file_name, b"foo")
        self.do_full_upload()
        self.transform_file_into_dir(file_name)
        fpath = "{}/{}".format(file_name, "file")
        self.add_file(fpath, b"bar")

        self.assertUpFileEqual(b"foo", file_name)

        self.do_upload()

        self.assertUpFileEqual(b"bar", fpath)

    def test_change_file_into_dir(self):
        self._test_change_file_into_dir("hello")

    def test_unicode_change_file_into_dir(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_change_file_into_dir("hello\u00d8")

    def test_change_dir_into_file(self):
        self.make_branch_and_working_tree()
        self.add_dir("hello")
        self.add_file("hello/file", b"foo")
        self.do_full_upload()
        self.delete_any("hello/file")
        self.transform_dir_into_file("hello", b"bar")

        self.assertUpFileEqual(b"foo", "hello/file")

        self.do_upload()

        self.assertUpFileEqual(b"bar", "hello")

    def _test_make_file_executable(self, file_name):
        self.make_branch_and_working_tree()
        self.add_file(file_name, b"foo")
        self.chmod_file(file_name, 0o664)
        self.do_full_upload()
        self.chmod_file(file_name, 0o755)

        self.assertUpPathModeEqual(file_name, 0o664)

        self.do_upload()

        self.assertUpPathModeEqual(file_name, 0o775)

    def test_make_file_executable(self):
        self._test_make_file_executable("hello")

    def test_unicode_make_file_executable(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_make_file_executable("hello\u00d8")

    def test_create_symlink(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_symlink("link", "target")

        self.do_upload()

        self.assertUpPathExists("link")

    def test_rename_symlink(self):
        self.make_branch_and_working_tree()
        old_name, new_name = "old-link", "new-link"
        self.add_symlink(old_name, "target")
        self.do_full_upload()

        self.rename_any(old_name, new_name)

        self.do_upload()

        self.assertUpPathExists(new_name)

    def get_upload_auto(self):
        # We need a fresh branch to check what has been saved on disk
        b = controldir.ControlDir.open(self.tree.basedir).open_branch()
        return b.get_config_stack().get("upload_auto")

    def test_upload_auto(self):
        """Test that upload --auto sets the upload_auto option"""
        self.make_branch_and_working_tree()

        self.add_file("hello", b"foo")
        self.assertFalse(self.get_upload_auto())
        self.do_full_upload(auto=True)
        self.assertUpFileEqual(b"foo", "hello")
        self.assertTrue(self.get_upload_auto())

        # and check that it stays set until it is unset
        self.add_file("bye", b"bar")
        self.do_full_upload()
        self.assertUpFileEqual(b"bar", "bye")
        self.assertTrue(self.get_upload_auto())

    def test_upload_noauto(self):
        """Test that upload --no-auto unsets the upload_auto option"""
        self.make_branch_and_working_tree()

        self.add_file("hello", b"foo")
        self.do_full_upload(auto=True)
        self.assertUpFileEqual(b"foo", "hello")
        self.assertTrue(self.get_upload_auto())

        self.add_file("bye", b"bar")
        self.do_full_upload(auto=False)
        self.assertUpFileEqual(b"bar", "bye")
        self.assertFalse(self.get_upload_auto())

        # and check that it stays unset until it is set
        self.add_file("again", b"baz")
        self.do_full_upload()
        self.assertUpFileEqual(b"baz", "again")
        self.assertFalse(self.get_upload_auto())

    def test_upload_from_subdir(self):
        self.make_branch_and_working_tree()
        self.build_tree(["branch/foo/", "branch/foo/bar"])
        self.tree.add(["foo/", "foo/bar"])
        self.tree.commit("Add directory")
        self.do_full_upload(directory="branch/foo")

    def test_upload_revid_path_in_dir(self):
        self.make_branch_and_working_tree()
        self.add_dir("dir")
        self.add_file("dir/goodbye", b"baz")

        revid_path = "dir/revid-path"
        self.tree.branch.get_config_stack().set("upload_revid_location", revid_path)
        self.assertUpPathDoesNotExist(revid_path)

        self.do_full_upload()

        self.add_file("dir/hello", b"foo")

        self.do_upload()

        self.assertUpPathExists(revid_path)
        self.assertUpFileEqual(b"baz", "dir/goodbye")
        self.assertUpFileEqual(b"foo", "dir/hello")

    def test_ignore_file(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file(".bzrignore-upload", b"foo")
        self.add_file("foo", b"bar")

        self.do_upload()

        self.assertUpPathDoesNotExist("foo")

    def test_ignore_regexp(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file(".bzrignore-upload", b"f*")
        self.add_file("foo", b"bar")

        self.do_upload()

        self.assertUpPathDoesNotExist("foo")

    def test_ignore_directory(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file(".bzrignore-upload", b"dir")
        self.add_dir("dir")

        self.do_upload()

        self.assertUpPathDoesNotExist("dir")

    def test_ignore_nested_directory(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file(".bzrignore-upload", b"dir")
        self.add_dir("dir")
        self.add_dir("dir/foo")
        self.add_file("dir/foo/bar", b"bar contents")

        self.do_upload()

        self.assertUpPathDoesNotExist("dir")
        self.assertUpPathDoesNotExist("dir/foo/bar")

    def test_ignore_change_file_into_dir(self):
        self.make_branch_and_working_tree()
        self.add_file("hello", b"foo")
        self.do_full_upload()
        self.add_file(".bzrignore-upload", b"hello")
        self.transform_file_into_dir("hello")
        self.add_file("hello/file", b"bar")

        self.assertUpFileEqual(b"foo", "hello")

        self.do_upload()

        self.assertUpFileEqual(b"foo", "hello")

    def test_ignore_change_dir_into_file(self):
        self.make_branch_and_working_tree()
        self.add_dir("hello")
        self.add_file("hello/file", b"foo")
        self.do_full_upload()

        self.add_file(".bzrignore-upload", b"hello")
        self.delete_any("hello/file")
        self.transform_dir_into_file("hello", b"bar")

        self.assertUpFileEqual(b"foo", "hello/file")

        self.do_upload()

        self.assertUpFileEqual(b"foo", "hello/file")

    def test_ignore_delete_dir_in_subdir(self):
        self.make_branch_and_working_tree()
        self.add_dir("dir")
        self.add_dir("dir/subdir")
        self.add_file("dir/subdir/a", b"foo")
        self.do_full_upload()
        self.add_file(".bzrignore-upload", b"dir/subdir")
        self.rename_any("dir/subdir/a", "dir/a")
        self.delete_any("dir/subdir")

        self.assertUpFileEqual(b"foo", "dir/subdir/a")

        self.do_upload()

        # The file in the dir is not ignored. This a bit contrived but
        # indicates that we may encounter problems when ignored items appear
        # and disappear... -- vila 100106
        self.assertUpFileEqual(b"foo", "dir/a")


class TestFullUpload(tests.TestCaseWithTransport, TestUploadMixin):
    do_upload = TestUploadMixin.do_full_upload

    def test_full_upload_empty_tree(self):
        self.make_branch_and_working_tree()

        self.do_full_upload()

        revid_path = self.tree.branch.get_config_stack().get("upload_revid_location")
        self.assertUpPathExists(revid_path)

    def test_invalid_revspec(self):
        self.make_branch_and_working_tree()
        rev1 = revisionspec.RevisionSpec.from_string("1")
        rev2 = revisionspec.RevisionSpec.from_string("2")

        self.assertRaises(
            errors.CommandError, self.do_incremental_upload, revision=[rev1, rev2]
        )

    def test_create_remote_dir_twice(self):
        self.make_branch_and_working_tree()
        self.add_dir("dir")
        self.do_full_upload()
        self.add_file("dir/goodbye", b"baz")

        self.assertUpPathDoesNotExist("dir/goodbye")

        self.do_full_upload()

        self.assertUpFileEqual(b"baz", "dir/goodbye")
        self.assertUpPathModeEqual("dir", 0o775)


class TestIncrementalUpload(tests.TestCaseWithTransport, TestUploadMixin):
    do_upload = TestUploadMixin.do_incremental_upload

    # XXX: full upload doesn't handle deletions....

    def test_delete_one_file(self):
        self.make_branch_and_working_tree()
        self.add_file("hello", b"foo")
        self.do_full_upload()
        self.delete_any("hello")

        self.assertUpFileEqual(b"foo", "hello")

        self.do_upload()

        self.assertUpPathDoesNotExist("hello")

    def test_delete_dir_and_subdir(self):
        self.make_branch_and_working_tree()
        self.add_dir("dir")
        self.add_dir("dir/subdir")
        self.add_file("dir/subdir/a", b"foo")
        self.do_full_upload()
        self.rename_any("dir/subdir/a", "a")
        self.delete_any("dir/subdir")
        self.delete_any("dir")

        self.assertUpFileEqual(b"foo", "dir/subdir/a")

        self.do_upload()

        self.assertUpPathDoesNotExist("dir/subdir/a")
        self.assertUpPathDoesNotExist("dir/subdir")
        self.assertUpPathDoesNotExist("dir")
        self.assertUpFileEqual(b"foo", "a")

    def test_delete_one_file_rename_to_deleted(self):
        self.make_branch_and_working_tree()
        self.add_file("a", b"foo")
        self.add_file("b", b"bar")
        self.do_full_upload()
        self.delete_any("a")
        self.rename_any("b", "a")

        self.assertUpFileEqual(b"foo", "a")

        self.do_upload()

        self.assertUpPathDoesNotExist("b")
        self.assertUpFileEqual(b"bar", "a")

    def test_rename_outside_dir_delete_dir(self):
        self.make_branch_and_working_tree()
        self.add_dir("dir")
        self.add_file("dir/a", b"foo")
        self.do_full_upload()
        self.rename_any("dir/a", "a")
        self.delete_any("dir")

        self.assertUpFileEqual(b"foo", "dir/a")

        self.do_upload()

        self.assertUpPathDoesNotExist("dir/a")
        self.assertUpPathDoesNotExist("dir")
        self.assertUpFileEqual(b"foo", "a")

    def test_delete_symlink(self):
        self.make_branch_and_working_tree()
        self.add_symlink("link", "target")
        self.do_full_upload()
        self.delete_any("link")

        self.do_upload()

        self.assertUpPathDoesNotExist("link")

    def test_upload_for_the_first_time_do_a_full_upload(self):
        self.make_branch_and_working_tree()
        self.add_file("hello", b"bar")

        revid_path = self.tree.branch.get_config_stack().get("upload_revid_location")
        self.assertUpPathDoesNotExist(revid_path)

        self.do_upload()

        self.assertUpFileEqual(b"bar", "hello")

    def test_ignore_delete_one_file(self):
        self.make_branch_and_working_tree()
        self.add_file("hello", b"foo")
        self.do_full_upload()
        self.add_file(".bzrignore-upload", b"hello")
        self.delete_any("hello")

        self.assertUpFileEqual(b"foo", "hello")

        self.do_upload()

        self.assertUpFileEqual(b"foo", "hello")


class TestBranchUploadLocations(per_branch.TestCaseWithBranch):
    def test_get_upload_location_unset(self):
        conf = self.get_branch().get_config_stack()
        self.assertEqual(None, conf.get("upload_location"))

    def test_get_push_location_exact(self):
        bedding.ensure_config_dir_exists()
        fn = bedding.locations_config_path()
        b = self.get_branch()
        with open(fn, "w") as f:
            f.write("[%s]\nupload_location=foo\n" % b.base.rstrip("/"))
        self.assertEqual("foo", b.get_config_stack().get("upload_location"))

    def test_set_push_location(self):
        conf = self.get_branch().get_config_stack()
        conf.set("upload_location", "foo")
        self.assertEqual("foo", conf.get("upload_location"))


class TestUploadFromRemoteBranch(tests.TestCaseWithTransport, UploadUtilsMixin):
    remote_branch_dir = "remote_branch"

    def setUp(self):
        super().setUp()
        if self._will_escape_isolation(self.transport_server):
            # FIXME: Some policy search ends up above the user home directory
            # and are seen as attemps to escape test isolation
            raise tests.TestNotApplicable("Escaping test isolation")
        self.remote_branch_url = self.make_remote_branch_without_working_tree()

    @staticmethod
    def _will_escape_isolation(transport_server):
        if not features.paramiko.available():
            return False
        from ....tests import stub_sftp

        if transport_server is stub_sftp.SFTPHomeDirServer:
            return True
        return False

    def make_remote_branch_without_working_tree(self):
        """Creates a branch without working tree to upload from.

        It's created from the existing self.branch_dir one which still has its
        working tree.
        """
        self.make_branch_and_working_tree()
        self.add_file("hello", b"foo")

        remote_branch_url = self.get_url(self.remote_branch_dir)
        self.run_bzr(["push", remote_branch_url, "--directory", self.branch_dir])
        return remote_branch_url

    def test_no_upload_to_remote_working_tree(self):
        cmd = self._get_cmd_upload()
        up_url = self.get_url(self.branch_dir)
        # Let's try to upload from the just created remote branch into the
        # branch (which has a working tree).
        self.assertRaises(
            cmds.CannotUploadToWorkingTree,
            cmd.run,
            up_url,
            directory=self.remote_branch_url,
        )

    def test_upload_without_working_tree(self):
        self.do_full_upload(directory=self.remote_branch_url)
        self.assertUpFileEqual(b"foo", "hello")


class TestUploadDiverged(tests.TestCaseWithTransport, UploadUtilsMixin):
    def setUp(self):
        super().setUp()
        self.diverged_tree = self.make_diverged_tree_and_upload_location()

    def make_diverged_tree_and_upload_location(self):
        tree_a = self.make_branch_and_tree("tree_a")
        tree_a.commit("message 1", rev_id=b"rev1")
        tree_a.commit("message 2", rev_id=b"rev2a")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        uncommit.uncommit(tree_b.branch, tree=tree_b)
        tree_b.commit("message 2", rev_id=b"rev2b")
        # upload tree a
        self.do_full_upload(directory=tree_a.basedir)
        return tree_b

    def assertRevidUploaded(self, revid):
        t = self.get_transport(self.upload_dir)
        uploaded_revid = t.get_bytes(".bzr-upload.revid")
        self.assertEqual(revid, uploaded_revid)

    def test_cant_upload_diverged(self):
        self.assertRaises(
            cmds.DivergedUploadedTree,
            self.do_incremental_upload,
            directory=self.diverged_tree.basedir,
        )
        self.assertRevidUploaded(b"rev2a")

    def test_upload_diverged_with_overwrite(self):
        self.do_incremental_upload(directory=self.diverged_tree.basedir, overwrite=True)
        self.assertRevidUploaded(b"rev2b")


class TestUploadBadRemoteReivd(tests.TestCaseWithTransport, UploadUtilsMixin):
    def test_raises_on_wrong_revid(self):
        tree = self.make_branch_and_working_tree()
        self.do_full_upload()
        # Put a fake revid on the remote branch
        t = self.get_transport(self.upload_dir)
        t.put_bytes(".bzr-upload.revid", b"fake")
        # Make a change
        self.add_file("foo", b"bar\n")
        self.assertRaises(cmds.DivergedUploadedTree, self.do_full_upload)
