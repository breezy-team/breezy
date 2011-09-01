#!/usr/bin/env python

from info import *

readme = file('README').read()


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
          long_description=readme,
          package_dir={'bzrlib.plugins.git':'.'},
          packages=['bzrlib.plugins.git',
                    'bzrlib.plugins.git.tests'],
          scripts=['bzr-receive-pack', 'bzr-upload-pack'],
          classifiers=[
              'Topic :: Software Development :: Version Control',
              'Environment :: Plugins',
              'Development Status :: 4 - Beta',
              'License :: OSI Approved :: GNU General Public License (GPL)',
              'Natural Language :: English',
              'Operating System :: OS Independent',
              'Programming Language :: Python',
              'Programming Language :: Python :: 2',
          ]
          )
