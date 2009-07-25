. lib.sh

create_hg test

rm -rf test.darcs
x2d -f hg test
diff_importhg test || die "initial conversion differs"
upd_file_hg test file2 upd_contents
x2d -f hg test
diff_importhg test || die "update differs"
upd_file_hg test hungarian.gif "binary to text"
x2d -f hg test
diff_importhg test || die "update2 differs"
x2d -f hg test
diff_importhg test || die "update3 (noop) differs"
