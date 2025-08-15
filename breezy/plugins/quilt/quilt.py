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

import os

from . import wrapper

QuiltError = wrapper.QuiltError


class QuiltPatches:
    """Management object for a stack of quilt patches."""

    def __init__(self, tree, patches_dir=None, series_file=None):
        """Initialize a QuiltPatches instance.

        Args:
            tree: The working tree containing the quilt patches.
            patches_dir: Directory containing patch files. If None, will be
                auto-detected from .pc/.quilt_patches or default to 'patches'.
            series_file: Name of the series file listing patches. If None,
                will be auto-detected from .pc/.quilt_series or default to 'series'.
        """
        self.tree = tree
        if patches_dir is None:
            if tree.has_filename(".pc/.quilt_patches"):
                patches_dir = os.fsdecode(
                    tree.get_file_text(".pc/.quilt_patches")
                ).rstrip("\n")
            else:
                patches_dir = wrapper.DEFAULT_PATCHES_DIR
        self.patches_dir = patches_dir
        if series_file is None:
            if tree.has_filename(".pc/.quilt_series"):
                series_file = os.fsdecode(
                    tree.get_file_text(".pc/.quilt_series")
                ).rstrip("\n")
            else:
                series_file = wrapper.DEFAULT_SERIES_FILE
        self.series_file = series_file
        self.series_path = os.path.join(self.patches_dir, self.series_file)

    @classmethod
    def find(cls, tree):
        """Find and create a QuiltPatches instance for a tree.

        Searches for quilt patch directories in common locations.

        Args:
            tree: The working tree to search for quilt patches.

        Returns:
            QuiltPatches instance if patches are found, None otherwise.
        """
        if tree.has_filename(".pc/.quilt_patches"):
            return cls(tree)
        for name in ["patches", "debian/patches"]:
            if tree.has_filename(name):
                return cls(tree, name)
        return None

    def upgrade(self):
        """Upgrade the quilt metadata to the latest version.

        Returns:
            Result of the quilt upgrade operation.
        """
        return wrapper.quilt_upgrade(self.tree.basedir)

    def series(self):
        """Get the list of all patches in the series.

        Returns:
            List of patch names in the order they appear in the series file.
        """
        return wrapper.quilt_series(self.tree, self.series_path)

    def applied(self):
        """Get the list of currently applied patches.

        Returns:
            List of patch names that are currently applied to the tree.
        """
        return wrapper.quilt_applied(self.tree)

    def unapplied(self):
        """Get the list of patches that are not currently applied.

        Returns:
            List of patch names that are in the series but not applied.
        """
        return wrapper.quilt_unapplied(
            self.tree.basedir, self.patches_dir, self.series_file
        )

    def pop_all(self, quiet=None, force=False, refresh=False):
        """Remove all applied patches from the tree.

        Args:
            quiet: If True, suppress normal output. If None, use default.
            force: If True, force removal even if patches don't apply cleanly.
            refresh: If True, refresh patches before removing.

        Returns:
            Result of the quilt pop operation.

        Raises:
            QuiltError: If the pop operation fails.
        """
        return wrapper.quilt_pop_all(
            self.tree.basedir,
            patches_dir=self.patches_dir,
            series_file=self.series_file,
            quiet=quiet,
            force=force,
            refresh=refresh,
        )

    def push_all(self, quiet=None, force=None, refresh=None):
        """Apply all patches in the series to the tree.

        Args:
            quiet: If True, suppress normal output. If None, use default.
            force: If True, force application even if patches don't apply cleanly.
            refresh: If True, refresh patches after applying.

        Returns:
            Result of the quilt push operation.

        Raises:
            QuiltError: If the push operation fails.
        """
        return wrapper.quilt_push_all(
            self.tree.basedir,
            patches_dir=self.patches_dir,
            series_file=self.series_file,
            quiet=quiet,
            force=force,
            refresh=refresh,
        )

    def push(self, patch, quiet=None, force=None, refresh=None):
        """Apply patches up to and including the specified patch.

        Args:
            patch: Name of the patch to push to.
            quiet: If True, suppress normal output. If None, use default.
            force: If True, force application even if patches don't apply cleanly.
            refresh: If True, refresh patches after applying.

        Returns:
            Result of the quilt push operation.

        Raises:
            QuiltError: If the push operation fails.
        """
        return wrapper.quilt_push(
            self.tree.basedir,
            patch,
            patches_dir=self.patches_dir,
            series_file=self.series_file,
            quiet=quiet,
            force=force,
            refresh=refresh,
        )

    def pop(self, patch, quiet=None):
        """Remove patches down to but not including the specified patch.

        Args:
            patch: Name of the patch to pop to.
            quiet: If True, suppress normal output. If None, use default.

        Returns:
            Result of the quilt pop operation.

        Raises:
            QuiltError: If the pop operation fails.
        """
        return wrapper.quilt_pop(
            self.tree.basedir,
            patch,
            patches_dir=self.patches_dir,
            series_file=self.series_file,
            quiet=quiet,
        )

    def delete(self, patch, remove=False):
        """Delete a patch from the series.

        Args:
            patch: Name of the patch to delete.
            remove: If True, also remove the patch file from disk.

        Returns:
            Result of the quilt delete operation.

        Raises:
            QuiltError: If the delete operation fails.
        """
        return wrapper.quilt_delete(
            self.tree.basedir,
            patch,
            patches_dir=self.patches_dir,
            series_file=self.series_file,
            remove=remove,
        )
