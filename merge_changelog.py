#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright ? 2008 Canonical Ltd.
# Author: Scott James Remnant <scott@ubuntu.com>.
# Hacked up by: Bryce Harrington <bryce@ubuntu.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os.path
import shutil
import subprocess
import tempfile

from bzrlib import (
    merge,
    )


class ChangeLogFileMerge(merge.ConfigurableFileMerger):

    name_prefix = 'deb_changelog'
    default_files = ['debian/changelog']

    def merge_text(self, params):
        return merge_changelog(params.this_lines, params.other_lines,
            params.base_lines)


def merge_changelog(this_lines, other_lines, base_lines=[]):
    """Merge a changelog file."""
    # Write the BASE, THIS and OTHER versions to files in a temporary
    # directory, and use dpkg-mergechangelogs to merge them.
    tmpdir = tempfile.mkdtemp('deb_changelog_merge')
    try:
        def writelines(filename, lines):
            with open(filename, 'w') as f:
                for line in lines:
                    f.write(line)
        base_filename = os.path.join(tmpdir, 'changelog.base')
        this_filename = os.path.join(tmpdir, 'changelog.this')
        other_filename = os.path.join(tmpdir, 'changelog.other')
        writelines(base_filename, base_lines)
        writelines(this_filename, this_lines)
        writelines(other_filename, other_lines)
        proc = subprocess.Popen(['dpkg-mergechangelogs', base_filename,
            this_filename, other_filename], stdout=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        retcode = proc.returncode
        if retcode == 1:
            return 'conflicted', stdout
        else:
            return 'success', stdout
    finally:
        shutil.rmtree(tmpdir)
