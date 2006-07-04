#!/usr/bin/env python2.4

from distutils.core import setup

setup(name='bzr-svn',
      description='Support for Subversion branches in Bazaar-NG',
      keywords='plugin bzr svn',
      version='0.1',
      url='http://bazaar-vcs.org/BzrForeignBranches/Subversion',
      download_url='http://bazaar-vcs.org/BzrSvn',
      license='GPL',
      author='Jelmer Vernooij',
      author_email='jelmer@samba.org',
      long_description="""
      This plugin adds support for branching off and 
      committing to Subversion repositories from 
      Bazaar.
      """,
      package_dir={'bzrlib.plugins.svn':'.', 
                   'bzrlib.plugins.svn.tests':'tests'},
      packages=['bzrlib.plugins.svn', 
                'bzrlib.plugins.svn.tests']
      )
