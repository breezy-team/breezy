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

    def backup_path(self):
        """Return the url of the backup path used."""
        return self.backup_newpath


def upgrade(urls, format=None, clean_up=False):
    """Upgrade locations to format.
    
    :param urls: a sequence of URLs to the locations to upgrade.
      For backwards compatibility, if urls is a string, it is treated
      as a single URL.
    :param format: the format to convert to or None for the best default
    :param clean-up: if True, the backup.bzr directory is removed if the
      upgrade succeeded for a given repo/branch/tree
    :return: the list of exceptions encountered
    """
    if isinstance(urls, str):
        urls = [urls]
    attempted_count = 0
    succeeded_count = 0
    all_exceptions = []
    for url in urls:
        starting_dir = BzrDir.open_unsupported(url)
        attempted, succeeded, exceptions = smart_upgrade(starting_dir, format,
            clean_up=clean_up)
        attempted_count += len(attempted)
        succeeded_count += len(succeeded)
        all_exceptions.extend(exceptions)
    if attempted_count > 1:
        failed_count = attempted_count - succeeded_count
        note("\nSUMMARY: %d upgrades attempted, %d succeeded, %d failed",
            attempted_count, succeeded_count, failed_count)
    return all_exceptions


def smart_upgrade(control_dir, format, clean_up=False):
    """Convert a control directory to a new format intelligently.

    If the control directory is a shared repository, dependent branches and
    trees are also converted provided the repository converted successfully.
    If the conversion of a branch fails, remaining branches are still tried.

    :param control_dir: the BzrDir to upgrade
    :param format: the format to convert to or None for the best default
    :param clean-up: if True, the backup.bzr directory is removed if the
      upgrade succeeded for a given repo/branch/tree
    :return: attempted-control-dirs, succeeded-control-dirs, exceptions
    """
    # If the URL is a shared repository, find the dependent branches & trees
    dependents = None
    try:
        repo = control_dir.open_repository()
    except errors.NoRepositoryPresent:
        # A branch or checkout using a shared repository higher up
        pass
    else:
        # The URL is a repository. If it successfully upgrades,
        # then upgrade the dependent branches and trees as well.
        if repo.is_shared():
            dependents = _find_repo_dependents(repo)

    # Do the conversions
    attempted = [control_dir]
    succeeded, exceptions = _convert_items([control_dir], format, clean_up,
        verbose=dependents)
    if succeeded and dependents:
        branches, trees = dependents
        note("Found %d dependents: %d branches, %d trees - upgrading ...",
            len(dependents), len(branches), len(trees))

        # Convert dependent branches
        branch_cdirs = [b.bzrdir for b in branches]
        successes, problems = _convert_items(branch_cdirs, format, clean_up,
            label="branch")
        attempted.extend(branch_cdirs)
        succeeded.append(successes)
        exceptions.append(problems)

        # Convert dependent trees
        # TODO: Filter trees so that we don't attempt to convert trees
        # referring to branches that failed.
        tree_cdirs = [t.bzrdir for t in trees]
        successes, problems = _convert_items(tree_cdirs, format, clean_up,
            label="tree")
        attempted.extend(tree_cdirs)
        succeeded.append(successes)
        exceptions.append(problems)

    # Return the result
    return attempted, succeeded, exceptions


def _convert_items(items, format, clean_up, label=None, verbose=True):
    """Convert a sequence of control directories to the given format.
 
    :param items: the control directories to upgrade
    :param format: the format to convert to or None for the best default
    :param clean-up: if True, the backup.bzr directory is removed if the
      upgrade succeeded for a given repo/branch/tree
    :param label: the label for these items or None to calculate one
    :param verbose: if True, output a message before starting and
      display any problems encountered
    :return: items successfully upgraded, exceptions
    """
    succeeded = []
    exceptions = []
    for control_dir in items:
        if verbose:
            type_label = label or control_dir.get_object_and_label()[1]
            location = control_dir.root_transport.base
            note("Upgrading %s %s ...", type_label, location)
        try:
            cv = Convert(control_dir=control_dir, format=format)
        except Exception, ex:
            # XXX: If this the right level in the Exception hierarchy to use?
            _verbose_warning(verbose, "conversion error: %s" % ex)
            exceptions.append(ex)
        else:
            if clean_up:
                try:
                    backup = cv.backup_path()
                    _clean_up(control_dir, backup, verbose)
                except Exception, ex:
                    _verbose_warning(verbose, "failed to clean-up %s: %s" %
                        (backup_dir, ex))
                    exceptions.append(ex)
            succeeded.append(control_dir)
    return succeeded, exceptions


def _clean_up(control_dir, backup, verbose):
    if backup.startswith("file://"):
        osutils.rmtree(backup[len("file://"):])
    else:
        # TODO: Use transport.delete_tree() so works on remote URLs
        _verbose_warning(verbose,
            "cannot clean-up after upgrading a remote URL yet")


def _verbose_warning(verbose, msg):
    mutter(msg)
    if verbose:
        warning(msg)


# Maybe move this helper method into repository.py ...
def _find_repo_dependents(repo):
    """Find the branches using a shared repository and trees using the branches.

    :return: (branches, trees) or None if none.
    """
    # TODO: find trees (lightweight checkouts), not just branches
    branches = repo.find_branches()
    if branches:
        return (branches, [])
    else:
        return None
