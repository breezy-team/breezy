# Copyright (C) 2006-2011 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""A collection of extra help information for using brz.

Help topics are meant to be help for items that aren't commands, but will
help brz become fully learnable without referring to a tutorial.

Limited formatting of help text is permitted to make the text useful
both within the reference manual (reStructuredText) and on the screen.
The help text should be reStructuredText with formatting kept to a
minimum and, in particular, no headings. The onscreen renderer applies
the following simple rules before rendering the text:

    1. A '::' appearing on the end of a line is replaced with ':'.
    2. Lines starting with a ':' have it stripped.

These rules mean that literal blocks and field lists respectively can
be used in the help text, producing sensible input to a manual while
rendering on the screen naturally.
"""

import breezy
from breezy import (
    config,
    osutils,
    registry,
    i18n,
    )


# Section identifiers (map topics to the right place in the manual)
SECT_COMMAND = "command"
SECT_CONCEPT = "concept"
SECT_HIDDEN = "hidden"
SECT_LIST = "list"
SECT_PLUGIN = "plugin"


class HelpTopicRegistry(registry.Registry):
    """A Registry customized for handling help topics."""

    def register(self, topic, detail, summary, section=SECT_LIST):
        """Register a new help topic.

        :param topic: Name of documentation entry
        :param detail: Function or string object providing detailed
            documentation for topic.  Function interface is detail(topic).
            This should return a text string of the detailed information.
            See the module documentation for details on help text formatting.
        :param summary: String providing single-line documentation for topic.
        :param section: Section in reference manual - see SECT_* identifiers.
        """
        # The detail is stored as the 'object' and the metadata as the info
        info = (summary, section)
        super(HelpTopicRegistry, self).register(topic, detail, info=info)

    def register_lazy(self, topic, module_name, member_name, summary,
                      section=SECT_LIST):
        """Register a new help topic, and import the details on demand.

        :param topic: Name of documentation entry
        :param module_name: The module to find the detailed help.
        :param member_name: The member of the module to use for detailed help.
        :param summary: String providing single-line documentation for topic.
        :param section: Section in reference manual - see SECT_* identifiers.
        """
        # The detail is stored as the 'object' and the metadata as the info
        info = (summary, section)
        super(HelpTopicRegistry, self).register_lazy(topic, module_name,
                                                     member_name, info=info)

    def get_detail(self, topic):
        """Get the detailed help on a given topic."""
        obj = self.get(topic)
        if callable(obj):
            return obj(topic)
        else:
            return obj

    def get_summary(self, topic):
        """Get the single line summary for the topic."""
        info = self.get_info(topic)
        if info is None:
            return None
        else:
            return info[0]

    def get_section(self, topic):
        """Get the section for the topic."""
        info = self.get_info(topic)
        if info is None:
            return None
        else:
            return info[1]

    def get_topics_for_section(self, section):
        """Get the set of topics in a section."""
        result = set()
        for topic in self.keys():
            if section == self.get_section(topic):
                result.add(topic)
        return result


topic_registry = HelpTopicRegistry()


# ----------------------------------------------------

def _help_on_topics(dummy):
    """Write out the help for topics to outfile"""

    topics = topic_registry.keys()
    lmax = max(len(topic) for topic in topics)

    out = []
    for topic in topics:
        summary = topic_registry.get_summary(topic)
        out.append("%-*s %s\n" % (lmax, topic, summary))
    return ''.join(out)


def _load_from_file(topic_name):
    """Load help from a file.

    Topics are expected to be txt files in breezy.help_topics.
    """
    resource_name = osutils.pathjoin("en", "%s.txt" % (topic_name,))
    return osutils.resource_string('breezy.help_topics', resource_name)


def _help_on_revisionspec(name):
    """Generate the help for revision specs."""
    import re
    import breezy.revisionspec

    out = []
    out.append(
        """Revision Identifiers

