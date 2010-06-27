. ./lib.sh

create_git test
cd test
# add two dirs with the some contents, then remove the second
# and make it a symlink to the first
mkdir dira
echo blabla > dira/file
echo blablabla > dira/file2
mkdir dirb
touch dirb/file
touch dirb/file2
git add dira dirb
git commit -a -m "add dira/dirb"
rm -rf dirb
ln -s dira dirb
git add dirb
git commit -a -m "change a dir to a symlink"
cd ..

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
(cd test; git fast-export --progress=2 HEAD) | (cd test.darcs; darcs-fast-import)
# we *do* want this to fail, but with error code 2. that means that we
# detected that symlinks are not supported and the user does not get a
# meaningless exception
[ $? = 2 ]
exit $?
