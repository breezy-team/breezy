# Copyright (C) 2005-2011 Canonical Ltd
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

"""\
This is an attempt to take the internal delta object, and represent
it as a single-file text-only changeset.
This should have commands for both generating a changeset,
and for applying a changeset.
"""

from io import BytesIO

from ... import errors
from ...commands import Command


class cmd_bundle_info(Command):
    __doc__ = """Output interesting stats about a bundle"""

    hidden = True
    takes_args = ["location"]
    takes_options = ["verbose"]
    encoding_type = "exact"

    def run(self, location, verbose=False):
        """Execute the bundle-info command.

        Args:
            location: Location of the bundle file.
            verbose: Whether to show verbose output.
        """
        from breezy import merge_directive, osutils
        from breezy.bzr.bundle.serializer import read_bundle
        from breezy.i18n import gettext

        from ...mergeable import read_mergeable_from_url

        term_encoding = osutils.get_terminal_encoding()
        bundle_info = read_mergeable_from_url(location)
        if isinstance(bundle_info, merge_directive.BaseMergeDirective):
            bundle_file = BytesIO(bundle_info.get_raw_bundle())
            bundle_info = read_bundle(bundle_file)
        else:
            if verbose:
                raise errors.CommandError(
                    gettext("--verbose requires a merge directive")
                )
        reader_method = getattr(bundle_info, "get_bundle_reader", None)
        if reader_method is None:
            raise errors.CommandError(gettext("Bundle format not supported"))

        by_kind = {}
        file_ids = set()
        for (
            bytes,
            parents,
            repo_kind,
            revision_id,
            file_id,
        ) in reader_method().iter_records():
            by_kind.setdefault(repo_kind, []).append(
                (bytes, parents, repo_kind, revision_id, file_id)
            )
            if file_id is not None:
                file_ids.add(file_id)
        self.outf.write(gettext("Records\n"))
        for kind, records in sorted(by_kind.items()):
            multiparent = sum(
                1 for b, m, k, r, f in records if len(m.get("parents", [])) > 1
            )
            self.outf.write(
                gettext("{0}: {1} ({2} multiparent)\n").format(
                    kind, len(records), multiparent
                )
            )
        self.outf.write(gettext("unique files: %d\n") % len(file_ids))
        self.outf.write("\n")
        nicks = set()
        committers = set()
        for revision in bundle_info.real_revisions:
            if "branch-nick" in revision.properties:
                nicks.add(revision.properties["branch-nick"])
            committers.add(revision.committer)

        self.outf.write(gettext("Revisions\n"))
        self.outf.write(
            (gettext("nicks: %s\n") % ", ".join(sorted(nicks))).encode(
                term_encoding, "replace"
            )
        )
        self.outf.write(
            gettext("committers: \n%s\n")
            % "\n".join(sorted(committers)).encode(term_encoding, "replace")
        )
        if verbose:
            self.outf.write("\n")
            bundle_file.seek(0)
            bundle_file.readline()
            bundle_file.readline()
            import bz2

            content = bz2.decompress(bundle_file.read())
            self.outf.write(gettext("Decoded contents\n"))
            self.outf.write(content)
            self.outf.write("\n")
