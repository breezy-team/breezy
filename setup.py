#! /usr/bin/env python

# This is an installation script for bzr.  Run it with
# './setup.py install', or
# './setup.py --help' for more options

# Reinvocation stolen from bzr, we need python2.4 by virtue of bzr_man
# including bzrlib.help

import os, sys

try:
    version_info = sys.version_info
except AttributeError:
    version_info = 1, 5 # 1.5 or older

REINVOKE = "__BZR_REINVOKE"
NEED_VERS = (2, 4)
KNOWN_PYTHONS = ('python2.4',)

if version_info < NEED_VERS:
    if not os.environ.has_key(REINVOKE):
        # mutating os.environ doesn't work in old Pythons
        os.putenv(REINVOKE, "1")
        for python in KNOWN_PYTHONS:
            try:
                os.execvp(python, [python] + sys.argv)
            except OSError:
                pass
    print >>sys.stderr, "bzr: error: cannot find a suitable python interpreter"
    print >>sys.stderr, "  (need %d.%d or later)" % NEED_VERS
    sys.exit(1)
if hasattr(os, "unsetenv"):
    os.unsetenv(REINVOKE)


from distutils.core import setup
from distutils.command.install_scripts import install_scripts
from distutils.command.build import build

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


class bzr_build(build):
    """Customized build distutils action.
    Generate bzr.1.
    """
    def run(self):
        build.run(self)

        import generate_docs
        generate_docs.main(argv=["bzr", "man"])

########################
## Setup
########################

setup(name='bzr',
      version='0.7pre',
      author='Martin Pool',
      author_email='mbp@sourcefrog.net',
      url='http://www.bazaar-ng.org/',
      description='Friendly distributed version control system',
      license='GNU GPL v2',
      packages=['bzrlib',
                'bzrlib.doc',
                'bzrlib.doc.api',
                'bzrlib.export',
                'bzrlib.plugins',
                'bzrlib.store',
                'bzrlib.tests',
                'bzrlib.tests.blackbox',
                'bzrlib.transport',
                'bzrlib.transport.http',
                'bzrlib.ui',
                'bzrlib.util',
                'bzrlib.util.elementtree',
                'bzrlib.util.effbot.org',
                'bzrlib.util.configobj',
                ],
      scripts=['bzr'],
      cmdclass={'install_scripts': my_install_scripts, 'build': bzr_build},
      data_files=[('man/man1', ['bzr.1'])],
    #   todo: install the txt files from bzrlib.doc.api.
     )
