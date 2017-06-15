#!/usr/bin/env python

from info import *

readme = file('README').read()


if __name__ == '__main__':
    from distutils.core import setup
    version = bzr_plugin_version[:3]
    version_string = ".".join([str(x) for x in version])

    command_classes = {}
    try:
        from breezy.bzr_distutils import build_mo
    except ImportError:
        pass
    else:
        command_classes['build_mo'] = build_mo

    setup(name='bzr-git',
          description='Support for Git branches in Bazaar',
          keywords='plugin bzr git bazaar',
          version=version_string,
          url='http://bazaar-vcs.org/BzrForeignBranches/Git',
          license='GPL',
          maintainer='Jelmer Vernooij',
          maintainer_email='jelmer@samba.org',
          long_description=readme,
          package_dir={'breezy.plugins.git':'.'},
          packages=['breezy.plugins.git',
                    'breezy.plugins.git.tests'],
          scripts=['bzr-receive-pack', 'bzr-upload-pack', 'git-remote-bzr'],
          classifiers=[
              'Topic :: Software Development :: Version Control',
              'Environment :: Plugins',
              'Development Status :: 4 - Beta',
              'License :: OSI Approved :: GNU General Public License (GPL)',
              'Natural Language :: English',
              'Operating System :: OS Independent',
              'Programming Language :: Python',
              'Programming Language :: Python :: 2',
          ],
          cmdclass=command_classes,
          )
