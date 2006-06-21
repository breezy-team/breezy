#!/usr/bin/env python2.4

from distutils.core import setup

setup(name='bzr-svn',
      description='Support for Subversion branches in Bazaar-NG',
      keywords='plugin bzr svn',
      version='0.1',
      url='http://bazaar-vcs.org/BzrForeignBranches/Subversion',
      download_url='http://samba.org/~jelmer/bzr/svn',
      license='GPL',
      author='Jelmer Vernooij',
      author_email='jelmer@samba.org',
      long_description="""
      This plugin adds support for branching off Subversion 
      repositories.
      """,
      package_dir={'bzrlib.plugins.svn':'.', 
                   'bzrlib.plugins.svn.tests':'tests'},
      packages=['bzrlib.plugins.svn', 
                'bzrlib.plugins.svn.tests'],
      scripts=['svn2bzr'],
      data_files=[('man/man1', ['svn2bzr.1'])],
      )
