# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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


"""Git inventory."""


from bzrlib import (
    inventory,
    osutils,
    urlutils,
    )


class GitInventory(inventory.Inventory):

    def __init__(self, tree_id, mapping, store, revision_id):
        super(GitInventory, self).__init__(revision_id)
        self.store = store
        self.mapping = mapping
        self.root.revision = revision_id
        self._build_inventory(tree_id, self.root, "")

    def _build_inventory(self, tree_id, ie, path):
        assert isinstance(path, str)
        tree = self.store[tree_id]
        for mode, name, hexsha in tree.entries():
            basename = name.decode("utf-8")
            if path == "":
                child_path = name
            else:
                child_path = urlutils.join(path, name)
            file_id = self.mapping.generate_file_id(child_path)
            entry_kind = (mode & 0700000) / 0100000
            if entry_kind == 0:
                child_ie = inventory.InventoryDirectory(file_id, basename, ie.file_id)
            elif entry_kind == 1:
                file_kind = (mode & 070000) / 010000
                b = self.store[hexsha]
                if file_kind == 0:
                    child_ie = inventory.InventoryFile(file_id, basename, ie.file_id)
                    child_ie.text_sha1 = osutils.sha_string(b.data)
                elif file_kind == 2:
                    child_ie = inventory.InventoryLink(file_id, basename, ie.file_id)
                    child_ie.symlink_target = b.data
                    child_ie.text_sha1 = osutils.sha_string("")
                else:
                    raise AssertionError(
                        "Unknown file kind, perms=%o." % (mode,))
                child_ie.text_id = b.id
                child_ie.text_size = len(b.data)
            else:
                raise AssertionError(
                    "Unknown blob kind, perms=%r." % (mode,))
            fs_mode = mode & 0777
            child_ie.executable = bool(fs_mode & 0111)
            # TODO: This should be set to the revision id in which 
            # child_ie was last changed instead.
            child_ie.revision = self.root.revision
            self.add(child_ie)
            if entry_kind == 0:
                self._build_inventory(hexsha, child_ie, child_path)
