#!/usr/bin/env python
# Setup file for bzr-svn
# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>

from distutils.core import setup
from distutils.extension import Extension
from distutils.command.install_lib import install_lib
from distutils import log
import sys
import os

# Build instructions for Windows:
# * Install the SVN dev kit ZIP for Windows from
#   http://subversion.tigris.org/servlets/ProjectDocumentList?folderID=91
#   At time of writing, this was svn-win32-1.4.6_dev.zip
# * Find the SVN binary ZIP file with the binaries for your dev kit.
#   At time of writing, this was svn-win32-1.4.6.zip
#   Unzip this in the *same directory* as the dev kit - README.txt will be
#   overwritten, but that is all. This is the default location the .ZIP file
#   will suggest (ie, the directory embedded in both .zip files are the same)
# * Set SVN_DEV to point at this directory.
# * Install the APR BDB and INTL packages - see README.txt from the devkit
# * Set SVN_BDB and SVN_LIBINTL to point at these dirs.
#
#  To install into a particular bzr location, use:
#  % python setup.py install --install-lib=c:\root\of\bazaar

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
        cmds = ["apr-config", "apr-1-config", "/usr/local/apr/bin/apr-config",
                "/usr/local/bin/apr-config"]
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
            return ([includedir], [os.path.join(basedir, "lib")], [])
    raise Exception("Subversion development files not found")

# Windows versions - we use environment variables to locate the directories
# and hard-code a list of libraries.
if os.name == "nt":
    # just clobber the functions above we can't use
    # for simplicitly, everything is done in the 'svn' one
    def apr_build_data():
        return '.', ''

    def svn_build_data():
        # environment vars for the directories we need.
        svn_dev_dir = os.environ.get("SVN_DEV")
        if not svn_dev_dir or not os.path.isdir(svn_dev_dir):
            raise Exception(
                "Please set SVN_DEV to the location of the svn development "
                "packages.\nThese can be downloaded from:\n"
                "http://subversion.tigris.org/servlets/ProjectDocumentList?folderID=91")
        svn_bdb_dir = os.environ.get("SVN_BDB")
        if not svn_bdb_dir or not os.path.isdir(svn_bdb_dir):
            raise Exception(
                "Please set SVN_BDB to the location of the svn BDB packages "
                "- see README.txt in the SV_DEV dir")
        svn_libintl_dir = os.environ.get("SVN_LIBINTL")
        if not svn_libintl_dir or not os.path.isdir(svn_libintl_dir):
            raise Exception(
                "Please set SVN_LIBINTL to the location of the svn libintl "
                "packages - see README.txt in the SV_DEV dir")

        includes = [
            # apr dirs.
            os.path.join(svn_dev_dir, r"include\apr"),
            os.path.join(svn_dev_dir, r"include\apr-utils"),
            os.path.join(svn_dev_dir, r"include\apr-iconv"),
            # svn dirs.
            os.path.join(svn_dev_dir, "include"), 
        ]
        lib_dirs = [
            os.path.join(svn_dev_dir, "lib"),
            os.path.join(svn_dev_dir, "lib", "apr"),
            os.path.join(svn_dev_dir, "lib", "apr-iconv"),
            os.path.join(svn_dev_dir, "lib", "apr-util"),
            os.path.join(svn_dev_dir, "lib", "neon"),
            os.path.join(svn_bdb_dir, "lib"),
            os.path.join(svn_libintl_dir, "lib"),
        ]
        libs = """libapr libapriconv libaprutil libneon
                  libsvn_subr-1 libsvn_client-1 libsvn_ra-1
                  libsvn_ra_dav-1 libsvn_ra_local-1 libsvn_ra_svn-1
                  libsvn_repos-1 libsvn_wc-1 libsvn_delta-1 libsvn_diff-1
                  libsvn_fs-1 libsvn_repos-1 libsvn_fs_fs-1 libsvn_fs_base-1
                  intl3_svn
                  libdb44 xml
                  advapi32 shell32 ws2_32 zlibstat
               """.split()

        return includes, lib_dirs, libs,

(apr_includedir, apr_ldflags) = apr_build_data()
(svn_includedirs, svn_libdirs, extra_libs) = svn_build_data()

def SvnExtension(name, *args, **kwargs):
    kwargs["include_dirs"] = [apr_includedir] + svn_includedirs
    kwargs["library_dirs"] = svn_libdirs
    kwargs["extra_link_args"] = apr_ldflags
    if os.name == 'nt':
        # on windows, just ignore and overwrite the libraries!
        kwargs["libraries"] = extra_libs
        # APR needs WIN32 defined.
        kwargs["define_macros"] = [("WIN32", None)]
    return Extension("bzrlib.plugins.svn.%s" % name, *args, **kwargs)

# On Windows, we install the apr binaries too.
class install_lib_with_dlls(install_lib):
    def _get_dlls(self):
        # return a list of of (FQ-in-name, relative-out-name) tuples.
        ret = []
        apr_bins = "libaprutil.dll libapriconv.dll libapr.dll".split()
        look_dirs = os.environ.get("PATH","").split(os.pathsep)
        look_dirs.insert(0, os.path.join(os.environ["SVN_DEV"], "bin"))
    
        for bin in apr_bins:
            for look in look_dirs:
                f = os.path.join(look, bin)
                if os.path.isfile(f):
                    target = os.path.join(self.install_dir, "bzrlib",
                                          "plugins", "svn", bin)
                    ret.append((f, target))
                    break
            else:
                log.warn("Could not find required DLL %r to include", bin)
                log.debug("(looked in %s)", look_dirs)
        return ret

    def run(self):
        install_lib.run(self)
        # the apr binaries.
        if os.name == 'nt':
            # On Windows we package up the apr dlls with the plugin.
            for s, d in self._get_dlls():
                self.copy_file(s, d)

    def get_outputs(self):
        ret = install_lib.get_outputs()
        if os.name == 'nt':
            ret.extend([info[1] for info in self._get_dlls()])
        return ret

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
          ],
      cmdclass = { 'install_lib': install_lib_with_dlls },
      )
