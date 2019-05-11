#    quilt.py -- Quilt patch handling
#    Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
#
#    Breezy is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    Breezy is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Breezy; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Quilt patch handling."""

from __future__ import absolute_import

import os

from . import wrapper

QuiltError = wrapper.QuiltError


class QuiltPatches(object):
    """Management object for a stack of quilt patches."""

    def __init__(self, tree, patches_dir='patches', series_file=None):
        self.tree = tree
        self.patches_dir = patches_dir
        if series_file is None:
            series_file = os.path.join(patches_dir, 'series')
        self.series_file = series_file

    def series(self):
        return wrapper.quilt_series(self.tree, self.series_file)

    def applied(self):
        return wrapper.quilt_applied(self.tree)

    def unapplied(self):
        return wrapper.quilt_unapplied(
            self.tree.basedir, self.patches_dir, self.series_file)

    def pop_all(self, quiet=None, force=False, refresh=False):
        return wrapper.quilt_pop_all(
            self.tree.basedir, patches_dir=self.patches_dir,
            series_file=self.series_file, quiet=quiet, force=force,
            refresh=refresh)

    def push_all(self, quiet=None, force=None, refresh=None):
        return wrapper.quilt_push_all(
            self.tree.basedir, patches_dir=self.patches_dir,
            series_file=self.series_file, quiet=quiet, force=force,
            refresh=refresh)

    def push(self, patch, quiet=None):
        return wrapper.quilt_push(
            self.tree.basedir, patch, patches_dir=self.patches_dir,
            series_file=self.series_file, quiet=quiet)

    def pop(self, patch, quiet=None):
        return wrapper.quilt_pop(
            self.tree.basedir, patch, patches_dir=self.patches_dir,
            series_file=self.series_file, quiet=quiet)
