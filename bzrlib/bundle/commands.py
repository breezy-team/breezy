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
from cStringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    branch,
    errors,
    merge_directive,
    revision as _mod_revision,
    urlutils,
    transport,
    )
""")

from bzrlib.commands import Command
from bzrlib.option import Option
from bzrlib.trace import note


class cmd_bundle_info(Command):
    """Output interesting stats about a bundle"""

    hidden = True
    takes_args = ['location']
    takes_options = ['verbose']
    encoding_type = 'exact'

    def run(self, location, verbose=False):
        from bzrlib.bundle.serializer import read_bundle
        from bzrlib.bundle import read_mergeable_from_url
        from bzrlib import osutils
        term_encoding = osutils.get_terminal_encoding()
        bundle_info = read_mergeable_from_url(location)
        if isinstance(bundle_info, merge_directive._BaseMergeDirective):
            bundle_file = StringIO(bundle_info.get_raw_bundle())
            bundle_info = read_bundle(bundle_file)
        else:
            if verbose:
                raise errors.BzrCommandError('--verbose requires a merge'
                    ' directive')
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
        self.outf.write('Records\n')
        for kind, records in sorted(by_kind.iteritems()):
            multiparent = sum(1 for b, m, k, r, f in records if
                              len(m.get('parents', [])) > 1)
            self.outf.write('%s: %d (%d multiparent)\n' % \
                (kind, len(records), multiparent))
        self.outf.write('unique files: %d\n' % len(file_ids))
        self.outf.write('\n')
        nicks = set()
        committers = set()
        for revision in bundle_info.real_revisions:
            if 'branch-nick' in revision.properties:
                nicks.add(revision.properties['branch-nick'])
            committers.add(revision.committer)

        self.outf.write('Revisions\n')
        self.outf.write(('nicks: %s\n'
            % ', '.join(sorted(nicks))).encode(term_encoding, 'replace'))
        self.outf.write(('committers: \n%s\n' %
        '\n'.join(sorted(committers)).encode(term_encoding, 'replace')))
        if verbose:
            self.outf.write('\n')
            bundle_file.seek(0)
            line = bundle_file.readline()
            line = bundle_file.readline()
            content = bundle_file.read().decode('bz2')
            self.outf.write("Decoded contents\n")
            self.outf.write(content)
            self.outf.write('\n')
