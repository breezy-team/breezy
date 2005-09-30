#! /usr/bin/env python

# This is an installation script for bzr.  Run it with
# './setup.py install', or
# './setup.py --help' for more options

from distutils.core import setup

# more sophisticated setup script, based on pychecker setup.py
import sys, os
from distutils.command.build_scripts import build_scripts


###############################
# Overridden distutils actions
###############################

class my_build_scripts(build_scripts):
    """Customized build_scripts distutils action.

    Create bzr.bat for win32.
    """

    def run(self):
        if sys.platform == "win32":
            bat_path = os.path.join(self.build_dir, "bzr.bat")
            self.scripts.append(bat_path)
            self.mkpath(self.build_dir)
            scripts_dir = self.distribution.get_command_obj("install").\
                                                            install_scripts
            self.execute(func=self._create_bat,
                         args=[bat_path, scripts_dir],
                         msg="Create %s" % bat_path)
        build_scripts.run(self) # invoke "standard" action

    def _create_bat(self, bat_path, scripts_dir):
        """ Creates the batch file for bzr on win32.
        """
        try:
            script_path = os.path.join(scripts_dir, "bzr")
            bat_str = "@%s %s %%*\n" % (sys.executable, script_path)
            file(bat_path, "w").write(bat_str)
            print "file written"
        except Exception, e:
            print "ERROR: Unable to create %s: %s" % (bat_path, e)
            raise e


########################
## Setup
########################

setup(name='bzr',
      version='0.0.6',
      author='Martin Pool',
      author_email='mbp@sourcefrog.net',
      url='http://www.bazaar-ng.org/',
      description='Friendly distributed version control system',
      license='GNU GPL v2',
      packages=['bzrlib',
                'bzrlib.plugins',
                'bzrlib.selftest',
                'bzrlib.util',
				'bzrlib.transport',
				'bzrlib.store',
                'bzrlib.util.elementtree',
                'bzrlib.util.effbot.org',
                ],
      scripts=['bzr'])
