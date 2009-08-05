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

See doc/developers/inventory.txt for the description of the format.

In this module the interesting classes are:
 - InventoryDeltaSerializer - object to read/write inventory deltas.
"""

__all__ = ['InventoryDeltaSerializer']

from bzrlib import errors
from bzrlib.osutils import basename
from bzrlib import inventory
from bzrlib.revision import NULL_REVISION


def _directory_content(entry):
    """Serialize the content component of entry which is a directory.
    
    :param entry: An InventoryDirectory.
    """
    return "dir"


def _file_content(entry):
    """Serialize the content component of entry which is a file.
    
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
    """Serialize the content component of entry which is a symlink.
    
    :param entry: An InventoryLink.
    """
    target = entry.symlink_target
    if target is None:
        raise errors.BzrError('Missing target for %s' % entry.file_id)
    return "link\x00%s" % target.encode('utf8')


def _reference_content(entry):
    """Serialize the content component of entry which is a tree-reference.
    
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

    # XXX: really, the serializer and deserializer should be two separate
    # classes.

    FORMAT_1 = 'bzr inventory delta v1 (bzr 1.14)'

    def __init__(self):
        """Create an InventoryDeltaSerializer."""
        self._versioned_root = None
        self._tree_references = None
        self._entry_to_content = {
            'directory': _directory_content,
            'file': _file_content,
            'symlink': _link_content,
        }

    def require_flags(self, versioned_root=None, tree_references=None):
        """Set the versioned_root and/or tree_references flags for this
        (de)serializer.

        :param versioned_root: If True, any root entry that is seen is expected
            to be versioned, and root entries can have any fileid.
        :param tree_references: If True support tree-reference entries.
        """
        if versioned_root is not None and self._versioned_root is not None:
            raise AssertionError(
                "require_flags(versioned_root=...) already called.")
        if tree_references is not None and self._tree_references is not None:
            raise AssertionError(
                "require_flags(tree_references=...) already called.")
        self._versioned_root = versioned_root
        self._tree_references = tree_references
        if tree_references:
            self._entry_to_content['tree-reference'] = _reference_content

    def delta_to_lines(self, old_name, new_name, delta_to_new):
        """Return a line sequence for delta_to_new.

        Both the versioned_root and tree_references flags must be set via
        require_flags before calling this.

        :param old_name: A UTF8 revision id for the old inventory.  May be
            NULL_REVISION if there is no older inventory and delta_to_new
            includes the entire inventory contents.
        :param new_name: The version name of the inventory we create with this
            delta.
        :param delta_to_new: An inventory delta such as Inventory.apply_delta
            takes.
        :return: The serialized delta as lines.
        """
        if self._versioned_root is None or self._tree_references is None:
            raise AssertionError(
                "Cannot serialise unless versioned_root/tree_references flags "
                "are both set.")
        if type(old_name) is not str:
            raise TypeError('old_name should be str, got %r' % (old_name,))
        if type(new_name) is not str:
            raise TypeError('new_name should be str, got %r' % (new_name,))
        lines = ['', '', '', '', '']
        to_line = self._delta_item_to_line
        for delta_item in delta_to_new:
            line = to_line(delta_item, new_name)
            if line.__class__ != str:
                raise errors.BzrError(
                    'to_line generated non-str output %r' % lines[-1])
            lines.append(line)
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

    def _delta_item_to_line(self, delta_item, new_version):
        """Convert delta_item to a line."""
        oldpath, newpath, file_id, entry = delta_item
        if newpath is None:
            # delete
            oldpath_utf8 = '/' + oldpath.encode('utf8')
            newpath_utf8 = 'None'
            parent_id = ''
            last_modified = NULL_REVISION
            content = 'deleted\x00\x00'
        else:
            if oldpath is None:
                oldpath_utf8 = 'None'
            else:
                oldpath_utf8 = '/' + oldpath.encode('utf8')
            if newpath == '/':
                raise AssertionError(
                    "Bad inventory delta: '/' is not a valid newpath "
                    "(should be '') in delta item %r" % (delta_item,))
            # TODO: Test real-world utf8 cache hit rate. It may be a win.
            newpath_utf8 = '/' + newpath.encode('utf8')
            # Serialize None as ''
            parent_id = entry.parent_id or ''
            # Serialize unknown revisions as NULL_REVISION
            last_modified = entry.revision
            # special cases for /
            if newpath_utf8 == '/' and not self._versioned_root:
                # This is an entry for the root, this inventory does not
                # support versioned roots.  So this must be an unversioned
                # root, i.e. last_modified == new revision.  Otherwise, this
                # delta is invalid.
                # Note: the non-rich-root repositories *can* have roots with
                # file-ids other than TREE_ROOT, e.g. repo formats that use the
                # xml5 serializer.
                if last_modified != new_version:
                    raise errors.BzrError(
                        'Version present for / in %s (%s != %s)'
                        % (file_id, last_modified, new_version))
            if last_modified is None:
                raise errors.BzrError("no version for fileid %s" % file_id)
            content = self._entry_to_content[entry.kind](entry)
        return ("%s\x00%s\x00%s\x00%s\x00%s\x00%s\n" %
            (oldpath_utf8, newpath_utf8, file_id, parent_id, last_modified,
                content))

    def _deserialize_bool(self, value):
        if value == "true":
            return True
        elif value == "false":
            return False
        else:
            raise errors.BzrError("value %r is not a bool" % (value,))

    def parse_text_bytes(self, bytes):
        """Parse the text bytes of a serialized inventory delta.

        If versioned_root and/or tree_references flags were set via
        require_flags, then the parsed flags must match or a BzrError will be
        raised.

        :param bytes: The bytes to parse. This can be obtained by calling
            delta_to_lines and then doing ''.join(delta_lines).
        :return: (parent_id, new_id, versioned_root, tree_references,
            inventory_delta)
        """
        if bytes[-1:] != '\n':
            last_line = bytes.rsplit('\n', 1)[-1]
            raise errors.BzrError('last line not empty: %r' % (last_line,))
        lines = bytes.split('\n')[:-1] # discard the last empty line
        if not lines or lines[0] != 'format: %s' % InventoryDeltaSerializer.FORMAT_1:
            raise errors.BzrError('unknown format %r' % lines[0:1])
        if len(lines) < 2 or not lines[1].startswith('parent: '):
            raise errors.BzrError('missing parent: marker')
        delta_parent_id = lines[1][8:]
        if len(lines) < 3 or not lines[2].startswith('version: '):
            raise errors.BzrError('missing version: marker')
        delta_version_id = lines[2][9:]
        if len(lines) < 4 or not lines[3].startswith('versioned_root: '):
            raise errors.BzrError('missing versioned_root: marker')
        delta_versioned_root = self._deserialize_bool(lines[3][16:])
        if len(lines) < 5 or not lines[4].startswith('tree_references: '):
            raise errors.BzrError('missing tree_references: marker')
        delta_tree_references = self._deserialize_bool(lines[4][17:])
        if (self._versioned_root is not None and
            delta_versioned_root != self._versioned_root):
            raise errors.BzrError(
                "serialized versioned_root flag is wrong: %s" %
                (delta_versioned_root,))
        if (self._tree_references is not None
            and delta_tree_references != self._tree_references):
            raise errors.BzrError(
                "serialized tree_references flag is wrong: %s" %
                (delta_tree_references,))
        result = []
        seen_ids = set()
        line_iter = iter(lines)
        for i in range(5):
            line_iter.next()
        for line in line_iter:
            (oldpath_utf8, newpath_utf8, file_id, parent_id, last_modified,
                content) = line.split('\x00', 5)
            parent_id = parent_id or None
            if file_id in seen_ids:
                raise errors.BzrError(
                    "duplicate file id in inventory delta %r" % lines)
            seen_ids.add(file_id)
            if (newpath_utf8 == '/' and not delta_versioned_root and
                last_modified != delta_version_id):
                    # Delta claims to be not rich root, yet here's a root entry
                    # with either non-default version, i.e. it's rich...
                    raise errors.BzrError("Versioned root found: %r" % line)
            elif newpath_utf8 != 'None' and last_modified[-1] == ':':
                # Deletes have a last_modified of null:, but otherwise special
                # revision ids should not occur.
                raise errors.BzrError('special revisionid found: %r' % line)
            if delta_tree_references is False and content.startswith('tree\x00'):
                raise errors.BzrError("Tree reference found: %r" % line)
            if oldpath_utf8 == 'None':
                oldpath = None
            elif oldpath_utf8[:1] != '/':
                raise errors.BzrError(
                    "oldpath invalid (does not start with /): %r"
                    % (oldpath_utf8,))
            else:
                oldpath_utf8 = oldpath_utf8[1:]
                oldpath = oldpath_utf8.decode('utf8')
            if newpath_utf8 == 'None':
                newpath = None
            elif newpath_utf8[:1] != '/':
                raise errors.BzrError(
                    "newpath invalid (does not start with /): %r"
                    % (newpath_utf8,))
            else:
                # Trim leading slash
                newpath_utf8 = newpath_utf8[1:]
                newpath = newpath_utf8.decode('utf8')
            content_tuple = tuple(content.split('\x00'))
            if content_tuple[0] == 'deleted':
                entry = None
            else:
                entry = _parse_entry(
                    newpath_utf8, file_id, parent_id, last_modified,
                    content_tuple)
            delta_item = (oldpath, newpath, file_id, entry)
            result.append(delta_item)
        return (delta_parent_id, delta_version_id, delta_versioned_root,
                delta_tree_references, result)


def _parse_entry(utf8_path, file_id, parent_id, last_modified, content):
    entry_factory = {
        'dir': _dir_to_entry,
        'file': _file_to_entry,
        'link': _link_to_entry,
        'tree': _tree_to_entry,
    }
    kind = content[0]
    if utf8_path.startswith('/'):
        raise AssertionError
    path = utf8_path.decode('utf8')
    name = basename(path)
    return entry_factory[content[0]](
            content, name, parent_id, file_id, last_modified)

