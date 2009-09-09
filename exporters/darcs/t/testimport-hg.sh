. ./lib.sh

create_hg test

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
(cd test; $pypath/bzrlib/plugins/fastimport/exporters/hg-fast-export.py -r .) | (cd test.darcs; darcs-fast-import)
if [ $? != 0 ]; then
	exit 1
fi
diff_importhg test
exit $?
