#!/usr/bin/env python

from distutils.core import setup

setup(name='bzr-rebase',
      description='Rebase plugin for Bazaar',
      keywords='plugin bzr rebase',
      version='0.1',
      url='http://bazaar-vcs.org/Rebase',
      download_url='http://bazaar-vcs.org/Rebase',
      license='GPL',
      author='Jelmer Vernooij',
      author_email='jelmer@samba.org',
      long_description="""
      Hooks into Bazaar and provides commands for rebasing.
      """,
      package_dir={'bzrlib.plugins.rebase':'.'},
      packages=['bzrlib.plugins.rebase']
      )
