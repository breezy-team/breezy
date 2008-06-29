#!/usr/bin/env python
# Setup file for bzr-svn
# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>

from distutils.core import setup
from distutils.extension import Extension
import os

class CommandException(Exception):
    """Encapsulate exit status of apr-config execution"""
    def __init__(self, msg, cmd, arg, status, val):
        self.message = msg % (cmd, val)
        super(CommandException, self).__init__(self.message)
        self.cmd = cmd
        self.arg = arg
        self.status = status
    def not_found(self):
        return os.WIFEXITED(self.status) and os.WEXITSTATUS(self.status) == 127

def run_cmd(cmd, arg):
    """Run specified command with given arguments, handling status"""
    f = os.popen("'%s' %s" % (cmd, arg))
    dir = f.read().rstrip("\n")
    status = f.close()
    if status is None:
        return dir
    if os.WIFEXITED(status):
        code = os.WEXITSTATUS(status)
        if code == 0:
            return dir
        raise CommandException("%s exited with status %d",
                               cmd, arg, status, code)
    if os.WIFSIGNALED(status):
        signal = os.WTERMSIG(status)
        raise CommandException("%s killed by signal %d",
                               cmd, arg, status, signal)
    raise CommandException("%s terminated abnormally (%d)",
                           cmd, arg, status, status)

def apr_config(arg):
    apr_config_cmd = os.getenv("APR_CONFIG")
    if apr_config_cmd is None:
        cmds = ["apr-config", "apr-1-config"]
        for cmd in cmds:
            try:
                res = run_cmd(cmd, arg)
                apr_config_cmd = cmd
                break
            except CommandException, e:
                if not e.not_found():
                    raise
        else:
            raise Exception("apr-config not found."
                            " Please set APR_CONFIG environment variable")
    else:
        res = run_cmd(apr_config_cmd, arg)
    return res

def apr_build_data():
    """Determine the APR header file location."""
    includedir = apr_config("--includedir")
    if not os.path.isdir(includedir):
        raise Exception("APR development headers not found")
    ldflags = filter(lambda x: x != "", apr_config("--link-ld").split(" "))
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
    kwargs["extra_link_args"] = apr_ldflags
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
          SvnExtension("client", ["client.c", "editor.c", "util.c", "ra.c", "wc.c"], libraries=["svn_client-1", "svn_subr-1"]), 
          SvnExtension("ra", ["ra.c", "util.c", "editor.c"], libraries=["svn_ra-1", "svn_delta-1", "svn_subr-1"]),
          SvnExtension("repos", ["repos.c", "util.c"], libraries=["svn_repos-1", "svn_subr-1"]),
          SvnExtension("wc", ["wc.c", "util.c", "editor.c"], libraries=["svn_wc-1", "svn_subr-1"]),
          ]
      )
