# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
# cmd_submit() based on cmd_commit() from bzrlib.builtins

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

from bzrlib.commands import Command, register_command, Option
from bzrlib.builtins import tree_files
from bzrlib.commit import (NullCommitReporter, ReportCommitToLog)
from bzrlib.errors import (PointlessCommit, ConflictsInTree,
                StrictCommitFailed)

def submit(message=None,
           timestamp=None,
           timezone=None,
           committer=None,
           specific_files=None,
           rev_id=None,
           allow_pointless=True,
           strict=False,
           verbose=False,
           revprops=None,
           working_tree=None,
           reporter=None,
           config=None):
    if revprops is None:
        revprops = {}
    
    print working_tree.branch

class cmd_submit(Command):
    """Submit a revision to a Subversion repository.
    
    This is basically a push to a Subversion repository, 
    without the guarantee that a pull from that same repository 
    is a no-op.
    """

    takes_args = ["selected*"]
    takes_options = ["revision","message","verbose", 
                     Option('strict',
                            help="refuse to commit if there are unknown "
                            "files in the working tree.")
                     ]
    aliases = ["push-svn"]
    
    def run(self, revision=None, message=None, file=None, verbose=True,
            selected_list=None, unchanged=False, strict=False):
        from bzrlib.msgeditor import edit_commit_message, \
                make_commit_message_template

        tree, selected_list = tree_files(selected_list)
        if selected_list == ['']:
            # workaround - commit of root of tree should be exactly the same
            # as just default commit in that tree, and succeed even though
            # selected-file merge commit is not done yet
            selected_list = []

        if message is None and not file:
            template = make_commit_message_template(tree, selected_list)
            message = edit_commit_message(template)
            if message is None:
                raise BzrCommandError("please specify a commit message"
                                      " with either --message or --file")
        elif message and file:
            raise BzrCommandError("please specify either --message or --file")

        if file:
            import codecs
            message = codecs.open(file, 'rt', bzrlib.user_encoding).read()

        if verbose:
            reporter = ReportCommitToLog()
        else:
            reporter = NullCommitReporter()
        
        try:
            submit(message, specific_files=selected_list,
                        allow_pointless=unchanged, strict=strict, 
                        working_tree=tree, reporter=reporter)
        except PointlessCommit:
            # FIXME: This should really happen before the file is read in;
            # perhaps prepare the commit; get the message; then actually commit
            raise BzrCommandError("no changes to commit",
                                  ["use --unchanged to commit anyhow"])
        except ConflictsInTree:
            raise BzrCommandError("Conflicts detected in working tree.  "
                'Use "bzr conflicts" to list, "bzr resolve FILE" to resolve.')
        except StrictCommitFailed:
            raise BzrCommandError("Commit refused because there are unknown "
                                  "files in the working tree.")

register_command(cmd_submit)
