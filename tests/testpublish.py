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
               "publishing_root=rsync://example.com/home/archives\n"
               "publishing_product=demo\n")


sample_version_config=(sample_config + 
                       "publishing_version=0\n")


class TestTest(TestCaseInTempDir):

    def test_get_publishing_root(self):
        my_config = self.get_config()
        self.assertEqual("rsync://example.com/home/archives", 
                         my_config.get_user_option("publishing_root"))

    def test_get_publising_product(self):
        my_config = self.get_config()
        self.assertEqual("demo",
                         my_config.get_user_option("publishing_product"))

#    def test_get_publishing_version(self):
#        my_config = self.get_config()
#        self.assertEqual(None,
#                         my_config.get_user_option("publishing_version"))
#
#    def test_get_present_publishing_version(self):
#        my_config = self.get_config(sample_version_config)
#        self.assertEqual('0',
#                         my_config.get_user_option("publishing_version"))

    def get_config(self, text=sample_config):
        branch = FakeBranch()
        my_config = config.BranchConfig(branch)
        config_file = StringIO(text)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        return my_config
