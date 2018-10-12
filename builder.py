#    builder.py -- Classes for building packages
#    Copyright (C) 2006, 2007 James Westby <jw+debian@jameswestby.net>
#    
#    This file is part of breezy-debian.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from __future__ import absolute_import

import shutil
import subprocess
import os

from ...trace import note

from .errors import (
    NoSourceDirError,
    BuildFailedError,
    )
from .quilt import quilt_push_all
from .util import (
    get_parent_dir,
    subprocess_setup,
    FORMAT_3_0_QUILT,
    )


class DebBuild(object):
    """The object that does the building work."""

    def __init__(self, distiller, target_dir, builder, use_existing=False):
        """Create a builder.

        :param distiller: the SourceDistiller that will get the source to
            build.
        :param target_dir: the directory in which to do all the work.
        :param builder: the build command to use.
        :param use_existing: whether to re-use the target_dir if it exists.
        """
        self.distiller = distiller
        self.target_dir = target_dir
        self.builder = builder
        self.use_existing = use_existing

    def prepare(self):
        """Do any preparatory steps that should be run before the build.

        It checks that everything is well, and that some needed dirs are
        created.
        """
        parent_dir = get_parent_dir(self.target_dir)
        if parent_dir != '' and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        if os.path.exists(self.target_dir):
            if not self.use_existing:
                note("Purging the build dir: %s", self.target_dir)
                shutil.rmtree(self.target_dir)
            else:
                note("Not purging build dir as requested: %s",
                        self.target_dir)
        else:
            if self.use_existing:
                raise NoSourceDirError

    def export(self, apply_quilt_patches=True):
        self.distiller.distill(self.target_dir)
        if apply_quilt_patches:
            self._apply_quilt_patches()

    def _apply_quilt_patches(self):
        if not os.path.isfile(os.path.join(self.target_dir, "debian/patches/series")):
            return
        format_path = os.path.join(self.target_dir, "debian/source/format")
        if not os.path.isfile(format_path):
            return
        with open(format_path, 'r') as f:
            if f.read().strip() == FORMAT_3_0_QUILT:
                quilt_push_all(os.path.abspath(self.target_dir))

    def build(self):
        """This builds the package using the supplied command."""
        note("Building the package in %s, using %s", self.target_dir,
                self.builder)
        proc = subprocess.Popen(self.builder, shell=True, cwd=self.target_dir,
                preexec_fn=subprocess_setup)
        proc.wait()
        if proc.returncode != 0:
            raise BuildFailedError

    def clean(self):
        """This removes the build directory."""
        note("Cleaning build dir: %s", self.target_dir)
        shutil.rmtree(self.target_dir)
