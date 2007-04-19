# Copyright (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""A collection of extra help information for using bzr.

Help topics are meant to be help for items that aren't commands, but will
help bzr become fully learnable without referring to a tutorial.
"""

from bzrlib import registry


class HelpTopicRegistry(registry.Registry):
    """A Registry customized for handling help topics."""

    def register(self, topic, detail, summary):
        """Register a new help topic.

        :param topic: Name of documentation entry
        :param detail: Function or string object providing detailed
            documentation for topic.  Function interface is detail(topic).
            This should return a text string of the detailed information.
        :param summary: String providing single-line documentation for topic.
        """
        # The detail is stored as the 'object' and the 
        super(HelpTopicRegistry, self).register(topic, detail, info=summary)

    def register_lazy(self, topic, module_name, member_name, summary):
        """Register a new help topic, and import the details on demand.

        :param topic: Name of documentation entry
        :param module_name: The module to find the detailed help.
        :param member_name: The member of the module to use for detailed help.
        :param summary: String providing single-line documentation for topic.
        """
        super(HelpTopicRegistry, self).register_lazy(topic, module_name,
                                                     member_name, info=summary)

    def get_detail(self, topic):
        """Get the detailed help on a given topic."""
        obj = self.get(topic)
        if callable(obj):
            return obj(topic)
        else:
            return obj

    def get_summary(self, topic):
        """Get the single line summary for the topic."""
        return self.get_info(topic)


topic_registry = HelpTopicRegistry()


#----------------------------------------------------

def _help_on_topics(dummy):
    """Write out the help for topics to outfile"""

    topics = topic_registry.keys()
    lmax = max(len(topic) for topic in topics)
        
    out = []
    for topic in topics:
        summary = topic_registry.get_summary(topic)
        out.append("%-*s %s\n" % (lmax, topic, summary))
    return ''.join(out)


def _help_on_revisionspec(name):
    """"Write the summary help for all documented topics to outfile."""
    import bzrlib.revisionspec

    out = []
    out.append("\nRevision prefix specifier:"
               "\n--------------------------\n")

    for i in bzrlib.revisionspec.SPEC_TYPES:
        doc = i.help_txt
        if doc == bzrlib.revisionspec.RevisionSpec.help_txt:
            doc = "N/A\n"
        while (doc[-2:] == '\n\n' or doc[-1:] == ' '):
            doc = doc[:-1]

        out.append("  %s %s\n\n" % (i.prefix, doc))

    return ''.join(out)


_basic_help= \
"""Bazaar -- a free distributed version-control tool
http://bazaar-vcs.org/

Basic commands:
  bzr init           makes this directory a versioned branch
  bzr branch         make a copy of another branch

  bzr add            make files or directories versioned
  bzr ignore         ignore a file or pattern
  bzr mv             move or rename a versioned file

  bzr status         summarize changes in working copy
  bzr diff           show detailed diffs

  bzr merge          pull in changes from another branch
  bzr commit         save some or all changes

  bzr log            show history of changes
  bzr check          validate storage

  bzr help init      more help on e.g. init command
  bzr help commands  list all commands
  bzr help topics    list all help topics
"""


_global_options =\
"""Global Options

These options may be used with any command, and may appear in front of any
command.  (e.g. "bzr --quiet help").

--quiet        Suppress informational output; only print errors and warnings
--version      Print the version number

--no-aliases   Do not process command aliases when running this command
--builtin      Use the built-in version of a command, not the plugin version.
               This does not suppress other plugin effects
--no-plugins   Do not process any plugins

-Derror        Instead of normal error handling, always print a traceback on
               error.
--profile      Profile execution using the hotshot profiler
--lsprof       Profile execution using the lsprof profiler
--lsprof-file  Profile execution using the lsprof profiler, and write the
               results to a specified file.

Note: --version must be supplied before any command.
"""

_checkouts = \
"""Checkouts

Checkouts are source trees that are connected to a branch, so that when
you commit in the source tree, the commit goes into that branch.  They
allow you to use a simpler, more centralized workflow, ignoring some of
Bazaar's decentralized features until you want them. Using checkouts
with shared repositories is very similar to working with SVN or CVS, but
doesn't have the same restrictions.  And using checkouts still allows
others working on the project to use whatever workflow they like.

A checkout is created with the bzr checkout command (see "help checkout").
You pass it a reference to another branch, and it will create a local copy
for you that still contains a reference to the branch you created the
checkout from (the master branch). Then if you make any commits they will be
made on the other branch first. This creates an instant mirror of your work, or
facilitates lockstep development, where each developer is working together,
continuously integrating the changes of others.

However the checkout is still a first class branch in Bazaar terms, so that
you have the full history locally.  As you have a first class branch you can
also commit locally if you want, for instance due to the temporary loss af a
network connection. Use the --local option to commit to do this. All the local
commits will then be made on the master branch the next time you do a non-local
commit.

If you are using a checkout from a shared branch you will periodically want to
pull in all the changes made by others. This is done using the "update"
command. The changes need to be applied before any non-local commit, but
Bazaar will tell you if there are any changes and suggest that you use this
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
that modify the revision history (as only one copy branch needs to be updated).
Heavyweight checkouts will generally be faster for any command that uses the
history but does not change it, but if the master branch is on the same disk
then there wont be a noticeable difference.

Another possible use for a checkout is to use it with a treeless repository
containing your branches, where you maintain only one working tree by
switching the master branch that the checkout points to when you want to 
work on a different branch.

Obviously to commit on a checkout you need to be able to write to the master
branch. This means that the master branch must be accessible over a writeable
protocol , such as sftp://, and that you have write permissions at the other
end. Checkouts also work on the local file system, so that all that matters is
file permissions.

You can change the master of a checkout by using the "bind" command (see "help
bind"). This will change the location that the commits are sent to. The bind
command can also be used to turn a branch into a heavy checkout. If you
would like to convert your heavy checkout into a normal branch so that every
commit is local, you can use the "unbind" command.

Related commands:

  checkout    Create a checkout. Pass --lightweight to get a lightweight
              checkout
  update      Pull any changes in the master branch in to your checkout
  commit      Make a commit that is sent to the master branch. If you have
              a heavy checkout then the --local option will commit to the 
              checkout without sending the commit to the master
  bind        Change the master branch that the commits in the checkout will
              be sent to
  unbind      Turn a heavy checkout into a standalone branch so that any
              commits are only made locally
"""


topic_registry.register("revisionspec", _help_on_revisionspec,
                        "Explain how to use --revision")
topic_registry.register('basic', _basic_help, "Basic commands")
topic_registry.register('topics', _help_on_topics, "Topics list")
def get_format_topic(topic):
    from bzrlib import bzrdir
    return bzrdir.format_registry.help_topic(topic)
topic_registry.register('formats', get_format_topic, 'Directory formats')
topic_registry.register('global-options', _global_options,
                        'Options that can be used with any command')
topic_registry.register('checkouts', _checkouts,
                        'Information on what a checkout is')


class HelpTopicContext(object):
    """A context for bzr help that returns topics."""
