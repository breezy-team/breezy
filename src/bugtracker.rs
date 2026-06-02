//! Provides a shorthand for referring to bugs on a variety of bug trackers.
//!
//! 'commit --fixes' stores references to bugs as a <bug_url> -> <bug_status>
//! mapping in the properties for that revision.
//!
//! However, it's inconvenient to type out full URLs for bugs on the command line,
//! particularly given that many users will be using only a single bug tracker per
//! branch.
//!
//! Thus, this module provides a registry of types of bug tracker (e.g. Launchpad,
//! Trac). Given an abbreviated name (e.g. 'lp', 'twisted') and a branch with
//! configuration information, these tracker types can return an instance capable
//! of converting bug IDs into URLs.

const BUGS_HELP: &str = r#"\
When making a commit, metadata about bugs fixed by that change can be
recorded by using the ``--fixes`` option. For each bug marked as fixed, an
entry is included in the 'bugs' revision property stating '<url> <status>'.
(The only ``status`` value currently supported is ``fixed.``)

The ``--fixes`` option allows you to specify a bug tracker and a bug identifier
rather than a full URL. This looks like::

    bzr commit --fixes <tracker>:<id>

or::

    bzr commit --fixes <id>

where "<tracker>" is an identifier for the bug tracker, and "<id>" is the
identifier for that bug within the bugtracker, usually the bug number.
If "<tracker>" is not specified the ``bugtracker`` set in the branch
or global configuration is used.

Bazaar knows about a few bug trackers that have many users. If
you use one of these bug trackers then there is no setup required to
use this feature, you just need to know the tracker identifier to use.
These are the bugtrackers that are built in:

  ============================ ============ ============
  URL                          Abbreviation Example
  ============================ ============ ============
  https://bugs.launchpad.net/  lp           lp:12345
  http://bugs.debian.org/      deb          deb:12345
  http://bugzilla.gnome.org/   gnome        gnome:12345
  ============================ ============ ============

For the bug trackers not listed above configuration is required.
Support for generating the URLs for any project using Bugzilla or Trac
is built in, along with a template mechanism for other bugtrackers with
simple URL schemes. If your bug tracker can't be described by one
of the schemes described below then you can write a plugin to support
it.

If you use Bugzilla or Trac, then you only need to set a configuration
variable which contains the base URL of the bug tracker. These options
can go into ``breezy.conf``, ``branch.conf`` or into a branch-specific
configuration section in ``locations.conf``.  You can set up these values
for each of the projects you work on.

Note: As you provide a short name for each tracker, you can specify one or
more bugs in one or more trackers at commit time if you wish.

Launchpad
---------

Use ``bzr commit --fixes lp:2`` to record that this commit fixes bug 2.

bugzilla_<tracker>_url
----------------------

If present, the location of the Bugzilla bug tracker referred to by
<tracker>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    bugzilla_squid_url = http://bugs.squid-cache.org

would allow ``bzr commit --fixes squid:1234`` to mark Squid's bug 1234 as
fixed.

trac_<tracker>_url
------------------

If present, the location of the Trac instance referred to by
<tracker>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    trac_twisted_url = http://www.twistedmatrix.com/trac

would allow ``bzr commit --fixes twisted:1234`` to mark Twisted's bug 1234 as
fixed.

bugtracker_<tracker>_url
------------------------

If present, the location of a generic bug tracker instance referred to by
<tracker>. The location must contain an ``{id}`` placeholder,
which will be replaced by a specific bug ID. This option can then be used
together with ``bzr commit --fixes`` to mark bugs in that tracker as being
fixed by that commit. For example::

    bugtracker_python_url = http://bugs.python.org/issue{id}

would allow ``bzr commit --fixes python:1234`` to mark bug 1234 in Python's
Roundup bug tracker as fixed, or::

    bugtracker_cpan_url = http://rt.cpan.org/Public/Bug/Display.html?id={id}

would allow ``bzr commit --fixes cpan:1234`` to mark bug 1234 in CPAN's
RT bug tracker as fixed, or::

    bugtracker_hudson_url = http://issues.hudson-ci.org/browse/{id}

would allow ``bzr commit --fixes hudson:HUDSON-1234`` to mark bug HUDSON-1234
in Hudson's JIRA bug tracker as fixed.
"#;

inventory::submit! {
    crate::help::HelpTopic::new(
        crate::help::Section::List,
        "bugs",
        "Bug tracker settings",
        crate::help::HelpContents::Text(BUGS_HELP),
    )
}
