# Copyright (C) 2006 Canonical Ltd
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
"""\
This is an attempt to take the internal delta object, and represent
it as a single-file text-only changeset.
This should have commands for both generating a changeset,
and for applying a changeset.
"""

import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    branch,
    errors,
    urlutils,
    transport,
    )
from bzrlib.revision import common_ancestor
""")

from bzrlib.commands import Command
from bzrlib.option import Option
from bzrlib.trace import note


class cmd_bundle_revisions(Command):
    """Generate a revision bundle.

    This bundle contains all of the meta-information of a
    diff, rather than just containing the patch information.

    You can apply it to another tree using 'bzr merge'.

    bzr bundle-revisions
        - Generate a bundle relative to a remembered location

    bzr bundle-revisions BASE
        - Bundle to apply the current tree into BASE

    bzr bundle-revisions --revision A
        - Bundle to apply revision A to remembered location 

    bzr bundle-revisions --revision A..B
        - Bundle to transform A into B
    """
    takes_options = ['revision', 'remember',
                     Option("output", help="write bundle to specified file",
                            type=unicode)]
    takes_args = ['base?']
    aliases = ['bundle']
    encoding_type = 'exact'

    def run(self, base=None, revision=None, output=None, remember=False):
        from bzrlib import user_encoding
        from bzrlib.bundle.serializer import write_bundle

        target_branch = branch.Branch.open_containing(u'.')[0]

        if base is None:
            base_specified = False
        else:
            base_specified = True

        if revision is None:
            target_revision = target_branch.last_revision()
        elif len(revision) < 3:
            target_revision = revision[-1].in_history(target_branch).rev_id
            if len(revision) == 2:
                if base_specified:
                    raise errors.BzrCommandError('Cannot specify base as well'
                                                 ' as two revision arguments.')
                base_revision = revision[0].in_history(target_branch).rev_id
        else:
            raise errors.BzrCommandError('--revision takes 1 or 2 parameters')

        if revision is None or len(revision) < 2:
            submit_branch = target_branch.get_submit_branch()
            if base is None:
                base = submit_branch
            if base is None:
                base = target_branch.get_parent()
            if base is None:
                raise errors.BzrCommandError("No base branch known or"
                                             " specified.")
            elif not base_specified:
                # FIXME:
                # note() doesn't pay attention to terminal_encoding() so
                # we must format with 'ascii' to be safe
                note('Using saved location: %s',
                     urlutils.unescape_for_display(base, 'ascii'))
            base_branch = branch.Branch.open(base)

            # We don't want to lock the same branch across
            # 2 different branches
            if target_branch.base == base_branch.base:
                base_branch = target_branch 
            if submit_branch is None or remember:
                if base_specified:
                    target_branch.set_submit_branch(base_branch.base)
                elif remember:
                    raise errors.BzrCommandError('--remember requires a branch'
                                                 ' to be specified.')
            target_branch.repository.fetch(base_branch.repository, 
                                           base_branch.last_revision())
            base_revision = common_ancestor(base_branch.last_revision(),
                                            target_revision,
                                            target_branch.repository)


        if output is not None:
            fileobj = file(output, 'wb')
        else:
            fileobj = sys.stdout
        target_branch.repository.lock_read()
        try:
            write_bundle(target_branch.repository, target_revision,
                         base_revision, fileobj)
        finally:
            target_branch.repository.unlock()


class cmd_bundle_info(Command):
    """Output interesting stats about a bundle"""

    hidden = True
    takes_args = ['location']
    takes_options = [Option('verbose', help="output decoded contents",
                            short_name='v')]

    def run(self, location, verbose=False):
        from bzrlib.bundle.serializer import read_bundle
        dirname, basename = urlutils.split(location)
        bundle_file = transport.get_transport(dirname).get(basename)
        bundle_info = read_bundle(bundle_file)
        reader_method = getattr(bundle_info, 'get_bundle_reader', None)
        if reader_method is None:
            raise errors.BzrCommandError('Bundle format not supported')

        by_kind = {}
        file_ids = set()
        for bytes, parents, repo_kind, revision_id, file_id\
            in reader_method().iter_records():
            by_kind.setdefault(repo_kind, []).append(
                (bytes, parents, repo_kind, revision_id, file_id))
            if file_id is not None:
                file_ids.add(file_id)
        print >> self.outf, 'Records'
        for kind, records in sorted(by_kind.iteritems()):
            multiparent = sum(1 for b, p, k, r, f in records if len(p) > 1)
            print >> self.outf, '%s: %d (%d multiparent)' % \
                (kind, len(records), multiparent)
        print >> self.outf, 'unique files: %d' % len(file_ids)
        print >> self.outf
        nicks = set()
        committers = set()
        for revision in bundle_info.real_revisions:
            nicks.add(revision.properties['branch-nick'])
            committers.add(revision.committer)

        print >> self.outf, 'Revisions'
        print >> self.outf, 'nicks: %s' % ', '.join(sorted(nicks))
        print >> self.outf, 'committers: \n%s' % '\n'.join(sorted(committers))
        if verbose:
            print >> self.outf
            bundle_file.seek(0)
            bundle_file.readline()
            bundle_file.readline()
            content = bundle_file.read().decode('base-64').decode('bz2')
            print >> self.outf, "Decoded contents"
            self.outf.write(content)
