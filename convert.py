# Copyright (C) 2005-2007 by Jelmer Vernooij
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
"""Conversion of full repositories."""
import os
import tempfile

from bzrlib.bzrdir import BzrDir, BzrDirFormat, Converter
from bzrlib.branch import Branch
from bzrlib.errors import (BzrError, NotBranchError, NoSuchFile, 
                           NoRepositoryPresent, NoSuchRevision)
import bzrlib.osutils as osutils
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
import bzrlib.urlutils as urlutils
import bzrlib.ui as ui

from format import get_rich_root_format
from repository import SvnRepository

import svn.core, svn.repos

def transport_makedirs(transport, location_url):
    needed = [(transport, transport.relpath(location_url))]
    while needed:
        try:
            transport, relpath = needed[-1]
            transport.mkdir(relpath)
            needed.pop()
        except NoSuchFile:
            if relpath == "":
                raise
            needed.append((transport, urlutils.dirname(relpath)))


class NotDumpFile(BzrError):
    """A file specified was not a dump file."""
    _fmt = """%(dumpfile)s is not a dump file."""
    def __init__(self, dumpfile):
        BzrError.__init__(self)
        self.dumpfile = dumpfile


def load_dumpfile(dumpfile, outputdir):
    from cStringIO import StringIO
    repos = svn.repos.svn_repos_create(outputdir, '', '', None, None)
    try:
        file = open(dumpfile)
        svn.repos.load_fs2(repos, file, StringIO(), 
                svn.repos.load_uuid_default, '', 0, 0, None)
    except svn.core.SubversionException, (svn.core.SVN_ERR_STREAM_MALFORMED_DATA, _):
        raise NotDumpFile(dumpfile)
    return repos


def convert_repository(source_repos, output_url, scheme=None, 
                       create_shared_repo=True, working_trees=False, all=False,
                       format=None, pb=None, filter_branch=None):
    """Convert a Subversion repository and its' branches to a 
    Bazaar repository.

    :param source_repos: Subversion repository
    :param output_url: URL to write Bazaar repository to.
    :param scheme: Branching scheme (object) to use
    :param create_shared_repo: Whether to create a shared Bazaar repository
    :param working_trees: Whether to create working trees
    :param all: Whether old revisions, even those not part of any existing 
        branches, should be imported
    :param format: Format to use
    :param pb: Progress bar to use
    """
    assert not all or create_shared_repo
    if format is None:
        format = get_rich_root_format()
    dirs = {}
    to_transport = get_transport(output_url)
    def get_dir(path):
        if dirs.has_key(path):
            return dirs[path]
        nt = to_transport.clone(path)
        try:
            dirs[path] = BzrDir.open_from_transport(nt)
        except NotBranchError:
            transport_makedirs(to_transport, urlutils.join(to_transport.base, path))
            dirs[path] = format.initialize_on_transport(nt)
        return dirs[path]

    if scheme is not None:
        source_repos.set_branching_scheme(scheme)

    if create_shared_repo:
        try:
            target_repos = get_dir("").open_repository()
            assert (source_repos.get_scheme().is_branch("") or 
                    source_repos.get_scheme().is_tag("") or 
                    target_repos.is_shared())
        except NoRepositoryPresent:
            target_repos = get_dir("").create_repository(shared=True)
        target_repos.set_make_working_trees(working_trees)
        if all:
            source_repos.copy_content_into(target_repos)

    if filter_branch is None:
        filter_branch = lambda (bp, rev, exists): exists

    existing_branches = [(bp, revnum) for (bp, revnum, _) in 
            filter(filter_branch,
                   source_repos.find_branches(source_repos.get_scheme()))]

    pb = ui.ui_factory.nested_progress_bar()
    try:
        i = 0
        for (branch, revnum) in existing_branches:
            if source_repos.transport.check_path(branch, revnum) == svn.core.svn_node_file:
                continue
            pb.update("%s:%d" % (branch, revnum), i, len(existing_branches))
            revid = source_repos.generate_revision_id(revnum, branch, 
                                          str(source_repos.get_scheme()))

            target_dir = get_dir(branch)
            if not create_shared_repo:
                try:
                    target_dir.open_repository()
                except NoRepositoryPresent:
                    target_dir.create_repository()
            source_branch_url = urlutils.join(source_repos.base, branch)
            try:
                target_branch = target_dir.open_branch()
            except NotBranchError:
                target_branch = target_dir.create_branch()
                target_branch.set_parent(source_branch_url)
            if revid != target_branch.last_revision():
                source_branch = Branch.open(source_branch_url)
                # Check if target_branch contains a subset of 
                # source_branch. If that is not the case, 
                # assume that source_branch has been replaced 
                # and remove target_branch
                try:
                    source_branch.revision_id_to_revno(
                            target_branch.last_revision())
                except NoSuchRevision:
                    target_branch.set_revision_history([])
                target_branch.pull(source_branch)
            if working_trees and not target_dir.has_workingtree():
                target_dir.create_workingtree()
            i += 1
    finally:
        pb.finished()
    

class SvnConverter(Converter):
    """Converts from a Subversion directory to a bzr dir."""
    def __init__(self, target_format):
        """Create a CopyConverter.
        :param target_format: The format the resulting repository should be.
        """
        self.target_format = target_format

    def convert(self, to_convert, pb):
        convert_repository(to_convert.open_repository(), to_convert.base, 
                           format=self.target_format, all=True, pb=pb)
