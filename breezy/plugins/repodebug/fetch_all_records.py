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

"""Command to fetch all records from one repository to another."""

from ... import errors, urlutils
from ...commands import Command
from ...controldir import ControlDir
from ...option import Option


class cmd_fetch_all_records(Command):
    """Fetch all records from another repository.

    This inserts every key from SOURCE_REPO into the target repository.  Unlike
    regular fetches this doesn't assume any relationship between keys (e.g.
    that text X may be assumed to be present if inventory Y is present), so it
    can be used to repair repositories where invariants about those
    relationships have somehow been violated.
    """

    __doc__ = """Fetch all records from another repository.

    This inserts every key from SOURCE_REPO into the target repository.  Unlike
    regular fetches this doesn't assume any relationship between keys (e.g.
    that text X may be assumed to be present if inventory Y is present), so it
    can be used to repair repositories where invariants about those
    relationships have somehow been violated.
    """

    hidden = True
    takes_args = ["source_repo"]
    takes_options = [
        "directory",
        Option(
            "dry-run", help="Show what would be done, but don't actually do anything."
        ),
    ]

    def run(self, source_repo, directory=".", dry_run=False):
        """Execute the fetch-all-records command.

        Args:
            source_repo: URL or path to the source repository.
            directory: Target directory containing the repository to update.
            dry_run: If True, show what would be done without actually doing it.
        """
        try:
            source = ControlDir.open(source_repo).open_repository()
        except (errors.NotBranchError, urlutils.InvalidURL):
            print(f"Not a branch or invalid URL: {source_repo}", file=self.outf)
            return

        try:
            target = ControlDir.open(directory).open_repository()
        except (errors.NotBranchError, urlutils.InvalidURL):
            print(f"Not a branch or invalid URL: {directory}", file=self.outf)
            return

        self.add_cleanup(source.lock_read().unlock)
        self.add_cleanup(target.lock_write().unlock)

        # We need to find the keys to insert before we start the stream.
        # Otherwise we'll be querying the target repo while we're trying to
        # insert into it.
        needed = []
        for vf_name in ["signatures", "texts", "chk_bytes", "inventories", "revisions"]:
            vf = getattr(source, vf_name)
            target_vf = getattr(target, vf_name)
            source_keys = vf.keys()
            target_keys = target_vf.keys()
            keys = source_keys.difference(target_keys)
            needed.append((vf_name, keys))

        def source_stream():
            for vf_name, keys in needed:
                vf = getattr(source, vf_name)
                yield (vf_name, vf.get_record_stream(keys, "unordered", True))

        resume_tokens, missing_keys = target._get_sink().insert_stream(
            source_stream(), source._format, []
        )

        if not resume_tokens:
            print("Done.", file=self.outf)
        else:
            print("Missing keys!", missing_keys, file=self.outf)
