#!/usr/bin/env python

bzr_plugin_name = "git"

dulwich_minimum_version = (0, 3, 1)

# versions ending in 'exp' mean experimental mappings
# versions ending in 'dev' mean development version
# versions ending in 'final' mean release (well tested, etc)
bzr_plugin_version = (0, 4, 1, 'dev', 0)

bzr_commands = ["svn-import", "svn-layout"]

bzr_compatible_versions = [(1, x, 0) for x in [14, 15, 16, 17, 18]]

bzr_minimum_version = bzr_compatible_versions[0]

bzr_maximum_version = bzr_compatible_versions[-1]

bzr_control_formats = {"Git":{'.git/': None}}

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