A revision identifier refers to a specific state of a branch's history.  It
can be expressed in several ways.  It can begin with a keyword to
unambiguously specify a given lookup type; some examples are 'last:1',
'before:yesterday' and 'submit:'.

Alternately, it can be given without a keyword, in which case it will be
checked as a revision number, a tag, a revision id, a date specification, or a
branch specification, in that order.  For example, 'date:today' could be
written as simply 'today', though if you have a tag called 'today' that will
be found first.

If 'REV1' and 'REV2' are revision identifiers, then 'REV1..REV2' denotes a
revision range. Examples: '3647..3649', 'date:yesterday..-1' and
'branch:/path/to/branch1/..branch:/branch2' (note that there are no quotes or
spaces around the '..').

Ranges are interpreted differently by different commands. To the "log" command,
a range is a sequence of log messages, but to the "diff" command, the range
denotes a change between revisions (and not a sequence of changes).  In
addition, "log" considers a closed range whereas "diff" and "merge" consider it
to be open-ended, that is, they include one end but not the other.  For example:
"brz log -r 3647..3649" shows the messages of revisions 3647, 3648 and 3649,
while "brz diff -r 3647..3649" includes the changes done in revisions 3648 and
3649, but not 3647.

The keywords used as revision selection methods are the following:
""")
    details = []
    details.append("\nIn addition, plugins can provide other keywords.")
    details.append(
        "\nA detailed description of each keyword is given below.\n")

    # The help text is indented 4 spaces - this re cleans that up below
    indent_re = re.compile(r'^    ', re.MULTILINE)
    for prefix, i in breezy.revisionspec.revspec_registry.iteritems():
        doc = i.help_txt
        if doc == breezy.revisionspec.RevisionSpec.help_txt:
            summary = "N/A"
            doc = summary + "\n"
        else:
            # Extract out the top line summary from the body and
            # clean-up the unwanted whitespace
            summary, doc = doc.split("\n", 1)
            #doc = indent_re.sub('', doc)
            while (doc[-2:] == '\n\n' or doc[-1:] == ' '):
                doc = doc[:-1]

        # Note: The leading : here are HACKs to get reStructuredText
        # 'field' formatting - we know that the prefix ends in a ':'.
        out.append(":%s\n\t%s" % (i.prefix, summary))
        details.append(":%s\n%s" % (i.prefix, doc))

    return '\n'.join(out + details)


def _help_on_transport(name):
    from breezy.transport import (
        transport_list_registry,
    )
    import textwrap

    def add_string(proto, help, maxl, prefix_width=20):
        help_lines = textwrap.wrap(help, maxl - prefix_width,
                                   break_long_words=False)
        line_with_indent = '\n' + ' ' * prefix_width
        help_text = line_with_indent.join(help_lines)
        return "%-20s%s\n" % (proto, help_text)

    def key_func(a):
        return a[:a.rfind("://")]

    protl = []
    decl = []
    protos = transport_list_registry.keys()
    protos.sort(key=key_func)
    for proto in protos:
        shorthelp = transport_list_registry.get_help(proto)
        if not shorthelp:
            continue
        if proto.endswith("://"):
            protl.append(add_string(proto, shorthelp, 79))
        else:
            decl.append(add_string(proto, shorthelp, 79))

    out = "URL Identifiers\n\n" + \
        "Supported URL prefixes::\n\n  " + \
        '  '.join(protl)

    if len(decl):
        out += "\nSupported modifiers::\n\n  " + \
            '  '.join(decl)

    out += """\
\nBreezy supports all of the standard parts within the URL::

  <protocol>://[user[:password]@]host[:port]/[path]

allowing URLs such as::

  http://brzuser:BadPass@brz.example.com:8080/brz/trunk

For brz+ssh:// and sftp:// URLs, Breezy also supports paths that begin
with '~' as meaning that the rest of the path should be interpreted
relative to the remote user's home directory.  For example if the user
``remote`` has a  home directory of ``/home/remote`` on the server
shell.example.com, then::

  brz+ssh://remote@shell.example.com/~/myproject/trunk

