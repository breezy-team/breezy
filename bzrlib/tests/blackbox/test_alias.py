# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
#

"""Tests of the 'bzr alias' command."""

from bzrlib.tests.blackbox import ExternalBase


class TestAlias(ExternalBase):

    def test_list_alias_with_none(self):
        """Calling alias with no parameters lists existing aliases."""
        out, err = self.run_bzr('alias')
        self.assertEquals('', out)

    def test_list_unknown_alias(self):
        out, err = self.run_bzr('alias commit')
        self.assertEquals('bzr alias: commit: not found\n', out)

    def test_add_alias_outputs_nothing(self):
        out, err = self.run_bzr('alias commit="commit --strict"')
        self.assertEquals('', out)

    def test_add_alias_visible(self):
        """Adding an alias makes it ..."""
        self.run_bzr('alias commit="commit --strict"')
        out, err = self.run_bzr('alias commit')
        self.assertEquals('bzr alias commit="commit --strict"\n', out)

    def test_alias_listing_alphabetical(self):
        self.run_bzr('alias commit="commit --strict"')
        self.run_bzr('alias ll="log --short"')
        self.run_bzr('alias add="add -q"')

        out, err = self.run_bzr('alias')
        self.assertEquals(
            'bzr alias add="add -q"\n'
            'bzr alias commit="commit --strict"\n'
            'bzr alias ll="log --short"\n',
            out)

    def test_remove_unknown_alias(self):
        out, err = self.run_bzr('alias --remove fooix', retcode=3)
        self.assertEquals('bzr: ERROR: The alias "fooix" does not exist.\n',
                          err)

    def test_remove_known_alias(self):
        self.run_bzr('alias commit="commit --strict"')
        out, err = self.run_bzr('alias commit')
        self.assertEquals('bzr alias commit="commit --strict"\n', out)
        # No output when removing an existing alias.
        out, err = self.run_bzr('alias --remove commit')
        self.assertEquals('', out)
        # Now its not.
        out, err = self.run_bzr('alias commit')
        self.assertEquals("bzr alias: commit: not found\n", out)
