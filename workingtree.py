# Foreign branch support for Subversion
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
#
# Published under the GNU GPL

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
