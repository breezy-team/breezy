# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for the propose plugin commands."""

from io import StringIO

from .... import errors, registry
from .... import forge as _mod_forge
from ....forge import Forge, ForgeLoginRequired, MergeProposal
from ....tests import TestCase
from ..cmds import cmd_forges, cmd_my_merge_proposals


class SampleProposal(MergeProposal):
    """Merge proposal with just a URL."""

    def __init__(self, url):
        self.url = url

    def get_target_branch_url(self):
        return self.url + "/target"

    def get_source_branch_url(self):
        return self.url + "/source"


class SampleForge(Forge):
    """Forge with one logged in user and one proposal."""

    forge_name = "sample"
    user = "sampleuser"

    @property
    def base_url(self):
        return f"https://{self.forge_name}.example.com/"

    @property
    def name(self):
        return self.forge_name

    def __repr__(self):
        return self.forge_name

    @classmethod
    def iter_instances(cls):
        return iter([cls()])

    def get_current_user(self):
        return self.user

    def get_user_url(self, user):
        return self.base_url + user

    def iter_my_proposals(self, status="open", author=None):
        return iter([SampleProposal(self.base_url + "proposal/1")])


class OtherForge(SampleForge):
    """A second working forge, so there is one to lose."""

    forge_name = "other"
    user = "otheruser"


class AnonymousForge(SampleForge):
    """Forge with no logged in user."""

    forge_name = "anonymous"

    def get_current_user(self):
        return None


class NoUserUrlForge(SampleForge):
    """Forge that knows the user but has no URL for them."""

    forge_name = "nouserurl"

    def get_user_url(self, user):
        return None


class LoginRequiredForge(SampleForge):
    """Forge that wants the user to log in first."""

    forge_name = "loginrequired"

    def get_current_user(self):
        raise ForgeLoginRequired(self.base_url)

    def iter_my_proposals(self, status="open", author=None):
        raise ForgeLoginRequired(self.base_url)


class BrokenCredentialsForge(SampleForge):
    """Forge whose stored credentials are refused."""

    forge_name = "brokencredentials"

    def get_current_user(self):
        raise errors.UnexpectedHttpStatus(self.base_url, 401)

    def iter_my_proposals(self, status="open", author=None):
        raise errors.UnexpectedHttpStatus(self.base_url, 401)


class BrokenUserUrlForge(SampleForge):
    """Forge that knows the user but fails to look up their URL."""

    forge_name = "brokenuserurl"

    def get_user_url(self, user):
        raise errors.UnexpectedHttpStatus(self.base_url, 500)


class BuggyForge(SampleForge):
    """Forge with a plain bug in it."""

    forge_name = "buggy"

    def get_current_user(self):
        raise ValueError("this is a bug, not a forge error")

    def iter_my_proposals(self, status="open", author=None):
        raise ValueError("this is a bug, not a forge error")


class ForgeWalkTestCase(TestCase):
    """Runs a command over a registry of made up forges.

    The names are registered as given and the registry sorts them, so a forge
    registered under a name sorting before "sample" is always reached first and
    the working one has to survive it.
    """

    def setUp(self):
        super().setUp()
        self.overrideAttr(_mod_forge, "forges", registry.Registry())

    def register(self, *forge_clses):
        for forge_cls in forge_clses:
            _mod_forge.forges.register(forge_cls.forge_name, forge_cls)

    def run_command(self, command, **kwargs):
        command.outf = StringIO()
        command.run(**kwargs)
        return command.outf.getvalue()


class CmdForgesTests(ForgeWalkTestCase):
    def test_lists_every_forge(self):
        self.register(SampleForge, OtherForge)
        self.assertEqual(
            "other (https://other.example.com/) - user: otheruser "
            "(https://other.example.com/otheruser)\n"
            "sample (https://sample.example.com/) - user: sampleuser "
            "(https://sample.example.com/sampleuser)\n",
            self.run_command(cmd_forges()),
        )

    def test_lists_a_forge_with_no_user(self):
        self.register(AnonymousForge)
        self.assertEqual(
            "anonymous (https://anonymous.example.com/) - not logged in\n",
            self.run_command(cmd_forges()),
        )

    def test_lists_a_forge_with_no_user_url(self):
        self.register(NoUserUrlForge)
        self.assertEqual(
            "nouserurl (https://nouserurl.example.com/) - user: sampleuser\n",
            self.run_command(cmd_forges()),
        )

    def test_skips_a_forge_needing_login(self):
        self.register(LoginRequiredForge, SampleForge)
        self.assertContainsRe(
            self.run_command(cmd_forges()), "^sample .* user: sampleuser"
        )
        self.assertContainsRe(self.get_log(), "Skipping loginrequired, login required")

    def test_skips_a_forge_with_broken_credentials(self):
        self.register(BrokenCredentialsForge, SampleForge)
        self.assertContainsRe(
            self.run_command(cmd_forges()), "^sample .* user: sampleuser"
        )
        self.assertContainsRe(self.get_log(), "Skipping brokencredentials")

    def test_skips_a_forge_that_cannot_look_up_the_user_url(self):
        self.register(BrokenUserUrlForge, SampleForge)
        self.assertContainsRe(
            self.run_command(cmd_forges()), "^sample .* user: sampleuser"
        )
        self.assertContainsRe(self.get_log(), "Skipping brokenuserurl")

    def test_does_not_hide_a_bug(self):
        self.register(BuggyForge, SampleForge)
        self.assertRaises(ValueError, self.run_command, cmd_forges())


class CmdMyMergeProposalsTests(ForgeWalkTestCase):
    def test_lists_every_forge(self):
        self.register(SampleForge, OtherForge)
        self.assertEqual(
            "https://other.example.com/proposal/1\n"
            "https://sample.example.com/proposal/1\n",
            self.run_command(cmd_my_merge_proposals()),
        )

    def test_skips_a_forge_needing_login(self):
        self.register(LoginRequiredForge, SampleForge)
        self.assertEqual(
            "https://sample.example.com/proposal/1\n",
            self.run_command(cmd_my_merge_proposals()),
        )
        self.assertContainsRe(self.get_log(), "Skipping loginrequired, login required")

    def test_skips_a_forge_with_broken_credentials(self):
        self.register(BrokenCredentialsForge, SampleForge)
        self.assertEqual(
            "https://sample.example.com/proposal/1\n",
            self.run_command(cmd_my_merge_proposals()),
        )
        self.assertContainsRe(self.get_log(), "Skipping brokencredentials")

    def test_does_not_hide_a_bug(self):
        self.register(BuggyForge, SampleForge)
        self.assertRaises(ValueError, self.run_command, cmd_my_merge_proposals())
