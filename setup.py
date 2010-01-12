#!/usr/bin/env python

from info import *

if __name__ == '__main__':
    from distutils.core import setup
    version = bzr_plugin_version[:3]
    version_string = ".".join([str(x) for x in version])

    setup(name='bzr-git',
          description='Support for Git branches in Bazaar',
          keywords='plugin bzr git bazaar',
          version=version_string,
          url='http://bazaar-vcs.org/BzrForeignBranches/Git',
          license='GPL',
          maintainer='Jelmer Vernooij',
          maintainer_email='jelmer@samba.org',
          long_description="""
          This plugin adds limited support for checking out and viewing
          Git branches in Bazaar.
          """,
          package_dir={'bzrlib.plugins.git':'.'},
          packages=['bzrlib.plugins.git',
                    'bzrlib.plugins.git.tests'],
          scripts=['bzr-receive-pack', 'bzr-upload-pack'],
          )
