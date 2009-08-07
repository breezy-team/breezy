. lib.sh

rm -rf test
mkdir test
cd test
git init
echo a > file
git add file
git commit -m a1
git mv file file2
git commit -m b
cd ..

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
(cd test; git fast-export -M HEAD) > out
cat out | (cd test.darcs; darcs-fast-import)
if [ $? != 0 ]; then
	exit 1
fi
diff_importgit test
exit $?
