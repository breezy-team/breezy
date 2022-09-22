#! /usr/bin/env python3

"""Installation script for brz.
Run it with
 './setup.py install', or
 './setup.py --help' for more options
"""

import os
import os.path
import sys
import glob

try:
    import setuptools
except ModuleNotFoundError as e:
    sys.stderr.write("[ERROR] Please install setuptools (%s)\n" % e)
    sys.exit(1)

try:
    from setuptools_rust import Binding, RustExtension, Strip
except ModuleNotFoundError as e:
    sys.stderr.write("[ERROR] Please install setuptools_rust (%s)\n" % e)
    sys.exit(1)


# NOTE: The directory containing setup.py, whether run by 'python setup.py' or
# './setup.py' or the equivalent with another path, should always be at the
# start of the path, so this should find the right one...
import breezy

I18N_FILES = []
for filepath in glob.glob("breezy/locale/*/LC_MESSAGES/*.mo"):
    langfile = filepath[len("breezy/locale/"):]
    targetpath = os.path.dirname(os.path.join("share/locale", langfile))
    I18N_FILES.append((targetpath, [filepath]))


from setuptools import setup
try:
    from packaging.version import Version
except ImportError:
    from distutils.version import LooseVersion as Version
from distutils.command.install import install
from distutils.command.install_data import install_data
from distutils.command.install_scripts import install_scripts
from distutils.command.build import build
from distutils.command.build_scripts import build_scripts

###############################
# Overridden distutils actions
###############################

class brz_build_scripts(build_scripts):
    """Fixup Rust extension binary files to live under scripts."""

    def run(self):
        build_scripts.run(self)

        self.run_command('build_ext')
        build_ext = self.get_finalized_command("build_ext")

        for ext in self.distribution.rust_extensions:
            if ext.binding == Binding.Exec:
                # GZ 2021-08-19: Not handling multiple binaries yet.
                os.replace(
                    os.path.join(build_ext.build_lib, ext.name),
                    os.path.join(self.build_dir, ext.name))


class brz_install(install):
    """Turns out easy_install was always just a bad idea."""

    def finalize_options(self):
        install.finalize_options(self)
        # Get us off the do_egg_install() path
        self.single_version_externally_managed = True


class bzr_build(build):
    """Customized build distutils action.
    Generate brz.1.
    """

    sub_commands = build.sub_commands + [
        ('build_mo', lambda _: True),
        ]

    def run(self):
        build.run(self)

        from tools import generate_docs
        generate_docs.main(argv=["brz", "man"])


########################
## Setup
########################

from breezy.bzr_distutils import build_mo

command_classes = {
    'build': bzr_build,
    'build_mo': build_mo,
    'build_scripts': brz_build_scripts,
    'install': brz_install,
}

from distutils import log
from distutils.errors import CCompilerError, DistutilsPlatformError
from distutils.extension import Extension
ext_modules = []
try:
    from Cython.Distutils import build_ext
    from Cython.Compiler.Version import version as cython_version
except ModuleNotFoundError:
    have_cython = False
    # try to build the extension from the prior generated source.
    print("")
    print("The python package 'Cython' is not available."
          " If the .c files are available,")
    print("they will be built,"
          " but modifying the .pyx files will not rebuild them.")
    print("")
    from distutils.command.build_ext import build_ext
else:
    minimum_cython_version = '0.29'
    cython_version_info = Version(cython_version)
    if cython_version_info < Version(minimum_cython_version):
        print("Version of Cython is too old. "
              "Current is %s, need at least %s."
              % (cython_version, minimum_cython_version))
        print("If the .c files are available, they will be built,"
              " but modifying the .pyx files will not rebuild them.")
        have_cython = False
    else:
        have_cython = True


class build_ext_if_possible(build_ext):

    user_options = build_ext.user_options + [
        ('allow-python-fallback', None,
         "When an extension cannot be built, allow falling"
         " back to the pure-python implementation.")
        ]

    def initialize_options(self):
        super(build_ext_if_possible, self).initialize_options()
        self.ext_map = {}
        self.allow_python_fallback = False

    def run(self):
        try:
            super(build_ext_if_possible, self).run()
        except DistutilsPlatformError:
            e = sys.exc_info()[1]
            if not self.allow_python_fallback:
                log.warn('\n  Cannot build extensions.\n'
                         '  Use "build_ext --allow-python-fallback" to use'
                         ' slower python implementations instead.\n')
                raise
            log.warn(str(e))
            log.warn('\n  Extensions cannot be built.\n'
                     '  Using the slower Python implementations instead.\n')

    def build_extension(self, ext):
        try:
            super(build_ext_if_possible, self).build_extension(ext)
        except CCompilerError:
            if not self.allow_python_fallback:
                log.warn('\n  Cannot build extension "%s".\n'
                         '  Use "build_ext --allow-python-fallback" to use'
                         ' slower python implementations instead.\n'
                         % (ext.name,))
                raise
            log.warn('\n  Building of "%s" extension failed.\n'
                     '  Using the slower Python implementation instead.'
                     % (ext.name,))


