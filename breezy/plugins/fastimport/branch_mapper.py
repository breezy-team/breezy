# Copyright (C) 2009 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""An object that maps git ref names to bzr branch names.  Note that it is not
used to map git ref names to bzr tag names."""

import re


class BranchMapper(object):
    _GIT_TRUNK_RE = re.compile(b'(?:git-)*trunk')

    def git_to_bzr(self, ref_name):
        """Map a git reference name to a Bazaar branch name.
        """
        parts = ref_name.split(b'/')
        if parts[0] == b'refs':
            parts.pop(0)
        category = parts.pop(0)
        if category == b'heads':
            git_name = b'/'.join(parts)
            bazaar_name = self._git_to_bzr_name(git_name)
        else:
            if category == b'remotes' and parts[0] == b'origin':
                parts.pop(0)
            git_name = b'/'.join(parts)
            if category.endswith(b's'):
                category = category[:-1]
            name_no_ext = self._git_to_bzr_name(git_name)
            bazaar_name = "%s.%s" % (name_no_ext, category.decode('ascii'))
        return bazaar_name

    def _git_to_bzr_name(self, git_name):
        # Make a simple name more bzr-like, by mapping git 'master' to bzr 'trunk'.
        # To avoid collision, map git 'trunk' to bzr 'git-trunk'.  Likewise
        # 'git-trunk' to 'git-git-trunk' and so on, such that the mapping is
        # one-to-one in both directions.
        if git_name == b'master':
            bazaar_name = 'trunk'
        elif self._GIT_TRUNK_RE.match(git_name):
            bazaar_name = 'git-%s' % (git_name.decode('utf-8'),)
        else:
            bazaar_name = git_name.decode('utf-8')
        return bazaar_name
