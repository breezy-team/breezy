# Copyright (C) 2009, 2010 Canonical Ltd
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


from breezy.tests.per_repository import TestCaseWithRepository


class TestDefaultStackingPolicy(TestCaseWithRepository):
    def test_sprout_to_smart_server_stacking_policy_handling(self):
        """Obey policy where possible, ignore otherwise."""
        self.make_branch("stack-on")
        parent_bzrdir = self.make_controldir(".", format="default")
        parent_bzrdir.get_config().set_default_stack_on("stack-on")
        source = self.make_branch("source")
        url = self.make_smart_server("target").abspath("")
        target = source.controldir.sprout(url).open_branch()
        self.assertEqual("../stack-on", target.get_stacked_on_url())
        self.assertEqual(source._format.network_name(), target._format.network_name())
