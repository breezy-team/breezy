# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for finding and reading the bzr config file[s]."""
# import system imports here
import os
import sys

#import bzrlib specific imports here
import bzrlib.config as config
from bzrlib.selftest import TestCase, TestCaseInTempDir


class TestConfigPath(TestCase):

    def test_config_dir(self):
        oldenv = os.environ.get('HOME', None)
        os.environ['HOME'] = '/home/bogus'
        self.assertEqual(config.config_dir(), '/home/bogus/.bazaar.conf')
