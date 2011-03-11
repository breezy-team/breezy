#    test_util.py -- Lookups via. launchpadlib
#    Copyright (C) 2009 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os

from bzrlib.config import config_dir
from bzrlib.trace import (
    mutter,
    note,
    )

try:
    from launchpadlib.launchpad import Launchpad
    from launchpadlib.credentials import Credentials
    from launchpadlib.uris import LPNET_SERVICE_ROOT
    HAVE_LPLIB = True
except ImportError:
    HAVE_LPLIB = False


def _get_launchpad():
    try:
        return Launchpad.login_with("bzr-builddeb", "production")
    except AttributeError: # older version of launchpadlib
        creds_path = os.path.join(config_dir(), "builddeb.lp_creds.txt")
        if not os.path.exists(creds_path):
            return None
        creds = Credentials("bzr-builddeb")
        f = open(creds_path)
        try:
            creds.load(f)
        finally:
            f.close()
        return Launchpad(creds, service_root=LPNET_SERVICE_ROOT)


def ubuntu_bugs_for_debian_bug(bug_id):
    if not HAVE_LPLIB:
        return []
    lp = _get_launchpad()
    if lp is None:
        return []
    try:
        bug = lp.load(str(lp._root_uri) + "bugs/bugtrackers/debbugs/%s")
        tasks = bug.bug_tasks
        for task in tasks:
            if task.bug_target_name.endswith("(Ubuntu)"):
                return str(bug.id)
    except Exception, e:
        mutter(str(e))
        return []
    return []


def debian_bugs_for_ubuntu_bug(bug_id):
    if not HAVE_LPLIB:
        return []
    lp = _get_launchpad()
    if lp is None:
        return []
    try:
        bug = lp.bugs[int(bug_id)]
        tasks = bug.bug_tasks
        for task in tasks:
            if task.bug_target_name.endswith("(Debian)"):
                watch = task.bug_watch
                if watch is None:
                    break
                return watch.remote_bug.encode("utf-8")
    except Exception, e:
        mutter(str(e))
        return []
    return []


def get_upstream_branch_url(package, distribution_name, distroseries_name):
    """Return the upstream branch URL based on a package in a distribution.

    :param distribution_name: Distribution name
    :param package: Source package name
    :param distroseries_name: Distroseries name
    """
    if not HAVE_LPLIB:
        return None
    lp = _get_launchpad()
    if lp is None:
        return None
    distribution = lp.distributions[distribution_name]
    if distribution is None:
        note("Launchpad: No such distribution %s" % distribution)
        return None
    distroseries = distribution.getSeries(name_or_version=distroseries_name)
    if distroseries is None:
        note("%s: No such distroseries %s" % (distribution_name, distroseries_name))
        return None
    sourcepackage = distroseries.getSourcePackage(name=package)
    if sourcepackage is None:
        note("%s: Source package %s not found in %s" % (distribution_name, package,
            sourcepackage))
        return None
    productseries = sourcepackage.productseries
    if productseries is None:
        note("%s: Source package %s in %s not linked to a product series" % (
            distribution_name, package, sourcepackage))
        return None
    branch = productseries.branch
    if branch is None:
        note(("%s: upstream product series %s for source package %s does not have "
             "a branch") % (distribution_name, distroseries, package))
        return None
    return branch.bzr_identity
