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

"""Track whether a directory structure was touched since last revision.
"""

from __future__ import absolute_import

# TODO(jelmer): Add support for ignore files

import os
try:
    from pyinotify import (
        WatchManager,
        IN_CREATE,
        IN_CLOSE_WRITE,
        IN_Q_OVERFLOW,
        IN_DELETE,
        IN_MOVED_TO,
        IN_MOVED_FROM,
        IN_ATTRIB,
        ProcessEvent,
        Notifier,
        Event,
        )
except ImportError as e:
    from .errors import DependencyNotPresent
    raise DependencyNotPresent(library='pyinotify', error=e)


MASK = (
    IN_CLOSE_WRITE | IN_DELETE | IN_Q_OVERFLOW | IN_MOVED_TO | IN_MOVED_FROM |
    IN_ATTRIB)


class _Process(ProcessEvent):

    def my_init(self):
        self.paths = set()
        self.created = set()

    def process_default(self, event):
        path = os.path.join(event.path, event.name)
        if event.mask & IN_CREATE:
            self.created.add(path)
        self.paths.add(path)
        if event.mask & IN_DELETE and path in self.created:
            self.paths.remove(path)
            self.created.remove(path)


class DirtyTracker(object):
    """Track the changes to (part of) a working tree."""

    def __init__(self, tree, subpath='.'):
        self._tree = tree
        self._wm = WatchManager()
        self._process = _Process()
        self._notifier = Notifier(self._wm, self._process)
        self._notifier.coalesce_events(True)

        def check_excluded(p):
            return tree.is_control_filename(tree.relpath(p))
        self._wdd = self._wm.add_watch(
            tree.abspath(subpath), MASK, rec=True, auto_add=True,
            exclude_filter=check_excluded)

    def _process_pending(self):
        if self._notifier.check_events(timeout=0):
            self._notifier.read_events()
        self._notifier.process_events()

    def __del__(self):
        self._notifier.stop()

    def mark_clean(self):
        """Mark the subtree as not having any changes."""
        self._process_pending()
        self._process.paths.clear()
        self._process.created.clear()

    def is_dirty(self):
        """Check whether there are any changes."""
        self._process_pending()
        return bool(self._process.paths)

    def paths(self):
        """Return the paths that have changed."""
        self._process_pending()
        return self._process.paths

    def relpaths(self):
        """Return the paths relative to the tree root that changed."""
        return set(self._tree.relpath(p) for p in self.paths())
