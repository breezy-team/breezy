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


from bzrlib import (
    config,
    merge,
    )


from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import fnmatch
import subprocess
import tempfile
import sys

from bzrlib import (
    cmdline,
    osutils,
    trace,
    )
""")


config.option_registry.register(config.Option(
        'po_merge.command',
        default='msgmerge -N "{other}" "{pot_file}" -C "{this}" -o "{result}"',
        help='''\
Command used to create a conflict-free .po file during merge.

The following parameters are provided by the hook:
``this`` is the ``.po`` file content before the merge in the current branch,
``other`` is the ``.po`` file content in the branch merged from,
``pot_file`` is the path to the ``.pot`` file corresponding to the ``.po``
file being merged.
``result`` is the path where ``msgmerge`` will output its result. The hook will
use the content of this file to produce the resulting ``.po`` file.

The command is invoked at the root of the working tree so all paths are
relative.
'''))


config.option_registry.register(config.Option(
        'po_merge.po_files', default=[],
        from_unicode=config.list_from_store,
        help='List of globs the po_merge hook applies to.'))


config.option_registry.register(config.Option(
        'po_merge.pot_file', default=[],
        from_unicode=config.list_from_store,
        help='List of ``.pot`` filenames related to ``po_merge.po_files``.'))


class PoMerger(merge.PerFileMerger):
    """Merge .po files."""

    def __init__(self, merger):
        super(merge.PerFileMerger, self).__init__(merger)
        # config options are cached locally until config files are (see
        # http://pad.lv/832042)

        # FIXME: We use the branch config as there is no tree config
        # -- vila 2011-11-23
        self.conf = merger.this_branch.get_config_stack()
        # Which files are targeted by the hook 
        self.po_files = self.conf.get('po_merge.po_files')
        # Which .pot file should be used
        self.pot_file = self.conf.get('po_merge.pot_file')
        self.command = self.conf.get('po_merge.command', expand=False)
        # file_matches() will set the following for merge_text()
        self.selected_po_file = None
        self.selected_pot_file = None

    def file_matches(self, params):
        """Return True if merge_matching should be called on this file."""
        if not self.po_files or not self.pot_file or not self.command:
            # Return early if there is no options defined
            return False
        match = False
        po_path = self.get_filepath(params, self.merger.this_tree)
        # Does the merged file match one of the globs
        for idx, glob in enumerate(self.po_files):
            if fnmatch.fnmatch(po_path, glob):
                match = True
                break
        if not match:
            return False
        # Do we have the corresponding .pot file
        try:
            pot_path = self.pot_file[idx]
        except KeyError:
            trace.note('po_merge.po_files and po_merge.pot_file mismatch'
                       ' for index %d' %d)
            return False
        if self.merger.this_tree.has_filename(pot_path):
            self.selected_pot_file = pot_path
            self.selected_po_file = po_path
            # FIXME: I can't find an easy way to know if the .pot file has
            # conflicts *during* the merge itself. So either the actual content
            # on disk is fine and msgmerge will work OR it's not and it will
            # fail. Conversely, either the result is ok for the user and he's
            # happy OR the user needs to resolve the conflicts in the .pot file
            # and use remerge. -- vila 2011-11-24
            return True
        return False

    def _invoke(self, command):
        proc = subprocess.Popen(cmdline.split(command),
                                # FIXME: cwd= ? -- vila 2011-11-24
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE)
        out, err = proc.communicate()
        return proc.returncode, out, err

    def merge_matching(self, params):
        return self.merge_text(params)

    def merge_text(self, params):
        """Calls msgmerge when .po files conflict.

        This requires a valid .pot file to reconcile both sides.
        """
        # Create tmp files with the 'this' and 'other' content
        tmpdir = tempfile.mkdtemp(prefix='po_merge')
        env = {}
        env['this'] = osutils.pathjoin(tmpdir, 'this')
        env['other'] = osutils.pathjoin(tmpdir, 'other')
        env['result'] = osutils.pathjoin(tmpdir, 'result')
        env['pot_file'] = self.selected_pot_file
        try:
            with osutils.open_file(env['this'], 'wb') as f:
                f.writelines(params.this_lines)
            with osutils.open_file(env['other'], 'wb') as f:
                f.writelines(params.other_lines)
            command = self.conf.expand_options(self.command, env)
            retcode, out, err = self._invoke(command)
            with osutils.open_file(env['result']) as f:
                # FIXME: To avoid the list() construct below which means the
                # whole 'result' file is kept in memory, there may be a way to
                # use an iterator that will close the file when it's done, but
                # there is still the issue of removing the tmp dir...
                # -- vila 2011-11-24
                return 'success', list(f.readlines())
        finally:
            osutils.rmtree(tmpdir)
        return 'not applicable', []
