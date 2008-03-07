# Copyright (C) 2007 Canonical Ltd
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

"""Upload a working tree, incrementally"""

from bzrlib import (
    commands,
    option,
    transport,
    workingtree,
    )

def upload_full_tree(tree, tdest):
    tdest.ensure_base() # XXX: Handle errors
    tree.lock_read()
    try:
        inv = tree.inventory
        entries = inv.iter_entries()
        entries.next() # skip root
        for dp, ie in entries:
            # .bzrignore has no meaning outside of a working tree
            # so do not export it
            if dp == ".bzrignore":
                continue

            import pdb; pdb.set_trace()
            ie.put_on_disk(tdest.local_abspath('.'), dp, tree)
    finally:
        tree.unlock()


class cmd_upload(commands.Command):
    """Upload a working tree, as a whole or incrementally.

    If no destination is specified use the last one used.
    If no revision is specified upload the changes since the last upload.
    """
    takes_args = ['dest?']
    takes_options = [
        'revision',
        option.Option('full', 'Upload the full working tree.'),
       ]
    def run(self, dest, full=False, revision=None):
        tree = workingtree.WorkingTree.open_containing(u'.')[0]
        b = tree.branch

        if dest is None:
            raise NotImplementedError
        else:
            tdest = transport.get_transport(dest)
        if revision is None:
            rev_id = tree.last_revision()
        else:
            if len(revision) != 1:
                raise errors.BzrCommandError(
                    'bzr upload --revision takes exactly 1 argument')
            rev_id = revision[0].in_history(b).rev_id

        tree_to_upload = b.repository.revision_tree(rev_id)
        if full:
            upload_full_tree(tree_to_upload, tdest)
        else:
            raise NotImplementedError


commands.register_command(cmd_upload)


def test_suite():
    from bzrlib.tests import TestUtil

    suite = TestUtil.TestSuite()
    loader = TestUtil.TestLoader()
    testmod_names = [
        'test_upload',
        ]

    suite.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return suite
