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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""An object that maps bzr branch names <-> git ref names."""


class BranchMapper(object):

    def git_to_bzr(self, ref_names):
        """Get the mapping from git reference names to Bazaar branch names.
        
        :return: a dictionary with git reference names as keys and
          the Bazaar branch names as values.
        """
        bazaar_names = {}
        for ref_name in sorted(ref_names):
            parts = ref_name.split('/')
            if parts[0] == 'refs':
                parts.pop(0)
            category = parts.pop(0)
            if category == 'heads':
                git_name = '/'.join(parts)
                bazaar_name = self._git_to_bzr_name(git_name)
            else:
                if category == 'remotes' and parts[0] == 'origin':
                    parts.pop(0)
                git_name = '/'.join(parts)
                if category.endswith('s'):
                    category = category[:-1]
                name_no_ext = self._git_to_bzr_name(git_name)
                bazaar_name = "%s.%s" % (name_no_ext, category)
            bazaar_names[ref_name] = bazaar_name
        return bazaar_names

    def _git_to_bzr_name(self, git_name):
        if git_name == 'master':
            bazaar_name = 'trunk'
        elif git_name.endswith('trunk'):
            bazaar_name = 'git-%s' % (git_name,)
        else:
            bazaar_name = git_name
        return bazaar_name

    def bzr_to_git(self, branch_names):
        """Get the mapping from Bazaar branch names to git reference names.
        
        :return: a dictionary with Bazaar branch names as keys and
          the git reference names as values.
        """
        raise NotImplementedError(self.bzr_to_git)