would refer to ``/home/remote/myproject/trunk``.

Many commands that accept URLs also accept location aliases too.
See :doc:`location-alias-help` and :doc:`url-special-chars-help`.
"""

    return out


_basic_help = \
    """Breezy %s -- a free distributed version-control tool
https://www.breezy-vcs.org/

Basic commands:
  brz init           makes this directory a versioned branch
  brz branch         make a copy of another branch

  brz add            make files or directories versioned
  brz ignore         ignore a file or pattern
  brz mv             move or rename a versioned file

  brz status         summarize changes in working copy
  brz diff           show detailed diffs

  brz merge          pull in changes from another branch
  brz commit         save some or all changes
  brz send           send changes via email

  brz log            show history of changes
  brz check          validate storage

  brz help init      more help on e.g. init command
  brz help commands  list all commands
  brz help topics    list all help topics
""" % breezy.__version__


_global_options = \
    """Global Options

These options may be used with any command, and may appear in front of any
command.  (e.g. ``brz --profile help``).

--version      Print the version number. Must be supplied before the command.
--no-aliases   Do not process command aliases when running this command.
--builtin      Use the built-in version of a command, not the plugin version.
               This does not suppress other plugin effects.
--no-plugins   Do not process any plugins.
--no-l10n      Do not translate messages.
--concurrency  Number of processes that can be run concurrently (selftest).

--profile      Profile execution using the hotshot profiler.
--lsprof       Profile execution using the lsprof profiler.
--lsprof-file  Profile execution using the lsprof profiler, and write the
               results to a specified file.  If the filename ends with ".txt",
               text format will be used.  If the filename either starts with
               "callgrind.out" or end with ".callgrind", the output will be
               formatted for use with KCacheGrind. Otherwise, the output
               will be a pickle.
--coverage     Generate line coverage report in the specified directory.

-Oname=value   Override the ``name`` config option setting it to ``value`` for
               the duration of the command.  This can be used multiple times if
               several options need to be overridden.

See https://www.breezy-vcs.org/developers/profiling.html for more
information on profiling.

A number of debug flags are also available to assist troubleshooting and
development.  See :doc:`debug-flags-help`.
"""

_standard_options = \
    """Standard Options

Standard options are legal for all commands.

--help, -h     Show help message.
--verbose, -v  Display more information.
--quiet, -q    Only display errors and warnings.

Unlike global options, standard options can be used in aliases.
"""


_checkouts = \
    """Checkouts

Checkouts are source trees that are connected to a branch, so that when
you commit in the source tree, the commit goes into that branch.  They
allow you to use a simpler, more centralized workflow, ignoring some of
Breezy's decentralized features until you want them. Using checkouts
with shared repositories is very similar to working with SVN or CVS, but
doesn't have the same restrictions.  And using checkouts still allows
others working on the project to use whatever workflow they like.

A checkout is created with the brz checkout command (see "help checkout").
You pass it a reference to another branch, and it will create a local copy
for you that still contains a reference to the branch you created the
checkout from (the master branch). Then if you make any commits they will be
made on the other branch first. This creates an instant mirror of your work, or
facilitates lockstep development, where each developer is working together,
continuously integrating the changes of others.

However the checkout is still a first class branch in Breezy terms, so that
you have the full history locally.  As you have a first class branch you can
also commit locally if you want, for instance due to the temporary loss af a
network connection. Use the --local option to commit to do this. All the local
commits will then be made on the master branch the next time you do a non-local
commit.

If you are using a checkout from a shared branch you will periodically want to
pull in all the changes made by others. This is done using the "update"
command. The changes need to be applied before any non-local commit, but
Breezy will tell you if there are any changes and suggest that you use this
command when needed.

It is also possible to create a "lightweight" checkout by passing the
--lightweight flag to checkout. A lightweight checkout is even closer to an
SVN checkout in that it is not a first class branch, it mainly consists of the
working tree. This means that any history operations must query the master
branch, which could be slow if a network connection is involved. Also, as you
don't have a local branch, then you cannot commit locally.

