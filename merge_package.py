# Copyright (C) 2009 Muharem Hrnjadovic
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


import re

from debian_bundle.changelog import Version

from bzrlib.plugins.builddeb.import_dsc import DistributionBranch

from bzrlib import builtins, errors, merge, revision
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.commands import Command
from bzrlib.option import Option, RegistryOption
from bzrlib.switch import switch
from bzrlib.workingtree import WorkingTree

class WrongBranchType(errors.BzrError):
    _fmt = "The merge target is not a packaging branch."

class MergeBranchCommand(Command):

    @staticmethod
    def _read_file(branch, path):
        try:
            tree = branch.basis_tree()
            tree.lock_read()
            content = tree.get_file_text(tree.path2id(path))
            tree.unlock()
        except errors.NoSuchId:
            raise WrongBranchType()

        return content

    @staticmethod
    def _latest_version(branch):
        """Get the version of the most recent source package upload.

        The latest upload version is extracted from the `changelog` passed.
        """
        upload_version = None
        changelog = MergeBranchCommand._read_file(branch, "debian/changelog")

        for line in changelog.splitlines():
            # Look for the top-level changelog stanza, extract the
            # upload version from it and break on success.
            match = re.search('^.+\(([^)]+)\).*$', line)
            if match is not None:
                (upload_version,) = match.groups(1)
                break

        return Version(upload_version)

    @staticmethod
    def upstream_branches_diverged(source_url, target_url):
        """Do the upstream branches of the merge source and target diverge?

        The upstream branches will not have diverged
            * if they are identical
            * or if one is a proper subtree of the other
        """
        try:
            source = Branch.open(source_url)
            source.lock_read()
            target = Branch.open(target_url)
            target.lock_read()

            upstream_versions = []
            for branch in (source, target):
                db = DistributionBranch(branch, branch)
                version = MergeBranchCommand._latest_version(branch)
                upstream_versions.append(
                    db.revid_of_upstream_version_from_branch(
                        version.upstream_version))

            graph = source.repository.get_graph(target.repository)
            heads = graph.heads(upstream_versions)
        finally:
            source.unlock()
            target.unlock()

        print heads
        return (len(heads) > 1)


if __name__ == '__main__':
    import sys
    result = MergeBranchCommand.upstream_branches_diverged(
        sys.argv[1], sys.argv[2])
    print "Upstream branches diverged: %s" % result
    sys.stdout.write("\n")

