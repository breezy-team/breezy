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

"""A generator which creates a rio stanza of the current tree info."""

from breezy import errors, hooks
from breezy.bzr.rio import Stanza
from breezy.revision import NULL_REVISION
from breezy.version_info_formats import VersionInfoBuilder, create_date_str


class RioVersionInfoBuilder(VersionInfoBuilder):
    """This writes a rio stream out."""

    def generate(self, to_file):
        info = Stanza()
        revision_id = self._get_revision_id()
        if revision_id != NULL_REVISION:
            info.add("revision-id", revision_id)
            rev = self._branch.repository.get_revision(revision_id)
            info.add("date", create_date_str(rev.timestamp, rev.timezone))
            try:
                revno = self._get_revno_str(revision_id)
            except errors.GhostRevisionsHaveNoRevno:
                revno = None
            for hook in RioVersionInfoBuilder.hooks["revision"]:
                hook(rev, info)
        else:
            revno = "0"

        info.add("build-date", create_date_str())
        if revno is not None:
            info.add("revno", revno)

        if self._branch.nick is not None:
            info.add("branch-nick", self._branch.nick)

        if self._check or self._include_file_revs:
            self._extract_file_revisions()

        if self._check:
            if self._clean:
                info.add("clean", "True")
            else:
                info.add("clean", "False")

        if self._include_history:
            log = Stanza()
            for (
                revision_id,
                message,
                timestamp,
                timezone,
            ) in self._iter_revision_history():
                log.add("id", revision_id)
                log.add("message", message)
                log.add("date", create_date_str(timestamp, timezone))
            info.add("revisions", log)

        if self._include_file_revs:
            files = Stanza()
            for path in sorted(self._file_revisions.keys()):
                files.add("path", path)
                files.add("revision", self._file_revisions[path])
            info.add("file-revisions", files)

        to_file.write(info.to_string())


class RioVersionInfoBuilderHooks(hooks.Hooks):
    """Hooks for rio-formatted version-info output."""

    def __init__(self):
        super().__init__(
            "breezy.version_info_formats.format_rio", "RioVersionInfoBuilder.hooks"
        )
        self.add_hook(
            "revision",
            "Invoked when adding information about a revision to the"
            " RIO stanza that is printed. revision is called with a"
            " revision object and a RIO stanza.",
            (1, 15),
        )


RioVersionInfoBuilder.hooks = RioVersionInfoBuilderHooks()  # type: ignore
