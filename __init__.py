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


import bzrlib.config as config


class EmailSender(object):
    """An email message sender."""

    def __init__(self, branch, revision_id, config):
        self.config = config

    def to(self):
        """What is the address the mail should go to."""
        return self.config.get_user_option('post_commit_to')

    def from_address(self):
        """What address should I send from."""
        return self.config.get_user_option('post_commit_sender')

    def should_send(self):
        return self.to() is not None and self.from_address() is not None


def post_commit(branch, revision_id):
    EmailSender(branch, revision_id, config.BranchConfig(branch)).send()


def test_suite():
    from unittest import TestSuite
    import bzrlib.plugins.email.tests 
    result = TestSuite()
    result.addTest(bzrlib.plugins.email.tests.test_suite())
    return result

