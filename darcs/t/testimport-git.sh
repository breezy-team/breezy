. lib.sh

create_git test

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
(cd test; git fast-export HEAD) | (cd test.darcs; darcs-fast-import)
if [ $? != 0 ]; then
	exit 1
fi
diff_importgit test
exit $?
