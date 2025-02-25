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

import os
import shutil
import subprocess
import tempfile

from debian.changelog import Changelog

from ... import errors as bzr_errors
from ...trace import note
from ...transport import FileExists, NoSuchFile
from .util import (
    export_with_nested,
    extract_orig_tarballs,
    get_parent_dir,
)


class SourceDistiller:
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

    def __init__(self, tree, subpath, use_existing=False):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        """
        super().__init__(tree, subpath)
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
                raise FileExists(target)
        export_with_nested(self.tree, target, subdir=self.subpath)


class FullSourceDistiller(SourceDistiller):
    """A SourceDistiller for full-source branches, a.k.a. normal mode."""

    def __init__(self, tree, subpath, upstream_provider, use_existing=False):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        :param upstream_provider: an UpstreamProvider to provide the upstream
            tarball if needed.
        """
        super().__init__(tree, subpath)
        self.upstream_provider = upstream_provider
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
                raise FileExists(target)
        parent_dir = get_parent_dir(target)
        self.upstream_provider.provide(parent_dir)
        export_with_nested(self.tree, target, subdir=self.subpath)
        # TODO(jelmer): Unapply patches, if they're applied.


class MergeModeDistiller(SourceDistiller):
    def __init__(
        self, tree, subpath, upstream_provider, top_level=False, use_existing=False
    ):
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
        super().__init__(tree, subpath)
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
                raise FileExists(target)
        elif self.use_existing:
            if not os.path.exists(target):
                raise bzr_errors.NotADirectory(target)

        # Get the upstream tarball
        parent_dir = get_parent_dir(target)
        if parent_dir != "" and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        if not self.use_existing:
            tarballs = self.upstream_provider.provide(parent_dir)
            if not os.path.exists(target):
                os.mkdir(target)
            extract_orig_tarballs(tarballs, target)
        # Now export the tree to provide the debian dir
        with tempfile.TemporaryDirectory(
            prefix="builddeb-merge-debian-"
        ) as basetempdir:
            tempdir = os.path.join(basetempdir, "export")
            if self.top_level:
                os.makedirs(tempdir)
                export_dir = os.path.join(tempdir, "debian")
            else:
                export_dir = tempdir
            export_with_nested(self.tree, export_dir, subdir=self.subpath)
            # Remove any upstream debian dir, or from previous export with
            # use_existing
            if os.path.exists(os.path.join(target, "debian")):
                shutil.rmtree(os.path.join(target, "debian"))
            shutil.copytree(tempdir, target, symlinks=True, dirs_exist_ok=True)


class DebcargoError(bzr_errors.BzrError):
    _fmt = "Debcargo failed to run."


def cargo_translate_dashes(crate):
    output = subprocess.check_output(["cargo", "search", crate])  # noqa: S607
    for line in output.splitlines(False):
        name = line.split(b" = ")[0].decode()
        return name
    return crate


def unmangle_debcargo_version(version):
    return version.replace("~", "-")


class DebcargoDistiller(SourceDistiller):
    """A SourceDistiller for unpacking a debcargo package."""

    def __init__(self, tree, subpath, top_level=False, use_existing=False):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param subpath: subpath in the tree where the package lives
        """
        super().__init__(tree, subpath)
        self.top_level = top_level
        self.use_existing = use_existing

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to
            place the tree containing the buildable source.
        """
        from debmutate.debcargo import parse_debcargo_source_name

        if os.path.exists(target):
            raise FileExists(target)
        with self.tree.get_file(
            os.path.join(
                self.subpath, "debian/changelog" if not self.top_level else "changelog"
            ),
            "r",
        ) as f:
            cl = Changelog(f, max_blocks=1)
            package = cl.package
            version = cl.version

        if not package.startswith("rust-"):
            raise NotImplementedError

        debcargo_path = [self.subpath]
        if not self.top_level:
            debcargo_path.append("debian")
        debcargo_path.append("debcargo.toml")
        try:
            debcargo_text = self.tree.get_file_text(os.path.join(*debcargo_path))
        except NoSuchFile:
            semver_suffix = False
        else:
            from toml.decoder import loads as loads_toml

            debcargo = loads_toml(debcargo_text.decode())
            semver_suffix = debcargo.get("semver_suffix")
        crate, crate_semver_version = parse_debcargo_source_name(package, semver_suffix)
        if "-" in crate:
            crate = cargo_translate_dashes(crate)
        crate_version = unmangle_debcargo_version(version.upstream_version)
        if crate_semver_version is not None:
            note(
                "Using crate name: %s, version %s (semver: %s)",
                crate,
                crate_version,
                crate_semver_version,
            )
        else:
            note("Using crate name: %s, version %s", crate, crate_version)
        try:
            subprocess.check_call(
                [
                    "debcargo",
                    "package",
                    "--changelog-ready",
                    "--config",
                    self.tree.abspath(os.path.join(*debcargo_path)),
                    "--directory",
                    target,
                    crate,
                ]
                + ([crate_version] if crate_version else [])
            )
        except subprocess.CalledProcessError as e:
            raise DebcargoError() from e
