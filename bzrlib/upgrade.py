# Copyright (C) 2005, 2006, 2008, 2009, 2010 Canonical Ltd
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


from bzrlib.bzrdir import BzrDir, format_registry
import bzrlib.errors as errors
from bzrlib.remote import RemoteBzrDir
import bzrlib.ui as ui


class Convert(object):

    def __init__(self, url, format=None):
        self.format = format
        self.bzrdir = BzrDir.open_unsupported(url)
        # XXX: Change to cleanup
        warning_id = 'cross_format_fetch'
        saved_warning = warning_id in ui.ui_factory.suppressed_warnings
        if isinstance(self.bzrdir, RemoteBzrDir):
            self.bzrdir._ensure_real()
            self.bzrdir = self.bzrdir._real_bzrdir
        if self.bzrdir.root_transport.is_readonly():
            raise errors.UpgradeReadonly
        self.transport = self.bzrdir.root_transport
        ui.ui_factory.suppressed_warnings.add(warning_id)
        try:
            self.convert()
        finally:
            if not saved_warning:
                ui.ui_factory.suppressed_warnings.remove(warning_id)

    def convert(self):
        try:
            branch = self.bzrdir.open_branch()
            if branch.bzrdir.root_transport.base != \
                self.bzrdir.root_transport.base:
                ui.ui_factory.note("This is a checkout. The branch (%s) needs to be "
                             "upgraded separately." %
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
        ui.ui_factory.note('starting upgrade of %s' % self.transport.base)

        self.bzrdir.backup_bzrdir()
        while self.bzrdir.needs_format_conversion(format):
            converter = self.bzrdir._format.get_converter(format)
            self.bzrdir = converter.convert(self.bzrdir, None)
        ui.ui_factory.note("finished")


def upgrade(url, format=None):
    """Upgrade to format, or the default bzrdir format if not supplied."""
    Convert(url, format)
