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
#
import os
import tempfile

from bzrlib.plugin import load_plugins
load_plugins()

from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.branch import Branch
from bzrlib.errors import (BzrError, NotBranchError, 
                           NoSuchFile, NoRepositoryPresent)
import bzrlib.osutils as osutils
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
import bzrlib.urlutils as urlutils
import bzrlib.ui as ui

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
    _fmt = """%(dumpfile)s is not a dump file."""
    def __init__(self, dumpfile):
        super(NotDumpFile, self).__init__()
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


def convert_repository(url, output_url, scheme, create_shared_repo=True, 
                       working_trees=False, all=False):
    assert not all or create_shared_repo


    if os.path.isfile(url):
        tmp_repos = tempfile.mkdtemp(prefix='bzr-svn-dump-')
        mutter('loading dumpfile %r to %r' % (url, tmp_repos))
        load_dumpfile(url, tmp_repos)
        url = tmp_repos
    else:
        tmp_repos = None

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
            dirs[path] = BzrDirFormat.get_default_format().initialize_on_transport(nt)
        return dirs[path]

    try:
        source_repos = SvnRepository.open(url)
        source_repos.set_branching_scheme(scheme)

        if create_shared_repo:
            try:
                target_repos = get_dir("").open_repository()
                assert scheme.is_branch("") or scheme.is_tag("") or target_repos.is_shared()
            except NoRepositoryPresent:
                target_repos = get_dir("").create_repository(shared=True)
            target_repos.set_make_working_trees(working_trees)
            if all:
                source_repos.copy_content_into(target_repos)

        pb = ui.ui_factory.nested_progress_bar()
        try:
            branches = source_repos.find_branches(pb=pb)
            existing_branches = filter(lambda (bp, revnum, exists): exists, 
                                   branches)
        finally:
            pb.finished()

        pb = ui.ui_factory.nested_progress_bar()
                       
        try:
            i = 0
            for (branch, revnum, _) in existing_branches:
                if source_repos.transport.check_path(branch, revnum) == svn.core.svn_node_file:
                    continue
                pb.update("%s:%d" % (branch, revnum), i, len(existing_branches))
                revid = source_repos.generate_revision_id(revnum, branch)

                target_dir = get_dir(branch)
                if not create_shared_repo:
                    try:
                        target_dir.open_repository()
                    except NoRepositoryPresent:
                        target_dir.create_repository()
                try:
                    target_branch = target_dir.open_branch()
                except NotBranchError:
                    target_branch = target_dir.create_branch()
                if not revid in target_branch.revision_history():
                    source_branch = Branch.open(urlutils.join(url, branch))
                    # Check if target_branch contains a subset of 
                    # source_branch. If that is not the case, 
                    # assume that source_branch has been replaced 
                    # and remove target_branch
                    if not target_branch.last_revision() in \
                            source_branch.revision_history():
                        target_branch.set_revision_history([])

                    target_branch.pull(source_branch)
                if working_trees and not target_dir.has_workingtree():
                    target_dir.create_workingtree()
                i += 1
        finally:
            pb.finished()
    finally:
        if tmp_repos:
            osutils.rmtree(tmp_repos)
