#!/usr/bin/env python2.4

from distutils.core import setup

setup(name='bzr-email',
      description='Email plugin for Bazaar',
      keywords='plugin bzr email',
      version='0.0.1',
      url='http://launchpad.net/bzr-email',
      download_url='http://launchpad.net/bzr-email',
      license='GPL',
      author='Robert Collins',
      author_email='robertc@robertcollins.net',
      long_description="""
      Hooks into Bazaar and sends commit notification emails.
      """,
      package_dir={'bzrlib.plugins.email':'.', 
                   'bzrlib.plugins.email.tests':'tests'},
      packages=['bzrlib.plugins.email', 
                'bzrlib.plugins.email.tests']
      )
