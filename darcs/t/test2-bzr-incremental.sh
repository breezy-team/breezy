. lib.sh

create_darcs test2 --darcs-2

rm -rf test2.darcs test2.bzr
mkdir test2.bzr
cd test2.bzr
bzr init-repo .
cd ..
if [ "$1" != "--stdout" ]; then
	dmark="$(pwd)/test2.dfe-marks"
	bmark="$(pwd)/test2.bfi-marks"
	rm -f $mark $gmark
	../darcs-fast-export --export-marks=$dmark test2 |(cd test2.bzr; bzr fast-import --export-marks=$bmark -)
	diff_bzr test2 || die "initial conversion differs"
	upd_file_darcs test2 file2 upd_contents
	../darcs-fast-export --export-marks=$dmark --import-marks=$dmark test2 |(cd test2.bzr; bzr fast-import --export-marks=$bmark --import-marks=$bmark -)
	diff_bzr test2 || die "update differs"
else
	../darcs-fast-export test2
fi
