# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Tests for plugins"""

# XXX: There are no plugin tests at the moment because the plugin module
# affects the global state of the process.  See bzrlib/plugins.py for more
# comments.

import os

import bzrlib.plugin
import bzrlib.plugins
from bzrlib.tests import TestCaseInTempDir
from bzrlib.osutils import pathjoin, abspath

class PluginTest(TestCaseInTempDir):
    """Create an external plugin and test loading."""
#    def test_plugin_loading(self):
#        orig_help = self.run_bzr_captured('bzr help commands')[0]
#        os.mkdir('plugin_test')
#        f = open(pathjoin('plugin_test', 'myplug.py'), 'wt')
#        f.write(PLUGIN_TEXT)
#        f.close()
#        newhelp = self.run_bzr_captured('bzr help commands')[0]
#        assert newhelp.startswith('You have been overridden\n')
#        # We added a line, but the rest should work
#        assert newhelp[25:] == help
#
#        assert backtick('bzr commit -m test') == "I'm sorry dave, you can't do that\n"
#
#        shutil.rmtree('plugin_test')
#

#         os.environ['BZRPLUGINPATH'] = abspath('plugin_test')
#         help = backtick('bzr help commands')
#         assert help.find('myplug') != -1
#         assert help.find('Just a simple test plugin.') != -1


#         assert backtick('bzr myplug') == 'Hello from my plugin\n'
#         assert backtick('bzr mplg') == 'Hello from my plugin\n'

#         f = open(pathjoin('plugin_test', 'override.py'), 'wb')
#         f.write("""import bzrlib, bzrlib.commands
#     class cmd_commit(bzrlib.commands.cmd_commit):
#         '''Commit changes into a new revision.'''
#         def run(self, *args, **kwargs):
#             print "I'm sorry dave, you can't do that"

#     class cmd_help(bzrlib.commands.cmd_help):
#         '''Show help on a command or other topic.'''
#         def run(self, *args, **kwargs):
#             print "You have been overridden"
#             bzrlib.commands.cmd_help.run(self, *args, **kwargs)

#         """

PLUGIN_TEXT = """\
import bzrlib.commands
class cmd_myplug(bzrlib.commands.Command):
    '''Just a simple test plugin.'''
    aliases = ['mplg']
    def run(self):
        print 'Hello from my plugin'
"""

# TODO: Write a test for plugin decoration of commands.

class TestOneNamedPluginOnly(TestCaseInTempDir):

    activeattributes = {}

    def test_plugins_with_the_same_name_are_not_loaded(self):
        # This test tests that having two plugins in different
        # directories does not result in both being loaded.
        # get a file name we can use which is also a valid attribute
        # for accessing in activeattributes. - we cannot give import parameters.
        tempattribute = "0"
        self.failIf(tempattribute in self.activeattributes)
        # set a place for the plugins to record their loading, and at the same
        # time validate that the location the plugins should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestOneNamedPluginOnly.activeattributes \
            [tempattribute] = []
        self.failUnless(tempattribute in self.activeattributes)
        # create two plugin directories
        os.mkdir('first')
        os.mkdir('second')
        # write a plugin that will record when its loaded in the 
        # tempattribute list.
        template = ("from bzrlib.tests.test_plugins import TestOneNamedPluginOnly\n"
                    "TestOneNamedPluginOnly.activeattributes[%r].append('%s')\n")
        print >> file(os.path.join('first', 'plugin.py'), 'w'), template % (tempattribute, 'first')
        print >> file(os.path.join('second', 'plugin.py'), 'w'), template % (tempattribute, 'second')
        try:
            bzrlib.plugin.load_from_dirs(['first', 'second'])
            self.assertEqual(['first'], self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if getattr(bzrlib.plugins, 'plugin', None):
                del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))


class TestAllPlugins(TestCaseInTempDir):

    def test_plugin_appears_in_all_plugins(self):
        # This test tests a new plugin appears in bzrlib.plugin.all_plugins().
        # check the plugin is not loaded already
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))
        # write a plugin that _cannot_ fail to load.
        print >> file('plugin.py', 'w'), ""
        try:
            bzrlib.plugin.load_from_dirs(['.'])
            self.failUnless('plugin' in bzrlib.plugin.all_plugins())
            self.failUnless(getattr(bzrlib.plugins, 'plugin', None))
            self.assertEqual(bzrlib.plugin.all_plugins()['plugin'],
                             bzrlib.plugins.plugin)
        finally:
            # remove the plugin 'plugin'
            if getattr(bzrlib.plugins, 'plugin', None):
                del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))