Lightweight checkouts work best when you have fast reliable access to the
master branch. This means that if the master branch is on the same disk or LAN
a lightweight checkout will be faster than a heavyweight one for any commands
that modify the revision history (as only one copy of the branch needs to
be updated). Heavyweight checkouts will generally be faster for any command
that uses the history but does not change it, but if the master branch is on
the same disk then there won't be a noticeable difference.

Another possible use for a checkout is to use it with a treeless repository
containing your branches, where you maintain only one working tree by
switching the master branch that the checkout points to when you want to
work on a different branch.

Obviously to commit on a checkout you need to be able to write to the master
branch. This means that the master branch must be accessible over a writeable
protocol , such as sftp://, and that you have write permissions at the other
end. Checkouts also work on the local file system, so that all that matters is
file permissions.

You can change the master of a checkout by using the "switch" command (see
"help switch").  This will change the location that the commits are sent to.
The "bind" command can also be used to turn a normal branch into a heavy
checkout. If you would like to convert your heavy checkout into a normal
branch so that every commit is local, you can use the "unbind" command. To see
whether or not a branch is bound or not you can use the "info" command. If the
branch is bound it will tell you the location of the bound branch.

Related commands::

  checkout    Create a checkout. Pass --lightweight to get a lightweight
              checkout
  update      Pull any changes in the master branch in to your checkout
  commit      Make a commit that is sent to the master branch. If you have
              a heavy checkout then the --local option will commit to the
              checkout without sending the commit to the master
  switch      Change the master branch that the commits in the checkout will
              be sent to
  bind        Turn a standalone branch into a heavy checkout so that any
              commits will be sent to the master branch
  unbind      Turn a heavy checkout into a standalone branch so that any
              commits are only made locally
  info        Displays whether a branch is bound or unbound. If the branch is
              bound, then it will also display the location of the bound branch
"""

_repositories = \
    """Repositories

Repositories in Breezy are where committed information is stored. There is
a repository associated with every branch.

Repositories are a form of database. Breezy will usually maintain this for
good performance automatically, but in some situations (e.g. when doing
very many commits in a short time period) you may want to ask brz to
optimise the database indices. This can be done by the 'brz pack' command.

By default just running 'brz init' will create a repository within the new
branch but it is possible to create a shared repository which allows multiple
branches to share their information in the same location. When a new branch is
created it will first look to see if there is a containing shared repository it
can use.

When two branches of the same project share a repository, there is
generally a large space saving. For some operations (e.g. branching
within the repository) this translates in to a large time saving.

To create a shared repository use the init-shared-repository command (or the
alias init-shared-repo). This command takes the location of the repository to
create. This means that 'brz init-shared-repository repo' will create a
directory named 'repo', which contains a shared repository. Any new branches
that are created in this directory will then use it for storage.

It is a good idea to create a repository whenever you might create more
than one branch of a project. This is true for both working areas where you
are doing the development, and any server areas that you use for hosting
projects. In the latter case, it is common to want branches without working
trees. Since the files in the branch will not be edited directly there is no
need to use up disk space for a working tree. To create a repository in which
the branches will not have working trees pass the '--no-trees' option to
'init-shared-repository'.

Related commands::

  init-shared-repository   Create a shared repository. Use --no-trees to create
                           one in which new branches won't get a working tree.
"""


_working_trees = \
    """Working Trees

A working tree is the contents of a branch placed on disk so that you can
see the files and edit them. The working tree is where you make changes to a
branch, and when you commit the current state of the working tree is the
snapshot that is recorded in the commit.

When you push a branch to a remote system, a working tree will not be
created. If one is already present the files will not be updated. The
branch information will be updated and the working tree will be marked
as out-of-date. Updating a working tree remotely is difficult, as there
may be uncommitted changes or the update may cause content conflicts that are
difficult to deal with remotely.

