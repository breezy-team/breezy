# Copyright (C) 2005 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""bzr upgrade logic."""

# change upgrade from .bzr to create a '.bzr-new', then do a bait and switch.


from bzrlib.bzrdir import ConvertBzrDir4To5, ConvertBzrDir5To6, BzrDir, BzrDirFormat4, BzrDirFormat5
import bzrlib.errors as errors
from bzrlib.transport import get_transport
import bzrlib.ui as ui


class Convert(object):

    def __init__(self, url):
        self.bzrdir = BzrDir.open_unsupported(url)
        if self.bzrdir.root_transport.is_readonly():
            raise errors.UpgradeReadonly
        self.transport = self.bzrdir.root_transport
        self.convert()

    def convert(self):
        self.pb = ui.ui_factory.progress_bar()
        branch = self.bzrdir.open_branch()
        if branch.bzrdir.root_transport.base != self.bzrdir.root_transport.base:
            self.pb.note("This is a checkout. The branch (%s) needs to be "
                         "upgraded separately.",
                         branch.bzrdir.root_transport.base)
        if not self.bzrdir.needs_format_update():
            raise errors.UpToDateFormat(self.bzrdir._format)
        if not self.bzrdir.can_update_format():
            raise errors.BzrError("cannot upgrade from branch format %s" %
                           self.bzrdir._format)
        self.pb.note('starting upgrade of %s', self.transport.base)
        self._backup_control_dir()
        while self.bzrdir.needs_format_update():
            converter = self.bzrdir._format.get_updater()
            self.bzrdir = converter.convert(self.bzrdir, self.pb)
        if isinstance(self.bzrdir._format, BzrDirFormat4):
            converter = ConvertBzrDir4To5()
            self.bzrdir = converter.convert(self.bzrdir, self.pb)
        if isinstance(self.bzrdir._format, BzrDirFormat5):
            converter = ConvertBzrDir5To6()
            self.bzrdir = converter.convert(self.bzrdir, self.pb)
        self.pb.note("finished")

    def _backup_control_dir(self):
        self.pb.note('making backup of tree history')
        self.transport.copy_tree('.bzr', '.bzr.backup')
        self.pb.note('%s.bzr has been backed up to %s.bzr.backup',
             self.transport.base,
             self.transport.base)
        self.pb.note('if conversion fails, you can move this directory back to .bzr')
        self.pb.note('if it succeeds, you can remove this directory if you wish')

def upgrade(url):
    Convert(url)
