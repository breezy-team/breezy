# Copyright (C) 2008 Aaron Bentley <aaron@aaronbentley.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from bzrlib import transform


class ShelfCreator(object):

    def __init__(self, work_tree):
        self.work_tree = work_tree
        self.work_transform = transform.TreeTransform(work_tree)
        self.base_tree = work_tree.basis_tree()
        self.shelf_transform = transform.TransformPreview(self.base_tree)
        self.renames = {}
        self.iter_changes = work_tree.iter_changes(self.base_tree)

    def __iter__(self):
        for (file_id, paths, changed, versioned, parents, names, kind,
             executable) in self.iter_changes:
            if names[0] != names[1] or parents[0] != parents[1]:
                self.renames[file_id] = (names, parents)
                yield ('rename', file_id) + paths

    def shelve_rename(self, file_id):
        names, parents = self.renames[file_id]
        w_trans_id = self.work_transform.trans_id_file_id(file_id)
        work_parent = self.work_transform.trans_id_file_id(parents[0])
        self.work_transform.adjust_path(names[0], work_parent, w_trans_id)

        s_trans_id = self.shelf_transform.trans_id_file_id(file_id)
        shelf_parent = self.shelf_transform.trans_id_file_id(parents[1])
        self.shelf_transform.adjust_path(names[1], shelf_parent, s_trans_id)

    def finalize(self):
        self.work_transform.finalize()
        self.shelf_transform.finalize()
