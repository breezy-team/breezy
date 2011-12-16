#!/usr/bin/env python
# vim: expandtab

# Copyright (C) 2011 Jelmer Vernooij <jelmer@apache.org>

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

import os

from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.git.git_remote_helper import open_local_dir


class OpenLocalDirTests(TestCaseWithTransport):

    def test_from_env(self):
        self.make_branch_and_tree('bla', format='git')
        self.overrideEnv('GIT_DIR', os.path.join(self.test_dir, 'bla'))
        open_local_dir()

    def test_from_env_dir(self):
        self.make_branch_and_tree('bla', format='git')
        self.overrideEnv('GIT_DIR', os.path.join(self.test_dir, 'bla', '.git'))
        open_local_dir()

    def test_from_dir(self):
        self.make_branch_and_tree('.', format='git')
        open_local_dir()
