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
from bzrlib.versionedfile import FulltextContentFactory, VersionedFiles

class SvnTexts(VersionedFiles):
    """Subversion texts backend."""

    def check(self, progressbar=None):
        return True

    def add_mpdiffs(self, records):
        raise NotImplementedError(self.add_mpdiffs)

    # TODO: annotate, get_parent_map, get_record_stream, get_sha1s, 
    # iter_lines_added_or_present_in_keys, keys


class FakeVersionedFiles(VersionedFiles):
    def __init__(self, get_parent_map, get_lines):
        self._get_parent_map = get_parent_map
        self._get_lines = get_lines
        
    def check(self, progressbar=None):
        return True

    def add_mpdiffs(self, records):
        raise NotImplementedError(self.add_mpdiffs)

    def get_parent_map(self, keys):
        return dict([((k,), tuple([(p,) for p in v])) for k,v in self._get_parent_map([k for (k,) in keys]).iteritems()])

    def get_sha1s(self, keys):
        ret = {}
        for (k,) in keys:
            lines = self._get_lines(k)
            if lines is not None:
                assert isinstance(lines, list)
                ret[(k,)] = osutils.sha_strings(lines)
        return ret

    def get_record_stream(self, keys, ordering, include_delta_closure):
        for (k,) in list(keys):
            lines = self._get_lines(k)
            if lines is not None:
                assert isinstance(lines, list)
                yield FulltextContentFactory((k,), None, 
                        sha1=osutils.sha_strings(lines),
                        text=''.join(lines))


class FakeRevisionTexts(FakeVersionedFiles):
    """Fake revisions backend."""
    def __init__(self, repository):
        self.repository = repository
        super(FakeRevisionTexts, self).__init__(self.repository.get_parent_map, self.get_lines)

    def get_lines(self, key):
        return None

    # TODO: annotate, get_record_stream, 
    # iter_lines_added_or_present_in_keys, keys


class FakeInventoryTexts(FakeVersionedFiles):
    """Fake inventories backend."""
    def __init__(self, repository):
        self.repository = repository
        super(FakeInventoryTexts, self).__init__(self.repository.get_parent_map, self.get_lines)

    def get_lines(self, key):
        return osutils.split_lines(self.repository.get_inventory_xml(key))

    # TODO: annotate, get_record_stream,
    # iter_lines_added_or_present_in_keys, keys


class FakeSignatureTexts(FakeVersionedFiles):
    """Fake signatures backend."""
    def __init__(self, repository):
        self.repository = repository
        super(FakeSignatureTexts, self).__init__(self.repository.get_parent_map, self.get_lines)

    def get_lines(self, key):
        return None

    # TODO: annotate, get_record_stream, 
    # iter_lines_added_or_present_in_keys, keys

