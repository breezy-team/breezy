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

    # TODO: annotate, get_parent_map, get_record_stream, get_sha1s, 
    # iter_lines_added_or_present_in_keys, keys


class FakeVersionedFiles(VersionedFiles):
    def __init__(self, get_parent_map):
        self._get_parent_map = get_parent_map
        
    def check(self, progressbar=None):
        return True

    def get_parent_map(self, keys):
        return dict([((k,), tuple([(p,) for p in v])) for k,v in self._get_parent_map([k for (k,) in keys]).iteritems()])


class FakeRevisionTexts(FakeVersionedFiles):
    """Fake revisions backend."""

    # TODO: annotate, get_record_stream, get_sha1s, 
    # iter_lines_added_or_present_in_keys, keys


class FakeInventoryTexts(FakeVersionedFiles):
    """Fake inventories backend."""

    # TODO: annotate, get_record_stream, get_sha1s, 
    # iter_lines_added_or_present_in_keys, keys


class FakeSignatureTexts(FakeVersionedFiles):
    """Fake signatures backend."""

    # TODO: annotate, get_record_stream, get_sha1s, 
    # iter_lines_added_or_present_in_keys, keys

