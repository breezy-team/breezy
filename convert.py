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
from bzrlib.errors import BzrError
import bzrlib.osutils as osutils
from bzrlib.repository import Repository
from bzrlib.trace import info

from format import SvnRemoteAccess, SvnFormat
from repository import SvnRepository
from transport import SvnRaTransport

def convert_repository(url, output_dir, scheme, create_shared_repo=True, working_trees=False):
    tmp_repos = None

    if os.path.isfile(url):
        tmp_repos = tempfile.mkdtemp(prefix='bzr-svn-dump-')
        import svn
        from svn.core import SubversionException
        from cStringIO import StringIO
        repos = svn.repos.svn_repos_create(tmp_repos, '', '', None, None)
        try:
            svn.repos.load_fs2(repos, open(url), StringIO(), svn.repos.load_uuid_default, '', 0, 0, None)
        except SubversionException, (svn.core.SVN_ERR_STREAM_MALFORMED_DATA, _):            
            raise BzrError("%s is not a dump file" % url)
        
        url = "svn+file://%s" % tmp_repos

    if create_shared_repo:
        target_repos = BzrDir.create_repository(output_dir, shared=True)
        target_repos.set_make_working_trees(working_trees)

    try:
        source_repos = SvnRemoteAccess(SvnRaTransport(url), SvnFormat(), 
                                       scheme).open_repository()

        branches = source_repos._log.find_branches(source_repos._latest_revnum)
        existing_branches = filter(lambda (bp, revnum, exists): exists, 
                                   branches)
        info('Importing branches: \n%s' % "".join(map(lambda (bp,revnum,exists): "%s\n" % bp, existing_branches)))

        for (branch, revnum, exists) in existing_branches:
            source_branch = Branch.open("%s/%s" % (source_repos.base, branch))

            target_dir = os.path.join(output_dir, branch)
            os.makedirs(target_dir)
            source_branch.bzrdir.sprout(target_dir, source_branch.last_revision())
            
            info('Converted %s:%d\n' % (branch, revnum))

    finally:
        if tmp_repos:
            osutils.rmtree(tmp_repos)


