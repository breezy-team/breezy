. lib.sh

create_darcs test2 --darcs-2

rm -rf test2.bzr
if [ "$1" != "--stdout" ]; then
	d2x -f bzr test2
	diff_bzr test2 || die "initial conversion differs"
	upd_file_darcs test2 file2 upd_contents
	d2x -f bzr test2
	diff_bzr test2 || die "update differs"
	upd_file_darcs test2 hungarian.gif "binary to text"
	d2x -f bzr test2
	diff_bzr test2 || die "update2 differs"
	d2x -f bzr test2
	diff_bzr test2 || die "update3 (noop) differs"
else
	darcs-fast-export test2
fi
