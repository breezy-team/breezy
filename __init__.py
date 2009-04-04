# Copyright (C) 2008-2009 Jelmer Vernooij <jelmer@samba.org>
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

"""Foreign branch utilities."""

from bzrlib import (
    errors,
    )
from bzrlib.branch import (
    Branch,
    )
from bzrlib.commands import (
    Command,
    Option,
    )


class ForeignBranch(Branch):
    """Branch that exists in a foreign version control system."""

    def __init__(self, mapping):
        self.mapping = mapping
        super(ForeignBranch, self).__init__()

    def dpull(self, source, stop_revision=None):
        """Pull deltas from another branch.

        :note: This does not, like pull, retain the revision ids from 
            the source branch and will, rather than adding bzr-specific 
            metadata, push only those semantics of the revision that can be 
            natively represented in this branch.

        :param source: Source branch
        :param stop_revision: Revision to pull, defaults to last revision.
        :return: Revision id map and file id map
        """
        raise NotImplementedError(self.dpull)


class FakeControlFiles(object):
    """Dummy implementation of ControlFiles.
    
    This is required as some code relies on controlfiles being 
    available."""
    def get_utf8(self, name):
        raise errors.NoSuchFile(name)

    def get(self, name):
        raise errors.NoSuchFile(name)

    def break_lock(self):
        pass


class cmd_foreign_mapping_upgrade(Command):
    """Upgrade revisions mapped from a foreign version control system.
    
    This will change the identity of revisions whose parents 
    were mapped from revisions in the other version control system.

    You are recommended to run "bzr check" in the local repository 
    after running this command.
    """
    aliases = ['svn-upgrade']
    takes_args = ['from_repository?']
    takes_options = ['verbose', 
            Option("idmap-file", help="Write map with old and new revision ids.", type=str)]

    def run(self, from_repository=None, verbose=False, idmap_file=None):
        from upgrade import upgrade_branch, upgrade_workingtree
        from bzrlib.branch import Branch
        from bzrlib.errors import NoWorkingTree, BzrCommandError
        from bzrlib.repository import Repository
        from bzrlib.trace import info
        from bzrlib.workingtree import WorkingTree
        try:
            wt_to = WorkingTree.open(".")
            branch_to = wt_to.branch
        except NoWorkingTree:
            wt_to = None
            branch_to = Branch.open(".")

        stored_loc = branch_to.get_parent()
        if from_repository is None:
            if stored_loc is None:
                raise BzrCommandError("No pull location known or"
                                             " specified.")
            else:
                import bzrlib.urlutils as urlutils
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                from_repository = Branch.open(stored_loc).repository
        else:
            from_repository = Repository.open(from_repository)

        vcs = getattr(from_repository, "vcs", None)
        if vcs is None:
            raise BzrCommandError("Repository at %s is not a foreign repository.a" % from_repository.base)

        new_mapping = from_repository.get_mapping()

        if wt_to is not None:
            renames = upgrade_workingtree(wt_to, from_repository, 
                                          new_mapping=new_mapping,
                                          allow_changes=True, verbose=verbose)
        else:
            renames = upgrade_branch(branch_to, from_repository, 
                                     new_mapping=new_mapping,
                                     allow_changes=True, verbose=verbose)

        if renames == {}:
            info("Nothing to do.")

        if idmap_file is not None:
            f = open(idmap_file, 'w')
            try:
                for oldid, newid in renames.iteritems():
                    f.write("%s\t%s\n" % (oldid, newid))
            finally:
                f.close()

        if wt_to is not None:
            wt_to.set_last_revision(branch_to.last_revision())


def test_suite():
    from unittest import TestSuite
    from bzrlib.tests import TestUtil
    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = ['test_versionedfiles', ]
    suite.addTest(loader.loadTestsFromModuleNames(testmod_names))
    return suite
