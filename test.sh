#! /bin/sh -pe

# Simple shell-based tests for bzr.

# This is meant to exercise the external behaviour, command line
# parsing and similar things and compliment the inwardly-turned
# testing done by doctest.

# This must already exist and be in the right place
if ! [ -d bzr-test.tmp ] 
then
    echo "please create bzr-test.tmp"
    exit 1
fi

rm -rf bzr-test.tmp
mkdir bzr-test.tmp

exec > bzr-test.log
exec 2>&1 
set -x

cd bzr-test.tmp 
rm -rf .bzr

# some information commands
bzr help
bzr version

# invalid commands are detected
! bzr pants

# some experiments with renames
bzr init
echo "hello world" > test.txt
bzr unknowns

# should be the only unknown file
[ "`bzr unknowns`" = test.txt ]

# can't rename unversioned files; use the regular unix rename command
! bzr rename test.txt new-test.txt

# ok, so now add it and see what happens
bzr add test.txt
[ -z "`bzr unknowns`" ]

# after adding even before committing you can rename files
bzr rename test.txt newname.txt
[ "`bzr status`" = "A       newname.txt" ]

bzr commit -m "add first revision"

# now more complicated renames
mkdir sub1
! bzr rename newname.txt sub1
! bzr rename newname.txt sub1/foo.txt
bzr add sub1
! bzr rename newname.txt sub1

bzr rename newname.txt sub1/foo.txt
[ -f sub1/foo.txt ]
[ ! -f newname.txt ]

bzr rename sub1/foo.txt newname.txt
[ -f newname.txt ]

bzr rename newname.txt sub1/foo.txt
bzr rename sub1/foo.txt sub1/bar.txt

cd sub1
mkdir sub2
bzr add sub2
bzr rename bar.txt sub2/bar.txt
cd sub2
bzr rename bar.txt ../../bar.txt
cd ../../

bzr commit -m "more renames"





