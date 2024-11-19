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

from pyinotify import (
    IN_ATTRIB,
    IN_CLOSE_WRITE,
    IN_CREATE,
    IN_DELETE,
    IN_MOVED_FROM,
    IN_MOVED_TO,
    IN_Q_OVERFLOW,
    Event,
    Notifier,
    ProcessEvent,
    WatchManager,
)

from .workingtree import WorkingTree

MASK = (
    IN_CLOSE_WRITE | IN_DELETE | IN_Q_OVERFLOW | IN_MOVED_TO | IN_MOVED_FROM | IN_ATTRIB
)


class TooManyOpenFiles(Exception):
    """Too many open files."""


class _Process(ProcessEvent):  # type: ignore
    paths: set[str]
    created: set[str]

    def my_init(self) -> None:
        self.paths = set()
        self.created = set()

    def process_default(self, event: Event) -> None:
        path = os.path.join(event.path, event.name)
        if event.mask & IN_CREATE:
            self.created.add(path)
        self.paths.add(path)
        if event.mask & IN_DELETE and path in self.created:
            self.paths.remove(path)
            self.created.remove(path)


class DirtyTracker:
    """Track the changes to (part of) a working tree."""

    _process: _Process

    def __init__(self, tree: WorkingTree, subpath: str = ".") -> None:
        self._tree = tree
        self._subpath = subpath

    def __enter__(self):
        try:
            self._wm = WatchManager()
        except OSError as e:
            if "EMFILE" in e.args[0]:
                raise TooManyOpenFiles() from e
            raise
        self._process = _Process()
        self._notifier = Notifier(self._wm, self._process)
        self._notifier.coalesce_events(True)

        def check_excluded(p: str) -> bool:
            return self._tree.is_control_filename(self._tree.relpath(p))  # type: ignore

        self._wdd = self._wm.add_watch(
            self._tree.abspath(self._subpath),
            MASK,
            rec=True,
            auto_add=True,
            exclude_filter=check_excluded,
        )

        return self

    def __exit__(self, exc_val, exc_typ, exc_tb):
        self._wdd.clear()
        self._wm.close()
        return False

    def _process_pending(self) -> None:
        if self._notifier.check_events(timeout=0):
            self._notifier.read_events()
        self._notifier.process_events()

    def mark_clean(self) -> None:
        """Mark the subtree as not having any changes."""
        self._process_pending()
        self._process.paths.clear()
        self._process.created.clear()

    def is_dirty(self) -> bool:
        """Check whether there are any changes."""
        self._process_pending()
        return bool(self._paths)

    def paths(self) -> set[str]:
        """Return the paths that have changed."""
        self._process_pending()
        return self._paths

    @property
    def _paths(self) -> set[str]:
        return self._process.paths

    @property
    def _created(self):
        return self._process.created

    def relpaths(self) -> set[str]:
        """Return the paths relative to the tree root that changed."""
        return {self._tree.relpath(p) for p in self.paths()}
