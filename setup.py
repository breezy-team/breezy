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
    from setuptools_gettext import build_mo  # noqa: F401
except ImportError:
    sys.stderr.write(
        "[ERROR] Please install setuptools_gettext to build translations.\n"
    )
    sys.exit(1)

from distutils.command.build_scripts import build_scripts

from setuptools import Command

###############################
# Overridden distutils actions
###############################


class brz_build_scripts(build_scripts):
    """Custom build_scripts command that handles Rust extension binaries.

    This class extends the standard build_scripts command to properly handle
    Rust extension binaries by moving executable Rust extensions from the
    build_lib directory to the scripts directory.
    """

    def run(self):
        """Execute the build_scripts command and handle Rust executables.

        First runs the standard build_scripts process, then moves any Rust
        executable extensions from the build_lib directory to the scripts
        build directory.
        """
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
    """Custom command to generate the brz.1 manual page.

    This command builds the Breezy extension modules and then uses the
    generate_docs tool to create the brz.1 manual page from the built
    modules.
    """

    def initialize_options(self):
        """Initialize command options.

        No options to initialize for this command.
        """
        pass

    def finalize_options(self):
        """Finalize command options.

        No options to finalize for this command.
        """
        pass

    def run(self):
        """Execute the manual page generation.

        Builds the extension modules, adds the build directory to sys.path,
        and then imports and runs the generate_docs tool to create the
        brz.1 manual page.
        """
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
        "breezy._patch_rs", "crates/patch-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension(
        "breezy._annotator_rs",
        "crates/annotate-py/Cargo.toml",
        binding=Binding.PyO3,
    ),
    RustExtension(
        "breezy.zlib_util", "crates/zlib-util-py/Cargo.toml", binding=Binding.PyO3
    ),
    RustExtension("breezy._git_rs", "crates/git-py/Cargo.toml", binding=Binding.PyO3),
]

entry_points = {
    "console_scripts": [
        "deb-update-packaging=breezy.plugins.debian.update_packaging:main",
        "deb-vcs-up-to-date=breezy.plugins.debian.vcs_up_to_date:main",
        "deb-move-orphaned=breezy.plugins.debian.move_orphaned:main",
        "deb-import-uncommitted=breezy.plugins.debian.import_uncommitted:main",
        "deb-auto-backport=breezy.plugins.debian.merge_package:auto_backport",
        "deb-new-upstream=breezy.plugins.debian.new_upstream:main",
        "deb-merge=breezy.plugins.debian.merge_package:main",
    ],
}

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
    entry_points["console_scripts"].append("brz=breezy.__main__:main")

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
    entry_points=entry_points,
    rust_extensions=rust_extensions,
)
