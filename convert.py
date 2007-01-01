#!/usr/bin/env python2.4
#
# Copyright (C) 2005-2006 by Jelmer Vernooij
# 
# Early versions based on svn2bzr
# Copyright (C) 2005 by Canonical Ltd
# Written by Gustavo Niemeyer <gustavo@niemeyer.net>
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

from bzrlib.bzrdir import BzrDir
from bzrlib.branch import Branch
from bzrlib.errors import BzrError, NotBranchError, NoSuchFile
import bzrlib.osutils as osutils
from bzrlib.progress import DummyProgress
from bzrlib.repository import Repository
from bzrlib.trace import info, mutter
from bzrlib.transport import get_transport
import bzrlib.urlutils as urlutils
from bzrlib.ui import ui_factory

from format import SvnRemoteAccess, SvnFormat
from repository import SvnRepository
from transport import SvnRaTransport

import svn.core

def transport_makedirs(transport, location_url):
    needed = [(transport, transport.relpath(location_url))]
    while needed:
        try:
            transport, relpath = needed[-1]
            transport.mkdir(relpath)
            needed.pop()
        except NoSuchFile:
            needed.append((transport, urlutils.dirname(relpath)))

def load_dumpfile(dumpfile, outputdir):
    import svn
    from svn.core import SubversionException
    from cStringIO import StringIO
    repos = svn.repos.svn_repos_create(outputdir, '', '', None, None)
    try:
        file = open(dumpfile)
        svn.repos.load_fs2(repos, file, StringIO(), 
                svn.repos.load_uuid_default, '', 0, 0, None)
    except SubversionException, (svn.core.SVN_ERR_STREAM_MALFORMED_DATA, _):            
        raise BzrError("%s is not a dump file" % dumpfile)
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

    try:
        source_repos = SvnRepository.open(url)
        source_repos.set_branching_scheme(scheme)
        to_transport = get_transport(output_url)

        if create_shared_repo:
            try:
                target_repos = Repository.open(output_url)
                assert target_repos.is_shared()
            except NotBranchError:
                if scheme.is_branch(""):
                    BzrDir.create_branch_and_repo(output_url)
                else:
                    BzrDir.create_repository(output_url, shared=True)
                target_repos = Repository.open(output_url)
            target_repos.set_make_working_trees(working_trees)
            if all:
                source_repos.copy_content_into(target_repos)

        pb = ui_factory.nested_progress_bar()
        try:
            branches = source_repos.find_branches(pb=pb)
            existing_branches = filter(lambda (bp, revnum, exists): exists, 
                                   branches)
        finally:
            pb.finished()

        pb = ui_factory.nested_progress_bar()
                       
        try:
            i = 0
            for (branch, revnum, exists) in existing_branches:
                if source_repos.transport.check_path(branch, revnum) == svn.core.svn_node_file:
                    continue
                pb.update("%s:%d" % (branch, revnum), i, len(existing_branches))
                revid = source_repos.generate_revision_id(revnum, branch)

                target_url = urlutils.join(to_transport.base, branch)
                try:
                    target_branch = Branch.open(target_url)
                    if not revid in target_branch.revision_history():
                        source_branch = Branch.open("%s/%s" % (url, branch))
                        target_branch.pull(source_branch)
                except NotBranchError:
                    source_branch = Branch.open("%s/%s" % (url, branch))
                    transport_makedirs(to_transport, target_url)
                    source_branch.bzrdir.sprout(target_url, 
                                                source_branch.last_revision())
                i+=1
        finally:
            pb.finished()
    finally:
        if tmp_repos:
            osutils.rmtree(tmp_repos)
