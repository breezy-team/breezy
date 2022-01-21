# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
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

from . import (
    TestCaseWithTransport,
    multiply_scenarios,
    features,
    )
from .scenarios import load_tests_apply_scenarios

from ..workspace import (
    WorkspaceDirty,
    Workspace,
    check_clean_tree,
    )


load_tests = load_tests_apply_scenarios


class CheckCleanTreeTests(TestCaseWithTransport):

    def make_test_tree(self, format=None):
        tree = self.make_branch_and_tree('.', format=format)
        self.build_tree_contents([
            ('debian/', ),
            ('debian/control', """\
Source: blah
Vcs-Git: https://example.com/blah
Testsuite: autopkgtest

Binary: blah
Arch: all

"""),
            ('debian/changelog', 'Some contents')])
        tree.add(['debian', 'debian/changelog', 'debian/control'])
        tree.commit('Initial thingy.')
        return tree

    def test_pending_changes(self):
        tree = self.make_test_tree()
        self.build_tree_contents([('debian/changelog', 'blah')])
        with tree.lock_write():
            self.assertRaises(
                WorkspaceDirty, check_clean_tree, tree)

    def test_pending_changes_bzr_empty_dir(self):
        # See https://bugs.debian.org/914038
        tree = self.make_test_tree(format='bzr')
        self.build_tree_contents([('debian/upstream/', )])
        with tree.lock_write():
            self.assertRaises(
                WorkspaceDirty, check_clean_tree, tree)

    def test_pending_changes_git_empty_dir(self):
        # See https://bugs.debian.org/914038
        tree = self.make_test_tree(format='git')
        self.build_tree_contents([('debian/upstream/', )])
        with tree.lock_write():
            check_clean_tree(tree)

    def test_pending_changes_git_dir_with_ignored(self):
        # See https://bugs.debian.org/914038
        tree = self.make_test_tree(format='git')
        self.build_tree_contents([
            ('debian/upstream/', ),
            ('debian/upstream/blah', ''),
            ('.gitignore', 'blah\n'),
            ])
        tree.add('.gitignore')
        tree.commit('add gitignore')
        with tree.lock_write():
            check_clean_tree(tree)

    def test_extra(self):
        tree = self.make_test_tree()
        self.build_tree_contents([('debian/foo', 'blah')])
        with tree.lock_write():
            self.assertRaises(
                WorkspaceDirty, check_clean_tree,
                tree)

    def test_subpath(self):
        tree = self.make_test_tree()
        self.build_tree_contents([("debian/foo", "blah"), ("foo/",)])
        tree.add("foo")
        tree.commit("add foo")
        with tree.lock_write():
            check_clean_tree(tree, tree.basis_tree(), subpath="foo")
            self.assertRaises(
                WorkspaceDirty, check_clean_tree, tree, tree.basis_tree(), subpath=""
            )

    def test_subpath_changed(self):
        tree = self.make_test_tree()
        self.build_tree_contents([("foo/",)])
        tree.add("foo")
        tree.commit("add foo")
        self.build_tree_contents([("debian/control", "blah")])
        with tree.lock_write():
            check_clean_tree(tree, tree.basis_tree(), subpath="foo")
            self.assertRaises(
                WorkspaceDirty, check_clean_tree, tree, tree.basis_tree(), subpath=""
            )


def vary_by_inotify():
    return [
        ('with_inotify', dict(_use_inotify=True)),
        ('without_inotify', dict(_use_inotify=False)),
    ]


def vary_by_format():
    return [
        ('bzr', dict(_format='bzr')),
        ('git', dict(_format='git')),
    ]


class WorkspaceTests(TestCaseWithTransport):

    scenarios = multiply_scenarios(
        vary_by_inotify(),
        vary_by_format(),
    )

    def setUp(self):
        super(WorkspaceTests, self).setUp()
        if self._use_inotify:
            self.requireFeature(features.pyinotify)

    def test_root_add(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        with Workspace(tree, use_inotify=self._use_inotify) as ws:
            self.build_tree_contents([('afile', 'somecontents')])
            changes = [c for c in ws.iter_changes() if c.path[1] != '']
            self.assertEqual(1, len(changes), changes)
            self.assertEqual((None, 'afile'), changes[0].path)
            ws.commit(message='Commit message')
            self.assertEqual(list(ws.iter_changes()), [])
            self.build_tree_contents([('afile', 'newcontents')])
            [change] = list(ws.iter_changes())
            self.assertEqual(('afile', 'afile'), change.path)

    def test_root_remove(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        self.build_tree_contents([('afile', 'somecontents')])
        tree.add(['afile'])
        tree.commit('Afile')
        with Workspace(tree, use_inotify=self._use_inotify) as ws:
            os.remove('afile')
            changes = list(ws.iter_changes())
            self.assertEqual(1, len(changes), changes)
            self.assertEqual(('afile', None), changes[0].path)
            ws.commit(message='Commit message')
            self.assertEqual(list(ws.iter_changes()), [])

    def test_subpath_add(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        self.build_tree(['subpath/'])
        tree.add('subpath')
        tree.commit('add subpath')
        with Workspace(
                tree, subpath='subpath', use_inotify=self._use_inotify) as ws:
            self.build_tree_contents([('outside', 'somecontents')])
            self.build_tree_contents([('subpath/afile', 'somecontents')])
            changes = [c for c in ws.iter_changes() if c.path[1] != 'subpath']
            self.assertEqual(1, len(changes), changes)
            self.assertEqual((None, 'subpath/afile'), changes[0].path)
            ws.commit(message='Commit message')
            self.assertEqual(list(ws.iter_changes()), [])

    def test_dirty(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        self.build_tree(['subpath'])
        self.assertRaises(
            WorkspaceDirty, Workspace(tree, use_inotify=self._use_inotify).__enter__)

    def test_reset(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        with Workspace(tree, use_inotify=self._use_inotify) as ws:
            self.build_tree(['blah'])
            ws.reset()
            self.assertPathDoesNotExist('blah')

    def test_tree_path(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        tree.mkdir('subdir')
        tree.commit('Add subdir')
        with Workspace(tree, use_inotify=self._use_inotify) as ws:
            self.assertEqual('foo', ws.tree_path('foo'))
            self.assertEqual('', ws.tree_path())
        with Workspace(tree, subpath='subdir', use_inotify=self._use_inotify) as ws:
            self.assertEqual('subdir/foo', ws.tree_path('foo'))
            self.assertEqual('subdir/', ws.tree_path())

    def test_abspath(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        tree.mkdir('subdir')
        tree.commit('Add subdir')
        with Workspace(tree, use_inotify=self._use_inotify) as ws:
            self.assertEqual(tree.abspath('foo'), ws.abspath('foo'))
            self.assertEqual(tree.abspath(''), ws.abspath())
        with Workspace(tree, subpath='subdir', use_inotify=self._use_inotify) as ws:
            self.assertEqual(tree.abspath('subdir/foo'), ws.abspath('foo'))
            self.assertEqual(tree.abspath('subdir') + '/', ws.abspath(''))
            self.assertEqual(tree.abspath('subdir') + '/', ws.abspath())

    def test_open_containing(self):
        tree = self.make_branch_and_tree('.', format=self._format)
        tree.mkdir('subdir')
        tree.commit('Add subdir')
        ws = Workspace.from_path('subdir')
        self.assertEqual(ws.tree.abspath('.'), tree.abspath('.'))
        self.assertEqual(ws.subpath, 'subdir')
        self.assertEqual(None, ws.use_inotify)
