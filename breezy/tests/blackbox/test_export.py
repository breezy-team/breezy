# Copyright (C) 2005-2011, 2016 Canonical Ltd
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


"""Black-box tests for brz export."""

import os
import stat
import tarfile
import time
import zipfile
from io import BytesIO

from ... import osutils
from ...archive import zip
from .. import TestCaseWithTransport, features


class TestExport(TestCaseWithTransport):
    # On Windows, if we fail to set the binary bit, and a '\r' or '\n'
    # ends up in the data stream, we will get corruption. Add a fair amount
    # of random data, to help ensure there is at least one.
    _file_content = (
        b"!\r\n\t\n \r"
        + b"r29trp9i1r8k0e24c2o7mcx2isrlaw7toh1hv2mtst3o1udkl36v9xn2z8kt\n"
        b"tvjn7e3i9cj1qs1rw9gcye9w72cbdueiufw8nky7bs08lwggir59d62knecp\n"
        b"7s0537r8sg3e8hdnidji49rswo47c3j8190nh8emef2b6j1mf5kdq45nt3f5\n"
        b"1sz9u7fuzrm4w8bebre7p62sh5os2nkj2iiyuk9n0w0pjpdulu9k2aajejah\n"
        b"ini90ny40qzs12ajuy0ua6l178n93lvy2atqngnntsmtlmqx7yhp0q9a1xr4\n"
        b"1n69kgbo6qu9osjpqq83446r00jijtcstzybfqwm1lnt9spnri2j07bt7bbh\n"
        b"rf3ejatdxta83te2s0pt9rc4hidgy3d2pc53p4wscdt2b1dfxdj9utf5m17f\n"
        b"f03oofcau950o090vyx6m72vfkywo7gp3ajzi6uk02dwqwtumq4r44xx6ho7\n"
        b"nhynborjdjep5j53f9548msb7gd3x9a1xveb4s8zfo6cbdw2kdngcrbakwu8\n"
        b"ql5a8l94gplkwr7oypw5nt1gj5i3xwadyjfr3lb61tfkz31ba7uda9knb294\n"
        b"1azhfta0q3ry9x36lxyanvhp0g5z0t5a0i4wnoc8p4htexi915y1cnw4nznn\n"
        b"aj70dvp88ifiblv2bsp98hz570teinj8g472ddxni9ydmazfzwtznbf3hrg6\n"
        b"84gigirjt6n2yagf70036m8d73cz0jpcighpjtxsmbgzbxx7nb4ewq6jbgnc\n"
        b"hux1b0qtsdi0zfhj6g1otf5jcldmtdvuon8y1ttszkqw3ograwi25yl921hy\n"
        b"izgscmfha9xdhxxabs07b40secpw22ah9iwpbmsns6qz0yr6fswto3ft2ez5\n"
        b"ngn48pdfxj1pw246drmj1y2ll5af5w7cz849rapzd9ih7qvalw358co0yzrs\n"
        b"xan9291d1ivjku4o5gjrsnmllrqwxwy86pcivinbmlnzasa9v3o22lgv4uyd\n"
        b"q8kw77bge3hr5rr5kzwjxk223bkmo3z9oju0954undsz8axr3kb3730otrcr\n"
        b"9cwhu37htnizdwxmpoc5qmobycfm7ubbykfumv6zgkl6b8zlslwl7a8b81vz\n"
        b"3weqkvv5csfza9xvwypr6lo0t03fwp0ihmci3m1muh0lf2u30ze0hjag691j\n"
        b"27fjtd3e3zbiin5n2hq21iuo09ukbs73r5rt7vaw6axvoilvdciir9ugjh2c\n"
        b"na2b8dr0ptftoyhyxv1iwg661y338e28fhz4xxwgv3hnoe98ydfa1oou45vj\n"
        b"ln74oac2keqt0agbylrqhfscin7ireae2bql7z2le823ksy47ud57z8ctomp\n"
        b"31s1vwbczdjwqp0o2jc7mkrurvzg8mj2zwcn2iily4gcl4sy4fsh4rignlyz\n"
    )

    def make_basic_tree(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/a", self._file_content)])
        tree.add("a")
        tree.commit("1")
        return tree

    def make_tree_with_extra_bzr_files(self):
        tree = self.make_basic_tree()
        self.build_tree_contents([("tree/.bzrrules", b"")])
        self.build_tree(["tree/.bzr-adir/", "tree/.bzr-adir/afile"])
        tree.add([".bzrrules", ".bzr-adir/", ".bzr-adir/afile"])

        self.run_bzr("ignore something -d tree")
        tree.commit("2")
        return tree

    def test_tar_export_ignores_bzr(self):
        tree = self.make_tree_with_extra_bzr_files()

        self.assertTrue(tree.has_filename(".bzrignore"))
        self.assertTrue(tree.has_filename(".bzrrules"))
        self.assertTrue(tree.has_filename(".bzr-adir"))
        self.assertTrue(tree.has_filename(".bzr-adir/afile"))
        self.run_bzr("export test.tar.gz -d tree")
        with tarfile.open("test.tar.gz") as ball:
            # Make sure the tarball contains 'a', but does not contain
            # '.bzrignore'.
            self.assertEqual(["test/a"], sorted(ball.getnames()))

    def test_tar_export_unicode_filename(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree("tar")
        # FIXME: using fname = u'\xe5.txt' below triggers a bug revealed since
        # bzr.dev revno 4216 but more related to OSX/working trees/unicode than
        # export itself --vila 20090406
        fname = "\N{EURO SIGN}.txt"
        self.build_tree(["tar/" + fname])
        tree.add([fname])
        tree.commit("first")

        self.run_bzr("export test.tar -d tar")
        with tarfile.open("test.tar") as ball:
            # all paths are prefixed with the base name of the tarball
            self.assertEqual(
                ["test/" + fname], [osutils.safe_unicode(n) for n in ball.getnames()]
            )

    def test_tar_export_unicode_basedir(self):
        """Test for bug #413406."""
        self.requireFeature(features.UnicodeFilenameFeature)
        basedir = "\N{EURO SIGN}"
        os.mkdir(basedir)
        self.run_bzr(["init", basedir])
        self.run_bzr(["export", "--format", "tgz", "test.tar.gz", "-d", basedir])

    def test_zip_export_ignores_bzr(self):
        tree = self.make_tree_with_extra_bzr_files()

        self.assertTrue(tree.has_filename(".bzrignore"))
        self.assertTrue(tree.has_filename(".bzrrules"))
        self.assertTrue(tree.has_filename(".bzr-adir"))
        self.assertTrue(tree.has_filename(".bzr-adir/afile"))
        self.run_bzr("export test.zip -d tree")

        zfile = zipfile.ZipFile("test.zip")
        # Make sure the zipfile contains 'a', but does not contain
        # '.bzrignore'.
        self.assertEqual(["test/a"], sorted(zfile.namelist()))

    # TODO: This really looks like something that should be using permutation
    #       testing. Though the actual setup and teardown functions are pretty
    #       different for each
    def assertZipANameAndContent(self, zfile, root=""):
        """The file should only contain name 'a' and _file_content."""
        fname = root + "a"
        self.assertEqual([fname], sorted(zfile.namelist()))
        zfile.testzip()
        self.assertEqualDiff(self._file_content, zfile.read(fname))

    def test_zip_export_stdout(self):
        self.make_basic_tree()
        contents = self.run_bzr_raw("export -d tree --format=zip -")[0]
        self.assertZipANameAndContent(zipfile.ZipFile(BytesIO(contents)))

    def test_zip_export_file(self):
        self.make_basic_tree()
        self.run_bzr("export -d tree test.zip")
        self.assertZipANameAndContent(zipfile.ZipFile("test.zip"), root="test/")

    def assertTarANameAndContent(self, ball, root=""):
        fname = root + "a"
        ball_iter = iter(ball)
        tar_info = next(ball_iter)
        self.assertEqual(fname, tar_info.name)
        self.assertEqual(tarfile.REGTYPE, tar_info.type)
        self.assertEqual(len(self._file_content), tar_info.size)
        f = ball.extractfile(tar_info)
        if self._file_content != f.read():
            self.fail(
                "File content has been corrupted."
                " Check that all streams are handled in binary mode."
            )
        # There should be no other files in the tarball
        self.assertRaises(StopIteration, next, ball_iter)

    def run_tar_export_disk_and_stdout(self, extension, tarfile_flags):
        self.make_basic_tree()
        fname = f"test.{extension}"
        self.run_bzr(f"export -d tree {fname}")
        mode = f"r|{tarfile_flags}"
        with tarfile.open(fname, mode=mode) as ball:
            self.assertTarANameAndContent(ball, root="test/")
        content = self.run_bzr_raw(f"export -d tree --format={extension} -")[0]
        with tarfile.open(mode=mode, fileobj=BytesIO(content)) as ball:
            self.assertTarANameAndContent(ball, root="")

    def test_tar_export(self):
        self.run_tar_export_disk_and_stdout("tar", "")

    def test_tgz_export(self):
        self.run_tar_export_disk_and_stdout("tgz", "gz")

    def test_tbz2_export(self):
        self.run_tar_export_disk_and_stdout("tbz2", "bz2")

    def test_zip_export_unicode(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree("zip")
        fname = "\N{EURO SIGN}.txt"
        self.build_tree(["zip/" + fname])
        tree.add([fname])
        tree.commit("first")

        os.chdir("zip")
        self.run_bzr("export test.zip")
        zfile = zipfile.ZipFile("test.zip")
        # all paths are prefixed with the base name of the zipfile
        self.assertEqual(["test/" + fname], sorted(zfile.namelist()))

    def test_zip_export_directories(self):
        tree = self.make_branch_and_tree("zip")
        self.build_tree(["zip/a", "zip/b/", "zip/b/c", "zip/d/"])
        tree.add(["a", "b", "b/c", "d"])
        tree.commit("init")

        os.chdir("zip")
        self.run_bzr("export test.zip")
        zfile = zipfile.ZipFile("test.zip")
        names = sorted(zfile.namelist())

        # even on win32, zipfile.ZipFile changes all names to use
        # forward slashes
        self.assertEqual(["test/a", "test/b/", "test/b/c", "test/d/"], names)

        file_attr = stat.S_IFREG | zip.FILE_PERMISSIONS
        dir_attr = stat.S_IFDIR | zip.ZIP_DIRECTORY_BIT | zip.DIR_PERMISSIONS

        a_info = zfile.getinfo(names[0])
        self.assertEqual(file_attr, a_info.external_attr)

        b_info = zfile.getinfo(names[1])
        self.assertEqual(dir_attr, b_info.external_attr)

        c_info = zfile.getinfo(names[2])
        self.assertEqual(file_attr, c_info.external_attr)

        d_info = zfile.getinfo(names[3])
        self.assertEqual(dir_attr, d_info.external_attr)

    def test_dir_export_nested(self):
        tree = self.make_branch_and_tree("dir")
        self.build_tree(["dir/a"])
        tree.add("a")

        subtree = self.make_branch_and_tree("dir/subdir")
        tree.add_reference(subtree)

        self.build_tree(["dir/subdir/b"])
        subtree.add("b")

        self.run_bzr("export --uncommitted direxport1 dir")
        self.assertFalse(os.path.exists("direxport1/subdir/b"))

        self.run_bzr("export --recurse-nested --uncommitted direxport2 dir")
        self.assertTrue(os.path.exists("direxport2/subdir/b"))

    def test_dir_export(self):
        tree = self.make_branch_and_tree("dir")
        self.build_tree(["dir/a"])
        tree.add("a")
        self.build_tree_contents([("dir/.bzrrules", b"")])
        tree.add(".bzrrules")
        self.build_tree(["dir/.bzr-adir/", "dir/.bzr-adir/afile"])
        tree.add([".bzr-adir/", ".bzr-adir/afile"])

        os.chdir("dir")
        self.run_bzr("ignore something")
        tree.commit("1")

        self.assertTrue(tree.has_filename(".bzrignore"))
        self.assertTrue(tree.has_filename(".bzrrules"))
        self.assertTrue(tree.has_filename(".bzr-adir"))
        self.assertTrue(tree.has_filename(".bzr-adir/afile"))
        self.run_bzr("export direxport")

        files = sorted(os.listdir("direxport"))
        # Make sure the exported directory contains 'a', but does not contain
        # '.bzrignore'.
        self.assertEqual(["a"], files)

    def example_branch(self):
        """Create a branch a 'branch' containing hello and goodbye."""
        tree = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/hello", b"foo")])
        tree.add("hello")
        tree.commit("setup")

        self.build_tree_contents([("branch/goodbye", b"baz")])
        tree.add("goodbye")
        tree.commit("setup")
        return tree

    def test_basic_directory_export(self):
        self.example_branch()
        os.chdir("branch")

        # Directory exports
        self.run_bzr("export ../latest")
        self.assertEqual(["goodbye", "hello"], sorted(os.listdir("../latest")))
        self.check_file_contents("../latest/goodbye", b"baz")
        self.run_bzr("export ../first -r 1")
        self.assertEqual(["hello"], sorted(os.listdir("../first")))
        self.check_file_contents("../first/hello", b"foo")

        # Even with .gz and .bz2 it is still a directory
        self.run_bzr("export ../first.gz -r 1")
        self.check_file_contents("../first.gz/hello", b"foo")
        self.run_bzr("export ../first.bz2 -r 1")
        self.check_file_contents("../first.bz2/hello", b"foo")

    def test_basic_tarfile_export(self):
        self.example_branch()
        os.chdir("branch")

        self.run_bzr("export ../first.tar -r 1")
        self.assertTrue(os.path.isfile("../first.tar"))
        with tarfile.open("../first.tar") as tf:
            self.assertEqual(["first/hello"], sorted(tf.getnames()))
            self.assertEqual(b"foo", tf.extractfile("first/hello").read())

        self.run_bzr("export ../first.tar.gz -r 1")
        self.assertTrue(os.path.isfile("../first.tar.gz"))
        self.run_bzr("export ../first.tbz2 -r 1")
        self.assertTrue(os.path.isfile("../first.tbz2"))
        self.run_bzr("export ../first.tar.bz2 -r 1")
        self.assertTrue(os.path.isfile("../first.tar.bz2"))
        self.run_bzr("export ../first.tar.tbz2 -r 1")
        self.assertTrue(os.path.isfile("../first.tar.tbz2"))

        with tarfile.open("../first.tar.tbz2", "r:bz2") as tf:
            self.assertEqual(["first.tar/hello"], sorted(tf.getnames()))
            self.assertEqual(b"foo", tf.extractfile("first.tar/hello").read())
        self.run_bzr("export ../first2.tar -r 1 --root pizza")
        with tarfile.open("../first2.tar") as tf:
            self.assertEqual(["pizza/hello"], sorted(tf.getnames()))
            self.assertEqual(b"foo", tf.extractfile("pizza/hello").read())

    def test_basic_zipfile_export(self):
        self.example_branch()
        os.chdir("branch")

        self.run_bzr("export ../first.zip -r 1")
        self.assertPathExists("../first.zip")
        with zipfile.ZipFile("../first.zip") as zf:
            self.assertEqual(["first/hello"], sorted(zf.namelist()))
            self.assertEqual(b"foo", zf.read("first/hello"))

        self.run_bzr("export ../first2.zip -r 1 --root pizza")
        with zipfile.ZipFile("../first2.zip") as zf:
            self.assertEqual(["pizza/hello"], sorted(zf.namelist()))
            self.assertEqual(b"foo", zf.read("pizza/hello"))

        self.run_bzr("export ../first-zip --format=zip -r 1")
        with zipfile.ZipFile("../first-zip") as zf:
            self.assertEqual(["first-zip/hello"], sorted(zf.namelist()))
            self.assertEqual(b"foo", zf.read("first-zip/hello"))

    def test_export_from_outside_branch(self):
        self.example_branch()

        # Use directory exports to test stating the branch location
        self.run_bzr("export latest branch")
        self.assertEqual(["goodbye", "hello"], sorted(os.listdir("latest")))
        self.check_file_contents("latest/goodbye", b"baz")
        self.run_bzr("export first -r 1 branch")
        self.assertEqual(["hello"], sorted(os.listdir("first")))
        self.check_file_contents("first/hello", b"foo")

    def test_export_partial_tree(self):
        tree = self.example_branch()
        self.build_tree(["branch/subdir/", "branch/subdir/foo.txt"])
        tree.smart_add(["branch"])
        tree.commit("more setup")
        out, err = self.run_bzr("export exported branch/subdir")
        self.assertEqual(["foo.txt"], os.listdir("exported"))

    def test_dir_export_per_file_timestamps(self):
        tree = self.example_branch()
        self.build_tree_contents([("branch/har", b"foo")])
        tree.add("har")
        # Earliest allowable date on FAT32 filesystems is 1980-01-01
        tree.commit("setup", timestamp=315532800)
        self.run_bzr("export --per-file-timestamps t branch")
        har_st = os.stat("t/har")
        self.assertEqual(315532800, har_st.st_mtime)

    def test_dir_export_partial_tree_per_file_timestamps(self):
        tree = self.example_branch()
        self.build_tree(["branch/subdir/", "branch/subdir/foo.txt"])
        tree.smart_add(["branch"])
        # Earliest allowable date on FAT32 filesystems is 1980-01-01
        tree.commit("setup", timestamp=315532800)
        self.run_bzr("export --per-file-timestamps tpart branch/subdir")
        foo_st = os.stat("tpart/foo.txt")
        self.assertEqual(315532800, foo_st.st_mtime)

    def test_export_directory(self):
        """Test --directory option."""
        self.example_branch()
        self.run_bzr(["export", "--directory=branch", "latest"])
        self.assertEqual(["goodbye", "hello"], sorted(os.listdir("latest")))
        self.check_file_contents("latest/goodbye", b"baz")

    def test_export_uncommitted(self):
        """Test --uncommitted option."""
        self.example_branch()
        os.chdir("branch")
        self.build_tree_contents([("goodbye", b"uncommitted data")])
        self.run_bzr(["export", "--uncommitted", "latest"])
        self.check_file_contents("latest/goodbye", b"uncommitted data")

    def test_export_uncommitted_no_tree(self):
        """Test --uncommitted option only works with a working tree."""
        tree = self.example_branch()
        tree.controldir.destroy_workingtree()
        os.chdir("branch")
        self.run_bzr_error(
            ["brz: ERROR: --uncommitted requires a working tree"],
            "export --uncommitted latest",
        )

    def test_zip_export_per_file_timestamps(self):
        tree = self.example_branch()
        self.build_tree_contents([("branch/har", b"foo")])
        tree.add("har")
        # Earliest allowable date on FAT32 filesystems is 1980-01-01
        timestamp = 347151600
        tree.commit("setup", timestamp=timestamp)
        self.run_bzr("export --per-file-timestamps test.zip branch")
        zfile = zipfile.ZipFile("test.zip")
        info = zfile.getinfo("test/har")
        self.assertEqual(time.localtime(timestamp)[:6], info.date_time)
