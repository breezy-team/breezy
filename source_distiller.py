#    source_distiller.py -- Getting the source to build from a branch
#    Copyright (C) 2008, 2009 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
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

from __future__ import absolute_import

from debian.changelog import Changelog

import os
import shutil
import subprocess
import sys
import tempfile

from ... import errors as bzr_errors
from ...export import (
    export,
    )

from .util import (
    extract_orig_tarballs,
    get_parent_dir,
    recursive_copy,
    )


class SourceDistiller(object):
    """A source distiller extracts the source to build from a location.

    It does whatever is needed to give you a source you can build at
    a location of your choice.
    """

    def __init__(self, tree, subpath):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        """
        self.tree = tree
        self.subpath = subpath

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to
            place the tree containing the buildable source.
        """
        raise NotImplementedError(self.distill)


class NativeSourceDistiller(SourceDistiller):
    """A SourceDistiller for unpacking a native package from a branch."""

    def __init__(self, tree, subpath):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        """
        super(NativeSourceDistiller, self).__init__(tree, subpath)

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to
            place the tree containing the buildable source.
        """
        if os.path.exists(target):
            raise bzr_errors.FileExists(target)
        export(self.tree, target, subdir=self.subpath)


class FullSourceDistiller(SourceDistiller):
    """A SourceDistiller for full-source branches, a.k.a. normal mode"""

    def __init__(self, tree, subpath, upstream_provider):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        :param upstream_provider: an UpstreamProvider to provide the upstream
            tarball if needed.
        """
        super(FullSourceDistiller, self).__init__(tree, subpath)
        self.upstream_provider = upstream_provider

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to
            place the tree containing the buildable source.
        """
        if os.path.exists(target):
            raise bzr_errors.FileExists(target)
        parent_dir = get_parent_dir(target)
        self.upstream_provider.provide(parent_dir)
        export(self.tree, target, subdir=self.subpath)
        # TODO(jelmer): Unapply patches, if they're applied.


class MergeModeDistiller(SourceDistiller):

    def __init__(self, tree, subpath, upstream_provider, top_level=False,
                 use_existing=False):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        :param upstream_provider: an UpstreamProvider to provide the upstream
            tarball if needed.
        :param top_level: if the tree is in the top level directory instead of
            inside debian/.
        :param use_existing: whether the distiller should re-use an existing
            target if the distiller supports it.
        """
        super(MergeModeDistiller, self).__init__(tree, subpath)
        self.upstream_provider = upstream_provider
        self.top_level = top_level
        self.use_existing = use_existing

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to
            place the tree containing the buildable source.
        """
        if not self.use_existing:
            if os.path.exists(target):
                raise bzr_errors.FileExists(target)
        elif self.use_existing:
            if not os.path.exists(target):
                raise bzr_errors.NotADirectory(target)

        # Get the upstream tarball
        parent_dir = get_parent_dir(target)
        if parent_dir != '' and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        if not self.use_existing:
            tarballs = self.upstream_provider.provide(parent_dir)
            if not os.path.exists(target):
                os.mkdir(target)
            extract_orig_tarballs(tarballs, target)
        # Now export the tree to provide the debian dir
        with tempfile.TemporaryDirectory(
                prefix='builddeb-merge-debian-') as basetempdir:
            tempdir = os.path.join(basetempdir, "export")
            if self.top_level:
                os.makedirs(tempdir)
                export_dir = os.path.join(tempdir, 'debian')
            else:
                export_dir = tempdir
            export(self.tree, export_dir, subdir=self.subpath)
            # Remove any upstream debian dir, or from previous export with
            # use_existing
            if os.path.exists(os.path.join(target, 'debian')):
                shutil.rmtree(os.path.join(target, 'debian'))
            if sys.version_info >= (3, 8):
                shutil.copytree(
                    tempdir, target, symlinks=True, dirs_exist_ok=True)
            else:
                recursive_copy(tempdir, target)


class DebcargoError(bzr_errors.BzrError):

    _fmt = "Debcargo failed to run."


class DebcargoDistiller(SourceDistiller):
    """A SourceDistiller for unpacking a debcargo package."""

    def __init__(self, tree, subpath, top_level=False, use_existing=False):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        """
        super(DebcargoDistiller, self).__init__(tree, subpath)
        self.top_level = top_level
        self.use_existing = use_existing

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to
            place the tree containing the buildable source.
        """
        if os.path.exists(target):
            raise bzr_errors.FileExists(target)
        with self.tree.get_file(os.path.join(
                self.subpath,
                'debian/changelog' if not self.top_level else
                'changelog'), 'r') as f:
            cl = Changelog(f, max_blocks=1)
            package = cl.package

        if not package.startswith('rust-'):
            raise NotImplementedError

        crate = package[len('rust-'):]

        debcargo_path = [self.subpath]
        if not self.top_level:
            debcargo_path.append('debian')
        debcargo_path.append('debcargo.toml')
        try:
            subprocess.check_call([
                'debcargo', 'package',
                '--changelog-ready',
                '--config', self.tree.abspath(os.path.join(*debcargo_path)),
                '--directory', target, crate])
        except subprocess.CalledProcessError:
            raise DebcargoError()
