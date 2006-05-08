# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.workingtree import WorkingTree
import bzrlib

import svn.core, svn.client, svn.wc
from libsvn._core import SubversionException

class SvnWorkingTree(WorkingTree):
    def __init__(self,path,branch):
        WorkingTree.__init__(self,path,branch)
        self.path = path

    def revert(self,filenames,old_tree=None,backups=True):
        # FIXME: Respect old_tree and backups
        svn.client.revert(filenames,True,self.client,self.pool)

    def move(self, from_paths, to_name):
        revt = svn.core.svn_opt_revision_t()
        revt.kind = svn.core.svn_opt_revision_unspecified
        for entry in from_paths:
            svn.client.move(entry, revt, to_name, False, self.client, self.pool)

    def rename_one(self, from_rel, to_rel):
        # There is no difference between rename and move in SVN
        self.move([from_rel], to_rel)

    def add(self, files, ids=None):
        for f in files:
            svn.client.add(f, False, self.client, self.pool)
            if ids:
                id = ids.pop()
                if id:
                    svn.client.propset('bzr:id', id, f, False, self.pool)
