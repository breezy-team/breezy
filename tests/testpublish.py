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

from cStringIO import StringIO
from unittest import TestLoader

from bzrlib.branch import Branch
import bzrlib.config as config
from bzrlib.selftest import TestCase, TestCaseInTempDir
from bzrlib.selftest.testconfig import FakeBranch


def test_suite():
    return TestLoader().loadTestsFromName(__name__)


sample_config=("[DEFAULT]\n"
               "publishing_root=rsync://example.com/home/archives\n")


class TestTest(TestCaseInTempDir):

    def test_get_publishing_root(self):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        config_file = StringIO(sample_config)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        self.assertEqual("rsync://example.com/home/archives", 
                         my_config.get_user_option("publishing_root"))