If you have a branch with no working tree you can use the 'checkout' command
to create a working tree. If you run 'brz checkout .' from the branch it will
create the working tree. If the branch is updated remotely, you can update the
working tree by running 'brz update' in that directory.

If you have a branch with a working tree that you do not want the 'remove-tree'
command will remove the tree if it is safe. This can be done to avoid the
warning about the remote working tree not being updated when pushing to the
branch. It can also be useful when working with a '--no-trees' repository
(see 'brz help repositories').

If you want to have a working tree on a remote machine that you push to you
can either run 'brz update' in the remote branch after each push, or use some
other method to update the tree during the push. There is an 'rspush' plugin
that will update the working tree using rsync as well as doing a push. There
is also a 'push-and-update' plugin that automates running 'brz update' via SSH
after each push.

Useful commands::

  checkout     Create a working tree when a branch does not have one.
  remove-tree  Removes the working tree from a branch when it is safe to do so.
  update       When a working tree is out of sync with its associated branch
               this will update the tree to match the branch.
"""


_branches = \
    """Branches

A branch consists of the state of a project, including all of its
history. All branches have a repository associated (which is where the
branch history is stored), but multiple branches may share the same
repository (a shared repository). Branches can be copied and merged.

In addition, one branch may be bound to another one.  Binding to another
branch indicates that commits which happen in this branch must also
happen in the other branch.  Breezy ensures consistency by not allowing
commits when the two branches are out of date.  In order for a commit
to succeed, it may be necessary to update the current branch using
``brz update``.

Related commands::

  init    Change a directory into a versioned branch.
  branch  Create a new branch that is a copy of an existing branch.
  merge   Perform a three-way merge.
  bind    Bind a branch to another one.
"""


_standalone_trees = \
    """Standalone Trees

A standalone tree is a working tree with an associated repository. It
is an independently usable branch, with no dependencies on any other.
Creating a standalone tree (via brz init) is the quickest way to put
an existing project under version control.

Related Commands::

  init    Make a directory into a versioned branch.
"""


_status_flags = \
    """Status Flags

Status flags are used to summarise changes to the working tree in a concise
manner.  They are in the form::

   xxx   <filename>

where the columns' meanings are as follows.

Column 1 - versioning/renames::

  + File versioned
  - File unversioned
  R File renamed
  ? File unknown
  X File nonexistent (and unknown to brz)
  C File has conflicts
  P Entry for a pending merge (not a file)

Column 2 - contents::

  N File created
  D File deleted
  K File kind changed
  M File modified

Column 3 - execute::

  * The execute bit was changed
"""


known_env_variables = [
    ("BRZPATH", "Path where brz is to look for shell plugin external commands."),
    ("BRZ_EMAIL", "E-Mail address of the user. Overrides EMAIL."),
    ("EMAIL", "E-Mail address of the user."),
    ("BRZ_EDITOR", "Editor for editing commit messages. Overrides EDITOR."),
    ("EDITOR", "Editor for editing commit messages."),
    ("BRZ_PLUGIN_PATH", "Paths where brz should look for plugins."),
    ("BRZ_DISABLE_PLUGINS", "Plugins that brz should not load."),
    ("BRZ_PLUGINS_AT", "Plugins to load from a directory not in BRZ_PLUGIN_PATH."),
    ("BRZ_HOME", "Directory holding breezy config dir. Overrides HOME."),
    ("BRZ_HOME (Win32)", "Directory holding breezy config dir. Overrides APPDATA and HOME."),
    ("BZR_REMOTE_PATH", "Full name of remote 'brz' command (for brz+ssh:// URLs)."),
    ("BRZ_SSH", "Path to SSH client, or one of paramiko, openssh, sshcorp, plink or lsh."),
    ("BRZ_LOG", "Location of brz.log (use '/dev/null' to suppress log)."),
    ("BRZ_LOG (Win32)", "Location of brz.log (use 'NUL' to suppress log)."),
    ("BRZ_COLUMNS", "Override implicit terminal width."),
    ("BRZ_CONCURRENCY", "Number of processes that can be run concurrently (selftest)"),
    ("BRZ_PROGRESS_BAR", "Override the progress display. Values are 'none' or 'text'."),
    ("BRZ_PDB", "Control whether to launch a debugger on error."),
    ("BRZ_SIGQUIT_PDB",
     "Control whether SIGQUIT behaves normally or invokes a breakin debugger."),
    ("BRZ_TEXTUI_INPUT",
     "Force console input mode for prompts to line-based (instead of char-based)."),
    ]


def _env_variables(topic):
    import textwrap
    ret = ["Environment Variables\n\n"
           "See brz help configuration for more details.\n\n"]
    max_key_len = max([len(k[0]) for k in known_env_variables])
    desc_len = (80 - max_key_len - 2)
    ret.append("=" * max_key_len + " " + "=" * desc_len + "\n")
    for k, desc in known_env_variables:
        ret.append(k + (max_key_len + 1 - len(k)) * " ")
        ret.append("\n".join(textwrap.wrap(
            desc, width=desc_len, subsequent_indent=" " * (max_key_len + 1))))
        ret.append("\n")
    ret += "=" * max_key_len + " " + "=" * desc_len + "\n"
    return "".join(ret)


_files = \
    r"""Files

