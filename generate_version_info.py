# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""\
Routines for extracting all version information from a bzr branch.
"""

import time
import pprint

from cStringIO import StringIO

import bzrlib.delta
from bzrlib.osutils import local_time_offset, format_date
import bzrlib.revision
from bzrlib.rio import RioReader, RioWriter, Stanza


# This contains a map of format id => formatter
# None is considered the default formatter
version_formats = {}

def create_date_str(timestamp=None, offset=None):
    """Just a wrapper around format_date to provide the right format.
    
    We don't want to use '%a' in the time string, because it is locale
    dependant. We also want to force timezone original, and show_offset

    Without parameters this function yields the current date in the local
    time zone.
    """
    if timestamp is None and offset is None:
        timestamp = time.time()
        offset = local_time_offset()
    return format_date(timestamp, offset, date_fmt='%Y-%m-%d %H:%M:%S',
                       timezone='original', show_offset=True)


class VersionInfoBuilder(object):
    """A class which lets you build up information about a revision.""" 

    def __init__(self, branch, working_tree=None,
                check_for_clean=False,
                include_revision_history=False,
                include_file_revisions=False,
                ):
        """Build up information about the given branch.
        If working_tree is given, it can be checked for changes.

        :param branch: The branch to work on
        :param working_tree: If supplied, preferentially check
            the working tree for changes.
        :param check_for_clean: If False, we will skip the expense
            of looking for changes.
        :param include_revision_history: If True, the output
            will include the full mainline revision history, including
            date and message
        :param include_file_revisions: The output should
            include the explicit last-changed revision for each file.
        """
        self._branch = branch
        self._working_tree = working_tree
        self._check = check_for_clean
        self._include_history = include_revision_history
        self._include_file_revs = include_file_revisions

        self._clean = None
        self._file_revisions = {}
        self._revision_history_info= []

    def _extract_file_revisions(self):
        """Extract the working revisions for all files"""

        # Things seem clean if we never look :)
        self._clean = True

        if self._working_tree is not None:
            basis_tree = self._working_tree.basis_tree()
        else:
            basis_tree = self._branch.basis_tree()

        # Build up the list from the basis inventory
        for info in basis_tree.list_files():
            self._file_revisions[info[0]] = info[-1].revision

        if not self._check or self._working_tree is None:
            return

        # We have both a working tree, and we are checking
        delta = bzrlib.delta.compare_trees(basis_tree, self._working_tree,
                                          want_unchanged=False)

        # Using a 2-pass algorithm for renames. This is because you might have
        # renamed something out of the way, and then created a new file
        # in which case we would rather see the new marker
        # Or you might have removed the target, and then renamed
        # in which case we would rather see the renamed marker
        for (old_path, new_path, file_id,
             kind, text_mod, meta_mod) in delta.renamed:
            self._clean = False
            self._file_revisions[old_path] = u'renamed to %s' % (new_path,)
        for path, file_id, kind in delta.removed:
            self._clean = False
            self._file_revisions[path] = 'removed'
        for path, file_id, kind in delta.added:
            self._clean = False
            self._file_revisions[path] = 'new'
        for (old_path, new_path, file_id,
             kind, text_mod, meta_mod) in delta.renamed:
            self._clean = False
            self._file_revisions[new_path] = u'renamed from %s' % (old_path,)
        for path, file_id, kind, text_mod, meta_mod in delta.modified:
            self._clean = False
            self._file_revisions[path] = 'modified'

        for path in self._working_tree.unknowns():
            self._clean = False
            self._file_revisions[path] = 'unversioned'

    def _extract_revision_history(self):
        """Find the messages for all revisions in history."""

        # Unfortunately, there is no WorkingTree.revision_history
        rev_hist = self._branch.revision_history()
        if self._working_tree is not None:
            last_rev = self._working_tree.last_revision()
            assert last_rev in rev_hist, \
                "Working Tree's last revision not in branch.revision_history"
            rev_hist = rev_hist[:rev_hist.index(last_rev)+1]

        repository =  self._branch.repository
        repository.lock_read()
        try:
            for revision_id in rev_hist:
                rev = repository.get_revision(revision_id)
                self._revision_history_info.append(
                    (rev.revision_id, rev.message,
                     rev.timestamp, rev.timezone))
        finally:
            repository.unlock()

    def _get_revision_id(self):
        """Get the revision id we are working on."""
        if self._working_tree is not None:
            return self._working_tree.last_revision()
        return self._branch.last_revision()

    def generate(self, to_file):
        """Output the version information to the supplied file.

        :param to_file: The file to write the stream to. The output
                will already be encoded, so to_file should not try
                to change encodings.
        :return: None
        """
        raise NotImplementedError(VersionInfoBuilder.generate)
            

class RioVersionInfoBuilder(VersionInfoBuilder):
    """This writes a rio stream out."""

    def generate(self, to_file):
        info = Stanza()
        revision_id = self._get_revision_id()
        if revision_id is not None:
            info.add('revision-id', revision_id)
            rev = self._branch.repository.get_revision(revision_id)
            info.add('date', create_date_str(rev.timestamp, rev.timezone))
            revno = str(self._branch.revision_id_to_revno(revision_id))
        else:
            revno = '0'

        info.add('build-date', create_date_str())
        info.add('revno', revno)

        if self._branch.nick is not None:
            info.add('branch-nick', self._branch.nick)

        if self._check or self._include_file_revs:
            self._extract_file_revisions()

        if self._check:
            if self._clean:
                info.add('clean', 'True')
            else:
                info.add('clean', 'False')

        if self._include_history:
            self._extract_revision_history()
            log = Stanza()
            for (revision_id, message,
                 timestamp, timezone) in self._revision_history_info:
                log.add('id', revision_id)
                log.add('message', message)
                log.add('date', create_date_str(timestamp, timezone))
            sio = StringIO()
            log_writer = RioWriter(to_file=sio)
            log_writer.write_stanza(log)
            info.add('revisions', sio.getvalue())

        if self._include_file_revs:
            files = Stanza()
            for path in sorted(self._file_revisions.keys()):
                files.add('path', path)
                files.add('revision', self._file_revisions[path])
            sio = StringIO()
            file_writer = RioWriter(to_file=sio)
            file_writer.write_stanza(files)
            info.add('file-revisions', sio.getvalue())

        writer = RioWriter(to_file=to_file)
        writer.write_stanza(info)


version_formats['rio'] = RioVersionInfoBuilder
# Default format is rio
version_formats[None] = RioVersionInfoBuilder


# Header and footer for the python format
_py_version_header = '''#!/usr/bin/env python
"""This file is automatically generated by generate_version_info
It uses the current working tree to determine the revision.
So don't edit it. :)
"""

'''


_py_version_footer = '''

if __name__ == '__main__':
    print 'revision: %(revno)d' % version_info
    print 'nick: %(branch_nick)s' % version_info
    print 'revision id: %(revision_id)s' % version_info
'''


class PythonVersionInfoBuilder(VersionInfoBuilder):
    """Create a version file which is a python source module."""

    def generate(self, to_file):
        info = {'build_date':create_date_str()
                  , 'revno':None
                  , 'revision_id':None
                  , 'branch_nick':self._branch.nick
                  , 'clean':None
                  , 'date':None
        }
        revisions = []

        revision_id = self._get_revision_id()
        if revision_id is None:
            info['revno'] = 0
        else:
            info['revno'] = self._branch.revision_id_to_revno(revision_id)
            info['revision_id'] = revision_id
            rev = self._branch.repository.get_revision(revision_id)
            info['date'] = create_date_str(rev.timestamp, rev.timezone)

        if self._check or self._include_file_revs:
            self._extract_file_revisions()

        if self._check:
            if self._clean:
                info['clean'] = True
            else:
                info['clean'] = False

        info_str = pprint.pformat(info)
        to_file.write(_py_version_header)
        to_file.write('version_info = ')
        to_file.write(info_str)
        to_file.write('\n\n')

        if self._include_history:
            self._extract_revision_history()
            revision_str = pprint.pformat(self._revision_history_info)
            to_file.write('revisions = ')
            to_file.write(revision_str)
            to_file.write('\n\n')
        else:
            to_file.write('revisions = {}\n\n')

        if self._include_file_revs:
            file_rev_str = pprint.pformat(self._file_revisions)
            to_file.write('file_revisions = ')
            to_file.write(file_rev_str)
            to_file.write('\n\n')
        else:
            to_file.write('file_revisions = {}\n\n')

        to_file.write(_py_version_footer)


version_formats['python'] = PythonVersionInfoBuilder

