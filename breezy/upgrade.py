# Copyright (C) 2005, 2006, 2008-2011 Canonical Ltd
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

"""brz upgrade logic."""

from . import errors, trace, ui, urlutils
from .bzr.remote import RemoteBzrDir
from .controldir import ControlDir, format_registry
from .i18n import gettext


class Convert:
    """Handles conversion of control directories between different formats.

    This class manages the upgrade process for Bazaar control directories,
    including backing up the existing directory and converting it to the
    specified format.
    """

    def __init__(self, url=None, format=None, control_dir=None):
        """Convert a Bazaar control directory to a given format.

        Either the url or control_dir parameter must be given.

        :param url: the URL of the control directory or None if the
          control_dir is explicitly given instead
        :param format: the format to convert to or None for the default
        :param control_dir: the control directory or None if it is
          specified via the URL parameter instead
        """
        self.format = format
        # XXX: Change to cleanup
        warning_id = "cross_format_fetch"
        saved_warning = warning_id in ui.ui_factory.suppressed_warnings
        if url is None and control_dir is None:
            raise AssertionError("either the url or control_dir parameter must be set.")
        if control_dir is not None:
            self.controldir = control_dir
        else:
            self.controldir = ControlDir.open_unsupported(url)
        if isinstance(self.controldir, RemoteBzrDir):
            self.controldir._ensure_real()
            self.controldir = self.controldir._real_bzrdir
        if self.controldir.root_transport.is_readonly():
            raise errors.UpgradeReadonly
        self.transport = self.controldir.root_transport
        ui.ui_factory.suppressed_warnings.add(warning_id)
        try:
            self.convert()
        finally:
            if not saved_warning:
                ui.ui_factory.suppressed_warnings.remove(warning_id)

    def convert(self):
        """Perform the actual conversion of the control directory.

        This method handles the conversion process, including:
        - Checking if the directory is a checkout
        - Determining the appropriate format if not specified
        - Backing up the existing directory
        - Converting to the new format

        Raises:
            errors.UpToDateFormat: If the directory is already in the requested format.
            errors.BzrError: If the directory cannot be upgraded from its current format.
        """
        try:
            branch = self.controldir.open_branch()
            if branch.user_url != self.controldir.user_url:
                ui.ui_factory.note(
                    gettext(
                        "This is a checkout. The branch (%s) needs to be upgraded"
                        " separately."
                    )
                    % (urlutils.unescape_for_display(branch.user_url, "utf-8"))
                )
            del branch
        except (errors.NotBranchError, errors.IncompatibleRepositories):
            # might not be a format we can open without upgrading; see e.g.
            # https://bugs.launchpad.net/bzr/+bug/253891
            pass
        if self.format is None:
            try:
                rich_root = self.controldir.find_repository()._format.rich_root_data
            except errors.NoRepositoryPresent:
                rich_root = False  # assume no rich roots
            format_name = "default-rich-root" if rich_root else "default"
            format = format_registry.make_controldir(format_name)
        else:
            format = self.format
        if not self.controldir.needs_format_conversion(format):
            raise errors.UpToDateFormat(self.controldir._format)
        if not self.controldir.can_convert_format():
            raise errors.BzrError(
                gettext("cannot upgrade from bzrdir format %s")
                % self.controldir._format
            )
        self.controldir.check_conversion_target(format)
        ui.ui_factory.note(
            gettext("starting upgrade of %s")
            % urlutils.unescape_for_display(self.transport.base, "utf-8")
        )

        self.backup_oldpath, self.backup_newpath = self.controldir.backup_bzrdir()
        while self.controldir.needs_format_conversion(format):
            converter = self.controldir._format.get_converter(format)
            self.controldir = converter.convert(self.controldir, None)
        ui.ui_factory.note(gettext("finished"))

    def clean_up(self):
        """Clean-up after a conversion.

        This removes the backup.bzr directory.
        """
        transport = self.transport
        backup_relpath = transport.relpath(self.backup_newpath)
        with ui.ui_factory.nested_progress_bar() as child_pb:
            child_pb.update(gettext("Deleting backup.bzr"))
            transport.delete_tree(backup_relpath)


def upgrade(url, format=None, clean_up=False, dry_run=False):
    """Upgrade locations to format.

    This routine wraps the smart_upgrade() routine with a nicer UI.
    In particular, it ensures all URLs can be opened before starting
    and reports a summary at the end if more than one upgrade was attempted.
    This routine is useful for command line tools. Other breezy clients
    probably ought to use smart_upgrade() instead.

    :param url: a URL of the locations to upgrade.
    :param format: the format to convert to or None for the best default
    :param clean-up: if True, the backup.bzr directory is removed if the
      upgrade succeeded for a given repo/branch/tree
    :param dry_run: show what would happen but don't actually do any upgrades
    :return: the list of exceptions encountered
    """
    control_dirs = [ControlDir.open_unsupported(url)]
    attempted, succeeded, exceptions = smart_upgrade(
        control_dirs, format, clean_up=clean_up, dry_run=dry_run
    )
    if len(attempted) > 1:
        attempted_count = len(attempted)
        succeeded_count = len(succeeded)
        failed_count = attempted_count - succeeded_count
        ui.ui_factory.note(
            gettext(
                "\nSUMMARY: {0} upgrades attempted, {1} succeeded, {2} failed"
            ).format(attempted_count, succeeded_count, failed_count)
        )
    return exceptions


