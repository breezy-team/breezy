#!/usr/bin/python3
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

"""Track whether a particular directory structure is dirty."""

import os
import inotify.adapters
import inotify.constants
from typing import Set
from .workingtree import WorkingTree


MASK = (
    inotify.constants.IN_CLOSE_WRITE | inotify.constants.IN_DELETE
    | inotify.constants.IN_CREATE | inotify.constants.IN_ISDIR
    | inotify.constants.IN_Q_OVERFLOW | inotify.constants.IN_MOVED_TO
    | inotify.constants.IN_MOVED_FROM | inotify.constants.IN_ATTRIB
)


class DirtyTrackerInvalid(Exception):
    """Dirty tracker invalid."""


class DirtyTracker(object):
    """Track the changes to (part of) a working tree."""

    _paths: Set[str]
    _created: Set[str]

    def __init__(self, tree: WorkingTree, subpath: str = ".") -> None:
        self._tree = tree
        self._subpath = subpath
        self._inotify = None
        self._paths = set()
        self._created = set()
        self._invalid = False

    def __enter__(self):
        self._start_watching()

    def _start_watching(self):
        self._inotify = inotify.adapters.Inotify(block_duration_s=0)
        start_path = self._tree.abspath(self._subpath)
        self._inotify.add_watch(start_path, MASK)
        for (dirpath, dirnames, filenames) in os.walk(start_path):
            for dirname in list(dirnames):
                if self._tree.is_control_filename(dirname):
                    dirnames.remove(dirname)
                else:
                    self._inotify.add_watch(
                        os.path.join(dirpath, dirname), MASK)
        self._invalid = False

    def __exit__(self, exc_val, exc_type, exc_tb):
        del self._inotify
        self._inotify = None
        return False

    def _track_new_directory(self, start_path):
        self._inotify.add_watch(start_path, MASK)
        for (dirpath, dirnames, filenames) in os.walk(start_path):
            for dirname in list(dirnames):
                path = os.path.join(dirpath, filename)
                self._created.add(path)
                self._paths.add(path)
                if self._tree.is_control_filename(dirname):
                    dirnames.remove(dirname)
                else:
                    self._inotify.add_watch(path, MASK)
            for filename in filenames:
                if self._tree.is_control_filename(filename):
                    continue
                path = os.path.join(dirpath, filename)
                self._created.add(path)
                self._paths.add(path)

        return self

    def __exit__(self, exc_val, exc_typ, exc_tb):
        self._wdd.clear()
        self._wm.close()
        return False

    def _process_pending(self) -> None:
        if self._inotify is None:
            raise RuntimeError("context manager not active")
        for (header, type_names, dirpath, name) in (
                self._inotify.event_gen(yield_nones=False, timeout_s=0.0001)):
            path = os.path.join(dirpath, name)
            if header.mask & inotify.constants.IN_Q_OVERFLOW:
                self._invalid = True
            if header.mask & inotify.constants.IN_ISDIR:
                # Need to update tracking
                if (header.mask & inotify.constants.IN_MOVED_TO
                        or header.mask & inotify.constants.IN_CREATE):
                    self._track_new_directory(path)
            if header.mask & inotify.constants.IN_CREATE:
                self._created.add(path)
            self._paths.add(path)
            if header.mask & inotify.constants.IN_DELETE and path in self._created:
                self._paths.remove(path)
                self._created.remove(path)

    def mark_clean(self) -> None:
        """Mark the subtree as not having any changes."""
        self._process_pending()
        self._paths.clear()
        self._created.clear()
        if self._invalid:
            self._start_watching()

    def is_dirty(self) -> bool:
        """Check whether there are any changes."""
        self._process_pending()
        if self._invalid:
            raise DirtyTrackerInvalid()
        return bool(self._paths)

    def paths(self) -> Set[str]:
        """Return the paths that have changed."""
        self._process_pending()
        if self._invalid:
            raise DirtyTrackerInvalid()
        return self._paths

    @property
    def _paths(self):
        return self._process.paths

    @property
    def _created(self):
        return self._process.created

    def relpaths(self) -> Set[str]:
        """Return the paths relative to the tree root that changed."""
        return set(self._tree.relpath(p) for p in self.paths())
