# Copyright (C) 2005-2007 by Jelmer Vernooij
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
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
from bzrlib import ui, urlutils
from bzrlib.bzrdir import BzrDir, Converter
from bzrlib.errors import (BzrError, NotBranchError, NoSuchFile, 
                           NoRepositoryPresent, NoSuchRevision) 
from bzrlib.repository import InterRepository
from bzrlib.revision import ensure_null
from bzrlib.transport import get_transport

from bzrlib.plugins.svn import repos
from bzrlib.plugins.svn.core import SubversionException
from bzrlib.plugins.svn.errors import ERR_STREAM_MALFORMED_DATA
from bzrlib.plugins.svn.format import get_rich_root_format


def transport_makedirs(transport, location_url):
    """Create missing directories.
    
    :param transport: Transport to use.
    :param location_url: URL for which parents should be created.
    """
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
    """Load a Subversion dump file.

    :param dumpfile: Path to dump file.
    :param outputdir: Directory in which Subversion repository should be 
        created.
    """
    from cStringIO import StringIO
    r = repos.create(outputdir)
    if dumpfile.endswith(".gz"):
        import gzip
        file = gzip.GzipFile(dumpfile)
    elif dumpfile.endswith(".bz2"):
        import bz2
        file = bz2.BZ2File(dumpfile)
    else:
        file = open(dumpfile)
    try:
        r.load_fs(file, StringIO(), repos.LOAD_UUID_DEFAULT)
    except SubversionException, (_, num):
        if num == ERR_STREAM_MALFORMED_DATA:
            raise NotDumpFile(dumpfile)
        raise
    return r


def convert_repository(source_repos, output_url, scheme=None, layout=None,
                       create_shared_repo=True, working_trees=False, all=False,
                       format=None, filter_branch=None):
    """Convert a Subversion repository and its' branches to a 
    Bazaar repository.

    :param source_repos: Subversion repository
    :param output_url: URL to write Bazaar repository to.
    :param scheme: Branching scheme to use.
    :param layout: Repository layout (object) to use
    :param create_shared_repo: Whether to create a shared Bazaar repository
    :param working_trees: Whether to create working trees
    :param all: Whether old revisions, even those not part of any existing 
        branches, should be imported
    :param format: Format to use
    """
    from mapping3 import SchemeDerivedLayout, set_branching_scheme
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

    if layout is not None:
        source_repos.set_layout(layout)
    elif scheme is not None:
        set_branching_scheme(source_repos, scheme)
        layout = SchemeDerivedLayout(source_repos, scheme)
    else:
        layout = source_repos.get_layout()

    if create_shared_repo:
        try:
            target_repos = get_dir("").open_repository()
            assert (layout.is_branch("") or layout.is_tag("") or target_repos.is_shared())
        except NoRepositoryPresent:
            target_repos = get_dir("").create_repository(shared=True)
        target_repos.set_make_working_trees(working_trees)

    source_repos.lock_read()
    try:
        existing_branches = source_repos.find_branches(layout=layout)
        if filter_branch is not None:
            existing_branches = filter(filter_branch, existing_branches)

        if create_shared_repo:
            inter = InterRepository.get(source_repos, target_repos)

            if all:
                inter.fetch()
            elif (target_repos.is_shared() and 
                  getattr(inter, '_supports_branches', None) and 
                  inter._supports_branches):
                inter.fetch(branches=existing_branches)

        source_graph = source_repos.get_graph()
        pb = ui.ui_factory.nested_progress_bar()
        try:
            i = 0
            for source_branch in existing_branches:
                pb.update("%s:%d" % (source_branch.get_branch_path(), source_branch.get_revnum()), i, len(existing_branches))
                target_dir = get_dir(source_branch.get_branch_path())
                if not create_shared_repo:
                    try:
                        target_dir.open_repository()
                    except NoRepositoryPresent:
                        target_dir.create_repository()
                try:
                    target_branch = target_dir.open_branch()
                except NotBranchError:
                    target_branch = target_dir.create_branch()
                    target_branch.set_parent(source_branch.base)
                if source_branch.last_revision() != target_branch.last_revision():
                    # Check if target_branch contains a subset of 
                    # source_branch. If that is not the case, 
                    # assume that source_branch has been replaced 
                    # and remove target_branch
                    if not source_graph.is_ancestor(
                            ensure_null(target_branch.last_revision()),
                            ensure_null(source_branch.last_revision())):
                        target_branch.set_revision_history([])
                    target_branch.pull(source_branch)
                if working_trees and not target_dir.has_workingtree():
                    target_dir.create_workingtree()
                i += 1
        finally:
            pb.finished()
    finally:
        source_repos.unlock()
        

class SvnConverter(Converter):
    """Converts from a Subversion directory to a bzr dir."""
    def __init__(self, target_format):
        """Create a SvnConverter.
        :param target_format: The format the resulting repository should be.
        """
        self.target_format = target_format

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        convert_repository(to_convert.open_repository(), to_convert.base, 
                           format=self.target_format, all=True, pb=pb)
