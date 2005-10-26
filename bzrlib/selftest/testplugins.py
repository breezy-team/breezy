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

from bzrlib.selftest import TestCaseInTempDir

class PluginTest(TestCaseInTempDir):
    """Create an external plugin and test loading."""
#    def test_plugin_loading(self):
#        orig_help = self.run_bzr_captured('bzr help commands')[0]
#        os.mkdir('plugin_test')
#        f = open(os.path.join('plugin_test', 'myplug.py'), 'wt')
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

#         os.environ['BZRPLUGINPATH'] = os.path.abspath('plugin_test')
#         help = backtick('bzr help commands')
#         assert help.find('myplug') != -1
#         assert help.find('Just a simple test plugin.') != -1


#         assert backtick('bzr myplug') == 'Hello from my plugin\n'
#         assert backtick('bzr mplg') == 'Hello from my plugin\n'

#         f = open(os.path.join('plugin_test', 'override.py'), 'wb')
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
