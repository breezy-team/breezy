# Copyright (C) 2009, 2010, 2011, 2016 Canonical Ltd
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

"""Tests for bzrlib.export."""

from cStringIO import StringIO
import os
import tarfile
import time
import zipfile

from bzrlib import (
    errors,
    export,
    tests,
    )
from bzrlib.export import get_root_name
from bzrlib.export.tar_exporter import export_tarball_generator
from bzrlib.tests import features


class TestDirExport(tests.TestCaseWithTransport):

    def test_missing_file(self):
        self.build_tree(['a/', 'a/b', 'a/c'])
        wt = self.make_branch_and_tree('.')
        wt.add(['a', 'a/b', 'a/c'])
        os.unlink('a/c')
        export.export(wt, 'target', format="dir")
        self.assertPathExists('target/a/b')
        self.assertPathDoesNotExist('target/a/c')

    def test_empty(self):
        wt = self.make_branch_and_tree('.')
        export.export(wt, 'target', format="dir")
        self.assertEqual([], os.listdir("target"))

    def test_symlink(self):
        self.requireFeature(features.SymlinkFeature)
        wt = self.make_branch_and_tree('.')
        os.symlink('source', 'link')
        wt.add(['link'])
        export.export(wt, 'target', format="dir")
        self.assertPathExists('target/link')

    def test_to_existing_empty_dir_success(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        wt = self.make_branch_and_tree('source')
        wt.add(['a', 'b', 'b/c'])
        wt.commit('1')
        self.build_tree(['target/'])
        export.export(wt, 'target', format="dir")
        self.assertPathExists('target/a')
        self.assertPathExists('target/b')
        self.assertPathExists('target/b/c')

    def test_empty_subdir(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        wt = self.make_branch_and_tree('source')
        wt.add(['a', 'b', 'b/c'])
        wt.commit('1')
        self.build_tree(['target/'])
        export.export(wt, 'target', format="dir", subdir='')
        self.assertPathExists('target/a')
        self.assertPathExists('target/b')
        self.assertPathExists('target/b/c')

    def test_to_existing_nonempty_dir_fail(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        wt = self.make_branch_and_tree('source')
        wt.add(['a', 'b', 'b/c'])
        wt.commit('1')
        self.build_tree(['target/', 'target/foo'])
        self.assertRaises(errors.BzrError,
            export.export, wt, 'target', format="dir")

    def test_existing_single_file(self):
        self.build_tree([
            'dir1/', 'dir1/dir2/', 'dir1/first', 'dir1/dir2/second'])
        wtree = self.make_branch_and_tree('dir1')
        wtree.add(['dir2', 'first', 'dir2/second'])
        wtree.commit('1')
        export.export(wtree, 'target1', format='dir', subdir='first')
        self.assertPathExists('target1/first')
        export.export(wtree, 'target2', format='dir', subdir='dir2/second')
        self.assertPathExists('target2/second')

    def test_files_same_timestamp(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        builder.build_snapshot(None, None, [
            ('add', ('', 'root-id', 'directory', '')),
            ('add', ('a', 'a-id', 'file', 'content\n'))])
        builder.build_snapshot(None, None, [
            ('add', ('b', 'b-id', 'file', 'content\n'))])
        builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        tree = b.basis_tree()
        orig_iter_files_bytes = tree.iter_files_bytes

        # Make iter_files_bytes slower, so we provoke mtime skew
        def iter_files_bytes(to_fetch):
            for thing in orig_iter_files_bytes(to_fetch):
                yield thing
                time.sleep(1)
        tree.iter_files_bytes = iter_files_bytes
        export.export(tree, 'target', format='dir')
        t = self.get_transport('target')
        st_a = t.stat('a')
        st_b = t.stat('b')
        # All files must be given the same mtime.
        self.assertEqual(st_a.st_mtime, st_b.st_mtime)

    def test_files_per_file_timestamps(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        # Earliest allowable date on FAT32 filesystems is 1980-01-01
        a_time = time.mktime((1999, 12, 12, 0, 0, 0, 0, 0, 0))
        b_time = time.mktime((1980, 01, 01, 0, 0, 0, 0, 0, 0))
        builder.build_snapshot(None, None, [
            ('add', ('', 'root-id', 'directory', '')),
            ('add', ('a', 'a-id', 'file', 'content\n'))],
            timestamp=a_time)
        builder.build_snapshot(None, None, [
            ('add', ('b', 'b-id', 'file', 'content\n'))],
            timestamp=b_time)
        builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        tree = b.basis_tree()
        export.export(tree, 'target', format='dir', per_file_timestamps=True)
        t = self.get_transport('target')
        self.assertEqual(a_time, t.stat('a').st_mtime)
        self.assertEqual(b_time, t.stat('b').st_mtime)

    def test_subdir_files_per_timestamps(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        foo_time = time.mktime((1999, 12, 12, 0, 0, 0, 0, 0, 0))
        builder.build_snapshot(None, None, [
            ('add', ('', 'root-id', 'directory', '')),
            ('add', ('subdir', 'subdir-id', 'directory', '')),
            ('add', ('subdir/foo.txt', 'foo-id', 'file', 'content\n'))],
            timestamp=foo_time)
        builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        tree = b.basis_tree()
        export.export(tree, 'target', format='dir', subdir='subdir',
            per_file_timestamps=True)
        t = self.get_transport('target')
        self.assertEqual(foo_time, t.stat('foo.txt').st_mtime)


class TarExporterTests(tests.TestCaseWithTransport):

    def test_xz(self):
        self.requireFeature(features.lzma)
        import lzma
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        wt.add(["a"])
        wt.commit("1")
        export.export(wt, 'target.tar.xz', format="txz")
        tf = tarfile.open(fileobj=lzma.LZMAFile('target.tar.xz'))
        self.assertEqual(["target/a"], tf.getnames())

    def test_lzma(self):
        self.requireFeature(features.lzma)
        import lzma
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        wt.add(["a"])
        wt.commit("1")
        export.export(wt, 'target.tar.lzma', format="tlzma")
        tf = tarfile.open(fileobj=lzma.LZMAFile('target.tar.lzma'))
        self.assertEqual(["target/a"], tf.getnames())

    def test_tgz(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        wt.add(["a"])
        wt.commit("1")
        export.export(wt, 'target.tar.gz', format="tgz")
        tf = tarfile.open('target.tar.gz')
        self.assertEqual(["target/a"], tf.getnames())

    def test_tgz_ignores_dest_path(self):
        # The target path should not be a part of the target file.
        # (bug #102234)
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        wt.add(["a"])
        wt.commit("1")
        os.mkdir("testdir1")
        os.mkdir("testdir2")
        export.export(wt, 'testdir1/target.tar.gz', format="tgz",
            per_file_timestamps=True)
        export.export(wt, 'testdir2/target.tar.gz', format="tgz",
            per_file_timestamps=True)
        file1 = open('testdir1/target.tar.gz', 'r')
        self.addCleanup(file1.close)
        file2 = open('testdir1/target.tar.gz', 'r')
        self.addCleanup(file2.close)
        content1 = file1.read()
        content2 = file2.read()
        self.assertEqualDiff(content1, content2)
        # the gzip module doesn't have a way to read back to the original
        # filename, but it's stored as-is in the tarfile.
        self.assertFalse("testdir1" in content1)
        self.assertFalse("target.tar.gz" in content1)
        self.assertTrue("target.tar" in content1)

    def test_tbz2(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        wt.add(["a"])
        wt.commit("1")
        export.export(wt, 'target.tar.bz2', format="tbz2")
        tf = tarfile.open('target.tar.bz2')
        self.assertEqual(["target/a"], tf.getnames())

    def test_xz_stdout(self):
        wt = self.make_branch_and_tree('.')
        self.assertRaises(errors.BzrError, export.export, wt, '-',
            format="txz")

    def test_export_tarball_generator(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        wt.add(["a"])
        wt.commit("1", timestamp=42)
        target = StringIO()
        ball = tarfile.open(None, "w|", target)
        wt.lock_read()
        try:
            for _ in export_tarball_generator(wt, ball, "bar"):
                pass
        finally:
            wt.unlock()
        # Ball should now be closed.
        target.seek(0)
        ball2 = tarfile.open(None, "r", target)
        self.addCleanup(ball2.close)
        self.assertEqual(["bar/a"], ball2.getnames())


class ZipExporterTests(tests.TestCaseWithTransport):

    def test_per_file_timestamps(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('har', 'foo')])
        tree.add('har')
        # Earliest allowable date on FAT32 filesystems is 1980-01-01
        timestamp = 347151600
        tree.commit('setup', timestamp=timestamp)
        export.export(tree.basis_tree(), 'test.zip', format='zip',
            per_file_timestamps=True)
        zfile = zipfile.ZipFile('test.zip')
        info = zfile.getinfo("test/har")
        self.assertEqual(time.localtime(timestamp)[:6], info.date_time)


class RootNameTests(tests.TestCase):

    def test_root_name(self):
        self.assertEqual('mytest', get_root_name('../mytest.tar'))
        self.assertEqual('mytar', get_root_name('mytar.tar'))
        self.assertEqual('mytar', get_root_name('mytar.tar.bz2'))
        self.assertEqual('tar.tar.tar', get_root_name('tar.tar.tar.tgz'))
        self.assertEqual('bzr-0.0.5', get_root_name('bzr-0.0.5.tar.gz'))
        self.assertEqual('bzr-0.0.5', get_root_name('bzr-0.0.5.zip'))
        self.assertEqual('bzr-0.0.5', get_root_name('bzr-0.0.5'))
        self.assertEqual('mytar', get_root_name('a/long/path/mytar.tgz'))
        self.assertEqual('other',
            get_root_name('../parent/../dir/other.tbz2'))
        self.assertEqual('', get_root_name('-'))
