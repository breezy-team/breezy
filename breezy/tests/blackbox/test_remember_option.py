# Copyright (C) 2011, 2016 Canonical Ltd
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

from breezy import branch, urlutils
from breezy.tests import script


class TestRememberMixin:
    """--remember and --no-remember set locations or not."""

    # the command to run (expecting additional arguments from the tests
    command: list[str] = []
    # the dir where the command should be run (it should contain a branch for
    # which the tested locations are/will be set)
    working_dir: str
    # argument list for the first command invocation
    first_use_args: list[str] = []
    # argument list for the next command invocation
    next_uses_args: list[str] = []

    def do_command(self, *args):
        # We always expect the same result here and care only about the
        # arguments used and their consequences on the remembered locations
        _out, _err = self.run_bzr(
            self.command + list(args), working_dir=self.working_dir
        )

    def test_first_use_no_option(self):
        self.do_command(*self.first_use_args)
        self.assertLocations(self.first_use_args)

    def test_first_use_remember(self):
        self.do_command("--remember", *self.first_use_args)
        self.assertLocations(self.first_use_args)

    def test_first_use_no_remember(self):
        self.do_command("--no-remember", *self.first_use_args)
        self.assertLocations([])

    def test_next_uses_no_option(self):
        self.setup_next_uses()
        self.do_command(*self.next_uses_args)
        self.assertLocations(self.first_use_args)

    def test_next_uses_remember(self):
        self.setup_next_uses()
        self.do_command("--remember", *self.next_uses_args)
        self.assertLocations(self.next_uses_args)

    def test_next_uses_no_remember(self):
        self.setup_next_uses()
        self.do_command("--no-remember", *self.next_uses_args)
        self.assertLocations(self.first_use_args)


class TestSendRemember(script.TestCaseWithTransportAndScript, TestRememberMixin):
    working_dir = "work"
    command = [
        "send",
        "-o-",
    ]
    first_use_args = [
        "../parent",
        "../grand_parent",
    ]
    next_uses_args = ["../new_parent", "../new_grand_parent"]

    def setUp(self):
        super().setUp()
        self.run_script(
            """
            $ brz init grand_parent
            $ cd grand_parent
            $ echo grand_parent > file
            $ brz add
            $ brz commit -m 'initial commit'
            $ cd ..
            $ brz branch grand_parent parent
            $ cd parent
            $ echo parent > file
            $ brz commit -m 'parent'
            $ cd ..
            $ brz branch parent {working_dir}
            $ cd {working_dir}
            $ echo {working_dir} > file
            $ brz commit -m '{working_dir}'
            $ cd ..
            """.format(working_dir=self.working_dir),
            null_output_matches_anything=True,
        )

    def setup_next_uses(self):
        # Do a first send that remembers the locations
        self.do_command(*self.first_use_args)
        # Now create some new targets
        self.run_script(
            """
            $ brz branch grand_parent new_grand_parent
            $ brz branch parent new_parent
            """,
            null_output_matches_anything=True,
        )

    def assertLocations(self, expected_locations):
        if not expected_locations:
            expected_submit_branch, expected_public_branch = None, None
        else:
            expected_submit_branch, expected_public_branch = expected_locations
        br, _ = branch.Branch.open_containing(self.working_dir)
        self.assertEqual(expected_submit_branch, br.get_submit_branch())
        self.assertEqual(expected_public_branch, br.get_public_branch())


class TestPushRemember(script.TestCaseWithTransportAndScript, TestRememberMixin):
    working_dir = "work"
    command = [
        "push",
    ]
    first_use_args = [
        "../target",
    ]
    next_uses_args = ["../new_target"]

    def setUp(self):
        super().setUp()
        self.run_script(
            """
            $ brz init {working_dir}
            $ cd {working_dir}
            $ echo some content > file
            $ brz add
            $ brz commit -m 'initial commit'
            $ cd ..
            """.format(working_dir=self.working_dir),
            null_output_matches_anything=True,
        )

    def setup_next_uses(self):
        # Do a first push that remembers the location
        self.do_command(*self.first_use_args)
        # Now create some new content
        self.run_script(
            """
            $ cd {working_dir}
            $ echo new content > file
            $ brz commit -m 'new content'
            $ cd ..
            """.format(working_dir=self.working_dir),
            null_output_matches_anything=True,
        )

    def assertLocations(self, expected_locations):
        br, _ = branch.Branch.open_containing(self.working_dir)
        if not expected_locations:
            self.assertEqual(None, br.get_push_location())
        else:
            expected_push_location = expected_locations[0]
            push_location = urlutils.relative_url(br.base, br.get_push_location())
            self.assertIsSameRealPath(expected_push_location, push_location)


class TestPullRemember(script.TestCaseWithTransportAndScript, TestRememberMixin):
    working_dir = "work"
    command = [
        "pull",
    ]
    first_use_args = [
        "../parent",
    ]
    next_uses_args = ["../new_parent"]

    def setUp(self):
        super().setUp()
        self.run_script(
            """
            $ brz init parent
            $ cd parent
            $ echo parent > file
            $ brz add
            $ brz commit -m 'initial commit'
            $ cd ..
            $ brz init {working_dir}
            """.format(working_dir=self.working_dir),
            null_output_matches_anything=True,
        )

    def setup_next_uses(self):
        # Do a first push that remembers the location
        self.do_command(*self.first_use_args)
        # Now create some new content
        self.run_script(
            """
            $ brz branch parent new_parent
            $ cd new_parent
            $ echo new parent > file
            $ brz commit -m 'new parent'
            $ cd ..
            """,
            null_output_matches_anything=True,
        )

    def assertLocations(self, expected_locations):
        br, _ = branch.Branch.open_containing(self.working_dir)
        if not expected_locations:
            self.assertEqual(None, br.get_parent())
        else:
            expected_pull_location = expected_locations[0]
            pull_location = urlutils.relative_url(br.base, br.get_parent())
            self.assertIsSameRealPath(expected_pull_location, pull_location)
