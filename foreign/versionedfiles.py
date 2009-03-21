# Copyright (C) 2005-2009 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib import (
    osutils,
    )
from bzrlib.versionedfile import (
    VirtualVersionedFiles,
    )

from bzrlib.errors import (
    NoSuchRevision,
    )


class VirtualRevisionTexts(VirtualVersionedFiles):
    """Virtual revisions backend."""
    def __init__(self, repository):
        self.repository = repository
        super(VirtualRevisionTexts, self).__init__(self.repository._make_parents_provider().get_parent_map, self.get_lines)

    def get_lines(self, key):
        try:
            return osutils.split_lines(self.repository.get_revision_xml(key))
        except NoSuchRevision:
            return None

    # TODO: annotate

    def keys(self):
        return self.repository.all_revision_ids()


class VirtualInventoryTexts(VirtualVersionedFiles):
    """Virtual inventories backend."""
    def __init__(self, repository):
        self.repository = repository
        super(VirtualInventoryTexts, self).__init__(self.repository._make_parents_provider().get_parent_map, self.get_lines)

    def get_lines(self, key):
        try:
            return osutils.split_lines(self.repository.get_inventory_xml(key))
        except NoSuchRevision:
            return None

    def keys(self):
        return self.repository.all_revision_ids()

    # TODO: annotate


class VirtualSignatureTexts(VirtualVersionedFiles):
    """Virtual signatures backend."""
    def __init__(self, repository):
        self.repository = repository
        super(VirtualSignatureTexts, self).__init__(self.repository._make_parents_provider().get_parent_map, self.get_lines)

    def get_lines(self, key):
        try:
            return osutils.split_lines(self.repository.get_signature_text(key))
        except NoSuchRevision:
            return None

    def keys(self):
        return self.repository.all_revision_ids()

    # TODO: annotate

