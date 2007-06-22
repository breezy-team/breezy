#    merge_upstream.py -- Merge new upstream versions of packages.
#    Copyright (C) 2007 Reinhard Tartler <siretart@tauware.de>
#                  2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os

from bzrlib.plugins.bzrtools.upstream_import import import_tar

def merge_upstream(tree, source, old_revision):

    current_revision = tree.last_revision()
    revno, rev_id = old_revision.in_branch(tree.branch)
    tree.revert([], tree.branch.repository.revision_tree(rev_id))
    tar_input = open(source, 'rb')
    import_tar(tree, tar_input)
    tree.set_parent_ids([rev_id])
    tree.branch.set_last_revision_info(revno, rev_id)
    tree.commit('import upstream from %s' % os.path.basename(source))
    tree.merge_from_branch(tree.branch, to_revision=current_revision)
    
