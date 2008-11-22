. lib.sh

create_bzr test

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
(cd test; /usr/lib/python2.5/site-packages/bzrlib/plugins/fastimport/exporters/bzr-fast-export .) | (cd test.darcs; darcs-fast-import)
if [ $? != 0 ]; then
	exit 1
fi
diff_importbzr test
exit $?
