#!/usr/bin/env python
# vim: expandtab

# Copyright (C) 2011 Jelmer Vernooij <jelmer@apache.org>

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


"""Remote helper for git for accessing bzr repositories."""

from __future__ import absolute_import

CAPABILITIES = ["fetch", "option", "push"]

import os

from ...controldir import ControlDir
from ...errors import NotBranchError, NoRepositoryPresent
from ...repository import InterRepository
from ...transport import get_transport_from_path

from . import (
    LocalGitProber,
    )
from .dir import (
    BareLocalGitControlDirFormat,
    LocalGitControlDirFormat,
    )

from .object_store import (
    get_object_store,
    )
from .refs import (
    get_refs_container,
    ref_to_branch_name,
    )
from .repository import (
    GitRepository,
    )

try:
    from ..fastimport import exporter as fastexporter
except ImportError:
    fastexporter = None
else:
    CAPABILITIES.append("import")

def open_remote_dir(url):
    try:
        return ControlDir.open(url)
    except NotBranchError:
        return ControlDir.create(url)


def fetch(outf, wants, shortname, remote_dir, local_dir):
    remote_repo = remote_dir.find_repository()
    local_repo = local_dir.find_repository()
    inter = InterRepository.get(remote_repo, local_repo)
    revs = []
    for (sha1, ref) in wants:
        revs.append((sha1, None))
    if (isinstance(remote_repo, GitRepository) and
        isinstance(local_repo, GitRepository)):
        lossy = False
    else:
        lossy = True
    inter.fetch_objects(revs, lossy=lossy)
    outf.write("\n")


def push(outf, wants, shortname, remote_dir, local_dir):
    for (src_ref, dest_ref) in wants:
        local_branch = local_dir.open_branch(ref=src_ref)
        dest_branch_name = ref_to_branch_name(dest_ref)
        if dest_branch_name == "master":
            dest_branch_name = None
        try:
            remote_branch = remote_dir.open_branch(name=dest_branch_name)
        except NotBranchError:
            remote_branch = remote_dir.create_branch(name=dest_branch_name)
        local_branch.push(remote_branch)
        outf.write("ok %s\n" % dest_ref)
    outf.write("\n")


class RemoteHelper(object):
    """Git remote helper."""

    def __init__(self, local_dir, shortname, remote_dir):
        self.local_dir = local_dir
        self.shortname = shortname
        self.remote_dir = remote_dir
        self.batchcmd = None
        self.wants = []

    def cmd_capabilities(self, outf, argv):
        outf.write("\n".join(CAPABILITIES)+"\n\n")

    def cmd_list(self, outf, argv):
        try:
            repo = self.remote_dir.find_repository()
        except NoRepositoryPresent:
            repo = self.remote_dir.create_repository()
        object_store = get_object_store(repo)
        object_store.lock_read()
        try:
            refs = get_refs_container(self.remote_dir, object_store)
            for ref, git_sha1 in refs.as_dict().iteritems():
                ref = ref.replace("~", "_")
                outf.write("%s %s\n" % (git_sha1, ref))
            outf.write("\n")
        finally:
            object_store.unlock()

    def cmd_option(self, outf, argv):
        outf.write("unsupported\n")

    def cmd_fetch(self, outf, argv):
        if self.batchcmd not in (None, "fetch"):
            raise Exception("fetch command inside other batch command")
        self.wants.append(tuple(argv[1:]))
        self.batchcmd = "fetch"

    def cmd_push(self, outf, argv):
        if self.batchcmd not in (None, "push"):
            raise Exception("push command inside other batch command")
        self.wants.append(tuple(argv[1].split(":", 1)))
        self.batchcmd = "push"

    def cmd_import(self, outf, argv):
        if fastexporter is None:
            raise Exception("install bzr-fastimport for 'import' command support")
        dest_branch_name = ref_to_branch_name(argv[1])
        if dest_branch_name == "master":
            dest_branch_name = None
        remote_branch = self.remote_dir.open_branch(name=dest_branch_name)
        exporter = fastexporter.BzrFastExporter(remote_branch,
            outf=outf, ref=argv[1],
            checkpoint=None, import_marks_file=None,
            export_marks_file=None, revision=None,
            verbose=None, plain_format=True,
            rewrite_tags=False)
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
        while True:
            l = inf.readline()
            if not l:
                break
            self.process_line(l, outf)

    def process_line(self, l, outf):
        argv = l.strip().split()
        if argv == []:
            if self.batchcmd == "fetch":
                fetch(outf, self.wants, self.shortname, self.remote_dir, self.local_dir)
            elif self.batchcmd == "push":
                push(outf, self.wants, self.shortname, self.remote_dir, self.local_dir)
            elif self.batchcmd is None:
                return
            else:
                raise AssertionError("invalid batch %r" % self.batchcmd)
            self.batchcmd = None
        else:
            try:
               self.commands[argv[0]](self, outf, argv)
            except KeyError:
               raise Exception("Unknown remote command %r" % argv)
        outf.flush()


def open_local_dir():
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
