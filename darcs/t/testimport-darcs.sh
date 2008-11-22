. lib.sh

create_darcs test2 --darcs-2

rm -rf test2.importdarcs test2.darcs
mkdir test2.importdarcs
cd test2.importdarcs
darcs init
cd ..

darcs-fast-export test2 | (cd test2.importdarcs; darcs-fast-import)

if [ $? != 0 ]; then
	exit 1
fi
diff_importdarcs test2 test2.importdarcs
exit $?
