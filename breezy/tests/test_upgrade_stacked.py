# Copyright (C) 2008, 2009, 2011 Canonical Ltd
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


"""Tests for upgrades of various stacking situations."""

from .. import check, controldir, errors, tests
from ..upgrade import upgrade
from .scenarios import load_tests_apply_scenarios


def upgrade_scenarios():
    """Generate test scenarios for different format upgrade combinations."""
    scenario_pairs = [  # old format, new format, model_change
        #        ('knit', 'rich-root', True),
        ("knit", "1.6", False),
        #        ('pack-0.92', '1.6', False),
        ("1.6", "1.6.1-rich-root", True),
    ]
    scenarios = []
    for old_name, new_name, model_change in scenario_pairs:
        name = old_name + ", " + new_name
        scenarios.append(
            (
                name,
                {
                    "scenario_old_format": old_name,
                    "scenario_new_format": new_name,
                    "scenario_model_change": model_change,
                },
            )
        )
    return scenarios


load_tests = load_tests_apply_scenarios


class TestStackUpgrade(tests.TestCaseWithTransport):
    """Tests for upgrading stacked repositories between different formats."""

    # TODO: This should possibly be repeated for all stacking repositories,
    # pairwise by rich/non-rich format; should possibly also try other kinds
    # of upgrades like knit->pack. -- mbp 20080804

    scenarios = upgrade_scenarios()

    def test_stack_upgrade(self):
        """Correct checks when stacked-on repository is upgraded.

        We initially stack on a repo with the same rich root support,
        we then upgrade it and should fail, we then upgrade the overlaid
        repository.
        """
        base = self.make_branch_and_tree("base", format=self.scenario_old_format)
        self.build_tree(["base/foo"])
        base.commit("base commit")
        # make another one stacked
        stacked = base.controldir.sprout("stacked", stacked=True)
        # this must really be stacked (or get_stacked_on_url raises an error)
        self.assertTrue(stacked.open_branch().get_stacked_on_url())
        # now we'll upgrade the underlying branch, then upgrade the stacked
        # branch, and this should still work.
        new_format = controldir.format_registry.make_controldir(
            self.scenario_new_format
        )
        upgrade("base", new_format)
        # in some cases you'll get an error if the underlying model has
        # changed; if just the data format has changed this should still work
        if self.scenario_model_change:
            self.assertRaises(errors.IncompatibleRepositories, stacked.open_branch)
        else:
            check.check_dwim("stacked", False, True, True)
        stacked = controldir.ControlDir.open("stacked")
        # but we can upgrade the stacked repository
        upgrade("stacked", new_format)
        # and now it opens ok
        stacked = controldir.ControlDir.open("stacked")
        # And passes check.
        check.check_dwim("stacked", False, True, True)
