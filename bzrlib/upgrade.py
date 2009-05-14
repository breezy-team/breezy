# Copyright (C) 2005, 2008, 2009 Canonical Ltd
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

"""bzr upgrade logic."""


from bzrlib import osutils
from bzrlib.bzrdir import BzrDir, BzrDirFormat, format_registry
import bzrlib.errors as errors
from bzrlib.remote import RemoteBzrDir
from bzrlib.transport import get_transport
from bzrlib.trace import mutter, note, warning
import bzrlib.ui as ui


class Convert(object):

    def __init__(self, url=None, format=None, control_dir=None):
        """Convert a Bazaar control directory to a given format.

        Either the url or control_dir parameter must be given.

        :param url: the URL of the control directory or None if the
          control_dir is explicitly given instead
        :param format: the format to convert to or None for the default
        :param control_dir: the control directory or None if it specified
          via the URL parameter instead
        """
        self.format = format
        if url is None and control_dir is None:
            raise AssertionError(
                "either the url or control_dir parameter must be set.")
        if control_dir is not None:
            self.bzrdir = control_dir
        else:
            self.bzrdir = BzrDir.open_unsupported(url)
        if isinstance(self.bzrdir, RemoteBzrDir):
            self.bzrdir._ensure_real()
            self.bzrdir = self.bzrdir._real_bzrdir
        if self.bzrdir.root_transport.is_readonly():
            raise errors.UpgradeReadonly
        self.transport = self.bzrdir.root_transport
        self.pb = ui.ui_factory.nested_progress_bar()
        try:
            self.convert()
        finally:
            self.pb.finished()

    def convert(self):
        try:
            branch = self.bzrdir.open_branch()
            if branch.bzrdir.root_transport.base != \
                self.bzrdir.root_transport.base:
                self.pb.note("This is a checkout. The branch (%s) needs to be "
                             "upgraded separately.",
                             branch.bzrdir.root_transport.base)
            del branch
        except (errors.NotBranchError, errors.IncompatibleRepositories):
            # might not be a format we can open without upgrading; see e.g.
            # https://bugs.launchpad.net/bzr/+bug/253891
            pass
        if self.format is None:
            try:
                rich_root = self.bzrdir.find_repository()._format.rich_root_data
            except errors.NoRepositoryPresent:
                rich_root = False # assume no rich roots
            if rich_root:
                format_name = "default-rich-root"
            else:
                format_name = "default"
            format = format_registry.make_bzrdir(format_name)
        else:
            format = self.format
        if not self.bzrdir.needs_format_conversion(format):
            raise errors.UpToDateFormat(self.bzrdir._format)
        if not self.bzrdir.can_convert_format():
            raise errors.BzrError("cannot upgrade from bzrdir format %s" %
                           self.bzrdir._format)
        self.bzrdir.check_conversion_target(format)
        self.pb.note('starting upgrade of %s', self.transport.base)
        self.backup_oldpath, self.backup_newpath = self.bzrdir.backup_bzrdir()
        while self.bzrdir.needs_format_conversion(format):
            converter = self.bzrdir._format.get_converter(format)
            self.bzrdir = converter.convert(self.bzrdir, self.pb)
        self.pb.note("finished")


def upgrade(url, format=None, clean_up=False):
    """Upgrade to format, or the default bzrdir format if not supplied."""
    starting_dir = BzrDir.open_unsupported(url)
    attempted, succeeded = smart_upgrade(starting_dir, format, clean_up)
    if len(attempted) > 1:
        failed = len(attempted) - len(succeeded)
        note("\nSUMMARY: %d upgrades attempted, %d succeeded, %d failed",
            len(attempted), len(succeeded), failed)


def smart_upgrade(control_dir, format, clean_up=False):
    """Convert a control directory to a new format intelligently.

    If the control directory is a shared repository, dependent branches
    are also converted provided the repository converted successfully.
    If the conversion of a branch fails, remaining branches are still tried.

    :control_dir: the BzrDir to upgrade
    :format: the format to convert to
    :param clean-up: if True, the backup.bzr directory is removed if the
      upgrade succeeded for a given repo/branch/checkout
    :return: control-dirs for attempted, control-dirs for succeeded upgrades
    """
    # If the URL is a shared repository, find the dependent branches
    dependent_branches = []
    try:
        repo = control_dir.open_repository()
    except errors.NoRepositoryPresent:
        # A branch or checkout using a shared repository higher up
        pass
    else:
        # The URL is a repository. If it successfully upgrades,
        # then upgrade the branches using it as well.
        if repo.is_shared():
            dependent_branches = repo.find_branches()

    # Do the conversions. For each conversion that succeeds, we record
    # the control directory and backup directory for later optional clean-up
    attempted = [control_dir]
    branch_info = []
    if dependent_branches:
        note("Upgrading shared repository ...")
        cv = Convert(control_dir=control_dir, format=format)
        branch_info.append((control_dir, cv.backup_newpath))
        unstacked, stacked = _sort_branches(dependent_branches)
        note("Found %d dependent branches: %d unstacked, %d stacked - "
            "upgrading ...", len(dependent_branches), len(unstacked),
            len(stacked))
        attempted.extend([br.bzrdir for br in stacked])
        branch_info.extend(_convert_branches(stacked, format, "stacked branch"))
        attempted.extend([br.bzrdir for br in unstacked])
        branch_info.extend(_convert_branches(unstacked, format))
    else:
        cv = Convert(control_dir=control_dir, format=format)
        branch_info.append((control_dir, cv.backup_newpath))

    # Clean-up if requested
    if clean_up:
        note("Removing backup directories for successful conversions ...")
        for control, backup_dir in branch_info:
            if backup_dir.startswith("file://"):
                try:
                    osutils.rmtree(backup_dir[len("file://"):])
                except Exception, ex:
                    mutter("failed to clean-up %s: %s", backup_dir, ex)
                    warning("failed to clean-up %s: %s", backup_dir, ex)
            else:
                # TODO: Use transport.delete_tree() so works on remote URLs
                warning("cannot clean-up after upgrading a remote URL yet")

    # Return the control directories for the attempted & successful conversions
    succeeded = [c for c, backup in branch_info]
    return attempted, succeeded


def _sort_branches(branches):
    """Partition branches into stacked vs unstacked.

    :return: unstacked_list, stacked_list
    """
    unstacked = []
    stacked = []
    for br in branches:
        try:
            br.get_stacked_on_url()
        except errors.NotStacked:
            unstacked.append(br)
        except errors.UnstackableBranchFormat:
            unstacked.append(br)
        else:
            stacked.append(br)
    # TODO: Within each sublist, sort the branches by path.
    return unstacked, stacked


def _convert_branches(branches, format, label="branch"):
    """Convert a sequence of branches to the given format.
    
    :return: list of (control-dir, backup-dir) tuples for successful upgrades
    """
    result = []
    for br in branches:
        try:
            cv = Convert(control_dir=br.bzrdir, format=format)
        except Exception, ex:
            # XXX: If this the right level in the Exception hierarchy to use?
            mutter("conversion error: %s", ex)
            warning("conversion error: %s", ex)
        else:
            result.append((br.bzrdir, cv.backup_newpath))
            note("upgraded %s %s", label, br.base)
    return result
