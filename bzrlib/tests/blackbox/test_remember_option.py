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


from bzrlib import branch
from bzrlib.tests import (
    scenarios,
    script,
    )


load_tests = scenarios.load_tests_apply_scenarios

def send_first_use(test):
    test.run_script('''
        $ bzr init grand_parent
        $ cd grand_parent
        $ echo grand_parent > file
        $ bzr add
        $ bzr commit -m 'initial commit'
        $ cd ..
        $ bzr branch grand_parent parent
        $ cd parent
        $ echo parent > file
        $ bzr commit -m 'parent'
        $ cd ..
        $ bzr branch parent %(working_dir)s
        $ cd %(working_dir)s
        $ echo %(working_dir)s > file
        $ bzr commit -m '%(working_dir)s'
        $ cd ..
''' % {'working_dir': test.working_dir}, null_output_matches_anything=True)


def send_next_uses(test):
    test.setup_first_use()
    # Do a first send that remembers the locations
    test.do_command('../parent', '../grand_parent')
    # Now create some new targets
    test.run_script('''
         $ bzr branch grand_parent new_grand_parent
         $ bzr branch parent new_parent
''', null_output_matches_anything=True)



class TestRemember(script.TestCaseWithTransportAndScript):
    """--remember and --no-remember set locations or not."""

    # scenarios arguments:
    # - command: the command to run (expecting additional arguments from the
    #   tests
    # - working_dir: the dir where the command should be run (it should contain
    #   a branch for which the tested locations are/will be set)
    # - first_use: a callable setting the context where the command will run
    #   for the first time
    # - next_uses: a callable setting the context where the command will run
    #   again (it generally will call first_use).

    scenarios = [('send',
                  {'command': ['send', '-o-',], 'working_dir': 'work',
                   'first_use': send_first_use, 'next_uses': send_next_uses},)
        ]

    def do_command(self, *args):
        # We always expect the same result here and care only about the
        # arguments used and their consequences on the remembered locations
        out, err = self.run_bzr(self.command + list(args),
                                working_dir=self.working_dir)

    def setup_first_use(self):
        self.first_use(self)

    def setup_next_uses(self):
        self.next_uses(self)

    def assertLocations(self, expected_submit_branch, expected_public_branch):
        br, _ = branch.Branch.open_containing(self.working_dir)
        self.assertEquals(expected_submit_branch, br.get_submit_branch())
        self.assertEquals(expected_public_branch, br.get_public_branch())

    def test_first_use_no_option(self):
        self.setup_first_use()
        self.do_command('../parent', '../grand_parent')
        self.assertLocations('../parent', '../grand_parent')

    def test_first_use_remember(self):
        self.setup_first_use()
        self.do_command('--remember', '../parent', '../grand_parent')
        self.assertLocations('../parent', '../grand_parent')

    def test_first_use_no_remember(self):
        self.setup_first_use()
        self.do_command('--no-remember', '../parent', '../grand_parent')
        self.assertLocations(None, None)

    def test_next_uses_no_option(self):
        self.setup_next_uses()
        self.do_command('../new_parent', '../new_grand_parent')
        self.assertLocations('../parent', '../grand_parent')

    def test_next_uses_remember(self):
        self.setup_next_uses()
        self.do_command('--remember', '../new_parent', '../new_grand_parent')
        self.assertLocations('../new_parent', '../new_grand_parent')

    def test_next_uses_no_remember(self):
        self.setup_next_uses()
        self.do_command('--no-remember', '../new_parent', '../new_grand_parent')
        self.assertLocations('../parent', '../grand_parent')
