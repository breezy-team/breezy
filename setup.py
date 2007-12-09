#!/usr/bin/env python2.4

from distutils.core import setup

setup(name='bzr-stats',
      description='Statistics plugin for Bazaar',
      keywords='plugin bzr stats',
      version='0.0.1',
      license='GPL',
      author='John Arbash Meinel',
      author_email="john@arbash-meinel.com",
      url="http://launchpad.net/bzr-stats",
      long_description="""
      Simple statistics plugin for Bazaar.
      """,
      package_dir={'bzrlib.plugins.stats':'.'},
      packages=['bzrlib.plugins.stats']
      )
