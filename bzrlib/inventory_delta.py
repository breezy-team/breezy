# Copyright (C) 2008, 2009 Canonical Ltd
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

"""Inventory delta serialisation.

See doc/developers/inventory.txt for the design and rationalisation.

In this module the interesting classes are:
 - InventoryDelta - object to read/write journalled inventories.
"""

__all__ = ['InventoryDelta']

from bzrlib import errors, lazy_regex
from bzrlib.osutils import basename, sha_string, sha_strings
from bzrlib import inventory
from bzrlib.revision import NULL_REVISION
from bzrlib.tsort import topo_sort


def _directory_content(entry):
    """Serialise the content component of entry which is a directory.
    
    :param entry: An InventoryDirectory.
    """
    return "dir"


def _file_content(entry):
    """Serialise the content component of entry which is a file.
    
    :param entry: An InventoryFile.
    """
    if entry.executable:
        exec_bytes = 'Y'
    else:
        exec_bytes = ''
    size_exec_sha = (entry.text_size, exec_bytes, entry.text_sha1)
    if None in size_exec_sha:
        raise errors.BzrError('Missing size or sha for %s' % entry.file_id)
    return "file\x00%d\x00%s\x00%s" % size_exec_sha


def _link_content(entry):
    """Serialise the content component of entry which is a symlink.
    
    :param entry: An InventoryLink.
    """
    target = entry.symlink_target
    if target is None:
        raise errors.BzrError('Missing target for %s' % entry.file_id)
    return "link\x00%s" % target.encode('utf8')


def _reference_content(entry):
    """Serialise the content component of entry which is a tree-reference.
    
    :param entry: A TreeReference.
    """
    tree_revision = entry.reference_revision
    if tree_revision is None:
        raise errors.BzrError('Missing reference revision for %s' % entry.file_id)
    return "tree\x00%s" % tree_revision


def _dir_to_entry(content, name, parent_id, file_id, last_modified,
    _type=inventory.InventoryDirectory):
    """Convert a dir content record to an InventoryDirectory."""
    result = _type(file_id, name, parent_id)
    result.revision = last_modified
    return result


def _file_to_entry(content, name, parent_id, file_id, last_modified,
    _type=inventory.InventoryFile):
    """Convert a dir content record to an InventoryFile."""
    result = _type(file_id, name, parent_id)
    result.revision = last_modified
    result.text_size = int(content[1])
    result.text_sha1 = content[3]
    if content[2]:
        result.executable = True
    else:
        result.executable = False
    return result


def _link_to_entry(content, name, parent_id, file_id, last_modified,
    _type=inventory.InventoryLink):
    """Convert a link content record to an InventoryLink."""
    result = _type(file_id, name, parent_id)
    result.revision = last_modified
    result.symlink_target = content[1].decode('utf8')
    return result


def _tree_to_entry(content, name, parent_id, file_id, last_modified,
    _type=inventory.TreeReference):
    """Convert a tree content record to a TreeReference."""
    result = _type(file_id, name, parent_id)
    result.revision = last_modified
    result.reference_revision = content[1]
    return result



