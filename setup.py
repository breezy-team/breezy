#! /usr/bin/env python

# This is an installation script for bzr.  Run it with
# './setup.py install', or
# './setup.py --help' for more options

from distutils.core import setup
from distutils.command.install_scripts import install_scripts


###############################
# Overridden distutils actions
###############################

class my_install_scripts(install_scripts):
    """ Customized install_scripts distutils action.
    Create bzr.bat for win32.
    """
    def run(self):
        import os
        import sys

        install_scripts.run(self)   # standard action

        if sys.platform == "win32":
            try:
                scripts_dir = self.install_dir
                script_path = os.path.join(scripts_dir, "bzr")
                batch_str = "@%s %s %%*\n" % (sys.executable, script_path)
                batch_path = script_path + ".bat"
                f = file(batch_path, "w")
                f.write(batch_str)
                f.close()
                print "Created:", batch_path
            except Exception, e:
                print "ERROR: Unable to create %s: %s" % (batch_path, e)


########################
## Setup
########################

setup(name='bzr',
      version='0.1',
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
                'bzrlib.util.configobj',
                ],
      scripts=['bzr'],
      cmdclass={'install_scripts': my_install_scripts},
     )
