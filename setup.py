#!/usr/bin/env python

bzr_plugin_name = 'rewrite'

bzr_plugin_version = (0, 5, 3, 'dev', 0)

bzr_compatible_versions = [(1, 14, 0), (1, 15, 0), (1, 16, 0), (1, 17, 0)]

bzr_minimum_version = bzr_compatible_versions[0]

bzr_maximum_version = bzr_compatible_versions[-1]

bzr_commands = [
    "replay",
    "rebase",
    "rebase_abort",
    "rebase_continue",
    "rebase_todo",
    "filter_branch",
    ]

if __name__ == '__main__':
    from distutils.core import setup

    version_string = ".".join([str(v) for v in bzr_plugin_version[:3]])

    setup(name='bzr-rewrite',
          description='Rebase plugin for Bazaar',
          keywords='plugin bzr rebase',
          version=version_string,
          url='http://bazaar-vcs.org/Rebase',
          download_url='http://samba.org/~jelmer/bzr/bzr-rebase-%s.tar.gz' % version_string,
          license='GPLv3 or later',
          author='Jelmer Vernooij',
          author_email='jelmer@samba.org',
          long_description="""
          Hooks into Bazaar and provides commands for rebasing.
          """,
          package_dir={'bzrlib.plugins.rebase':'.'},
          packages=['bzrlib.plugins.rebase']
    )
