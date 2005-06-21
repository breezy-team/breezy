#! /bin/sh -ex

# --include-from is used to make sure that only versioned files and
# control files are copied.  We use includes/excludes rather than
# --files-from so that we can delete any files from the destination
# that are no longer present on the source.

repo=jameinel@bzr.arbash-meinel.com:/srv/bzr/public/plugins
dir=bzr-changeset
cd ~/dev/bzr/$dir

# note: don't use -a because that can mess up the permissions

chmod a+rX `bzr inventory`

bzr inventory | 
rsync -rltv				\
    -e 'ssh -c blowfish'		\
    $repo/$dir/				\
    .					\
    --include-from -			\
    --include .bzr			\
    --include '.bzr/**'			\
    --exclude-from .rsyncexclude	\
    --exclude-from .bzrignore		\
    --exclude \*			\
    --exclude '.*'			\
    --delete-excluded --delete		\
