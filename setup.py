#!/usr/bin/env python
import os
from distutils.core import setup

bzr_plugin_name = 'groupcompress'

bzr_plugin_version = (1, 6, 0, 'dev', 0)

from distutils import log
from distutils.errors import CCompilerError, DistutilsPlatformError
from distutils.extension import Extension
ext_modules = []
try:
    from Pyrex.Distutils import build_ext
except ImportError:
    have_pyrex = False
    # try to build the extension from the prior generated source.
    print
    print ("The python package 'Pyrex' is not available."
           " If the .c files are available,")
    print ("they will be built,"
           " but modifying the .pyx files will not rebuild them.")
    print
    from distutils.command.build_ext import build_ext
else:
    have_pyrex = True


class build_ext_if_possible(build_ext):

    user_options = build_ext.user_options + [
        ('allow-python-fallback', None,
         "When an extension cannot be built, allow falling"
         " back to the pure-python implementation.")
        ]

    def initialize_options(self):
        build_ext.initialize_options(self)
        self.allow_python_fallback = False

    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError, e:
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
            build_ext.build_extension(self, ext)
        except CCompilerError:
            if not self.allow_python_fallback:
                log.warn('\n  Cannot build extension (%s).\n'
                         '  Use "build_ext --allow-python-fallback" to use'
                         ' slower python implementations instead.\n'
                         % (ext.name,))
                raise
            log.warn('\n  Building of "%s" extension failed.\n'
                     '  Using the slower Python implementation instead.'
                     % (ext.name,))


# Override the build_ext if we have Pyrex available
unavailable_files = []


def add_pyrex_extension(module_name, extra_source=[]):
    """Add a pyrex module to build.

    This will use Pyrex to auto-generate the .c file if it is available.
    Otherwise it will fall back on the .c file. If the .c file is not
    available, it will warn, and not add anything.

    You can pass any extra options to Extension through kwargs. One example is
    'libraries = []'.

    :param module_name: The python path to the module. This will be used to
        determine the .pyx and .c files to use.
    """
    path = module_name.replace('.', '/')
    pyrex_name = path + '.pyx'
    c_name = path + '.c'
    # Manually honour package_dir :(
    module_name = 'bzrlib.plugins.groupcompress.' + module_name
    if have_pyrex:
        source = [pyrex_name]
    elif not os.path.isfile(c_name):
        unavailable_files.append(c_name)
        return
    else:
        source = [c_name]
    source.extend(extra_source)
    ext_modules.append(Extension(module_name, source,
        extra_compile_args = ['-O3']))

add_pyrex_extension('_groupcompress_pyx',
                    extra_source=['diff-delta.c'])


if __name__ == '__main__':
    setup(name="bzr groupcompress",
          version="1.6.0dev0",
          description="bzr group compression.",
          author="Robert Collins",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-groupcompress",
          packages=['bzrlib.plugins.groupcompress',
                    'bzrlib.plugins.groupcompress.tests',
                    ],
          package_dir={'bzrlib.plugins.groupcompress': '.'},
          cmdclass={'build_ext': build_ext_if_possible},
          ext_modules=ext_modules,
          )
