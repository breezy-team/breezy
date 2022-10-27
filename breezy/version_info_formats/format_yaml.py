# Copyright (C) 2006, 2009, 2010 Canonical Ltd
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

"""A generator which creates a yaml stanza of the current tree info"""

from breezy import (
    errors,
    hooks,
    )
from breezy.revision import (
    NULL_REVISION,
    )
import yaml

from breezy.version_info_formats import (
    create_date_str,
    VersionInfoBuilder,
    )


class YamlVersionInfoBuilder(VersionInfoBuilder):
    """This writes a yaml stream out."""

    def generate(self, to_file):
        info = {}
        revision_id = self._get_revision_id()
        if revision_id != NULL_REVISION:
            info['revision-id'] = revision_id.decode('utf-8')
            rev = self._branch.repository.get_revision(revision_id)
            info['date'] = create_date_str(rev.timestamp, rev.timezone)
            try:
                revno = self._get_revno_str(revision_id)
            except errors.GhostRevisionsHaveNoRevno:
                revno = None
            for hook in YamlVersionInfoBuilder.hooks['revision']:
                hook(rev, info)
        else:
            revno = '0'

        info['build-date'] = create_date_str()
        if revno is not None:
            info['revno'] = revno

        if self._branch.nick is not None:
            info['branch-nick'] = self._branch.nick

        if self._check or self._include_file_revs:
            self._extract_file_revisions()

        if self._check:
            if self._clean:
                info['clean'] = True
            else:
                info['clean'] = False

        if self._include_history:
            log = []
            for (revision_id, message,
                 timestamp, timezone) in self._iter_revision_history():
                log.append({
                    'id': revision_id.decode('utf-8'),
                    'message': message,
                    'date': create_date_str(timestamp, timezone),
                })
            info['revisions'] = log

        if self._include_file_revs:
            files = []
            for path in sorted(self._file_revisions.keys()):
                files.append({
                    'path': path,
                    'revision': (
                        self._file_revisions[path].decode('utf-8')
                        if isinstance(self._file_revisions[path], bytes) else self._file_revisions[path])
                })
            info['file-revisions'] = files

        yaml.dump(info, to_file)


class YamlVersionInfoBuilderHooks(hooks.Hooks):
    """Hooks for yaml-formatted version-info output."""

    def __init__(self):
        super(YamlVersionInfoBuilderHooks, self).__init__(
            "breezy.version_info_formats.format_yaml", "YamlVersionInfoBuilder.hooks")
        self.add_hook('revision',
                      "Invoked when adding information about a revision to the"
                      " YAML stanza that is printed. revision is called with a"
                      " revision object and a YAML stanza.", (3, 3))


YamlVersionInfoBuilder.hooks = YamlVersionInfoBuilderHooks()
