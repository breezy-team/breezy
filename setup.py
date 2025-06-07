#! /usr/bin/env python3

"""Installation script for brz.
Run it with
 './setup.py install', or
 './setup.py --help' for more options.
"""

import os
import os.path
import sys

try:
    import setuptools  # noqa: F401
except ModuleNotFoundError as e:
    sys.stderr.write(f"[ERROR] Please install setuptools ({e})\n")
    sys.exit(1)

try:
    from setuptools_rust import Binding, RustExtension, Strip
except ModuleNotFoundError as e:
    sys.stderr.write(f"[ERROR] Please install setuptools_rust ({e})\n")
    sys.exit(1)

from setuptools import setup
from setuptools.command.build import build

try:
    from packaging.version import Version
except ImportError:
    from distutils.version import LooseVersion as Version

from distutils.command.build_scripts import build_scripts

from setuptools import Command

###############################
# Overridden distutils actions
###############################


class brz_build_scripts(build_scripts):
    """Fixup Rust extension binary files to live under scripts."""

    def run(self):
        build_scripts.run(self)

        self.run_command("build_ext")
        build_ext = self.get_finalized_command("build_ext")

        for ext in self.distribution.rust_extensions:
            if ext.binding == Binding.Exec:
                # GZ 2021-08-19: Not handling multiple binaries yet.
                os.replace(
                    os.path.join(build_ext.build_lib, ext.name),
                    os.path.join(self.build_dir, ext.name),
                )


class build_man(Command):
    """Generate brz.1."""

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        build_ext_cmd = self.get_finalized_command("build_ext")
        build_lib_dir = build_ext_cmd.build_lib
        sys.path.insert(0, os.path.abspath(build_lib_dir))
        import importlib

        importlib.invalidate_caches()
        del sys.modules["breezy"]
        from tools import generate_docs

        generate_docs.main(["generate-docs", "man"])


########################
## Setup
########################

command_classes = {
    "build_man": build_man,
}

from distutils.extension import Extension

ext_modules = []
try:
    from Cython.Compiler.Version import version as cython_version
    from Cython.Distutils import build_ext
except ModuleNotFoundError:
    have_cython = False
    # try to build the extension from the prior generated source.
    print("")
    print(
        "The python package 'Cython' is not available. If the .c files are available,"
    )
    print("they will be built, but modifying the .pyx files will not rebuild them.")
    print("")
    from distutils.command.build_ext import build_ext
else:
    minimum_cython_version = "0.29"
    cython_version_info = Version(cython_version)
    if cython_version_info < Version(minimum_cython_version):
        print(
            "Version of Cython is too old. "
            f"Current is {cython_version}, need at least {minimum_cython_version}."
        )
        print(
            "If the .c files are available, they will be built,"
            " but modifying the .pyx files will not rebuild them."
        )
        have_cython = False
    else:
        have_cython = True


# Override the build_ext if we have Cython available
command_classes["build_ext"] = build_ext
unavailable_files = []


def add_cython_extension(module_name, libraries=None, extra_source=None):
    """Add a cython module to build.

    This will use Cython to auto-generate the .c file if it is available.
    Otherwise it will fall back on the .c file. If the .c file is not
    available, it will warn, and not add anything.

    You can pass any extra options to Extension through kwargs. One example is
    'libraries = []'.

    :param module_name: The python path to the module. This will be used to
        determine the .pyx and .c files to use.
    """
    if extra_source is None:
        extra_source = []
    path = module_name.replace(".", "/")
    cython_name = path + ".pyx"
    c_name = path + ".c"
    define_macros = []
    if sys.platform == "win32":
        # cython uses the macro WIN32 to detect the platform, even though it
        # should be using something like _WIN32 or MS_WINDOWS, oh well, we can
        # give it the right value.
        define_macros.append(("WIN32", None))
    if have_cython:
        source = [cython_name]
    else:
        if not os.path.isfile(c_name):
            unavailable_files.append(c_name)
            return
        else:
            source = [c_name]
    source.extend(extra_source)
    include_dirs = ["breezy"]
    ext_modules.append(
        Extension(
            module_name,
            source,
            define_macros=define_macros,
            libraries=libraries,
            include_dirs=include_dirs,
            optional=os.environ.get("CIBUILDWHEEL", "0") != "1",
        )
    )


add_cython_extension(
    "bzrformats._groupcompress_pyx", extra_source=["bzrformats/diff-delta.c"]
)
add_cython_extension("bzrformats._knit_load_data_pyx")
if sys.platform == "win32":
    add_cython_extension("bzrformats._dirstate_helpers_pyx", libraries=["Ws2_32"])
else:
    add_cython_extension("bzrformats._dirstate_helpers_pyx")
    add_cython_extension("breezy._readdir_pyx")
add_cython_extension("bzrformats._btree_serializer_pyx")


if unavailable_files:
    print("C extension(s) not found:")
    print("   {}".format("\n  ".join(unavailable_files)))
    print("The python versions will be used instead.")
    print("")


if "editable_wheel" not in sys.argv:
    command_classes["build_scripts"] = brz_build_scripts


# ad-hoc for easy_install
DATA_FILES = []
if (
    "bdist_egg" not in sys.argv
    and "bdist_wheel" not in sys.argv
    and "editable_wheel" not in sys.argv
):
    # generate and install brz.1 only with plain install, not the
    # easy_install one
    build.sub_commands.append(("build_man", lambda _: True))
    DATA_FILES = [("man/man1", ["brz.1", "breezy/git/git-remote-bzr.1"])]

import site

site.ENABLE_USER_SITE = "--user" in sys.argv

rust_extensions = [
    RustExtension("breezy._cmd_rs", "crates/cmd-py/Cargo.toml", binding=Binding.PyO3),
    RustExtension(
        "breezy._osutils_rs", "crates/osutils-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "breezy._transport_rs", "crates/transport-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "breezy._graph_rs", "crates/graph-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "breezy._patch_rs", "crates/patch-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "breezy.zlib_util", "crates/zlib-util-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "breezy._transport_rs", "crates/transport-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "breezy._urlutils_rs", "crates/urlutils-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "bzrformats._bzr_rs", "bzrformats/bazaar-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension("breezy._git_rs", "crates/git-py/Cargo.toml", binding=Binding.PyO3),
]
entry_points = {}

if (
    os.environ.get("CIBUILDWHEEL", "0") == "0"
    and "__pypy__" not in sys.builtin_module_names
    and sys.platform != "win32"
):
    rust_extensions.append(RustExtension("brz", binding=Binding.Exec, strip=Strip.All))
else:
    # Fall back to python main on cibuildwheels, since it doesn't provide
    # -lpython3.7 to link binaries against

    # also, disable it for PyPy. See https://foss.heptapod.net/pypy/pypy/-/issues/3286
    entry_points.setdefault("console_scripts", []).append("brz=breezy.__main__:main")

# std setup
setup(
    scripts=[  # TODO(jelmer): Only install the git scripts if
        # Dulwich was found.
        "breezy/git/git-remote-bzr",
        "breezy/git/bzr-receive-pack",
        "breezy/git/bzr-upload-pack",
    ],
    data_files=DATA_FILES,
    cmdclass=command_classes,
    ext_modules=ext_modules,
    entry_points=entry_points,
    rust_extensions=rust_extensions,
)
