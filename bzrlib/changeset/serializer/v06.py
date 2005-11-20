# (C) 2005 Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Serializer factory for reading and writing changesets.
"""

import os
import bzrlib.errors as errors
from bzrlib.testament import Testament
from bzrlib.changeset.serializer import (ChangesetSerializer, 
        CHANGESET_HEADER,
        format_highres_date, unpack_highres_date)
from sha import sha
from bzrlib.diff import internal_diff
from bzrlib.delta import compare_trees


class ChangesetSerializerV06(ChangesetSerializer):
    def read(self, f):
        """Read the rest of the changesets from the supplied file.

        :param f: The file to read from
        :return: A list of changesets
        """
        assert self.version == '0.6'
        # The first line of the header should have been read
        raise NotImplementedError

    def write(self, source, revision_ids, f):
        """Write the changesets to the supplied files.

        :param source: A source for revision information
        :param revision_ids: The list of revision ids to serialize
        :param f: The file to output to
        """
        self.source = source
        self.revision_ids = revision_ids
        self.to_file = f
        source.lock_read()
        try:
            self._write_main_header()
            self._write_revisions()
        finally:
            source.unlock()

    def _write_main_header(self):
        """Write the header for the changes"""
        f = self.to_file
        f.write(CHANGESET_HEADER)
        f.write('0.6\n')
        f.write('#\n')

    def _write(self, key, value, indent=1):
        """Write out meta information, with proper indenting, etc"""
        assert indent > 0, 'indentation must be greater than 0'
        f = self.to_file
        f.write('#' + (' ' * indent))
        f.write(key.encode('utf-8'))
        if not value:
            f.write(':\n')
        elif '\n' not in value:
            f.write(': ')
            f.write(value.encode('utf-8'))
            f.write('\n')
        else:
            f.write(':\n')
            for line in value.split('\n'):
                f.write('#' + (' ' * (indent+2)))
                f.write(line)
                f.write('\n')

    def _write_revisions(self):
        """Write the information for all of the revisions."""
        # The next version of changesets will write a rollup
        # at the top, and back-patches, or something else after that.
        # For now, we just write the patches in order.

        # Optimize for the case of revisions in order
        last_rev_id = None
        last_rev = None
        last_rev_tree = None

        for rev_id in self.revision_ids:
            rev = self.source.get_revision(rev_id)
            rev_tree = self.source.revision_tree(rev_id)

            # Try to only grab bases which are in the
            # revision set
            base_id = None
            for p_id in rev.parent_ids:
                if p_id in self.revision_ids:
                    base_id = p_id
                    break
            if base_id is None and rev.parent_ids:
                base_id = rev.parent_ids[0]

            if base_id == last_rev_id:
                base_rev = last_rev
                base_tree = last_rev_tree
            else:
                base_rev = self.source.get_revision(base_id)
                base_tree = self.source.revision_tree(base_id)

            self._write_revision(rev, rev_tree, base_rev, base_tree)

            last_rev_id = rev_id
            last_rev = rev
            last_rev_tree = rev_tree

    def _write_revision(self, rev, rev_tree, base_rev, base_tree):
        """Write out the information for a revision."""
        def w(key, value):
            self._write(key, value, indent=1)

        w('revision id', rev.revision_id)
        w('committer', rev.committer)
        w('date', format_highres_date(rev.timestamp, rev.timezone))
        w('message', rev.message)
        self.to_file.write('\n')

        self._write_delta(rev_tree, base_tree)

        s = sha()
        t = Testament.from_revision(self.source, rev.revision_id)
        map(s.update, t.as_text_lines())
        w('sha1', s.hexdigest())
        if rev.parent_ids:
            w('parent ids', '\n'.join(rev.parent_ids))
        if rev.properties:
            self._write('properties', None, indent=1)
            for name, value in rev.properties.items():
                self._write(name, value, indent=3)
        
        # Add an extra blank space at the end
        self.to_file.write('\n')

    def _write_delta(self, new_tree, old_tree):
        """Write out the changes between the trees."""
        DEVNULL = '/dev/null'
        old_label = ''
        new_label = ''

        def pjoin(*args):
            # Only forward slashes in changesets
            return os.path.join(*args).replace('\\', '/')

        def do_diff(old_path, file_id, new_path, kind):
            new_entry = new_tree.inventory[file_id]
            old_tree.inventory[file_id].diff(internal_diff,
                    pjoin(old_label, old_path), old_tree,
                    pjoin(new_label, new_path), new_entry, new_tree,
                    self.to_file)
        def do_meta(file_id):
            ie = new_tree.inventory[file_id]
            w(' // executable:')
            if ie.executable:
                w('yes')
            else:
                w('no')


        delta = compare_trees(old_tree, new_tree, want_unchanged=False)

        w = self.to_file.write

        for path, file_id, kind in delta.removed:
            w('=== removed %s %s\n' % (kind, path))

        for path, file_id, kind in delta.added:
            w('=== added %s %s // file-id:%s\n' % (kind, path, file_id))
            new_tree.inventory[file_id].diff(internal_diff,
                    pjoin(new_label, path), new_tree,
                    DEVNULL, None, None,
                    self.to_file, reverse=True)

        for (old_path, new_path, file_id, kind,
             text_modified, meta_modified) in delta.renamed:
            w('=== renamed %s %s // %s' % (kind, old_path, new_path))
            if meta_modified:
                do_meta(file_id)
            w('\n')
            if text_modified:
                do_diff(old_path, file_id, new_path, text_modified)

        for (path, file_id, kind,
             text_modified, meta_modified) in delta.modified:
            # TODO: Handle meta_modified
            #prop_str = get_prop_change(meta_modified)
            w('=== modified %s %s' % (kind, path))
            if meta_modified:
                do_meta(file_id)
            w('\n')
            if text_modified:
                do_diff(path, file_id, path, kind)


