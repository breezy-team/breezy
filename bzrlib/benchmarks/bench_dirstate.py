# Copyright (C) 2007 Canonical Ltd
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

"""Benchmarks for bzr DirState performance."""

import os

from bzrlib import (
    benchmarks,
    dirstate,
    generate_ids,
    osutils,
    tests,
    )
from bzrlib.tests.compiled.test_dirstate_helpers import (
    CompiledDirstateHelpersFeature,
    )


class BenchmarkDirState(benchmarks.Benchmark):
    """Benchmarks for DirState functions."""

    def build_helper(self, layout):
        """This is a helper with the common build_??_dirstate funcs.

        :param layout: [(num_dirs, files_per_dir)]
            The number of directories per level, and the number of files to put
            in it.
        :return: A DirState object with the given layout.
        """
        self.build_tree(['dir/'])
        contents = 'x'*10000
        self.build_tree_contents([('file', contents)])
        file_stat = os.lstat('file')
        dir_stat = os.lstat('dir')
        file_sha1 = osutils.sha_string(contents)

        state = dirstate.DirState.initialize('state')
        try:
            def create_entries(base, layout):
                if not layout:
                    return
                num_dirs, num_files = layout[0]
                for dnum in xrange(num_dirs):
                    if base:
                        path = '%s/%02d_directory' % (base, dnum)
                    else:
                        path = '%02d_directory' % (dnum,)
                    dir_id = generate_ids.gen_file_id(path)
                    state.add(path, dir_id, 'directory', dir_stat, '')
                    for fnum in xrange(num_files):
                        fname = '%s/%02d_filename' % (path, fnum)
                        file_id = generate_ids.gen_file_id(fname)
                        state.add(fname, file_id, 'file', file_stat, file_sha1)
                    create_entries(path, layout[1:])
            create_entries(None, layout)
            state.save()
        finally:
            state.unlock()
        return state

    def build_10k_dirstate_dirs(self):
        """Build a DirState file with 10k directories"""
        return self.build_helper([(10, 0), (10, 0), (10, 0), (10, 1)])

    def build_20k_dirstate(self):
        """Build a DirState file with 20k records.

        This approximates a kernel tree, based on the number of directories
        (1000), and number of files per directory (20) and depth (3).
        Because DirState doesn't have to have actual disk records, we just add
        random files.
        We try to have reasonable filename lengths, as well as a reasonable
        stat value, etc.
        """
        return self.build_helper([(10, 0), (10, 0), (10, 20)])

    def build_20k_dirstate_with_parents(self, num_parents):
        """Build a DirState file with 20k records and N parents.

        With 1 parent, this is equivalent to after a simple commit. With 2 it
        is equivalent to after a merge.
        """
        # All files are marked as changed in the same revision, and this occurs
        # supposedly in the history of the current trees.
        last_changed_id = generate_ids.gen_revision_id('joe@foo.com')
        parent_revision_ids = [generate_ids.gen_revision_id('joe@foo.com')
                               for i in xrange(num_parents)]
        # Start with a dirstate file with 0 parents
        state = self.build_20k_dirstate()
        state.lock_write()
        try:
            # This invasively updates the internals of DirState to be fast,
            # since we don't have an api other than passing in Revision Tree
            # objects, but that requires having a real inventory, etc.
            for entry in state._iter_entries():
                minikind, fingerprint, size, is_exec, packed_stat = entry[1][0]
                for parent_id in parent_revision_ids:
                    # Add a parent record for this record
                    entry[1].append((minikind, fingerprint, size, is_exec,
                                     last_changed_id))
            state._parents = parent_revision_ids
            state._ghosts = []
            state._dirblock_state = dirstate.DirState.IN_MEMORY_MODIFIED
            state._header_state = dirstate.DirState.IN_MEMORY_MODIFIED
            state._validate()
            state.save()
        finally:
            state.unlock()
        return state

    def test_build_20k_dirstate(self):
        state = self.time(self.build_20k_dirstate)
        state.lock_read()
        try:
            entries = list(state._iter_entries())
            self.assertEqual(21111, len(entries))
        finally:
            state.unlock()

    def test_build_20k_dirstate_1_parent(self):
        state = self.time(self.build_20k_dirstate_with_parents, 1)
        state.lock_read()
        try:
            state._validate()
            entries = list(state._iter_entries())
            self.assertEqual(21111, len(entries))
        finally:
            state.unlock()

    def test_build_20k_dirstate_2_parents(self):
        state = self.time(self.build_20k_dirstate_with_parents, 2)
        state.lock_read()
        try:
            state._validate()
            entries = list(state._iter_entries())
            self.assertEqual(21111, len(entries))
        finally:
            state.unlock()

    def test_save_20k_tree_0_parents(self):
        state = self.build_20k_dirstate()
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_header_if_needed()
            state._dirblock_state = dirstate.DirState.IN_MEMORY_MODIFIED
            self.time(state.save)
        finally:
            state.unlock()

    def test_save_20k_tree_1_parent(self):
        state = self.build_20k_dirstate_with_parents(1)
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_dirblocks_if_needed()
            state._dirblock_state = dirstate.DirState.IN_MEMORY_MODIFIED
            self.time(state.save)
        finally:
            state.unlock()

    def test_save_20k_tree_2_parents(self):
        state = self.build_20k_dirstate_with_parents(2)
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_dirblocks_if_needed()
            state._dirblock_state = dirstate.DirState.IN_MEMORY_MODIFIED
            self.time(state.save)
        finally:
            state.unlock()

    def test__read_dirblocks_20k_tree_0_parents_py(self):
        state = self.build_20k_dirstate()
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_header_if_needed()
            self.time(dirstate._read_dirblocks_py, state)
        finally:
            state.unlock()

    def test__read_dirblocks_20k_tree_0_parents_c(self):
        self.requireFeature(CompiledDirstateHelpersFeature)
        from bzrlib.compiled.dirstate_helpers import _read_dirblocks_c
        state = self.build_20k_dirstate()
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_header_if_needed()
            self.time(_read_dirblocks_c, state)
        finally:
            state.unlock()

    def test__read_dirblocks_20k_tree_1_parent_py(self):
        state = self.build_20k_dirstate_with_parents(1)
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_header_if_needed()
            self.time(dirstate._read_dirblocks_py, state)
        finally:
            state.unlock()

    def test__read_dirblocks_20k_tree_1_parent_c(self):
        self.requireFeature(CompiledDirstateHelpersFeature)
        from bzrlib.compiled.dirstate_helpers import _read_dirblocks_c
        state = self.build_20k_dirstate_with_parents(1)
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_header_if_needed()
            self.time(_read_dirblocks_c, state)
        finally:
            state.unlock()

    def test__read_dirblocks_20k_tree_2_parents_py(self):
        state = self.build_20k_dirstate_with_parents(2)
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_header_if_needed()
            self.time(dirstate._read_dirblocks_py, state)
        finally:
            state.unlock()

    def test__read_dirblocks_20k_tree_2_parents_c(self):
        self.requireFeature(CompiledDirstateHelpersFeature)
        from bzrlib.compiled.dirstate_helpers import _read_dirblocks_c
        state = self.build_20k_dirstate_with_parents(2)
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            state._read_header_if_needed()
            self.time(_read_dirblocks_c, state)
        finally:
            state.unlock()

    def do_bisect_list(self, bisect_func):
        """Call bisect_dirblock for each path."""
        # We use self._paths and self._blocks because we expect it to be a very
        # long list. And the interface for 'self.time()' causes the parameters
        # to be printed when run with --lsprof-timed. Which is *really* ugly
        # when the list is thousands of entries.
        blocks = self._blocks
        return [bisect_func(blocks, path) for path in self._paths]

    def do_bisect_list_cached(self, bisect_func):
        """Same as do_bisect_list, but cache the split paths"""
        cache = {}
        blocks = self._blocks
        return [bisect_func(blocks, path, cache=cache) for path in self._paths]

    def setup_paths_and_offsets(self, state):
        """Get a list of paths and expected offsets.

        This will be used to check do_bisect_list*
        """
        state._read_dirblocks_if_needed()
        paths = ['']
        expected_offsets = [0]
        for offset, info in enumerate(state._dirblocks):
            dirname = info[0]
            # We already handled the empty path
            if dirname == '':
                continue
            # all paths are of the form ##_directory
            # so search for ##_director, ##_directory
            paths.extend([dirname[:-1], dirname])
            expected_offsets.extend([offset, offset])
        self._paths = paths
        self._expected_offsets = expected_offsets
        self._blocks = state._dirblocks

    def checkOffsets(self, offsets):
        """Make sure offsets matches self._expected_offsets"""
        # These are really long lists, so it is easier to compare them with
        # assertEqualDiff. So turn them into strings.
        expected_str = '\n'.join(str(x) for x in self._expected_offsets)
        offset_str = '\n'.join(str(x) for x in offsets)
        self.assertEqualDiff(expected_str, offset_str)

    def test_bisect_dirblock_py(self):
        state = self.build_10k_dirstate_dirs()
        state.lock_read()
        try:
            self.setup_paths_and_offsets(state)
            offsets = self.time(self.do_bisect_list,
                                dirstate.bisect_dirblock_py)
            self.checkOffsets(offsets)
        finally:
            state.unlock()

    def test_bisect_dirblock_cached_py(self):
        state = self.build_10k_dirstate_dirs()
        state.lock_read()
        try:
            self.setup_paths_and_offsets(state)
            offsets = self.time(self.do_bisect_list_cached,
                                dirstate.bisect_dirblock_py)
            self.checkOffsets(offsets)
        finally:
            state.unlock()

    def test_bisect_dirblock_c(self):
        self.requireFeature(CompiledDirstateHelpersFeature)
        from bzrlib.compiled.dirstate_helpers import bisect_dirblock_c
        state = self.build_10k_dirstate_dirs()
        state.lock_read()
        try:
            self.setup_paths_and_offsets(state)
            offsets = self.time(self.do_bisect_list, bisect_dirblock_c)
            self.checkOffsets(offsets)
        finally:
            state.unlock()

    def create_path_names(self, layout, base=''):
        """Create a list of paths with auto-generated names.

        :param layout: A list of [(num_dirs, num_files)] tuples. For each
            level, the given number of directories will be created, each
            containing that many files.
            So [(2, 5), (3, 4)] will create 2 top level directories, containing
            5 files, and each top level directory will contain 3 subdirs with 4
            files.
        :param base: The base path to prepend to all entries, most callers will
            pass ''
        :return: A list of path names.
        """
        if not layout:
            return []

        paths = []
        num_dirs, num_files = layout[0]
        for dnum in xrange(num_dirs):
            if base:
                path = '%s/%02d_directory' % (base, dnum)
            else:
                path = '%02d_directory' % (dnum,)
            paths.append(path)
            for fnum in xrange(num_files):
                fname = '%s/%02d_filename' % (path, fnum)
                paths.append(fname)
            paths.extend(self.create_path_names(layout[1:], base=path))
        return paths

    def test_create_path_names(self):
        names = self.create_path_names([(2, 3), (1, 2)])
        self.assertEqual(['00_directory',
                          '00_directory/00_filename',
                          '00_directory/01_filename',
                          '00_directory/02_filename',
                          '00_directory/00_directory',
                          '00_directory/00_directory/00_filename',
                          '00_directory/00_directory/01_filename',
                          '01_directory',
                          '01_directory/00_filename',
                          '01_directory/01_filename',
                          '01_directory/02_filename',
                          '01_directory/00_directory',
                          '01_directory/00_directory/00_filename',
                          '01_directory/00_directory/01_filename',
                         ], names)
        names = self.time(self.create_path_names, [(10, 2), (10, 2), (10, 20)])
        # 20 files + 1 directory name, 10 times, plus 2 filenames and 1 dir, 10
        # times, and another 2 files + 1 dir, 10 times
        self.assertEqual(21330, 10*(3 + 10*(3 + 10*(1 + 20))))
        self.assertEqual(21330, len(names))

    def compareAllPaths(self, cmp_func, layout):
        """Compare N^2 paths.

        Basically, compare every path in the list against every other path.
        """
        paths = self.create_path_names(layout)
        def compare_all():
            for path1 in paths:
                for path2 in paths:
                    cmp_func(path1, path2)
        self.time(compare_all)

    def test_cmp_by_dirs_py(self):
        """Benchmark 103041 comparisons."""
        self.compareAllPaths(dirstate.cmp_by_dirs_py,
                             [(3, 1), (3, 1), (3, 1), (3, 2)])

    def test_cmp_by_dirs_c(self):
        self.requireFeature(CompiledDirstateHelpersFeature)
        from bzrlib.compiled.dirstate_helpers import cmp_by_dirs_c
        self.compareAllPaths(cmp_by_dirs_c,
                             [(3, 1), (3, 1), (3, 1), (3, 2)])
