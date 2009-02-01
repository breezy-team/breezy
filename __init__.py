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

from bzrlib import errors
from bzrlib.branch import Branch
from bzrlib.commands import Command, Option


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


class cmd_dpush(Command):
    """Push diffs into a foreign version control system without any 
    Bazaar-specific metadata.

    This will afterwards rebase the local Bazaar branch on the remote
    branch unless the --no-rebase option is used, in which case 
    the two branches will be out of sync. 
    """
    takes_args = ['location?']
    takes_options = ['remember', Option('directory',
            help='Branch to push from, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            ),
            Option('no-rebase', help="Don't rebase after push")]

    def run(self, location=None, remember=False, directory=None, 
            no_rebase=False):
        from bzrlib import urlutils
        from bzrlib.bzrdir import BzrDir
        from bzrlib.errors import BzrCommandError, NoWorkingTree
        from bzrlib.inventory import Inventory
        from bzrlib.revision import NULL_REVISION
        from bzrlib.trace import info
        from bzrlib.workingtree import WorkingTree
        from upgrade import update_workinginv_fileids

        def get_inv(wt, revid):
            if revid == NULL_REVISION:
                return Inventory()
            else:
                return wt.branch.repository.get_inventory(revid)

        if directory is None:
            directory = "."
        try:
            source_wt = WorkingTree.open_containing(directory)[0]
            source_branch = source_wt.branch
        except NoWorkingTree:
            source_branch = Branch.open_containing(directory)[0]
            source_wt = None
        stored_loc = source_branch.get_push_location()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No push location known or specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc

        bzrdir = BzrDir.open(location)
        target_branch = bzrdir.open_branch()
        target_branch.lock_write()
        try:
            if getattr(target_branch, "dpull", None) is None:
                info("target branch is not a foreign branch, using regular push.")
                target_branch.pull(source_branch)
                no_rebase = True
            else:
                revid_map = target_branch.dpull(source_branch)
            # We successfully created the target, remember it
            if source_branch.get_push_location() is None or remember:
                source_branch.set_push_location(target_branch.base)
            if not no_rebase:
                _, old_last_revid = source_branch.last_revision_info()
                new_last_revid = revid_map[old_last_revid]
                if source_wt is not None:
                    source_wt.pull(target_branch, overwrite=True, 
                                   stop_revision=new_last_revid)
                    source_wt.lock_write()
                    try:
                        update_workinginv_fileids(source_wt, 
                            get_inv(source_wt, old_last_revid), 
                            get_inv(source_wt, new_last_revid))
                    finally:
                        source_wt.unlock()
                else:
                    source_branch.pull(target_branch, overwrite=True, 
                                       stop_revision=new_last_revid)
        finally:
            target_branch.unlock()

def test_suite():
    from unittest import TestSuite
    from bzrlib.tests import TestUtil
    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = ['test_versionedfiles', ]
    suite.addTest(loader.loadTestsFromModuleNames(testmod_names))
    return suite


def escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    if message is None:
        return None
    import re
    # FIXME: RBC 20060419 this should be done by the revision
    # serialiser not by commit. Then we can also add an unescaper
    # in the deserializer and start roundtripping revision messages
    # precisely. See repository_implementations/test_repository.py
    
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


