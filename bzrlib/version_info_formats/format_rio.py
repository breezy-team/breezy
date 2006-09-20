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

"""A generator which creates a rio stanza of the current tree info"""

from cStringIO import StringIO

from bzrlib.rio import RioReader, RioWriter, Stanza

from bzrlib.version_info_formats import (
    create_date_str,
    VersionInfoBuilder,
    )


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


