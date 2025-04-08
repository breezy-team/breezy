use lazy_static::lazy_static;
use regex::Regex;
use std::collections::HashSet;
use std::ffi::OsStr;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use unicode_normalization::{is_nfc, UnicodeNormalization};

pub fn is_inside(dir: &Path, fname: &Path) -> bool {
    fname.starts_with(dir)
}

pub fn is_inside_any(dir_list: &[&Path], fname: &Path) -> bool {
    for dirname in dir_list {
        if is_inside(dirname, fname) {
            return true;
        }
    }
    false
}

pub fn is_inside_or_parent_of_any(dir_list: &[&Path], fname: &Path) -> bool {
    for dirname in dir_list {
        if is_inside(dirname, fname) || is_inside(fname, dirname) {
            return true;
        }
    }
    false
}

pub fn minimum_path_selection(paths: HashSet<&Path>) -> HashSet<&Path> {
    if paths.len() < 2 {
        return paths;
    }

    let mut sorted_paths: Vec<&Path> = paths.iter().copied().collect();
    sorted_paths.sort_by_key(|&path| path.components().collect::<Vec<_>>());

    let mut search_paths = vec![sorted_paths[0]];
    for &path in &sorted_paths[1..] {
        if !is_inside(search_paths.last().unwrap(), path) {
            search_paths.push(path);
        }
    }

    search_paths.into_iter().collect()
}

#[cfg(target_os = "windows")]
pub fn find_executable_on_path(name: &str) -> Option<String> {
    use std::env;
    use winreg::enums::{HKEY_LOCAL_MACHINE, KEY_QUERY_VALUE};
    use winreg::RegKey;
    let exts = env::var("PATHEXT").unwrap_or_default();
    let exts = exts
        .split(';')
        .map(|ext| ext.to_lowercase())
        .collect::<Vec<_>>();
    let (name, exts) = {
        let mut path = PathBuf::from(name);
        let ext = path
            .extension()
            .and_then(|ext| ext.to_str())
            .unwrap_or_default()
            .to_lowercase();
        if !exts.is_empty() && !exts.contains(&ext) {
            (
                path.file_stem()
                    .unwrap_or_default()
                    .to_str()
                    .unwrap_or_default(),
                vec![ext],
            )
        } else {
            (
                path.file_stem()
                    .unwrap_or_default()
                    .to_str()
                    .unwrap_or_default(),
                exts,
            )
        }
    };
    let paths = env::var("PATH").unwrap_or_default();
    let paths = paths.split(';').collect::<Vec<_>>();
    for ext in &exts {
        for path in &paths {
            let exe_path = PathBuf::from(path).join(format!("{}{}", name, ext));
            if exe_path.is_file() {
                return Some(exe_path.to_str().unwrap_or_default().to_owned());
            }
        }
    }
    if let Ok(reg_key) = RegKey::predef(HKEY_LOCAL_MACHINE)
        .open_subkey(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
    {
        if let Ok(value) = reg_key.get_value(name) {
            if let Some(value) = value.as_string() {
                return Some(value);
            }
        }
    }
    None
}

pub fn parent_directories(path: &Path) -> impl Iterator<Item = &Path> {
    let mut path = path;
    std::iter::from_fn(move || {
        if let Some(parent) = path.parent() {
            path = parent;
            if path.parent().is_none() {
                None
            } else {
                Some(path)
            }
        } else {
            None
        }
    })
}

pub fn available_backup_name<E>(
    path: &Path,
    exists: &dyn Fn(&Path) -> Result<bool, E>,
) -> Result<PathBuf, E> {
    let mut counter = 0;
    let mut next = || {
        counter += 1;
        PathBuf::from(format!("{}.~{}~", path.to_str().unwrap(), counter))
    };
    let mut ret = next();
    while exists(ret.as_path())? {
        ret = next();
    }
    Ok(ret)
}

#[cfg(not(target_os = "windows"))]
pub fn find_executable_on_path(name: &str) -> Option<String> {
    use std::env;

    let paths = env::var("PATH").unwrap_or_default();
    let paths = paths.split(':').collect::<Vec<_>>();
    for path in &paths {
        let exe_path = PathBuf::from(path).join(name);
        if let Ok(md) = exe_path.metadata() {
            if md.permissions().mode() & 0o111 != 0 {
                return Some(exe_path.to_str().unwrap_or_default().to_owned());
            }
        }
    }
    None
}

pub fn accessible_normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    path.to_str().map(|path_str| {
        if is_nfc(path_str) {
            (path.to_path_buf(), true)
        } else {
            (PathBuf::from(path_str.nfc().collect::<String>()), true)
        }
    })
}

