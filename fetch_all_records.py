# Copyright (C) 2011 Canonical Ltd
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

from bzrlib.bzrdir import BzrDir
from bzrlib.commands import Command, Option
from bzrlib import errors


class cmd_fetch_all_records(Command):
    __doc__ = """Fetch all records from another repository.
    
    This inserts every key from SOURCE_REPO into the target repository.  Unlike
    regular fetches this doesn't assume any relationship between keys (e.g.
    that text X may be assumed to be present if inventory Y is present), so it
    can be used to repair repositories where invariants about those
    relationships have somehow been violated.
    """

    takes_args = ['source_repo']
    takes_options = [
        'directory',
        Option('dry-run',
               help="Show what would be done, but don't actually do anything."),
        ]

    def run(self, source_repo, directory=u'.', dry_run=False):
        try:
            source = BzrDir.open(source_repo).open_repository()
        except (errors.NotBranchError, errors.InvalidURL):
            print >>self.outf, u"Not a branch or invalid URL: %s" % source_repo
            return

        try:
            target = BzrDir.open(directory).open_repository()
        except (errors.NotBranchError, errors.InvalidURL):
            print >>self.outf, u"Not a branch or invalid URL: %s" % directory
            return

        self.add_cleanup(source.lock_read().unlock)
        self.add_cleanup(target.lock_write().unlock)
        
        def source_stream():
            for vf_name in ['signatures', 'texts', 'chk_bytes', 'inventories',
                    'revisions']:
                vf = getattr(source, vf_name)
                keys = set(vf.keys()).difference(getattr(target,vf_name).keys())
                yield (vf_name, vf.get_record_stream(keys, 'unordered', True))
        
        resume_tokens, missing_keys = target._get_sink().insert_stream(
            source_stream(), source._format, [])

        if not resume_tokens:
            print >> self.outf, "Done."
        else:
            print >> self.outf, "Missing keys!", missing_keys



