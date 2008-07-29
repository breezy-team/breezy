#!/usr/bin/env python
# Setup file for bzr-svn
# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>

from distutils.core import setup
from distutils.extension import Extension
from distutils.command.install_lib import install_lib
from distutils import log
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


class BuildData:
    _libs = ['svn_subr-1', 'svn_client-1', 
            'svn_ra-1', 'svn_ra_dav-1', 'svn_ra_local-1', 'svn_ra_svn-1',
            'svn_repos-1', 'svn_wc-1', 'svn_delta-1', 'svn_diff-1', 'svn_fs-1', 
            'svn_repos-1', 'svn_fs_fs-1', 'svn_fs_base-1']
    
    def apr_build_data(self):
        return (self._apr_include_dirs(), self._apr_lib_dirs(), '')

    def svn_build_data(self):
        return (self._svn_include_dirs(), self._svn_lib_dirs())

class PosixBuildData(BuildData):
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
                return (includedir, [os.path.join(basedir, "lib")])
        raise Exception("Subversion development files not found")

    def libify(self, libname):
        return libname

class WindowsBuildData(BuildData):

    def __init__(self):
        for i, v in enumerate(self._libs):
            self._libs[i] = 'lib' + v
        self._libs = self._libs + ['libapr', 'libapriconv', 'libaprutil', 'intl3_svn', 'advapi32', 'shell32', 
                'libneon', 'xml',
                'libdb44',
                'ws2_32', 'zlibstat'
                ]

        # environment vars for the directories we need.
        self.svn_dev_dir = os.environ.get("SVN_DEV")
        if not self.svn_dev_dir or not os.path.isdir(self.svn_dev_dir):
            raise RuntimeError(
                "Please set SVN_DEV to the location of the svn development "
                "packages.\nThese can be downloaded from:\n"
                "http://subversion.tigris.org/servlets/ProjectDocumentList?folderID=91")
        self.svn_bdb_dir = os.environ.get("SVN_BDB")
        if not self.svn_bdb_dir or not os.path.isdir(self.svn_bdb_dir):
            raise RuntimeError(
                "Please set SVN_BDB to the location of the svn BDB packages "
                "- see README.txt in the SV_DEV dir")
        self.svn_libintl_dir = os.environ.get("SVN_LIBINTL")
        if not self.svn_libintl_dir or not os.path.isdir(self.svn_libintl_dir):
            raise RuntimeError(
                "Please set SVN_LIBINTL to the location of the svn libintl "
                "packages - see README.txt in the SV_DEV dir")

    def _apr_include_dirs(self):
        return [os.path.join(self.svn_dev_dir, r"include\apr"),
                os.path.join(self.svn_dev_dir, r"include\apr-utils"),
                os.path.join(self.svn_dev_dir, r"include\apr-iconv")]
    def _apr_lib_dirs(self):
        stub = os.path.join(self.svn_dev_dir, "lib")
        return [stub + r'\apr',
                stub + r'\apr-iconv',
                stub + r'\apr-util',
                stub + r'\neon']
    def _svn_include_dirs(self):
        return [os.path.join(self.svn_dev_dir, "include"), 
                r"c:\src\svn-win32-libintl"]
    def _svn_lib_dirs(self):
        return [os.path.join(self.svn_dev_dir, "lib"),
                os.path.join(self.svn_bdb_dir, "lib"),
                os.path.join(self.svn_libintl_dir, "lib")]

    def lib_list(self):
        return self._libs;

    def libify(self, libname):
        return ('lib' + libname )

SVN_SUBR = 0
SVN_CLIENT = 1
SVN_RA = 2
SVN_RA_DAV = 3
SVN_RA_LOCAL = 4
SVN_RA_SVN = 5
SVN_REPOS = 6
SVN_WC = 7
SVN_DELTA = 8
SVN_DIFF = 9
SVN_FS = 10
SVN_REPO = 11
SVN_FS_FS = 12
SVN_FS_BASE = 13
APR = 14
APR_ICONV = 15
APR_UTIL = 16
LIB_INTL = 17
ADVAPI = 18
SHELL = 19
NEON = 20
XML = 21
BDB = 22
WINSOCK = 23
ZLIB = 24

if os.name == 'nt':
    deps = WindowsBuildData()
else:
    deps = PosixBuildData()

(apr_includedir, apr_libdir, apr_ldflags) = deps.apr_build_data()
(svn_includedir, svn_libdir) = deps.svn_build_data()

def SvnExtension(name, *args, **kwargs):
    kwargs["include_dirs"] = apr_includedir + svn_includedir
    kwargs["library_dirs"] = svn_libdir + apr_libdir
    kwargs["extra_link_args"] = apr_ldflags
    if os.name == 'nt':
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
          SvnExtension("client", ["client.c", "editor.c", "util.c", "ra.c", "wc.c"], libraries=[deps.lib_list()[x] for x in 
              [SVN_CLIENT, SVN_SUBR, APR, SVN_WC, SVN_RA, LIB_INTL, SVN_DELTA, APR_UTIL, SHELL, ADVAPI, SVN_DIFF, SVN_RA_LOCAL, SVN_RA_DAV, SVN_RA_SVN,
                  SVN_FS, SVN_REPO, NEON, SVN_FS_FS, SVN_FS_BASE, WINSOCK, XML, BDB]]), 
          SvnExtension("ra", ["ra.c", "util.c", "editor.c"], libraries=[deps.lib_list()[x] for x in [SVN_RA, SVN_DELTA, SVN_SUBR,
              APR, SVN_RA_LOCAL, SVN_RA_DAV, SVN_RA_SVN, LIB_INTL, APR_UTIL, XML, SHELL, ADVAPI, SVN_FS, SVN_REPO, NEON, WINSOCK, SVN_FS_FS, SVN_FS_BASE, BDB]]),
          SvnExtension("repos", ["repos.c", "util.c"], libraries=[deps.lib_list()[x] for x in [SVN_REPO, SVN_SUBR,
              APR, LIB_INTL, SVN_FS, SVN_DELTA, APR_UTIL, SHELL, ADVAPI, SVN_FS_FS, SVN_FS_BASE, ZLIB, BDB, XML]]),
          SvnExtension("wc", ["wc.c", "util.c", "editor.c"], libraries=[deps.lib_list()[x] for x in [SVN_WC, SVN_SUBR,
              APR, LIB_INTL, SVN_DELTA, SVN_DIFF, APR_UTIL, XML, SHELL, ADVAPI]]),
          ],
      cmdclass = { 'install_lib': install_lib_with_dlls },
      )
