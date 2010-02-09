try:
    import hashlib as md5
except ImportError:
    import md5
import os
import shutil

from bzrlib import (
    bzrdir,
    transport,
    workingtree,
    )
from bzrlib import errors as bzr_errors

from bzrlib.plugins.builddeb import (
    default_orig_dir,
    import_dsc,
    util,
    )


def _get_tree(package_name):
    try:
        tree = workingtree.WorkingTree.open_containing(".")[0]
    except bzr_errors.NotBranchError:
        if os.path.exists(package_name):
            raise bzr_errors.BzrCommandError("Either run the command from an "
                    "existing branch of upstream, or move %s aside "
                    "and a new branch will be created there."
                    % package_name)
        to_transport = transport.get_transport(package_name)
        tree = to_transport.ensure_base()
        try:
            a_bzrdir = bzrdir.BzrDir.open_from_transport(to_transport)
        except bzr_errors.NotBranchError:
            # really a NotBzrDir error...
            create_branch = bzrdir.BzrDir.create_branch_convenience
            branch = create_branch(to_transport.base,
                                   possible_transports=[to_transport])
            a_bzrdir = branch.bzrdir
        else:
            if a_bzrdir.has_branch():
                raise bzr_errors.AlreadyBranchError(package_name)
            branch = a_bzrdir.create_branch()
            a_bzrdir.create_workingtree()
        try:
            tree = a_bzrdir.open_workingtree()
        except bzr_errors.NoWorkingTree:
            tree = a_bzrdir.create_workingtree()
    return tree


def _get_tarball(tree, tarball, package_name, version):
    from bzrlib.plugins.builddeb.repack_tarball import repack_tarball
    config = util.debuild_config(tree, tree, False)
    orig_dir = config.orig_dir or default_orig_dir
    orig_dir = os.path.join(tree.basedir, orig_dir)
    if not os.path.exists(orig_dir):
        os.makedirs(orig_dir)
    dest_name = util.tarball_name(package_name, version)
    tarball_filename = os.path.join(orig_dir, dest_name)
    repack_tarball(tarball, dest_name, target_dir=orig_dir)
    m = md5.md5()
    m.update(open(tarball_filename).read())
    md5sum = m.hexdigest()
    return tarball_filename, md5sum


def import_upstream(tarball, package_name, version):
    tree = _get_tree(package_name)
    parents = [tree.branch.last_revision()]
    tarball_filename, md5sum = _get_tarball(tree, tarball,
            package_name, version)
    db = import_dsc.DistributionBranch(tree.branch, tree.branch, tree=tree,
            upstream_tree=tree)
    dbs = import_dsc.DistributionBranchSet()
    dbs.add_branch(db)
    tarball_dir = db._extract_tarball_to_tempdir(tarball_filename)
    try:
        db.import_upstream(tarball_dir, version, md5sum, parents,
                upstream_tarball=tarball_filename)
    finally:
        shutil.rmtree(tarball_dir)
    return tree
