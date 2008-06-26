# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib.versionedfile import VersionedFiles

class SvnTexts(VersionedFiles):
    """Subversion texts backend."""

    def check(self, progressbar=None):
        return True


class FakeRevisionTexts(VersionedFiles):
    """Fake revisions backend."""

    def check(self, progressbar=None):
        return True


class FakeInventoryTexts(VersionedFiles):
    """Fake inventories backend."""

    def check(self, progressbar=None):
        return True


