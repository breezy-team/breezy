#    __init__.py -- Quilt support for breezy
#
#    Breezy is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    Breezy is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Breezy; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Quilt patch integration.

This plugin adds support for three configuration options:

 * quilt.commit_policy
 * quilt.smart_merge
 * quilt.tree_policy

"""

from ... import trace
from ...errors import BzrError


class QuiltUnapplyError(BzrError):
    """Error raised when unable to unapply quilt patches.

    This exception is raised when the quilt patch unapplication process fails
    during merge operations or other quilt-related operations.
    """

    _fmt = "Unable to unapply quilt patches for %(kind)r tree: %(msg)s"

    def __init__(self, kind, msg):
        """Initialize a QuiltUnapplyError.

        Args:
            kind (str): The type of tree where unapplying failed (e.g., 'this', 'base', 'other').
            msg (str): The error message from the quilt operation, or None.
        """
        BzrError.__init__(self)
        self.kind = kind
        if msg is not None and msg.count("\n") == 1:
            msg = msg.strip()
        self.msg = msg


def pre_merge_quilt(merger):
    """Pre-merge hook that unapplies quilt patches to prevent spurious conflicts.

    This function is called before merge operations to temporarily unapply quilt
    patches from the working tree, base tree, and other tree involved in the merge.
    This helps prevent conflicts that would arise from patches being applied
    differently across the trees being merged.

    Args:
        merger: The merger object containing the trees to be merged and merge configuration.

    Raises:
        QuiltUnapplyError: If unapplying patches fails on any of the trees.
    """
    if getattr(merger, "_no_quilt_unapplying", False):
        return

    config = merger.working_tree.get_config_stack()
    merger.debuild_config = config
    if not config.get("quilt.smart_merge"):
        trace.mutter("skipping smart quilt merge, not enabled.")
        return

    if (
        not merger.other_tree.is_versioned(".pc")
        and not merger.this_tree.is_versioned(".pc")
        and not merger.working_tree.is_versioned(".pc")
    ):
        return

    from .quilt import QuiltError, QuiltPatches

    quilt = QuiltPatches(merger.working_tree)
    from .merge import tree_unapply_patches

    trace.note("Unapplying quilt patches to prevent spurious conflicts")
    merger._quilt_tempdirs = []
    merger._old_quilt_series = quilt.series()
    if merger._old_quilt_series:
        quilt.pop_all()
    try:
        merger.this_tree, this_dir = tree_unapply_patches(
            merger.this_tree, merger.this_branch, force=True
        )
    except QuiltError as e:
        raise QuiltUnapplyError("this", e.stderr) from e
    else:
        if this_dir is not None:
            merger._quilt_tempdirs.append(this_dir)
    try:
        merger.base_tree, base_dir = tree_unapply_patches(
            merger.base_tree, merger.this_branch, force=True
        )
    except QuiltError as e:
        raise QuiltUnapplyError("base", e.stderr) from e
    else:
        if base_dir is not None:
            merger._quilt_tempdirs.append(base_dir)
    other_branch = getattr(merger, "other_branch", None)
    if other_branch is None:
        other_branch = merger.this_branch
    try:
        merger.other_tree, other_dir = tree_unapply_patches(
            merger.other_tree, other_branch, force=True
        )
    except QuiltError as e:
        raise QuiltUnapplyError("other", e.stderr) from e
    else:
        if other_dir is not None:
            merger._quilt_tempdirs.append(other_dir)


def post_merge_quilt_cleanup(merger):
    """Post-merge hook that cleans up temporary directories and processes patches.

    This function is called after merge operations to clean up any temporary
    directories created during the pre-merge quilt processing and to apply
    the configured quilt tree policy for post-merge patch handling.

    Args:
        merger: The merger object that was used for the merge operation.
    """
    import shutil

    for dir in getattr(merger, "_quilt_tempdirs", []):
        shutil.rmtree(dir)
    config = merger.working_tree.get_config_stack()
    policy = config.get("quilt.tree_policy")
    if policy is None:
        return
    from .merge import post_process_quilt_patches

    post_process_quilt_patches(
        merger.working_tree, getattr(merger, "_old_quilt_series", []), policy
    )


def start_commit_check_quilt(tree):
    """start_commit hook which checks the state of quilt patches."""
    config = tree.get_config_stack()
    policy = config.get("quilt.commit_policy")
    from .merge import start_commit_quilt_patches
    from .wrapper import QuiltNotInstalled

    try:
        start_commit_quilt_patches(tree, policy)
    except QuiltNotInstalled:
        trace.warning("quilt not installed; not updating patches")


def post_build_tree_quilt(tree):
    """Post-build-tree hook that applies quilt patches according to tree policy.

    This function is called after tree building operations (like checkout or update)
    to apply quilt patches according to the configured quilt.tree_policy setting.

    Args:
        tree: The tree that was just built and may need patch processing.
    """
    config = tree.get_config_stack()
    policy = config.get("quilt.tree_policy")
    if policy is None:
        return
    from .merge import post_process_quilt_patches
    from .wrapper import QuiltNotInstalled

    try:
        post_process_quilt_patches(tree, [], policy)
    except QuiltNotInstalled:
        trace.warning("quilt not installed; not touching patches")


from ...hooks import install_lazy_named_hook

install_lazy_named_hook(
    "breezy.merge",
    "Merger.hooks",
    "pre_merge_quilt",
    pre_merge_quilt,
    "Quilt patch (un)applying",
)
install_lazy_named_hook(
    "breezy.mutabletree",
    "MutableTree.hooks",
    "start_commit",
    start_commit_check_quilt,
    "Check for (un)applied quilt patches",
)
install_lazy_named_hook(
    "breezy.merge",
    "Merger.hooks",
    "post_merge",
    post_merge_quilt_cleanup,
    "Cleaning up quilt temporary directories",
)
install_lazy_named_hook(
    "breezy.mutabletree",
    "MutableTree.hooks",
    "post_build_tree",
    post_build_tree_quilt,
    "Applying quilt patches.",
)


from ...config import Option, bool_from_store, option_registry

option_registry.register(
    Option(
        "quilt.smart_merge",
        default=True,
        from_unicode=bool_from_store,
        help="Unapply quilt patches before merging.",
    )
)


def policy_from_store(s):
    """Convert a string from configuration store to a valid quilt policy.

    Validates that the policy string is one of the allowed values for quilt
    commit and tree policies.

    Args:
        s (str): The policy string from configuration storage.

    Returns:
        str: The validated policy string.

    Raises:
        ValueError: If the policy string is not 'applied' or 'unapplied'.
    """
    if s not in ("applied", "unapplied"):
        raise ValueError(f"Invalid quilt.commit_policy: {s}")
    return s


option_registry.register(
    Option(
        "quilt.commit_policy",
        default=None,
        from_unicode=policy_from_store,
        help="Whether to apply or unapply all patches in commits.",
    )
)

option_registry.register(
    Option(
        "quilt.tree_policy",
        default=None,
        from_unicode=policy_from_store,
        help="Whether to apply or unapply all patches after checkout/update.",
    )
)


def load_tests(loader, basic_tests, pattern):
    """Load tests for the quilt plugin.

    This function is called by the test framework to discover and load
    tests for this plugin module.

    Args:
        loader: The test loader instance.
        basic_tests: The basic test suite to add tests to.
        pattern: Pattern for test discovery (unused).

    Returns:
        TestSuite: The test suite with quilt plugin tests added.
    """
    basic_tests.addTest(loader.loadTestsFromName(__name__ + ".tests"))
    return basic_tests