def smart_upgrade(control_dirs, format, clean_up=False, dry_run=False):
    """Convert control directories to a new format intelligently.

    If the control directory is a shared repository, dependent branches
    are also converted provided the repository converted successfully.
    If the conversion of a branch fails, remaining branches are still tried.

    :param control_dirs: the BzrDirs to upgrade
    :param format: the format to convert to or None for the best default
    :param clean_up: if True, the backup.bzr directory is removed if the
      upgrade succeeded for a given repo/branch/tree
    :param dry_run: show what would happen but don't actually do any upgrades
    :return: attempted-control-dirs, succeeded-control-dirs, exceptions
    """
    all_attempted = []
    all_succeeded = []
    all_exceptions = []
    for control_dir in control_dirs:
        attempted, succeeded, exceptions = _smart_upgrade_one(
            control_dir, format, clean_up=clean_up, dry_run=dry_run
        )
        all_attempted.extend(attempted)
        all_succeeded.extend(succeeded)
        all_exceptions.extend(exceptions)
    return all_attempted, all_succeeded, all_exceptions


def _smart_upgrade_one(control_dir, format, clean_up=False, dry_run=False):
    """Convert a control directory to a new format intelligently.

    See smart_upgrade for parameter details.
    """
    # If the URL is a shared repository, find the dependent branches
    dependents = None
    try:
        repo = control_dir.open_repository()
    except errors.NoRepositoryPresent:
        # A branch or checkout using a shared repository higher up
        pass
    else:
        # The URL is a repository. If it successfully upgrades,
        # then upgrade the dependent branches as well.
        if repo.is_shared():
            dependents = list(repo.find_branches(using=True))

    # Do the conversions
    attempted = [control_dir]
    succeeded, exceptions = _convert_items([control_dir], format, clean_up, dry_run)
    if succeeded and dependents:
        ui.ui_factory.note(
            gettext("Found %d dependent branches - upgrading ...") % (len(dependents),)
        )
        # Convert dependent branches
        branch_cdirs = [b.controldir for b in dependents]
        successes, problems = _convert_items(
            branch_cdirs, format, clean_up, dry_run, label="branch"
        )
        attempted.extend(branch_cdirs)
        succeeded.extend(successes)
        exceptions.extend(problems)

    # Return the result
    return attempted, succeeded, exceptions


# FIXME: There are several problems below:
# - RemoteRepository doesn't support _unsupported (really ?)
# - raising AssertionError is rude and may not be necessary
# - no tests
# - the only caller uses only the label


def _get_object_and_label(control_dir):
    """Return the primary object and type label for a control directory.

    :return: object, label where:
      * object is a Branch, Repository or WorkingTree and
      * label is one of:
        * branch            - a branch
        * repository        - a repository
        * tree              - a lightweight checkout
    """
    try:
        try:
            br = control_dir.open_branch(unsupported=True, ignore_fallbacks=True)
        except NotImplementedError:
            # RemoteRepository doesn't support the unsupported parameter
            br = control_dir.open_branch(ignore_fallbacks=True)
    except errors.NotBranchError:
        pass
    else:
        return br, "branch"
    try:
        repo = control_dir.open_repository()
    except errors.NoRepositoryPresent:
        pass
    else:
        return repo, "repository"
    try:
        wt = control_dir.open_workingtree()
    except (errors.NoWorkingTree, errors.NotLocalUrl):
        pass
    else:
        return wt, "tree"
    raise AssertionError("unknown type of control directory %s", control_dir)


def _convert_items(items, format, clean_up, dry_run, label=None):
    """Convert a sequence of control directories to the given format.

    :param items: the control directories to upgrade
    :param format: the format to convert to or None for the best default
    :param clean-up: if True, the backup.bzr directory is removed if the
      upgrade succeeded for a given repo/branch/tree
    :param dry_run: show what would happen but don't actually do any upgrades
    :param label: the label for these items or None to calculate one
    :return: items successfully upgraded, exceptions
    """
    succeeded = []
    exceptions = []
    with ui.ui_factory.nested_progress_bar() as child_pb:
        child_pb.update(gettext("Upgrading bzrdirs"), 0, len(items))
        for i, control_dir in enumerate(items):
            # Do the conversion
            location = control_dir.root_transport.base
            _bzr_object, bzr_label = _get_object_and_label(control_dir)
            type_label = label or bzr_label
            child_pb.update(gettext("Upgrading %s") % (type_label), i + 1, len(items))
            ui.ui_factory.note(
                gettext("Upgrading {0} {1} ...").format(
                    type_label,
                    urlutils.unescape_for_display(location, "utf-8"),
                )
            )
            try:
                if not dry_run:
                    cv = Convert(control_dir=control_dir, format=format)
            except errors.UpToDateFormat as ex:
                ui.ui_factory.note(str(ex))
                succeeded.append(control_dir)
                continue
            except Exception as ex:
                trace.warning(f"conversion error: {ex}")
                exceptions.append(ex)
                continue

            # Do any required post processing
            succeeded.append(control_dir)
            if clean_up:
                try:
                    ui.ui_factory.note(gettext("Removing backup ..."))
                    if not dry_run:
                        cv.clean_up()
                except Exception as ex:
                    trace.warning(
                        gettext("failed to clean-up {0}: {1}") % (location, ex)
                    )
                    exceptions.append(ex)

    # Return the result
    return succeeded, exceptions