:On Unix:   ~/.config/breezy/breezy.conf
:On Windows: %APPDATA%\\breezy\\breezy.conf

Contains the user's default configuration. The section ``[DEFAULT]`` is
used to define general configuration that will be applied everywhere.
The section ``[ALIASES]`` can be used to create command aliases for
commonly used options.

A typical config file might look something like::

  [DEFAULT]
  email=John Doe <jdoe@isp.com>

  [ALIASES]
  commit = commit --strict
  log10 = log --short -r -10..-1
"""

_criss_cross = \
    """Criss-Cross

A criss-cross in the branch history can cause the default merge technique
to emit more conflicts than would normally be expected.

In complex merge cases, ``brz merge --lca`` or ``brz merge --weave`` may give
better results.  You may wish to ``brz revert`` the working tree and merge
again.  Alternatively, use ``brz remerge`` on particular conflicted files.

Criss-crosses occur in a branch's history if two branches merge the same thing
and then merge one another, or if two branches merge one another at the same
time.  They can be avoided by having each branch only merge from or into a
designated central branch (a "star topology").

Criss-crosses cause problems because of the way merge works.  Breezy's default
merge is a three-way merger; in order to merge OTHER into THIS, it must
find a basis for comparison, BASE.  Using BASE, it can determine whether
differences between THIS and OTHER are due to one side adding lines, or
from another side removing lines.

Criss-crosses mean there is no good choice for a base.  Selecting the recent
merge points could cause one side's changes to be silently discarded.
Selecting older merge points (which Breezy does) mean that extra conflicts
are emitted.

The ``weave`` merge type is not affected by this problem because it uses
line-origin detection instead of a basis revision to determine the cause of
differences.
"""

_branches_out_of_sync = """Branches Out of Sync

When reconfiguring a checkout, tree or branch into a lightweight checkout,
a local branch must be destroyed.  (For checkouts, this is the local branch
that serves primarily as a cache.)  If the branch-to-be-destroyed does not
have the same last revision as the new reference branch for the lightweight
checkout, data could be lost, so Breezy refuses.

How you deal with this depends on *why* the branches are out of sync.

If you have a checkout and have done local commits, you can get back in sync
by running "brz update" (and possibly "brz commit").

If you have a branch and the remote branch is out-of-date, you can push
the local changes using "brz push".  If the local branch is out of date, you
can do "brz pull".  If both branches have had changes, you can merge, commit
and then push your changes.  If you decide that some of the changes aren't
useful, you can "push --overwrite" or "pull --overwrite" instead.
"""


_storage_formats = \
    """Storage Formats

To ensure that older clients do not access data incorrectly,
Breezy's policy is to introduce a new storage format whenever
new features requiring new metadata are added. New storage
formats may also be introduced to improve performance and
scalability.

