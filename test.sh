#! /bin/sh -pe

# Simple shell-based tests for bzr.

# This is meant to exercise the external behaviour, command line
# parsing and similar things and compliment the inwardly-turned
# testing done by doctest.

# This must already exist and be in the right place
if ! [ -d bzr-test.tmp ] 
then
    echo "please create directory bzr-test.tmp"
    exit 1
fi

echo "testing `which bzr`"
bzr --version | head -n 1
echo

rm -rf bzr-test.tmp
mkdir bzr-test.tmp

# save it for real errors
exec 3>&2

exec > bzr-test.log
exec 2>&1 
set -x

quitter() {
    echo "tests failed, look in bzr-test.log" >&3; exit 2; 
}

trap quitter ERR

cd bzr-test.tmp 
rm -rf .bzr

mkdir branch1
cd branch1

# some information commands
bzr help
bzr version

[ $(bzr help commands | wc -l) -gt 20 ]

# invalid commands are detected
! bzr pants

# some experiments with renames
bzr init
echo "hello world" > test.txt
bzr unknowns

# should be the only unknown file
[ "`bzr unknowns`" = test.txt ]

bzr status --all > status.tmp
! diff -u - status.tmp <<EOF
?       status.tmp
?       test.txt
EOF

# command alias
bzr st --all | diff -u - status.tmp

# can't rename unversioned files; use the regular unix rename command
! bzr rename test.txt new-test.txt

# ok, so now add it and see what happens
bzr add test.txt
[ -z "`bzr unknowns`" ]

# after adding even before committing you can rename files
bzr rename test.txt newname.txt
[ "`bzr status`" = "A       newname.txt" ]

[ `bzr revno` = 0 ]
bzr commit -m "add first revision"
[ `bzr revno` = 1 ]

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
[ `bzr revno` = 2 ] 

# now try pulling that file back out, checking it was stored properly
[ "`bzr cat -r 1 newname.txt`" = "hello world" ]

! bzr rename sub1 sub1/knotted-up





# now test hardlinked branches in subdirectories
cd ..
[ -d branch2 ] && rm -rf branch2
cp -al branch1 branch2

cd branch2
bzr log 
[ `bzr revno` = 2 ]

echo "added in branch2" > new-in-2.txt
bzr add new-in-2.txt
bzr commit -m "add file to branch 2 only"

[ `bzr revno` = 3 ]

cd ../branch1
[ `bzr revno` = 2 ]

bzr check


echo "tests completed ok" >&3