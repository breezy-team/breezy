#! /usr/bin/env python

# This is an installation script for bzr.  Run it with
# './setup.py install', or
# './setup.py --help' for more options

from distutils.core import setup

setup(name='bzr',
      version='0.0.0',
      author='Martin Pool',
      author_email='mbp@sourcefrog.net',
      url='http://www.bazaar-ng.org/',
      description='Friendly distributed version control system',
      license='GNU GPL v2',
      packages=['bzrlib',
                'bzrlib.plugins',
                'bzrlib.selftest',
                'bzrlib.util',
                'bzrlib.util.elementtree',
                'bzrlib.util.effbot.org',
                'bzrlib.util.urlgrabber'],
      scripts=['bzr'])
