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

import shutil
import subprocess
import os
import tempfile

from ...errors import BzrError
from ...trace import note

from .hooks import run_hook
from .util import (
    get_parent_dir,
    subprocess_setup,
    find_changes_files,
    dget_changes,
    )


class ChangesFileMissing(BzrError):

    _fmt = "Missing changes file."


class NoSourceDirError(BzrError):

    _fmt = ("There is no existing source directory to use. Use "
            "--export-only or --dont-purge to get one that can be used")


class BuildFailedError(BzrError):
    _fmt = "The build failed."


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

    def export(self):
        self.distiller.distill(self.target_dir)

    def before_build(self):
        subprocess.check_call(
            ['dpkg-source', '--before-build', self.target_dir],
            preexec_fn=subprocess_setup)

    def after_build(self):
        subprocess.check_call(
            ['dpkg-source', '--after-build', self.target_dir],
            preexec_fn=subprocess_setup, )

    def build(self):
        """This builds the package using the supplied command."""
        note("Building the package in %s, using %s", self.target_dir,
             self.builder)
        proc = subprocess.Popen(
            self.builder, shell=True, cwd=self.target_dir,
            preexec_fn=subprocess_setup)
        proc.wait()
        if proc.returncode != 0:
            raise BuildFailedError

    def clean(self):
        """This removes the build directory."""
        note("Cleaning build dir: %s", self.target_dir)
        shutil.rmtree(self.target_dir)


def do_build(package_name, version, distiller, local_tree, config,
             build_command, target_dir=None):
    """Actually run a build."""
    with tempfile.TemporaryDirectory() as bd:
        build_source_dir = os.path.join(
            bd, package_name + "-" + version.upstream_version)
        builder = DebBuild(
                distiller, build_source_dir,
                build_command,
                use_existing=False)
        builder.prepare()
        run_hook(local_tree, 'pre-export', config)
        builder.export()
        run_hook(local_tree, 'pre-build', config, wd=build_source_dir)
        builder.build()
        run_hook(local_tree, 'post-build', config, wd=build_source_dir)
        if target_dir is not None:
            ret = {}
            for kind, entry in find_changes_files(bd, package_name, version):
                ret[kind] = dget_changes(entry.path, target_dir)
            if not ret:
                raise ChangesFileMissing()
            return ret
