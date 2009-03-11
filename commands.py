# Copyright (C) 2006-2009 Canonical Ltd

# Authors: Robert Collins <robert.collins@canonical.com>
#          Jelmer Vernooij <jelmer@samba.org>
#          John Carr <john.carr@unrouted.co.uk>
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


"""Git-specific subcommands for Bazaar."""

from bzrlib.commands import Command
from bzrlib.option import Option

class cmd_git_serve(Command):
    """Provide access to a Bazaar branch using the git protocol.

    This command is experimental and doesn't do much yet.
    """
    takes_options = [
        Option('directory',
               help='serve contents of directory',
               type=unicode)
    ]

    def run(self, directory=None):
        lazy_check_versions()
        from dulwich.server import TCPGitServer
        from bzrlib.plugins.git.server import BzrBackend
        from bzrlib.trace import warning
        import os

        warning("server support in bzr-git is experimental.")

        if directory is None:
            directory = os.getcwd()

        backend = BzrBackend(directory)

        server = TCPGitServer(backend, 'localhost')
        server.serve_forever()

class cmd_git_import(Command):
    """Import all branches from a git repository.

    """

    takes_args = ["src_location", "dest_location?"]

    def run(self, src_location, dest_location=None):
        import os
        from bzrlib import (
            ui,
            urlutils,
            )
        from bzrlib.bzrdir import (
            BzrDir,
            format_registry,
            )
        from bzrlib.errors import (
            BzrCommandError,
            NoRepositoryPresent,
            NotBranchError,
            )
        from bzrlib.repository import Repository
        from bzrlib.plugins.git.fetch import InterGitNonGitRepository
        from bzrlib.plugins.git.repository import GitRepository

        if dest_location is None:
            dest_location = os.path.basename(src_location.rstrip("/\\"))

        source_repo = Repository.open(src_location)
        if not isinstance(source_repo, GitRepository):
            raise BzrCommandError("%r is not a git repository" % src_location)
        format = format_registry.make_bzrdir("1.9-rich-root")
        try:
            target_bzrdir = BzrDir.open(dest_location)
        except NotBranchError:
            target_bzrdir = BzrDir.create(dest_location, format=format)
        try:
            target_repo = target_bzrdir.open_repository()
        except NoRepositoryPresent:
            target_repo = target_bzrdir.create_repository(shared=True)

        interrepo = InterGitNonGitRepository(source_repo, target_repo)
        mapping = source_repo.get_mapping()
        refs = interrepo.fetch_refs()
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, (name, ref) in enumerate(refs.iteritems()):
                pb.update("creating branches", i, len(refs))
                if name.endswith("^{}"):
                    continue
                head_loc = os.path.join(dest_location, name)
                try:
                    head_bzrdir = BzrDir.open(head_loc)
                except NotBranchError:
                    parent_path = urlutils.dirname(head_loc)
                    if not os.path.isdir(parent_path):
                        os.makedirs(parent_path)
                    head_bzrdir = BzrDir.create(head_loc, format=format)
                try:
                    head_branch = head_bzrdir.open_branch()
                except NotBranchError:
                    head_branch = head_bzrdir.create_branch()
                if ("%s^{}" % name) in refs:
                    revid = mapping.revision_id_foreign_to_bzr(refs["%s^{}" % name])
                else:
                    revid = mapping.revision_id_foreign_to_bzr(ref)
                head_branch.generate_revision_history(revid)
        finally:
            pb.finished()

