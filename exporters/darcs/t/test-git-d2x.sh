. lib.sh

create_darcs test --old-fashioned-inventory

rm -rf test.git
if [ "$1" != "--stdout" ]; then
	d2x -f git test
	diff_git test || die "initial conversion differs"
	upd_file_darcs test file2 upd_contents
	d2x -f git test
	diff_git test || die "update differs"
	upd_file_darcs test hungarian.gif "binary to text"
	d2x -f git test
	diff_git test || die "update2 differs"
	d2x -f git test
	diff_git test || die "update3 (noop) differs"
else
	darcs-fast-export test
fi
