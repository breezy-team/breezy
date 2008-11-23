. lib.sh

create_git test

rm -rf test.darcs
x2d -f git test
diff_importgit test || die "initial conversion differs"
upd_file_git test file2 upd_contents
x2d -f git test
diff_importgit test || die "update differs"
upd_file_git test hungarian.gif "binary to text"
x2d -f git test
diff_importgit test || die "update2 differs"
x2d -f git test
diff_importgit test || die "update3 (noop) differs"
