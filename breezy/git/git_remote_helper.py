# vim: expandtab

# Copyright (C) 2011-2018 Jelmer Vernooij <jelmer@jelmer.uk>

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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Remote helper for git for accessing bzr repositories."""

CAPABILITIES = ["fetch", "option", "push"]

import os

from ..controldir import ControlDir
from ..errors import NoRepositoryPresent, NotBranchError
from ..plugins.fastimport import exporter as fastexporter
from ..repository import InterRepository
from ..transport import get_transport_from_path
from . import LocalGitProber
from .dir import BareLocalGitControlDirFormat, LocalGitControlDirFormat
from .object_store import get_object_store
from .refs import get_refs_container, ref_to_branch_name
from .repository import GitRepository

try:
    import fastimport  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    CAPABILITIES.append("import")
    CAPABILITIES.append("refspec *:*")


def open_remote_dir(url):
    """Open or create a remote control directory.

    Args:
        url: URL of the remote directory to open.

    Returns:
        ControlDir: The opened or newly created control directory.
    """
    try:
        return ControlDir.open(url)
    except NotBranchError:
        return ControlDir.create(url)


def fetch(outf, wants, shortname, remote_dir, local_dir):
    """Fetch revisions from remote to local repository.

    Args:
        outf: Output file stream to write progress.
        wants: List of (sha1, ref) tuples to fetch.
        shortname: Short name of the remote.
        remote_dir: Remote control directory.
        local_dir: Local control directory.
    """
    remote_repo = remote_dir.find_repository()
    local_repo = local_dir.find_repository()
    inter = InterRepository.get(remote_repo, local_repo)
    revs = []
    for sha1, _ref in wants:
        revs.append((sha1, None))
    if isinstance(remote_repo, GitRepository) and isinstance(local_repo, GitRepository):
        lossy = False
    else:
        lossy = True
    inter.fetch_revs(revs, lossy=lossy)
    outf.write(b"\n")


def push(outf, wants, shortname, remote_dir, local_dir):
    """Push branches from local to remote repository.

    Args:
        outf: Output file stream to write results.
        wants: List of (src_ref, dest_ref) tuples to push.
        shortname: Short name of the remote.
        remote_dir: Remote control directory.
        local_dir: Local control directory.
    """
    for src_ref, dest_ref in wants:
        local_branch = local_dir.open_branch(ref=src_ref)
        dest_branch_name = ref_to_branch_name(dest_ref)
        if dest_branch_name == "master":
            dest_branch_name = None
        try:
            remote_branch = remote_dir.open_branch(name=dest_branch_name)
        except NotBranchError:
            remote_branch = remote_dir.create_branch(name=dest_branch_name)
        local_branch.push(remote_branch)
        outf.write(b"ok %s\n" % dest_ref)
    outf.write(b"\n")


class RemoteHelper:
    """Git remote helper."""

    def __init__(self, local_dir, shortname, remote_dir):
        """Initialize the Git remote helper.

        Args:
            local_dir: Local control directory.
            shortname: Short name of the remote.
            remote_dir: Remote control directory.
        """
        self.local_dir = local_dir
        self.shortname = shortname
        self.remote_dir = remote_dir
        self.batchcmd = None
        self.wants = []

    def cmd_capabilities(self, outf, argv):
        """Handle the 'capabilities' command.

        Args:
            outf: Output file stream.
            argv: Command arguments.
        """
        outf.write(b"\n".join([c.encode() for c in CAPABILITIES]) + b"\n\n")

    def cmd_list(self, outf, argv):
        """List all refs in the remote repository.

        Args:
            outf: Output file stream.
            argv: Command arguments.
        """
        try:
            repo = self.remote_dir.find_repository()
        except NoRepositoryPresent:
            repo = self.remote_dir.create_repository()
        object_store = get_object_store(repo)
        with object_store.lock_read():
            refs = get_refs_container(self.remote_dir, object_store)
            for ref, git_sha1 in refs.as_dict().items():
                ref = ref.replace(b"~", b"_")
                outf.write(b"%s %s\n" % (git_sha1, ref))
            outf.write(b"\n")

    def cmd_option(self, outf, argv):
        """Handle the 'option' command.

        Args:
            outf: Output file stream.
            argv: Command arguments.
        """
        outf.write(b"unsupported\n")

    def cmd_fetch(self, outf, argv):
        """Handle the 'fetch' command (batch mode).

        Args:
            outf: Output file stream.
            argv: Command arguments.

        Raises:
            Exception: If called inside another batch command.
        """
        if self.batchcmd not in (None, "fetch"):
            raise Exception("fetch command inside other batch command")
        self.wants.append(tuple(argv[1:]))
        self.batchcmd = "fetch"

    def cmd_push(self, outf, argv):
        """Handle the 'push' command (batch mode).

        Args:
            outf: Output file stream.
            argv: Command arguments.

        Raises:
            Exception: If called inside another batch command.
        """
        if self.batchcmd not in (None, "push"):
            raise Exception("push command inside other batch command")
        self.wants.append(tuple(argv[1].split(":", 1)))
        self.batchcmd = "push"

    def cmd_import(self, outf, argv):
        """Handle the 'import' command to export branch data.

        Args:
            outf: Output file stream.
            argv: Command arguments.

        Raises:
            Exception: If fastimport module is not available.
        """
        if "fastimport" in CAPABILITIES:
            raise Exception("install fastimport for 'import' command support")
        ref = argv[1].encode("utf-8")
        dest_branch_name = ref_to_branch_name(ref)
        if dest_branch_name == "master":
            dest_branch_name = None
        remote_branch = self.remote_dir.open_branch(name=dest_branch_name)
        exporter = fastexporter.BzrFastExporter(
            remote_branch,
            outf=outf,
            ref=ref,
            checkpoint=None,
            import_marks_file=None,
            export_marks_file=None,
            revision=None,
            verbose=None,
            plain_format=True,
            rewrite_tags=False,
        )
        exporter.run()

    commands = {
        "capabilities": cmd_capabilities,
        "list": cmd_list,
        "option": cmd_option,
        "fetch": cmd_fetch,
        "push": cmd_push,
        "import": cmd_import,
    }

    def process(self, inf, outf):
        """Process commands from input stream.

        Args:
            inf: Input file stream.
            outf: Output file stream.
        """
        while True:
            line = inf.readline()
            if not line:
                break
            self.process_line(line, outf)

    def process_line(self, l, outf):
        """Process a single command line.

        Args:
            l: Command line to process.
            outf: Output file stream.

        Raises:
            Exception: If command is unknown.
            AssertionError: If batch command is invalid.
        """
        argv = l.strip().split()
        if argv == []:
            if self.batchcmd == "fetch":
                fetch(outf, self.wants, self.shortname, self.remote_dir, self.local_dir)
            elif self.batchcmd == "push":
                push(outf, self.wants, self.shortname, self.remote_dir, self.local_dir)
            elif self.batchcmd is None:
                return
            else:
                raise AssertionError(f"invalid batch {self.batchcmd!r}")
            self.batchcmd = None
        else:
            try:
                self.commands[argv[0].decode()](self, outf, argv)
            except KeyError as err:
                raise Exception(f"Unknown remote command {argv!r}") from err
        outf.flush()


def open_local_dir():
    """Open the local Git directory.

    Determines the local Git directory from GIT_DIR environment variable
    or by probing the current directory.

    Returns:
        ControlDir: The opened local Git control directory.
    """
    try:
        git_path = os.environ["GIT_DIR"]
    except KeyError:
        git_transport = get_transport_from_path(".")
        git_format = LocalGitProber().probe_transport(git_transport)
    else:
        if git_path.endswith("/.git"):
            git_format = LocalGitControlDirFormat()
            git_path = git_path[:-4]
        else:
            git_format = BareLocalGitControlDirFormat()
        git_transport = get_transport_from_path(git_path)

    return git_format.open(git_transport)
