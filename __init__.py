# Copyright (C) 2006 Canonical Ltd
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


"""A GIT branch and repository format implementation for bzr."""

try:
    import dulwich as git
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dulwich"))
    import dulwich as git
from bzrlib import bzrdir
from bzrlib.foreign import ForeignVcs, VcsMappingRegistry, foreign_vcs_registry
from bzrlib.plugins.git.dir import LocalGitBzrDirFormat, RemoteGitBzrDirFormat
from bzrlib.transport import register_lazy_transport
from bzrlib.commands import Command, register_command
from bzrlib.option import Option

bzrdir.format_registry.register(
    'git', LocalGitBzrDirFormat,
    help='GIT repository.', 
    native=False, experimental=True,
    )

bzrdir.BzrDirFormat.register_control_format(LocalGitBzrDirFormat)
bzrdir.BzrDirFormat.register_control_format(RemoteGitBzrDirFormat)

register_lazy_transport("git://", 'bzrlib.plugins.git.remote',
                        'GitSmartTransport')


class ForeignGit(ForeignVcs):
    """Foreign Git."""


git_mapping_registry = VcsMappingRegistry()
git_mapping_registry.register_lazy('git-experimental', "bzrlib.plugins.git.mapping",
                                   "BzrGitMappingExperimental")
foreign_vcs_registry.register("git", ForeignGit(git_mapping_registry), 
                                      "Stupid content tracker")


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

register_command(cmd_git_serve)


class cmd_git_import(Command):
    """Import all branches from a git repository.

    """

    takes_args = ["src_location", "dest_location"]

    def run(self, src_location, dest_location):
        from bzrlib.bzrdir import BzrDir, format_registry
        from bzrlib.errors import NoRepositoryPresent, NotBranchError
        from bzrlib.repository import Repository
        source_repo = Repository.open(src_location)
        format = format_registry.make_bzrdir('rich-root-pack')
        try:
            target_bzrdir = BzrDir.open(dest_location)
        except NotBranchError:
            target_bzrdir = BzrDir.create(dest_location, format=format)
        try:
            target_repo = target_bzrdir.open_repository()
        except NoRepositoryPresent:
            target_repo = target_bzrdir.create_repository(shared=True)

        target_repo.fetch(source_repo)
        for name, ref in source_repo._git.heads().iteritems():
            head_loc = os.path.join(dest_location, name)
            try:
                head_bzrdir = BzrDir.open(head_loc)
            except NotBranchError:
                head_bzrdir = BzrDir.create(head_loc, format=format)
            try:
                head_branch = head_bzrdir.open_branch()
            except NotBranchError:
                head_branch = head_bzrdir.create_branch()
            head_branch.generate_revision_history(source_repo.get_mapping().revision_id_foreign_to_bzr(ref))


register_command(cmd_git_import)


def test_suite():
    from bzrlib.plugins.git import tests
    return tests.test_suite()
