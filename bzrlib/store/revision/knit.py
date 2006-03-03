# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""VersionedFile based revision store.

This stores revisions as individual versions in a VersionedFileStore.
"""


from bzrlib.store.revision import RevisionStore
from bzrlib.transport import get_transport


class KnitRevisionStoreFactory(object):
    """Factory to create a KnitRevisionStore for testing."""

    def create(self, url):
        """Create a revision store at url."""
        t = get_transport(url)
        return RevisionStore()

    def __str__(self):
        return "KnitRevisionStore"
