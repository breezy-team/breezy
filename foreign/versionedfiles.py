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

from bzrlib import osutils
from bzrlib.versionedfile import VirtualVersionedFiles


class VirtualRevisionTexts(VirtualVersionedFiles):
    """Virtual revisions backend."""
    def __init__(self, repository):
        self.repository = repository
        super(VirtualRevisionTexts, self).__init__(self.repository._make_parents_provider().get_parent_map, self.get_lines)

    def get_lines(self, key):
        return osutils.split_lines(self.repository.get_revision_xml(key))

    # TODO: annotate, iter_lines_added_or_present_in_keys, keys


class VirtualInventoryTexts(VirtualVersionedFiles):
    """Virtual inventories backend."""
    def __init__(self, repository):
        self.repository = repository
        super(VirtualInventoryTexts, self).__init__(self.repository._make_parents_provider().get_parent_map, self.get_lines)

    def get_lines(self, key):
        return osutils.split_lines(self.repository.get_inventory_xml(key))

    # TODO: annotate, iter_lines_added_or_present_in_keys, keys


class VirtualSignatureTexts(VirtualVersionedFiles):
    """Virtual signatures backend."""
    def __init__(self, repository):
        self.repository = repository
        super(VirtualSignatureTexts, self).__init__(self.repository._make_parents_provider().get_parent_map, self.get_lines)

    def get_lines(self, key):
        return osutils.split_lines(self.repository.get_signature_text(key))

    # TODO: annotate, iter_lines_added_or_present_in_keys, keys