# Override the build_ext if we have Cython available
command_classes['build_ext'] = build_ext_if_possible
unavailable_files = []


def add_cython_extension(module_name, libraries=None, extra_source=[]):
    """Add a cython module to build.

    This will use Cython to auto-generate the .c file if it is available.
    Otherwise it will fall back on the .c file. If the .c file is not
    available, it will warn, and not add anything.

    You can pass any extra options to Extension through kwargs. One example is
    'libraries = []'.

    :param module_name: The python path to the module. This will be used to
        determine the .pyx and .c files to use.
    """
    path = module_name.replace('.', '/')
    cython_name = path + '.pyx'
    c_name = path + '.c'
    define_macros = []
    if sys.platform == 'win32':
        # cython uses the macro WIN32 to detect the platform, even though it
        # should be using something like _WIN32 or MS_WINDOWS, oh well, we can
        # give it the right value.
        define_macros.append(('WIN32', None))
    if have_cython:
        source = [cython_name]
    else:
        if not os.path.isfile(c_name):
            unavailable_files.append(c_name)
            return
        else:
            source = [c_name]
    source.extend(extra_source)
    include_dirs = ['breezy']
    ext_modules.append(
        Extension(
            module_name, source, define_macros=define_macros,
            libraries=libraries, include_dirs=include_dirs))


add_cython_extension('breezy.bzr._simple_set_pyx')
ext_modules.append(Extension('breezy.bzr._static_tuple_c',
                             ['breezy/bzr/_static_tuple_c.c']))
add_cython_extension('breezy._annotator_pyx')
add_cython_extension('breezy._chunks_to_lines_pyx')
add_cython_extension('breezy.bzr._groupcompress_pyx',
                     extra_source=['breezy/bzr/diff-delta.c'])
add_cython_extension('breezy.bzr._knit_load_data_pyx')
add_cython_extension('breezy._known_graph_pyx')
add_cython_extension('breezy.bzr._rio_pyx')
if sys.platform == 'win32':
    add_cython_extension('breezy.bzr._dirstate_helpers_pyx',
                         libraries=['Ws2_32'])
    add_cython_extension('breezy._walkdirs_win32')
else:
    add_cython_extension('breezy.bzr._dirstate_helpers_pyx')
    add_cython_extension('breezy._readdir_pyx')
add_cython_extension('breezy.bzr._chk_map_pyx')
add_cython_extension('breezy.bzr._btree_serializer_pyx')


if unavailable_files:
    print('C extension(s) not found:')
    print(('   %s' % ('\n  '.join(unavailable_files),)))
    print('The python versions will be used instead.')
    print("")


# ad-hoc for easy_install
DATA_FILES = []
if 'bdist_egg' not in sys.argv:
    # generate and install brz.1 only with plain install, not the
    # easy_install one
    DATA_FILES = [('man/man1', ['brz.1', 'breezy/git/git-remote-bzr.1'])]

DATA_FILES = DATA_FILES + I18N_FILES

import site
site.ENABLE_USER_SITE = "--user" in sys.argv

# std setup
setup(
    scripts=[# TODO(jelmer): Only install the git scripts if
             # Dulwich was found.
             'breezy/git/git-remote-bzr',
             'breezy/git/bzr-receive-pack',
             'breezy/git/bzr-upload-pack'],
    data_files=DATA_FILES,
    cmdclass=command_classes,
    ext_modules=ext_modules,
    rust_extensions=[
        RustExtension("brz", binding=Binding.Exec, strip=Strip.All),
        RustExtension("breezy.bzr._rio_rs", "lib-rio/Cargo.toml", binding=Binding.PyO3),
    ],
    # install files from selftest suite
    package_data={'breezy': ['doc/api/*.txt',
                             'tests/test_patches_data/*',
                             'help_topics/en/*.txt',
                             'tests/ssl_certs/ca.crt',
                             'tests/ssl_certs/server_without_pass.key',
                             'tests/ssl_certs/server_with_pass.key',
                             'tests/ssl_certs/server.crt',
]})
