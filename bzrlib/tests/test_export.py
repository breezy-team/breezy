# Copyright (C) 2009, 2010 Canonical Ltd
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

import os
import time

from bzrlib import (
    errors,
    export,
    tests,
    )


class TestExport(tests.TestCaseWithTransport):

    def test_dir_export_missing_file(self):
        self.build_tree(['a/', 'a/b', 'a/c'])
        wt = self.make_branch_and_tree('.')
        wt.add(['a', 'a/b', 'a/c'])
        os.unlink('a/c')
        export.export(wt, 'target', format="dir")
        self.failUnlessExists('target/a/b')
        self.failIfExists('target/a/c')

    def test_dir_export_symlink(self):
        self.requireFeature(tests.SymlinkFeature)
        wt = self.make_branch_and_tree('.')
        os.symlink('source', 'link')
        wt.add(['link'])
        export.export(wt, 'target', format="dir")
        self.failUnlessExists('target/link')

    def test_dir_export_to_existing_empty_dir_success(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        wt = self.make_branch_and_tree('source')
        wt.add(['a', 'b', 'b/c'])
        wt.commit('1')
        self.build_tree(['target/'])
        export.export(wt, 'target', format="dir")
        self.failUnlessExists('target/a')
        self.failUnlessExists('target/b')
        self.failUnlessExists('target/b/c')

    def test_dir_export_to_existing_nonempty_dir_fail(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        wt = self.make_branch_and_tree('source')
        wt.add(['a', 'b', 'b/c'])
        wt.commit('1')
        self.build_tree(['target/', 'target/foo'])
        self.assertRaises(errors.BzrError, export.export, wt, 'target', format="dir")

    def test_dir_export_existing_single_file(self):
        self.build_tree(['dir1/', 'dir1/dir2/', 'dir1/first', 'dir1/dir2/second'])
        wtree = self.make_branch_and_tree('dir1')
        wtree.add(['dir2', 'first', 'dir2/second'])
        wtree.commit('1')
        export.export(wtree, 'target1', format='dir', subdir='first')
        self.failUnlessExists('target1/first')
        export.export(wtree, 'target2', format='dir', subdir='dir2/second')
        self.failUnlessExists('target2/second')
        
    def test_dir_export_files_same_timestamp(self):
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

    def test_dir_export_files_per_file_timestamps(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        builder.build_snapshot(None, None, [
            ('add', ('', 'root-id', 'directory', '')),
            ('add', ('a', 'a-id', 'file', 'content\n'))],
            timestamp=3423)
        builder.build_snapshot(None, None, [
            ('add', ('b', 'b-id', 'file', 'content\n'))],
            timestamp=42)
        builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        tree = b.basis_tree()
        export.export(tree, 'target', format='dir', per_file_timestamps=True)
        t = self.get_transport('target')
        st_a = t.stat('a')
        st_b = t.stat('b')
        self.assertEqual(42.0, st_b.st_mtime)
        self.assertEqual(3423.0, st_a.st_mtime)
