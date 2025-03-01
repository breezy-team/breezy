#!/usr/bin/python
# Copyright (C) 2019 Jelmer Vernooij
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

"""Tests for breezy.dirty_tracker."""

import os

import breezy
from breezy.tests import TestCaseWithTransport


class DirtyTrackerTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.tree = self.make_branch_and_tree("tree")
        try:
            from ..dirty_tracker import DirtyTracker
        except ModuleNotFoundError as e:
            if e.name == "pyinotify":
                self.skipTest("pyinotify not available")
            raise
        self.tracker = DirtyTracker(self.tree)

    def test_nothing_changes(self):
        try:
            with self.tracker:
                self.assertFalse(self.tracker.is_dirty())
        except breezy.dirty_tracker.TooManyOpenFiles:
            self.skipTest("Too many open files")

    def test_regular_file_added(self):
        with self.tracker:
            self.build_tree_contents([("tree/foo", "bar")])
            self.assertTrue(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), {"foo"})

    def test_many_added(self):
        with self.tracker:
            self.build_tree_contents([("tree/f%d" % d, "content") for d in range(100)])
            self.assertTrue(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), {"f%d" % d for d in range(100)})

    def test_regular_file_in_subdir_added(self):
        with self.tracker:
            self.build_tree_contents([("tree/foo/",), ("tree/foo/blah", "bar")])
            self.assertTrue(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), {"foo", "foo/blah"})

    def test_directory_added(self):
        with self.tracker:
            self.build_tree_contents([("tree/foo/",)])
            self.assertTrue(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), {"foo"})

    def test_file_removed(self):
        with self.tracker:
            self.build_tree_contents([("tree/foo", "foo")])
            self.assertTrue(self.tracker.is_dirty())
            self.tracker.mark_clean()
            self.build_tree_contents([("tree/foo", "bar")])
            self.assertTrue(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), {"foo"})

    def test_control_file(self):
        with self.tracker:
            self.tree.commit("Some change")
            self.assertFalse(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), set())

    def test_renamed(self):
        with self.tracker:
            self.build_tree_contents([("tree/foo", "bar")])
            self.tracker.mark_clean()
            self.assertFalse(self.tracker.is_dirty())
            os.rename("tree/foo", "tree/bar")
            self.assertTrue(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), {"foo", "bar"})

    def test_deleted(self):
        with self.tracker:
            self.build_tree_contents([("tree/foo", "bar")])
            self.tracker.mark_clean()
            self.assertFalse(self.tracker.is_dirty())
            os.unlink("tree/foo")
            self.assertTrue(self.tracker.is_dirty(), self.tracker._paths)
            self.assertEqual(self.tracker.relpaths(), {"foo"})

    def test_added_then_deleted(self):
        with self.tracker:
            self.tracker.mark_clean()
            self.assertFalse(self.tracker.is_dirty())
            self.build_tree_contents([("tree/foo", "bar")])
            os.unlink("tree/foo")
            self.assertFalse(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), set())

    def test_file_modified(self):
        self.build_tree_contents([("tree/foo", "bla")])
        with self.tracker:
            self.assertFalse(self.tracker.is_dirty())
            self.build_tree_contents([("tree/foo", "bar")])
            self.assertTrue(self.tracker.is_dirty())
            self.assertEqual(self.tracker.relpaths(), {"foo"})
