#!/cygdrive/C/Python25/python
"""A script to help automate the build process."""

# When preparing a new release, make sure to set all of these to the latest
# values.
VERSIONS = {
    "brz": "1.17",
    "qbzr": "0.12",
    "bzrtools": "1.17.0",
    "bzr-svn": "0.6.3",
    "bzr-rewrite": "0.5.2",
    "subvertpy": "0.6.8",
}

# This will be passed to 'make' to ensure we build with the right python
PYTHON = "/cygdrive/c/Python25/python"

# Create the final build in this directory
TARGET_ROOT = "release"

DEBUG_SUBPROCESS = True


import os
import shutil
import subprocess
import sys

BRZ_EXE = None


def brz():
    """Get the appropriate brz executable name.

    Attempts to find either 'brz' or 'brz.bat' in the system PATH.

    Returns:
        str: The name of the brz executable ('brz' or 'brz.bat').

    Raises:
        RuntimeError: If neither brz nor brz.bat can be found on the PATH.
    """
    global BRZ_EXE
    if BRZ_EXE is not None:
        return BRZ_EXE
    try:
        subprocess.call(
            ["brz", "--version"],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        BRZ_EXE = "brz"
    except OSError:
        try:
            subprocess.call(
                ["brz.bat", "--version"],  # noqa: S607
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            BRZ_EXE = "brz.bat"
        except OSError as err:
            raise RuntimeError("Could not find brz or brz.bat on your path.") from err
    return BRZ_EXE


def call_or_fail(*args, **kwargs):
    """Call a subprocess, and fail if the return code is not 0."""
    if DEBUG_SUBPROCESS:
        print(f'  calling: "{" ".join(args[0])}"')
    p = subprocess.Popen(*args, **kwargs)
    (out, _err) = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(f"Failed to run: {args}, {kwargs}")
    return out


TARGET = None


def get_target():
    """Get the target directory path for the build.

    Creates a target directory name based on the current brz version.
    The directory follows the pattern TARGET_ROOT-{version}.

    Returns:
        str: Absolute path to the target build directory.
    """
    global TARGET
    if TARGET is not None:
        return TARGET
    out = call_or_fail(
        [get_brz_dir() + "/brz", "version", "--short"], stdout=subprocess.PIPE
    )
    version = out.strip()
    TARGET = os.path.abspath(TARGET_ROOT + "-" + version)
    return TARGET


def clean_target():
    """Nuke the target directory so we know we are starting from scratch."""
    target = get_target()
    if os.path.isdir(target):
        print(f"Deleting: {target}")
        shutil.rmtree(target)


def get_brz_dir():
    """Get the brz source directory name.

    Returns:
        str: Directory name for the brz source, formatted as 'brz.{version}'.
    """
    return "brz." + VERSIONS["brz"]


def update_brz():
    """Ensure we have the latest brz source code.

    Downloads or updates the brz source code from the configured version.
    If the directory doesn't exist, it checks out the code from launchpad.
    If it exists, it updates the existing checkout.
    """
    brz_dir = get_brz_dir()
    if not os.path.isdir(brz_dir):
        brz_version = VERSIONS["brz"]
        brz_url = "lp:brz/" + brz_version
        print(f"Getting brz release {brz_version} from {brz_url}")
        call_or_fail([brz(), "co", brz_url, brz_dir])
    else:
        print(f"Ensuring {brz_dir} is up-to-date")
        call_or_fail([brz(), "update", brz_dir])


def create_target():
    """Create the target build directory.

    Checks out a copy of the brz source to the target directory
    where the final build will be assembled.
    """
    target = get_target()
    print(f"Creating target dir: {target}")
    call_or_fail([brz(), "co", get_brz_dir(), target])


def get_plugin_trunk_dir(plugin_name):
    """Get the trunk directory path for a plugin.

    Args:
        plugin_name (str): Name of the plugin.

    Returns:
        str: Directory path for the plugin trunk.
    """
    return f"{plugin_name}/trunk"


def get_plugin_release_dir(plugin_name):
    """Get the release directory path for a plugin.

    Args:
        plugin_name (str): Name of the plugin.

    Returns:
        str: Directory path for the plugin release version.
    """
    return f"{plugin_name}/{VERSIONS[plugin_name]}"


def get_plugin_trunk_branch(plugin_name):
    """Get the launchpad branch URL for a plugin's trunk.

    Args:
        plugin_name (str): Name of the plugin.

    Returns:
        str: Launchpad URL for the plugin's trunk branch.
    """
    return f"lp:{plugin_name}"


def update_plugin_trunk(plugin_name):
    """Update or checkout the trunk version of a plugin.

    Downloads the latest trunk version of the specified plugin from launchpad.
    If the directory doesn't exist, it checks out the code.
    If it exists, it updates the existing checkout.

    Args:
        plugin_name (str): Name of the plugin to update.

    Returns:
        str: Path to the trunk directory.
    """
    trunk_dir = get_plugin_trunk_dir(plugin_name)
    if not os.path.isdir(trunk_dir):
        plugin_trunk = get_plugin_trunk_branch(plugin_name)
        print(f"Getting latest {plugin_name} trunk")
        call_or_fail([brz(), "co", plugin_trunk, trunk_dir])
    else:
        print(f"Ensuring {trunk_dir} is up-to-date")
        call_or_fail([brz(), "update", trunk_dir])
    return trunk_dir


def _plugin_tag_name(plugin_name):
    """Get the tag name format for a plugin's release.

    Different plugins use different tag naming conventions.
    Some use '{plugin}-{version}' while others use 'release-{version}'.

    Args:
        plugin_name (str): Name of the plugin.

    Returns:
        str: The tag name for the plugin's configured version.
    """
    if plugin_name in ("bzr-svn", "bzr-rewrite", "subvertpy"):
        return f"{plugin_name}-{VERSIONS[plugin_name]}"
    # bzrtools and qbzr use 'release-X.Y.Z'
    return "release-" + VERSIONS[plugin_name]


def update_plugin(plugin_name):
    """Update or checkout a specific version of a plugin.

    Downloads the tagged release version of the specified plugin.
    First updates the trunk, then creates a checkout of the specific tagged version.

    Args:
        plugin_name (str): Name of the plugin to update.

    Returns:
        str: Path to the release directory.
    """
    release_dir = get_plugin_release_dir(plugin_name)
    if not os.path.isdir(plugin_name):
        if plugin_name in ("bzr-svn", "bzr-rewrite"):
            # bzr-svn uses a different repo format
            call_or_fail([brz(), "init-shared-repo", "--rich-root-pack", plugin_name])
        else:
            os.mkdir(plugin_name)
    if os.path.isdir(release_dir):
        print(f"Removing existing dir: {release_dir}")
        shutil.rmtree(release_dir)
    # First update trunk
    trunk_dir = update_plugin_trunk(plugin_name)
    # Now create the tagged directory
    tag_name = _plugin_tag_name(plugin_name)
    print(f"Creating the branch {release_dir}")
    call_or_fail([brz(), "co", f"-rtag:{tag_name}", trunk_dir, release_dir])
    return release_dir


def install_plugin(plugin_name):
    """Install a plugin into the target build directory.

    Updates the plugin to the correct version and then runs its setup.py
    to install it into the target build directory.

    Args:
        plugin_name (str): Name of the plugin to install.
    """
    release_dir = update_plugin(plugin_name)
    # at least bzrtools doesn't like you to call 'setup.py' unless you are in
    # that directory specifically, so we cd, rather than calling it from
    # outside
    print(f"Installing {release_dir}")
    call_or_fail(
        [sys.executable, "setup.py", "install", "-O1", f"--install-lib={get_target()}"],
        cwd=release_dir,
    )


def update_tbzr():
    """Update TortoiseBZR to the latest version.

    Updates the TortoiseBZR installation located at the path specified
    by the TBZR environment variable.

    Raises:
        ValueError: If the TBZR environment variable is not set.
    """
    tbzr_loc = os.environ.get("TBZR", None)
    if tbzr_loc is None:
        raise ValueError("You must set TBZR to the location of tortoisebzr.")
    print(f"Updating {tbzr_loc}")
    call_or_fail([brz(), "update", tbzr_loc])


def build_installer():
    """Build the standalone Windows installer.

    Runs the make command to build the installer in the target directory
    using the configured Python interpreter.
    """
    target = get_target()
    print()
    print()
    print("*" * 60)
    print("Building standalone installer")
    call_or_fail(["make", f"PYTHON={PYTHON}", "installer"], cwd=target)


def main(args):
    """Main entry point for the build release script.

    Orchestrates the complete build process:
    1. Updates brz and TortoiseBZR
    2. Cleans and creates target directory
    3. Installs all configured plugins
    4. Builds the final installer

    Args:
        args (list): Command line arguments (currently unused).
    """
    import optparse

    p = optparse.OptionParser(usage="%prog [OPTIONS]")
    _opts, args = p.parse_args(args)

    update_brz()
    update_tbzr()
    clean_target()
    create_target()
    install_plugin("subvertpy")
    install_plugin("bzrtools")
    install_plugin("qbzr")
    install_plugin("bzr-svn")
    install_plugin("bzr-rewrite")

    build_installer()


if __name__ == "__main__":
    main(sys.argv[1:])

# vim: ts=4 sw=4 sts=4 et ai
