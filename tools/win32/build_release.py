#!/cygdrive/C/Python25/python
"""A script to help automate the build process."""

# When preparing a new release, make sure to set all of these to the latest
# values.
VERSIONS = {
    'brz': '1.17',
    'qbzr': '0.12',
    'bzrtools': '1.17.0',
    'bzr-svn': '0.6.3',
    'bzr-rewrite': '0.5.2',
    'subvertpy': '0.6.8',
}

# This will be passed to 'make' to ensure we build with the right python
PYTHON = '/cygdrive/c/Python25/python'

# Create the final build in this directory
TARGET_ROOT = 'release'

DEBUG_SUBPROCESS = True


import os
import shutil
import subprocess
import sys


BRZ_EXE = None
def brz():
    global BRZ_EXE
    if BRZ_EXE is not None:
        return BRZ_EXE
    try:
        subprocess.call(['brz', '--version'], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
        BRZ_EXE = 'brz'
    except OSError:
        try:
            subprocess.call(['brz.bat', '--version'], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
            BRZ_EXE = 'brz.bat'
        except OSError:
            raise RuntimeError('Could not find brz or brz.bat on your path.')
    return BRZ_EXE


def call_or_fail(*args, **kwargs):
    """Call a subprocess, and fail if the return code is not 0."""
    if DEBUG_SUBPROCESS:
        print('  calling: "%s"' % (' '.join(args[0]),))
    p = subprocess.Popen(*args, **kwargs)
    (out, err) = p.communicate()
    if p.returncode != 0:
        raise RuntimeError('Failed to run: %s, %s' % (args, kwargs))
    return out


TARGET = None
def get_target():
    global TARGET
    if TARGET is not None:
        return TARGET
    out = call_or_fail([get_brz_dir() + '/brz',
                        'version', '--short'], stdout=subprocess.PIPE)
    version = out.strip()
    TARGET = os.path.abspath(TARGET_ROOT + '-' + version)
    return TARGET


def clean_target():
    """Nuke the target directory so we know we are starting from scratch."""
    target = get_target()
    if os.path.isdir(target):
        print("Deleting: %s" % (target,))
        shutil.rmtree(target)

def get_brz_dir():
    return 'brz.' + VERSIONS['brz']


def update_brz():
    """Make sure we have the latest brz in play."""
    brz_dir = get_brz_dir()
    if not os.path.isdir(brz_dir):
        brz_version = VERSIONS['brz']
        brz_url = 'lp:brz/' + brz_version
        print("Getting brz release %s from %s" % (brz_version, brz_url))
        call_or_fail([brz(), 'co', brz_url, brz_dir])
    else:
        print("Ensuring %s is up-to-date" % (brz_dir,))
        call_or_fail([brz(), 'update', brz_dir])


def create_target():
    target = get_target()
    print("Creating target dir: %s" % (target,))
    call_or_fail([brz(), 'co', get_brz_dir(), target])


def get_plugin_trunk_dir(plugin_name):
    return '%s/trunk' % (plugin_name,)


def get_plugin_release_dir(plugin_name):
    return '%s/%s' % (plugin_name, VERSIONS[plugin_name])


def get_plugin_trunk_branch(plugin_name):
    return 'lp:%s' % (plugin_name,)


def update_plugin_trunk(plugin_name):
    trunk_dir = get_plugin_trunk_dir(plugin_name)
    if not os.path.isdir(trunk_dir):
        plugin_trunk = get_plugin_trunk_branch(plugin_name)
        print("Getting latest %s trunk" % (plugin_name,))
        call_or_fail([brz(), 'co', plugin_trunk,
                      trunk_dir])
    else:
        print("Ensuring %s is up-to-date" % (trunk_dir,))
        call_or_fail([brz(), 'update', trunk_dir])
    return trunk_dir


def _plugin_tag_name(plugin_name):
    if plugin_name in ('bzr-svn', 'bzr-rewrite', 'subvertpy'):
        return '%s-%s' % (plugin_name, VERSIONS[plugin_name])
    # bzrtools and qbzr use 'release-X.Y.Z'
    return 'release-' + VERSIONS[plugin_name]


def update_plugin(plugin_name):
    release_dir = get_plugin_release_dir(plugin_name)
    if not os.path.isdir(plugin_name):
        if plugin_name in ('bzr-svn', 'bzr-rewrite'):
            # bzr-svn uses a different repo format
            call_or_fail(
                [brz(), 'init-shared-repo', '--rich-root-pack', plugin_name])
        else:
            os.mkdir(plugin_name)
    if os.path.isdir(release_dir):
        print("Removing existing dir: %s" % (release_dir,))
        shutil.rmtree(release_dir)
    # First update trunk
    trunk_dir = update_plugin_trunk(plugin_name)
    # Now create the tagged directory
    tag_name = _plugin_tag_name(plugin_name)
    print("Creating the branch %s" % (release_dir,))
    call_or_fail([brz(), 'co', '-rtag:%s' % (tag_name,),
                  trunk_dir, release_dir])
    return release_dir


def install_plugin(plugin_name):
    release_dir = update_plugin(plugin_name)
    # at least bzrtools doesn't like you to call 'setup.py' unless you are in
    # that directory specifically, so we cd, rather than calling it from
    # outside
    print("Installing %s" % (release_dir,))
    call_or_fail([sys.executable, 'setup.py', 'install', '-O1',
                  '--install-lib=%s' % (get_target(),)],
                 cwd=release_dir)


def update_tbzr():
    tbzr_loc = os.environ.get('TBZR', None)
    if tbzr_loc is None:
        raise ValueError('You must set TBZR to the location of tortoisebzr.')
    print('Updating %s' % (tbzr_loc,))
    call_or_fail([brz(), 'update', tbzr_loc])


def build_installer():
    target = get_target()
    print()
    print()
    print('*' * 60)
    print('Building standalone installer')
    call_or_fail(['make', 'PYTHON=%s' % (PYTHON,), 'installer'],
                 cwd=target)


def main(args):
    import optparse

    p = optparse.OptionParser(usage='%prog [OPTIONS]')
    opts, args = p.parse_args(args)

    update_brz()
    update_tbzr()
    clean_target()
    create_target()
    install_plugin('subvertpy')
    install_plugin('bzrtools')
    install_plugin('qbzr')
    install_plugin('bzr-svn')
    install_plugin('bzr-rewrite')

    build_installer()


if __name__ == '__main__':
    main(sys.argv[1:])

# vim: ts=4 sw=4 sts=4 et ai
