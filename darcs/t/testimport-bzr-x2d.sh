. lib.sh

create_bzr test

rm -rf test.darcs
x2d -f bzr test
diff_importbzr test || die "initial conversion differs"
upd_file_bzr test file2 upd_contents
x2d -f bzr test
diff_importbzr test || die "update differs"
upd_file_bzr test hungarian.gif "binary to text"
x2d -f bzr test
diff_importbzr test || die "update2 differs"
x2d -f bzr test
diff_importbzr test || die "update3 (noop) differs"