pub fn inaccessible_normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    path.to_str().map(|path_str| {
        if is_nfc(path_str) {
            (path.to_path_buf(), true)
        } else {
            let normalized_path = path_str.nfc().collect::<String>();
            let accessible = normalized_path == path_str;
            (PathBuf::from(normalized_path), accessible)
        }
    })
}

/// Get the unicode normalized path, and if you can access the file.
///
/// On platforms where the system normalizes filenames (Mac OSX),
/// you can access a file by any path which will normalize correctly.
/// On platforms where the system does not normalize filenames
/// (everything else), you have to access a file by its exact path.
///
/// Internally, bzr only supports NFC normalization, since that is
/// the standard for XML documents.
///
/// So return the normalized path, and a flag indicating if the file
/// can be accessed by that path.
#[cfg(target_os = "macos")]
pub fn normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    accessible_normalized_filename(path)
}

/// Get the unicode normalized path, and if you can access the file.
///
/// On platforms where the system normalizes filenames (Mac OSX),
/// you can access a file by any path which will normalize correctly.
/// On platforms where the system does not normalize filenames
/// (everything else), you have to access a file by its exact path.
///
/// Internally, bzr only supports NFC normalization, since that is
/// the standard for XML documents.
///
/// So return the normalized path, and a flag indicating if the file
/// can be accessed by that path.

#[cfg(not(target_os = "macos"))]
pub fn normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    inaccessible_normalized_filename(path)
}

pub fn normalizes_filenames() -> bool {
    #[cfg(target_os = "macos")]
    return true;

    #[cfg(not(target_os = "macos"))]
    return false;
}

// Check whether the supplied path is legal.
// This is only required on Windows, so we don't test on other platforms
// right now.
//
#[cfg(not(windows))]
pub fn legal_path(_path: &Path) -> bool {
    true
}

