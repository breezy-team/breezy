#!/usr/bin/env python
# Setup file for bzr-svn
# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>

from distutils.core import setup
from distutils.extension import Extension
import os

def apr_include_dir():
    """Determine the APR header file location."""
    f = os.popen("apr-config --includedir")
    dir = f.read().rstrip("\n")
    if not os.path.isdir(dir):
        raise Exception("APR development headers not found")
    return dir

def svn_include_dir():
    """Determine the Subversion header file location."""
    dirs = ["/usr/local/include/subversion-1", "/usr/include/subversion-1"]
    for dir in dirs:
        if os.path.isdir(dir):
            return dir
    raise Exception("Subversion development headers not found")

setup(name='bzr-svn',
      description='Support for Subversion branches in Bazaar',
      keywords='plugin bzr svn',
      version='0.4.11',
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
                'bzrlib.plugins.svn.mapping3', 
                'bzrlib.plugins.svn.tests'],
      ext_modules=[
          Extension("repos", ["repos.c", "util.c"], libraries=["svn_repos-1"], 
                    include_dirs=[apr_include_dir(), svn_include_dir()]), 
          Extension("wc", ["wc.c", "util.c", "editor.c"], libraries=["svn_wc-1"],
                     include_dirs=[apr_include_dir(), svn_include_dir()])],
      )
