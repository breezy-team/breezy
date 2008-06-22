#!/usr/bin/env python
# Setup file for bzr-svn
# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>

from distutils.core import setup
from distutils.extension import Extension
import os

def apr_build_data():
    """Determine the APR header file location."""
    def apr_config(arg):
        f = os.popen("apr-config %s" % arg)
        dir = f.read().rstrip("\n")
        return dir
    includedir = apr_config("--includedir")
    if not os.path.isdir(includedir):
        raise Exception("APR development headers not found")
    ldflags = apr_config("--ldflags")
    return (includedir, ldflags)

def svn_build_data():
    """Determine the Subversion header file location."""
    basedirs = ["/usr/local", "/usr"]
    for basedir in basedirs:
        includedir = os.path.join(basedir, "include/subversion-1")
        if os.path.isdir(includedir):
            return (includedir, os.path.join(basedir, "lib"))
    raise Exception("Subversion development files not found")

(apr_includedir, apr_ldflags) = apr_build_data()
(svn_includedir, svn_libdir) = svn_build_data()

def SvnExtension(*args, **kwargs):
    kwargs["include_dirs"] = [apr_includedir, svn_includedir]
    kwargs["library_dirs"] = [svn_libdir]
    kwargs["extra_link_args"] = [apr_ldflags]
    return Extension(*args, **kwargs)


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
          SvnExtension("core", ["core.c", "util.c"], libraries=["svn_subr-1"]), 
          SvnExtension("client", ["client.c", "editor.c", "util.c", "ra.c", "wc.c"], libraries=["svn_client-1"]), 
          SvnExtension("ra", ["ra.c", "util.c", "editor.c"], libraries=["svn_ra-1"]),
          SvnExtension("repos", ["repos.c", "util.c"], libraries=["svn_repos-1"]),
          SvnExtension("wc", ["wc.c", "util.c", "editor.c"], libraries=["svn_wc-1"]),
          ]
      )