class InventoryDeltaSerializer(object):
    """Serialize and deserialize inventory deltas."""

    FORMAT_1 = 'bzr inventory delta v1 (bzr 1.14)'
    _file_ids_altered_regex = lazy_regex.lazy_compile(
        '^(?P<path_utf8>[^\x00]+)\x00(?P<file_id>[^\x00]+)\x00[^\x00]*\x00'
        '(?P<revision_id>[^\x00]+)\x00'
        )

    def __init__(self, versioned_root, tree_references):
        """Create an InventoryDelta.

        :param versioned_root: If True, any root entry that is seen is expected
            to be versioned, and root entries can have any fileid.
        :param tree_references: If True support tree-reference entries.
        """
        self._versioned_root = versioned_root
        self._tree_references = tree_references
        self._entry_to_content = {
            'directory': _directory_content,
            'file': _file_content,
            'symlink': _link_content,
        }
        if tree_references:
            self._entry_to_content['tree-reference'] = _reference_content

    def delta_to_lines(self, old_name, new_name, delta_to_new):
        """Return a line sequence for delta_to_new.

        :param old_name: A UTF8 revision id for the old inventory.  May be
            NULL_REVISION if there is no older inventory and delta_to_new
            includes the entire inventory contents.
        :param new_name: The version name of the inventory we create with this
            delta.
        :param delta_to_new: An inventory delta such as Inventory.apply_delta
            takes.
        :return: The serialised delta as lines.
        """
        lines = ['', '', '', '', '']
        to_line = self._delta_item_to_line
        for delta_item in delta_to_new:
            lines.append(to_line(delta_item))
            if lines[-1].__class__ != str:
                raise errors.BzrError(
                    'to_line generated non-str output %r' % lines[-1])
        lines.sort()
        lines[0] = "format: %s\n" % InventoryDeltaSerializer.FORMAT_1
        lines[1] = "parent: %s\n" % old_name
        lines[2] = "version: %s\n" % new_name
        lines[3] = "versioned_root: %s\n" % self._serialize_bool(
            self._versioned_root)
        lines[4] = "tree_references: %s\n" % self._serialize_bool(
            self._tree_references)
        return lines

    def _serialize_bool(self, value):
        if value:
            return "true"
        else:
            return "false"

    def _delta_item_to_line(self, delta_item):
        """Convert delta_item to a line."""
        _, newpath, file_id, entry = delta_item
        if newpath is None:
            # delete
            newpath_utf8 = 'None'
            parent_id = ''
            last_modified = NULL_REVISION
            content = 'deleted\x00\x00'
        else:
            # TODO: Test real-world utf8 cache hit rate. It may be a win.
            newpath_utf8 = '/' + newpath.encode('utf8')
            # Serialise None as ''
            parent_id = entry.parent_id or ''
            # Serialise unknown revisions as NULL_REVISION
            last_modified = entry.revision
            # special cases for /
            if newpath_utf8 == '/' and not self._versioned_root:
                if file_id != 'TREE_ROOT':
                    raise errors.BzrError(
                        'file_id %s is not TREE_ROOT for /' % file_id)
                if last_modified is not None:
                    raise errors.BzrError(
                        'Version present for / in %s' % file_id)
                last_modified = NULL_REVISION
            if last_modified is None:
                raise errors.BzrError("no version for fileid %s" % file_id)
            content = self._entry_to_content[entry.kind](entry)
        return ("%s\x00%s\x00%s\x00%s\x00%s\n" %
            (newpath_utf8, file_id, parent_id, last_modified, content))

    def _deserialize_bool(self, value):
        if value == "true":
            return True
        elif value == "false":
            return False
        else:
            raise errors.BzrError("value %r is not a bool" % (value,))

    def parse_text_bytes(self, bytes):
        """Parse the text bytes of a journal entry.

        :param bytes: The bytes to parse. This can be obtained by calling
            delta_to_lines and then doing ''.join(delta_lines).
        :return: (parent_id, new_id, inventory_delta)
        """
        lines = bytes.split('\n')[:-1] # discard the last empty line
        if not lines or lines[0] != 'format: %s' % InventoryDeltaSerializer.FORMAT_1:
            raise errors.BzrError('unknown format %r' % lines[0:1])
        if len(lines) < 2 or not lines[1].startswith('parent: '):
            raise errors.BzrError('missing parent: marker')
        journal_parent_id = lines[1][8:]
        if len(lines) < 3 or not lines[2].startswith('version: '):
            raise errors.BzrError('missing version: marker')
        journal_version_id = lines[2][9:]
        if len(lines) < 4 or not lines[3].startswith('versioned_root: '):
            raise errors.BzrError('missing versioned_root: marker')
        journal_versioned_root = self._deserialize_bool(lines[3][16:])
        if len(lines) < 5 or not lines[4].startswith('tree_references: '):
            raise errors.BzrError('missing tree_references: marker')
        journal_tree_references = self._deserialize_bool(lines[4][17:])
        if journal_versioned_root != self._versioned_root:
            raise errors.BzrError(
                "serialized versioned_root flag is wrong: %s" %
                (journal_versioned_root,))
        if journal_tree_references != self._tree_references:
            raise errors.BzrError(
                "serialized tree_references flag is wrong: %s" %
                (journal_tree_references,))
        result = []
        seen_ids = set()
        line_iter = iter(lines)
        for i in range(5):
            line_iter.next()
        for line in line_iter:
            newpath_utf8, file_id, parent_id, last_modified, content \
                = line.split('\x00', 4)
            parent_id = parent_id or None
            if file_id in seen_ids:
                raise errors.BzrError(
                    "duplicate file id in journal entry %r" % lines)
            seen_ids.add(file_id)
            if newpath_utf8 == '/' and not journal_versioned_root and (
                last_modified != 'null:' or file_id != 'TREE_ROOT'):
                    raise errors.BzrError("Versioned root found: %r" % line)
            elif last_modified[-1] == ':':
                    raise errors.BzrError('special revisionid found: %r' % line)
            if not journal_tree_references and content.startswith('tree\x00'):
                raise errors.BzrError("Tree reference found: %r" % line)
            content_tuple = tuple(content.split('\x00'))
            entry = _parse_entry(
                newpath_utf8, file_id, parent_id, last_modified, content_tuple)
            oldpath = None # XXX: apply_delta ignores this value.
            delta_item = (oldpath, newpath_utf8, file_id, entry)
            result.append(delta_item)
        return journal_parent_id, journal_version_id, result


def _parse_entry(utf8_path, file_id, parent_id, last_modified, content):
    entry_factory = {
        'dir': _dir_to_entry,
        'file': _file_to_entry,
        'link': _link_to_entry,
        'tree': _tree_to_entry,
    }
    kind = content[0]
    path = utf8_path[1:].decode('utf8')
    name = basename(path)
    return entry_factory[content[0]](
            content, name, parent_id, file_id, last_modified)