#[cfg(windows)]
use lazy_static::lazy_static;
#[cfg(windows)]
lazy_static! {
use regex::Regex;
static ref VALID_WIN32_PATH_RE: Regex = Regex::new(r#"^([A-Za-z]:[/\\])?[^:<>*"?\|]*$"#).unwrap();
}

#[cfg(windows)]
pub fn legal_path(path: &Path) -> bool {
    VALID_WIN32_PATH_RE.is_match(path)
}

/// Return a quoted filename filename
///
/// This previously used backslash quoting, but that works poorly on
/// Windows.
pub fn quotefn(f: &str) -> String {
    lazy_static! {
        static ref QUOTE_RE: Regex = Regex::new(r#"([^a-zA-Z0-9.,:/\\_~-])"#).unwrap();
    }

    if QUOTE_RE.is_match(f) {
        format!(r#""{}""#, f)
    } else {
        f.to_string()
    }
}

pub mod win32 {
    use lazy_static::lazy_static;
    use regex::Regex;
    use std::ffi::OsStr;
    use std::path::{Path, PathBuf};

    /// Force drive letters to be consistent.

    /// win32 is inconsistent whether it returns lower or upper case
    /// and even if it was consistent the user might type the other
    /// so we force it to uppercase
    /// running python.exe under cmd.exe return capital C:\\
    /// running win32 python inside a cygwin shell returns lowercase c:\\
    pub fn fixdrive(path: &Path) -> PathBuf {
        if path.as_os_str().len() < 2 || path.to_str().unwrap().chars().nth(1).unwrap() != ':' {
            return path.into();
        }
        if let Some(drive) = path.as_os_str().to_str().unwrap().get(..2) {
            PathBuf::from(drive.to_uppercase() + path.to_str().unwrap().get(2..).unwrap())
        } else {
            path.into()
        }
    }

    /// Return path with directory separators changed to forward slashes
    pub fn fix_separators(path: &Path) -> PathBuf {
        if path.to_path_buf().to_str().unwrap().contains('\\') {
            path.to_path_buf()
                .to_str()
                .unwrap()
                .replace('\\', "/")
                .into()
        } else {
            path.into()
        }
    }

    lazy_static! {
        static ref ABS_WINDOWS_PATH_RE: Regex = Regex::new(r#"^[A-Za-z]:[/\\]"#).unwrap();
    }

    pub fn abspath(path: &Path) -> Result<PathBuf, std::io::Error> {
        #[cfg(not(windows))]
        if ABS_WINDOWS_PATH_RE.is_match(path.to_str().unwrap()) {
            return Ok(path.to_path_buf());
        }
        use path_clean::PathClean;
        let cwd = std::env::current_dir()?;
        let ap = cwd.join(path).clean();
        Ok(fixdrive(&fix_separators(ap.as_path())))
    }

    pub fn normpath<P: AsRef<Path>>(p: P) -> PathBuf {
        let mut parts = Vec::new();

        // Split the path into its components
        let p = p.as_ref().to_path_buf();
        for component in p.components() {
            match component {
                // Ignore empty components and "."
                std::path::Component::Normal(c) if c != "." => parts.push(c),
                // Pop the last component if ".." is encountered
                std::path::Component::Normal(c) if c == ".." => if parts.pop().is_some() {},
                // Ignore root components ("\" on Windows)
                std::path::Component::RootDir => {}
                // Ignore non-Unicode components
                _ => {
                    return p;
                }
            }
        }

        // If the path was empty or only contained root components, return the root component(s)
        if parts.is_empty() {
            return PathBuf::from(if p.to_str().unwrap().starts_with('\\') {
                "\\"
            } else {
                ""
            });
        }

        // Join the normalized components into a path string
        let mut path = PathBuf::new();
        for part in &parts {
            path.push(part);
        }

        fixdrive(&fix_separators(&path))
    }

    pub fn getcwd() -> std::io::Result<PathBuf> {
        Ok(fixdrive(
            fix_separators(std::env::current_dir()?.as_path()).as_path(),
        ))
    }

    pub fn pathjoin(ps: &[&OsStr]) -> PathBuf {
        let mut p = PathBuf::from(ps[0]);
        for s in ps[1..].iter() {
            p.push(s);
        }
        fix_separators(&p)
    }

    #[cfg(test)]
    mod test {
        #[test]
        fn test_abspath() {
            assert_eq!(
                super::abspath(std::path::Path::new("C:/foo/bar")).unwrap(),
                std::path::Path::new("C:/foo/bar")
            );
        }
    }
}

pub mod posix {
    use std::collections::HashMap;
    use std::ffi::OsStr;
    use std::path::{Component, Path, PathBuf};

    pub fn abspath(path: &Path) -> Result<PathBuf, std::io::Error> {
        use path_clean::PathClean;
        if path.is_absolute() {
            return Ok(path.to_path_buf());
        }
        let cwd = std::env::current_dir()?;
        let ap = cwd.join(path).clean();
        Ok(ap.as_path().to_path_buf())
    }

    pub fn normpath(path: &Path) -> PathBuf {
        let mut stack = Vec::new();

        for component in path.components() {
            match component {
                Component::Prefix(_) => {
                    // skip the prefix, if any
                    stack.clear();
                    stack.push(component.as_os_str());
                }
                Component::RootDir => {
                    // keep the root
                    stack.clear();
                    stack.push(component.as_os_str());
                }
                Component::CurDir => {
                    // skip the current directory
                }
                Component::ParentDir => {
                    if stack.len() > 1 {
                        // pop the previous component if not the root
                        stack.pop();
                    }
                }
                Component::Normal(c) => {
                    stack.push(c);
                }
            }
        }

        // Join the path components back
        let mut result = PathBuf::new();
        for c in stack {
            result.push(c);
        }
        result
    }

    pub fn realpath<P: AsRef<Path>>(filename: P) -> std::io::Result<PathBuf> {
        let filename = filename.as_ref().to_path_buf();
        let (path, _) = join_realpath(Path::new(""), &filename, &mut HashMap::new())?;
        abspath(path.as_path())
    }

    fn join_realpath(
        path: &Path,
        rest: &Path,
        seen: &mut HashMap<PathBuf, Option<PathBuf>>,
    ) -> std::io::Result<(PathBuf, bool)> {
        let rest = rest.to_path_buf();
        let mut path = path.to_path_buf();

        let mut components = rest.components();
        while let Some(component) = components.next() {
            match component {
                Component::RootDir => {
                    // absolute path
                    path = PathBuf::from("/");
                }
                Component::CurDir | Component::Prefix(_) => {}
                Component::ParentDir => {
                    // parent dir
                    if path.components().next().is_none() {
                        path = PathBuf::from("..");
                    } else if path.file_name().unwrap() == ".." {
                        path = path.join("..");
                    } else {
                        path = path.parent().unwrap().to_path_buf();
                    }
                }
                Component::Normal(name) => {
                    let mut newpath = path.join(name);
                    let st = std::fs::symlink_metadata(&newpath);
                    let is_link = st.is_ok() && st.unwrap().file_type().is_symlink();
                    if !is_link {
                        path = newpath;
                    } else if let Some(cached) = seen.get(&newpath) {
                        match cached {
                            Some(target) => {
                                path = target.clone();
                            }
                            None => {
                                return Ok((newpath, false));
                            }
                        }
                    } else {
                        seen.insert(newpath.clone(), None);
                        let ok;
                        (path, ok) = join_realpath(
                            path.as_path(),
                            std::fs::read_link(&newpath)?.as_path(),
                            seen,
                        )?;
                        if !ok {
                            components.for_each(|c| newpath.push(c));
                            return Ok((newpath, false));
                        }
                        seen.insert(newpath, Some(path.clone()));
                    }
                }
            }
        }

        Ok((path.to_path_buf(), true))
    }

    pub fn pathjoin(ps: &[&OsStr]) -> PathBuf {
        let mut p = PathBuf::new();
        for s in ps {
            p.push(s);
        }
        p
    }
}

pub fn abspath(path: &Path) -> Result<PathBuf, std::io::Error> {
    #[cfg(windows)]
    return win32::abspath(path);

    #[cfg(not(windows))]
    return posix::abspath(path);
}

pub fn normpath<P: AsRef<Path>>(path: P) -> PathBuf {
    #[cfg(windows)]
    return win32::normpath(path.as_ref());

    #[cfg(not(windows))]
    return posix::normpath(path.as_ref());
}

#[cfg(not(windows))]
pub const MIN_ABS_PATHLENGTH: usize = 1;

#[cfg(windows)]
pub const MIN_ABS_PATHLENGTH: usize = 3;

/// Return path relative to base, or raise PathNotChild exception.
///
/// The path may be either an absolute path or a path relative to the
/// current working directory.
///
/// os.path.commonprefix (python2.4) has a bad bug that it works just
/// on string prefixes, assuming that '/u' is a prefix of '/u2'.  This
/// avoids that problem.
///
/// NOTE: `base` should not have a trailing slash otherwise you'll get
/// PathNotChild exceptions regardless of `path`.
pub fn relpath(base: &Path, path: &Path) -> Option<PathBuf> {
    if base.to_str().unwrap().len() < MIN_ABS_PATHLENGTH {
        return None;
    }

    let rp = abspath(path).unwrap();

    let mut s = Vec::new();
    let mut head = rp.as_path();
    let mut tail;
    loop {
        if head.as_os_str().len() <= base.as_os_str().len() && head != base {
            return None;
        }
        if head == base {
            break;
        }
        (head, tail) = (head.parent().unwrap(), head.file_name().unwrap());
        if !tail.is_empty() {
            s.push(tail);
        }
    }

    Some(s.into_iter().rev().collect::<PathBuf>())
}

pub fn normalizepath<P: AsRef<Path>>(f: P) -> std::io::Result<PathBuf> {
    let p = f.as_ref().parent();
    let e = f.as_ref().file_name();

    // Broken filename
    if e.is_none() || e == Some(OsStr::new(".")) || e == Some(OsStr::new("..")) {
        realpath(f.as_ref())
    // Base and filename present
    } else if let Some(p) = p {
        let p = realpath(p)?;
        Ok(p.join(e.unwrap()))
    } else {
        // Just filename
        Ok(PathBuf::from(e.unwrap()))
    }
}

pub fn realpath(f: &Path) -> std::io::Result<PathBuf> {
    #[cfg(windows)]
    return win32::realpath(f);

    #[cfg(not(windows))]
    return posix::realpath(f);
}

#[derive(Debug)]
pub struct InvalidPathSegmentError(pub String);

pub fn splitpath(p: &str) -> std::result::Result<Vec<&str>, InvalidPathSegmentError> {
    #[cfg(windows)]
    let split = |c| c == '/' || c == '\\';
    #[cfg(not(windows))]
    let split = |c| c == '/';

    let mut rps = Vec::new();
    for f in p.split(split) {
        if f == ".." {
            return Err(InvalidPathSegmentError(f.to_string()));
        } else if f == "." || f.is_empty() {
            continue;
        } else {
            rps.push(f);
        }
    }

    Ok(rps)
}

pub fn pathjoin(ps: &[&OsStr]) -> PathBuf {
    #[cfg(windows)]
    return win32::pathjoin(ps);

    #[cfg(not(windows))]
    return posix::pathjoin(ps);
}

pub fn joinpath(ps: &[&OsStr]) -> std::result::Result<PathBuf, InvalidPathSegmentError> {
    for p in ps {
        if p == &"" || p == &".." {
            return Err(InvalidPathSegmentError(p.to_string_lossy().into_owned()));
        }
    }

    Ok(pathjoin(ps))
}

/// Determine the real path to a file.
///
/// All parent elements are dereferenced.  But the file itself is not
/// dereferenced.
/// Args:
///   path: The original path.  May be absolute or relative.
/// Returns:the real path *to* the file
pub fn dereference_path(path: &Path) -> std::io::Result<PathBuf> {
    let filename = if let Some(filename) = path.file_name() {
        filename
    } else {
        return Ok(PathBuf::from(path));
    };
    if let Some(parent) = path.parent() {
        Ok(realpath(parent)?.join(filename))
    } else {
        Ok(PathBuf::from(filename))
    }
}
