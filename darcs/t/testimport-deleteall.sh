. lib.sh

rm -rf test
mkdir test
cd test
git init
echo a > file
git add file
echo A > file2
git add file2
git commit -m a12
git rm file*
echo b>file3
git add file3
git commit -m b
cd ..

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
(cd test; git fast-export --progress=2 HEAD) > out
sed -i '/^D file$/d' out
sed -i 's/^D file2$/deleteall/' out
cat out | (cd test.darcs; darcs-fast-import)
if [ $? != 0 ]; then
	exit 1
fi
diff_importgit test
exit $?
