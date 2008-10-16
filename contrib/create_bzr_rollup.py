#!/usr/bin/env python
"""\
This script runs after rsyncing bzr.
It checks the bzr version, and sees if there is a tarball and
zipfile that exist with that version.
If not, it creates them.
"""

import os, sys, tempfile

def sync(remote, local, verbose=False):
	"""Do the actual synchronization
	"""
	if verbose:
		status = os.system('rsync -av --delete "%s" "%s"' % (remote, local))
	else:
		status = os.system('rsync -a --delete "%s" "%s"' % (remote, local))
	return status==0

def create_tar_gz(local_dir, output_dir=None, verbose=False):
	import tarfile, bzrlib
	out_name = os.path.basename(local_dir) + '-' + str(bzrlib.Branch(local_dir).revno())
	final_path = os.path.join(output_dir, out_name + '.tar.gz')
	if os.path.exists(final_path):
		if verbose:
			print 'Output file already exists: %r' % final_path
		return
	fn, tmp_path=tempfile.mkstemp(suffix='.tar', prefix=out_name, dir=output_dir)
	os.close(fn)
	try:
		if verbose:
			print 'Creating %r (%r)' % (final_path, tmp_path)
		tar = tarfile.TarFile(name=tmp_path, mode='w')
		tar.add(local_dir, arcname=out_name, recursive=True)
		tar.close()

		if verbose:
			print 'Compressing...'
		if os.system('gzip "%s"' % tmp_path) != 0:
			raise ValueError('Failed to compress')
		tmp_path += '.gz'
                os.chmod(tmp_path, 0644)
		os.rename(tmp_path, final_path)
	except:
		os.remove(tmp_path)
		raise

def create_tar_bz2(local_dir, output_dir=None, verbose=False):
	import tarfile, bzrlib
	out_name = os.path.basename(local_dir) + '-' + str(bzrlib.Branch(local_dir).revno())
	final_path = os.path.join(output_dir, out_name + '.tar.bz2')
	if os.path.exists(final_path):
		if verbose:
			print 'Output file already exists: %r' % final_path
		return
	fn, tmp_path=tempfile.mkstemp(suffix='.tar', prefix=out_name, dir=output_dir)
	os.close(fn)
	try:
		if verbose:
			print 'Creating %r (%r)' % (final_path, tmp_path)
		tar = tarfile.TarFile(name=tmp_path, mode='w')
		tar.add(local_dir, arcname=out_name, recursive=True)
		tar.close()

		if verbose:
			print 'Compressing...'
		if os.system('bzip2 "%s"' % tmp_path) != 0:
			raise ValueError('Failed to compress')
		tmp_path += '.bz2'
                os.chmod(tmp_path, 0644)
		os.rename(tmp_path, final_path)
	except:
		os.remove(tmp_path)
		raise

def create_zip(local_dir, output_dir=None, verbose=False):
	import zipfile, bzrlib
	out_name = os.path.basename(local_dir) + '-' + str(bzrlib.Branch(local_dir).revno())
	final_path = os.path.join(output_dir, out_name + '.zip')
	if os.path.exists(final_path):
		if verbose:
			print 'Output file already exists: %r' % final_path
		return
	fn, tmp_path=tempfile.mkstemp(suffix='.zip', prefix=out_name, dir=output_dir)
	os.close(fn)
	try:
		if verbose:
			print 'Creating %r (%r)' % (final_path, tmp_path)
		zip = zipfile.ZipFile(file=tmp_path, mode='w')
		try:
			for root, dirs, files in os.walk(local_dir):
				for f in files:
					path = os.path.join(root, f)
					arcname = os.path.join(out_name, path[len(local_dir)+1:])
					zip.write(path, arcname=arcname)
		finally:
			zip.close()

                os.chmod(tmp_path, 0644)
		os.rename(tmp_path, final_path)
	except:
		os.remove(tmp_path)
		raise

def get_local_dir(remote, local):
	"""This returns the full path to the local directory where 
	the files are kept.

	rsync has the trick that if the source directory ends in a '/' then
	the file will be copied *into* the target. If it does not end in a slash,
	then the directory will be added into the target.
	"""
	if remote[-1:] == '/':
		return local
	# rsync paths are typically user@host:path/to/something
	# the reason for the split(':') is in case path doesn't contain a slash
	extra = remote.split(':')[-1].split('/')[-1]
	return os.path.join(local, extra)

def get_output_dir(output, local):
	if output:
		return output
	return os.path.dirname(os.path.realpath(local))


def main(args):
	import optparse
	p = optparse.OptionParser(usage='%prog [options] [remote] [local]'
		'\n  rsync the remote repository to the local directory'
		'\n  if remote is not given, it defaults to "bazaar-ng.org::bazaar-ng/bzr/bzr.dev"'
		'\n  if local is not given it defaults to "."')

        p.add_option('--verbose', action='store_true'
                , help="Describe the process")
	p.add_option('--no-tar-gz', action='store_false', dest='create_tar_gz', default=True
		, help="Don't create a gzip compressed tarfile.")
	p.add_option('--no-tar-bz2', action='store_false', dest='create_tar_bz2', default=True
		, help="Don't create a bzip2 compressed tarfile.")
	p.add_option('--no-zip', action='store_false', dest='create_zip', default=True
		, help="Don't create a zipfile.")
	p.add_option('--output-dir', default=None
		, help="Set the output location, default is just above the final local directory.")


	(opts, args) = p.parse_args(args)

	if len(args) < 1:
		remote = 'bazaar-ng.org::bazaar-ng/bzr/bzr.dev'
	else:
		remote = args[0]
	if len(args) < 2:
		local = '.'
	else:
		local = args[1]
	if len(args) > 2:
		print 'Invalid number of arguments, see --help for details.'

	if not sync(remote, local, verbose=opts.verbose):
		if opts.verbose:
			print '** rsync failed'
		return 1
	# Now we have the new update
	local_dir = get_local_dir(remote, local)

	output_dir = get_output_dir(opts.output_dir, local_dir)
	if opts.create_tar_gz:
		create_tar_gz(local_dir, output_dir=output_dir, verbose=opts.verbose)
	if opts.create_tar_bz2:
		create_tar_bz2(local_dir, output_dir=output_dir, verbose=opts.verbose)
	if opts.create_zip:
		create_zip(local_dir, output_dir=output_dir, verbose=opts.verbose)

	return 0
		
if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))

