#!/usr/bin/env python2.4

from distutils.core import setup

setup(name='bzr-git',
      description='Support for Git branches in Bazaar',
      keywords='plugin bzr git bazaar',
      version='0.1',
      url='http://bazaar-vcs.org/BzrForeignBranches/Git',
      license='GPL',
      author='Robert Collins',
      author_email='robertc@robertcollins.net',
      long_description="""
      This plugin adds limited support for checking out and viewing 
      Git branches in Bazaar.
      """,
      package_dir={'bzrlib.plugins.git':'.'},
      packages=['bzrlib.plugins.git']
      )
