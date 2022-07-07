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

from ...controldir import ControlDir
from ...commands import Command


class cmd_repo_has_key(Command):
    """Does a repo have a key?

    e.g.::

      bzr repo-has-key texts FILE-ID REVISION-ID
      bzr repo-has-key revisions REVISION-ID

    It either prints "True" or "False", and terminates with exit code 0 or 1
    respectively.
    """

    hidden = True
    takes_args = ['repo', 'key_parts*']

    def run(self, repo, key_parts_list=None):
        vf_name, key = key_parts_list[0], key_parts_list[1:]
        bd = ControlDir.open(repo)
        repo = bd.open_repository()
        with repo.lock_read():
            vf = getattr(repo, vf_name)
            key = tuple(key)
            if key in vf.get_parent_map([key]):
                self.outf.write("True\n")
                return 0
            else:
                self.outf.write("False\n")
                return 1
