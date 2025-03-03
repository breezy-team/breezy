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

"""Merge logic for po_merge plugin."""

from breezy.lazy_import import lazy_import

from ... import config, merge

lazy_import(
    globals(),
    """
import fnmatch
import subprocess
import tempfile

from breezy import (
    cmdline,
    osutils,
    trace,
    )
""",
)


command_option = config.Option(
    "po_merge.command",
    default='msgmerge -N "{other}" "{pot_file}" -C "{this}" -o "{result}"',
    help="""\
Command used to create a conflict-free .po file during merge.

The following parameters are provided by the hook:
``this`` is the ``.po`` file content before the merge in the current branch,
``other`` is the ``.po`` file content in the branch merged from,
``pot_file`` is the path to the ``.pot`` file corresponding to the ``.po``
file being merged.
``result`` is the path where ``msgmerge`` will output its result. The hook will
use the content of this file to produce the resulting ``.po`` file.

All paths are absolute.
""",
)


po_dirs_option = config.ListOption(
    "po_merge.po_dirs",
    default="po,debian/po",
    help="List of dirs containing .po files that the hook applies to.",
)


po_glob_option = config.Option(
    "po_merge.po_glob",
    default="*.po",
    help="Glob matching all ``.po`` files in one of ``po_merge.po_dirs``.",
)

pot_glob_option = config.Option(
    "po_merge.pot_glob",
    default="*.pot",
    help="Glob matching the ``.pot`` file in one of ``po_merge.po_dirs``.",
)


class PoMerger(merge.PerFileMerger):
    """Merge .po files."""

    def __init__(self, merger):
        super(merge.PerFileMerger, self).__init__(merger)
        # config options are cached locally until config files are (see
        # http://pad.lv/832042)

        # FIXME: We use the branch config as there is no tree config
        # -- vila 2011-11-23
        self.conf = merger.this_branch.get_config_stack()
        # Which dirs are targeted by the hook
        self.po_dirs = self.conf.get("po_merge.po_dirs")
        # Which files are targeted by the hook
        self.po_glob = self.conf.get("po_merge.po_glob")
        # Which .pot file should be used
        self.pot_glob = self.conf.get("po_merge.pot_glob")
        self.command = self.conf.get("po_merge.command", expand=False)
        # file_matches() will set the following for merge_text()
        self.pot_file_abspath = None
        trace.mutter("PoMerger created")

    def file_matches(self, params):
        """Return True if merge_matching should be called on this file."""
        if not self.po_dirs or not self.command:
            # Return early if there is no options defined
            return False
        po_dir = None
        po_path = params.this_path
        for po_dir in self.po_dirs:
            glob = osutils.pathjoin(po_dir, self.po_glob)
            if fnmatch.fnmatch(po_path, glob):
                trace.mutter("po {} matches: {}".format(po_path, glob))
                break
        else:
            trace.mutter(
                "PoMerger did not match for {} and {}".format(
                    self.po_dirs, self.po_glob
                )
            )
            return False
        # Do we have the corresponding .pot file
        for path, _file_class, _kind, entry in self.merger.this_tree.list_files(
            from_dir=po_dir, recursive=False
        ):
            pot_name, _pot_file_id = path, entry
            if fnmatch.fnmatch(pot_name, self.pot_glob):
                relpath = osutils.pathjoin(po_dir, pot_name)
                self.pot_file_abspath = self.merger.this_tree.abspath(relpath)
                # FIXME: I can't find an easy way to know if the .pot file has
                # conflicts *during* the merge itself. So either the actual
                # content on disk is fine and msgmerge will work OR it's not
                # and it will fail. Conversely, either the result is ok for the
                # user and he's happy OR the user needs to resolve the
                # conflicts in the .pot file and use remerge.
                # -- vila 2011-11-24
                trace.mutter(
                    "will msgmerge {} using {}".format(po_path, self.pot_file_abspath)
                )
                return True
        else:
            return False

    def _invoke(self, command):
        trace.mutter("Will msgmerge: {}".format(command))
        # We use only absolute paths so we don't care about the cwd
        proc = subprocess.Popen(
            cmdline.split(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        out, err = proc.communicate()
        return proc.returncode, out, err

    def merge_matching(self, params):
        return self.merge_text(params)

    def merge_text(self, params):
        """Calls msgmerge when .po files conflict.

        This requires a valid .pot file to reconcile both sides.
        """
        # Create tmp files with the 'this' and 'other' content
        tmpdir = tempfile.mkdtemp(prefix="po_merge")
        env = {}
        env["this"] = osutils.pathjoin(tmpdir, "this")
        env["other"] = osutils.pathjoin(tmpdir, "other")
        env["result"] = osutils.pathjoin(tmpdir, "result")
        env["pot_file"] = self.pot_file_abspath
        try:
            with open(env["this"], "wb") as f:
                f.writelines(params.this_lines)
            with open(env["other"], "wb") as f:
                f.writelines(params.other_lines)
            command = self.conf.expand_options(self.command, env)
            retcode, out, err = self._invoke(command)
            with open(env["result"], "rb") as f:
                # FIXME: To avoid the list() construct below which means the
                # whole 'result' file is kept in memory, there may be a way to
                # use an iterator that will close the file when it's done, but
                # there is still the issue of removing the tmp dir...
                # -- vila 2011-11-24
                return "success", list(f.readlines())
        finally:
            osutils.rmtree(tmpdir)
        return "not applicable", []