The newest format, 2a, is highly recommended. If your
project is not using 2a, then you should suggest to the
project owner to upgrade.


.. note::

   Some of the older formats have two variants:
   a plain one and a rich-root one. The latter include an additional
   field about the root of the tree. There is no performance cost
   for using a rich-root format but you cannot easily merge changes
   from a rich-root format into a plain format. As a consequence,
   moving a project to a rich-root format takes some co-ordination
   in that all contributors need to upgrade their repositories
   around the same time. 2a and all future formats will be
   implicitly rich-root.

See :doc:`current-formats-help` for the complete list of
currently supported formats. See :doc:`other-formats-help` for
descriptions of any available experimental and deprecated formats.
"""


# Register help topics
topic_registry.register("revisionspec", _help_on_revisionspec,
                        "Explain how to use --revision")
topic_registry.register('basic', _basic_help, "Basic commands", SECT_HIDDEN)
topic_registry.register('topics', _help_on_topics, "Topics list", SECT_HIDDEN)


def get_current_formats_topic(topic):
    from breezy import controldir
    return "Current Storage Formats\n\n" + \
        controldir.format_registry.help_topic(topic)


def get_other_formats_topic(topic):
    from breezy import controldir
    return "Other Storage Formats\n\n" + \
        controldir.format_registry.help_topic(topic)


topic_registry.register('current-formats', get_current_formats_topic,
                        'Current storage formats')
topic_registry.register('other-formats', get_other_formats_topic,
                        'Experimental and deprecated storage formats')
topic_registry.register('standard-options', _standard_options,
                        'Options that can be used with any command')
topic_registry.register('global-options', _global_options,
                        'Options that control how Breezy runs')
topic_registry.register('urlspec', _help_on_transport,
                        "Supported transport protocols")
topic_registry.register('status-flags', _status_flags,
                        "Help on status flags")


def get_bugs_topic(topic):
    from breezy import bugtracker
    return ("Bug Tracker Settings\n\n"
            + bugtracker.tracker_registry.help_topic(topic))


topic_registry.register('bugs', get_bugs_topic, 'Bug tracker settings')
topic_registry.register('env-variables', _env_variables,
                        'Environment variable names and values')
topic_registry.register('files', _files,
                        'Information on configuration and log files')
topic_registry.register_lazy('hooks', 'breezy.hooks', 'hooks_help_text',
                             'Points at which custom processing can be added')
topic_registry.register_lazy('location-alias', 'breezy.directory_service',
                             'AliasDirectory.help_text',
                             'Aliases for remembered locations')

# Load some of the help topics from files. Note that topics which reproduce API
# details will tend to skew (quickly usually!) so please seek other solutions
# for such things.
topic_registry.register('authentication', _load_from_file,
                        'Information on configuring authentication')
topic_registry.register('configuration', _load_from_file,
                        'Details on the configuration settings available')
topic_registry.register('conflict-types', _load_from_file,
                        'Types of conflicts and what to do about them')
topic_registry.register('debug-flags', _load_from_file,
                        'Options to show or record debug information')
topic_registry.register('glossary', _load_from_file, 'Glossary')
topic_registry.register('log-formats', _load_from_file,
                        'Details on the logging formats available')
topic_registry.register('missing-extensions', _load_from_file,
                        'What to do when compiled extensions are missing')
topic_registry.register('url-special-chars', _load_from_file,
                        'Special character handling in URLs')


# Register concept topics.
# Note that we might choose to remove these from the online help in the
# future or implement them via loading content from files. In the meantime,
# please keep them concise.
topic_registry.register('branches', _branches,
                        'Information on what a branch is', SECT_CONCEPT)
topic_registry.register('checkouts', _checkouts,
                        'Information on what a checkout is', SECT_CONCEPT)
topic_registry.register('content-filters', _load_from_file,
                        'Conversion of content into/from working trees',
                        SECT_CONCEPT)
topic_registry.register('diverged-branches', _load_from_file,
                        'How to fix diverged branches',
                        SECT_CONCEPT)
topic_registry.register('eol', _load_from_file,
                        'Information on end-of-line handling',
                        SECT_CONCEPT)
topic_registry.register('formats', _storage_formats,
                        'Information on choosing a storage format',
                        SECT_CONCEPT)
topic_registry.register('patterns', _load_from_file,
                        'Information on the pattern syntax',
                        SECT_CONCEPT)
topic_registry.register('repositories', _repositories,
                        'Basic information on shared repositories.',
                        SECT_CONCEPT)
topic_registry.register('rules', _load_from_file,
                        'Information on defining rule-based preferences',
                        SECT_CONCEPT)
topic_registry.register('standalone-trees', _standalone_trees,
                        'Information on what a standalone tree is',
                        SECT_CONCEPT)
topic_registry.register('working-trees', _working_trees,
                        'Information on working trees', SECT_CONCEPT)
topic_registry.register('criss-cross', _criss_cross,
                        'Information on criss-cross merging', SECT_CONCEPT)
topic_registry.register('sync-for-reconfigure', _branches_out_of_sync,
                        'Steps to resolve "out-of-sync" when reconfiguring',
                        SECT_CONCEPT)


class HelpTopicIndex(object):
    """A index for brz help that returns topics."""

    def __init__(self):
        self.prefix = ''

    def get_topics(self, topic):
        """Search for topic in the HelpTopicRegistry.

        :param topic: A topic to search for. None is treated as 'basic'.
        :return: A list which is either empty or contains a single
            RegisteredTopic entry.
        """
        if topic is None:
            topic = 'basic'
        if topic in topic_registry:
            return [RegisteredTopic(topic)]
        else:
            return []


def _format_see_also(see_also):
    result = ''
    if see_also:
        result += '\n:See also: '
        result += ', '.join(sorted(set(see_also)))
        result += '\n'
    return result


class RegisteredTopic(object):
    """A help topic which has been registered in the HelpTopicRegistry.

    These topics consist of nothing more than the name of the topic - all
    data is retrieved on demand from the registry.
    """

    def __init__(self, topic):
        """Constructor.

        :param topic: The name of the topic that this represents.
        """
        self.topic = topic

    def get_help_text(self, additional_see_also=None, plain=True):
        """Return a string with the help for this topic.

        :param additional_see_also: Additional help topics to be
            cross-referenced.
        :param plain: if False, raw help (reStructuredText) is
            returned instead of plain text.
        """
        result = topic_registry.get_detail(self.topic)
        result += _format_see_also(additional_see_also)
        if plain:
            result = help_as_plain_text(result)
        i18n.install()
        result = i18n.gettext_per_paragraph(result)
        return result

    def get_help_topic(self):
        """Return the help topic this can be found under."""
        return self.topic


def help_as_plain_text(text):
    """Minimal converter of reStructuredText to plain text."""
    import re
    # Remove the standalone code block marker
    text = re.sub(r"(?m)^\s*::\n\s*$", "", text)
    lines = text.splitlines()
    result = []
    for line in lines:
        if line.startswith(':'):
            line = line[1:]
        elif line.endswith('::'):
            line = line[:-1]
        # Map :doc:`xxx-help` to ``brz help xxx``
        line = re.sub(":doc:`(.+?)-help`", r'``brz help \1``', line)
        result.append(line)
    return "\n".join(result) + "\n"


class ConfigOptionHelpIndex(object):
    """A help index that returns help topics for config options."""

    def __init__(self):
        self.prefix = 'configuration/'

    def get_topics(self, topic):
        """Search for topic in the registered config options.

        :param topic: A topic to search for.
        :return: A list which is either empty or contains a single
            config.Option entry.
        """
        if topic is None:
            return []
        elif topic.startswith(self.prefix):
            topic = topic[len(self.prefix):]
        if topic in config.option_registry:
            return [config.option_registry.get(topic)]
        else:
            return []
