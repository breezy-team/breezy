use lazy_static::lazy_static;
use regex::Regex;
use std::collections::HashSet;
use std::ffi::OsStr;
#[cfg(unix)]
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
    use winreg::enums::HKEY_LOCAL_MACHINE;
    use winreg::RegKey;
    let pathext = env::var("PATHEXT").unwrap_or_default();
    let pathext_exts = pathext
        .split(';')
        .filter(|ext| !ext.is_empty())
        .map(|ext| {
            if ext.starts_with('.') {
                ext.to_lowercase()
            } else {
                format!(".{}", ext.to_lowercase())
            }
        })
        .collect::<Vec<_>>();
    // If `name` already has an extension, only try that exact one; otherwise
    // try `name` itself plus each PATHEXT entry. Always probe `name` with no
    // extra extension first, so e.g. `find_executable_on_path("foo.bat")`
    // matches `foo.bat` directly rather than `foo.bat.exe`.
    let (name, exts) = {
        let path = PathBuf::from(name);
        let ext = path
            .extension()
            .and_then(|ext| ext.to_str())
            .unwrap_or_default()
            .to_lowercase();
        let stem = path
            .file_stem()
            .unwrap_or_default()
            .to_str()
            .unwrap_or_default()
            .to_owned();
        if !ext.is_empty() {
            // User specified a specific extension; only look for that.
            (name.to_owned(), vec![String::new()])
        } else if pathext_exts.is_empty() {
            (stem, vec![String::new()])
        } else {
            let mut e = vec![String::new()];
            e.extend(pathext_exts);
            (stem, e)
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
    // Fall back to the App Paths registry. Each application registers under
    // a subkey like `App Paths\\iexplore.exe`, with the executable's full
    // path as the (default) value of that subkey.
    if let Ok(app_paths) = RegKey::predef(HKEY_LOCAL_MACHINE)
        .open_subkey(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
    {
        let mut candidates: Vec<String> = Vec::new();
        if name.contains('.') {
            candidates.push(name.clone());
        } else {
            // Try the bare name plus name + each PATHEXT extension.
            candidates.push(name.clone());
            for ext in &exts {
                if !ext.is_empty() {
                    candidates.push(format!("{}{}", name, ext));
                }
            }
            // Default to .exe if PATHEXT is empty (matches common usage).
            if !candidates.iter().any(|c| c.ends_with(".exe")) {
                candidates.push(format!("{}.exe", name));
            }
        }
        for candidate in &candidates {
            if let Ok(subkey) = app_paths.open_subkey(candidate) {
                if let Ok(value) = subkey.get_value::<String, _>("") {
                    return Some(value);
                }
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

/// Override for the platform default behaviour of [`normalized_filename`].
///
/// Tests need to exercise both the accessible (macOS-like) and inaccessible
/// (Linux/Windows-like) code paths regardless of the host platform. Setting a
/// non-`Auto` mode forces the corresponding implementation.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum NormalizationMode {
    /// Use the platform default: accessible on macOS, inaccessible elsewhere.
    Auto,
    /// Force `accessible_normalized_filename` (filesystem normalizes paths).
    Accessible,
    /// Force `inaccessible_normalized_filename` (filesystem does not).
    Inaccessible,
}

thread_local! {
    static NORMALIZATION_MODE: std::cell::Cell<NormalizationMode> =
        const { std::cell::Cell::new(NormalizationMode::Auto) };
}

/// Set the normalization mode for the current thread, returning the previous mode.
pub fn set_normalization_mode(mode: NormalizationMode) -> NormalizationMode {
    NORMALIZATION_MODE.with(|m| m.replace(mode))
}

/// Return the normalization mode for the current thread.
pub fn normalization_mode() -> NormalizationMode {
    NORMALIZATION_MODE.with(|m| m.get())
}

fn platform_default_normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    #[cfg(target_os = "macos")]
    {
        accessible_normalized_filename(path)
    }
    #[cfg(not(target_os = "macos"))]
    {
        inaccessible_normalized_filename(path)
    }
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
///
/// The behaviour can be overridden for testing via [`set_normalization_mode`].
pub fn normalized_filename(path: &Path) -> Option<(PathBuf, bool)> {
    match normalization_mode() {
        NormalizationMode::Auto => platform_default_normalized_filename(path),
        NormalizationMode::Accessible => accessible_normalized_filename(path),
        NormalizationMode::Inaccessible => inaccessible_normalized_filename(path),
    }
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
lazy_static! {
    static ref VALID_WIN32_PATH_RE: Regex =
        Regex::new(r#"^([A-Za-z]:[/\\])?[^:<>*"?\|]*$"#).unwrap();
}

#[cfg(windows)]
pub fn legal_path(path: &Path) -> bool {
    match path.to_str() {
        Some(s) => VALID_WIN32_PATH_RE.is_match(s),
        None => false,
    }
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
        let ap = fixdrive(&fix_separators(ap.as_path()));
        // ``path_clean`` may leave a trailing ``/`` on UNC paths like
        // ``//HOST/share/``; strip it so the result mirrors what
        // ``ntpath.abspath`` returns on Windows.
        let s = ap.to_str().unwrap_or_default();
        let trimmed = if s.len() > 3 && s.ends_with('/') {
            PathBuf::from(&s[..s.len() - 1])
        } else {
            ap
        };
        Ok(trimmed)
    }

    pub fn normpath<P: AsRef<Path>>(p: P) -> PathBuf {
        let mut parts: Vec<&std::ffi::OsStr> = Vec::new();

        // Split the path into its components
        let p = p.as_ref().to_path_buf();
        for component in p.components() {
            match component {
                // Drop "." entries; they don't affect the path.
                std::path::Component::CurDir => {}
                // Pop the last component for "..".
                std::path::Component::ParentDir => {
                    parts.pop();
                }
                // Ignore root components ("\" on Windows).
                std::path::Component::RootDir => {}
                // Skip the prefix marker (e.g. drive letter); it gets
                // re-added separately when reassembling.
                std::path::Component::Prefix(_) => {}
                std::path::Component::Normal(c) => parts.push(c),
            }
        }

        // If the path was empty or only contained root components, return
        // the root marker. Empty path stays empty; '/' or '\\' stays as
        // the root char so callers can still distinguish "current dir"
        // from "filesystem root".
        if parts.is_empty() {
            let raw = p.to_str().unwrap();
            return PathBuf::from(if raw.starts_with('\\') {
                "\\"
            } else if raw.starts_with('/') {
                "/"
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

    /// Strip the `\\?\` extended-length path prefix that
    /// `std::fs::canonicalize` adds on Windows. The prefix lets paths exceed
    /// MAX_PATH but breaks downstream code that expects a regular drive path.
    /// `ntpath.realpath` strips it when the result still fits, and we mirror
    /// that behaviour here.
    fn strip_verbatim_prefix(path: PathBuf) -> PathBuf {
        let s = match path.to_str() {
            Some(s) => s,
            None => return path,
        };
        if let Some(rest) = s.strip_prefix(r"\\?\UNC\") {
            // \\?\UNC\server\share\... -> \\server\share\...
            return PathBuf::from(format!(r"\\{rest}"));
        }
        if let Some(rest) = s.strip_prefix(r"\\?\") {
            // Only strip when followed by a drive letter; \\?\Volume{...}
            // and similar forms don't have a non-verbatim equivalent.
            let bytes = rest.as_bytes();
            if bytes.len() >= 2 && bytes[1] == b':' && bytes[0].is_ascii_alphabetic() {
                return PathBuf::from(rest);
            }
        }
        path
    }

    /// Canonicalise the longest prefix of `f` that exists on disk, leaving
    /// the rest as-is. `std::fs::canonicalize` requires the entire path to
    /// exist, but Python's `ntpath.realpath` (and the rest of the codebase)
    /// expects realpath to be tolerant of missing tail components.
    fn canonicalize_existing_prefix(f: &Path) -> std::io::Result<PathBuf> {
        match std::fs::canonicalize(f) {
            Ok(p) => Ok(p),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                let parent = match f.parent() {
                    Some(p) if !p.as_os_str().is_empty() => p,
                    // No parent: return absolute path without canonicalisation.
                    _ => return abspath(f),
                };
                let base = match f.file_name() {
                    Some(b) => b,
                    None => return abspath(f),
                };
                let mut canonical_parent = canonicalize_existing_prefix(parent)?;
                canonical_parent.push(base);
                Ok(canonical_parent)
            }
            Err(e) => Err(e),
        }
    }

    pub fn realpath(f: &Path) -> std::io::Result<PathBuf> {
        let canonical = canonicalize_existing_prefix(f)?;
        let stripped = strip_verbatim_prefix(canonical);
        Ok(fixdrive(fix_separators(stripped.as_path()).as_path()))
    }

    #[cfg(test)]
    mod test {
        use super::strip_verbatim_prefix;
        use std::path::PathBuf;

        #[test]
        fn test_abspath() {
            assert_eq!(
                super::abspath(std::path::Path::new("C:/foo/bar")).unwrap(),
                std::path::Path::new("C:/foo/bar")
            );
        }

        #[test]
        fn test_strip_verbatim_prefix_drive() {
            assert_eq!(
                strip_verbatim_prefix(PathBuf::from(r"\\?\C:\Users\foo")),
                PathBuf::from(r"C:\Users\foo")
            );
        }

        #[test]
        fn test_strip_verbatim_prefix_unc() {
            assert_eq!(
                strip_verbatim_prefix(PathBuf::from(r"\\?\UNC\server\share\foo")),
                PathBuf::from(r"\\server\share\foo")
            );
        }

        #[test]
        fn test_strip_verbatim_prefix_unknown_kept() {
            assert_eq!(
                strip_verbatim_prefix(PathBuf::from(r"\\?\Volume{abc}\foo")),
                PathBuf::from(r"\\?\Volume{abc}\foo")
            );
        }

        #[test]
        fn test_strip_verbatim_prefix_no_prefix() {
            assert_eq!(
                strip_verbatim_prefix(PathBuf::from(r"C:\Users\foo")),
                PathBuf::from(r"C:\Users\foo")
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
        // POSIX semantics: any path starting with '/' is absolute, even on
        // Windows where ``Path::is_absolute`` would otherwise demand a
        // drive letter.
        let starts_with_slash = path.to_str().map(|s| s.starts_with('/')).unwrap_or(false);
        if path.is_absolute() || starts_with_slash {
            return Ok(path.to_path_buf());
        }
        let cwd = std::env::current_dir()?;
        let ap = cwd.join(path).clean();
        Ok(ap.as_path().to_path_buf())
    }

    pub fn normpath(path: &Path) -> PathBuf {
        let mut absolute = false;
        let mut stack: Vec<&OsStr> = Vec::new();

        for component in path.components() {
            match component {
                Component::Prefix(_) => {
                    // POSIX semantics: drop any drive-letter prefix that
                    // Windows might have parsed.
                }
                Component::RootDir => {
                    absolute = true;
                    stack.clear();
                }
                Component::CurDir => {
                    // skip the current directory
                }
                Component::ParentDir => {
                    if !stack.is_empty() {
                        stack.pop();
                    } else if !absolute {
                        // ".." with no preceding component is significant
                        // for relative paths; preserve it.
                        stack.push(OsStr::new(".."));
                    }
                }
                Component::Normal(c) => {
                    stack.push(c);
                }
            }
        }

        // Reassemble with explicit forward slashes so the result is the same
        // string regardless of host platform; ``Path::join`` would otherwise
        // use `\` on Windows when re-rendering a POSIX path.
        let parts: Vec<String> = stack
            .iter()
            .map(|s| s.to_string_lossy().into_owned())
            .collect();
        let joined = parts.join("/");
        let rendered = if absolute {
            if joined.is_empty() {
                "/".to_string()
            } else {
                format!("/{joined}")
            }
        } else if joined.is_empty() {
            ".".to_string()
        } else {
            joined
        };
        PathBuf::from(rendered)
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

    let result: PathBuf = s.into_iter().rev().collect();
    // breezy paths use forward slashes everywhere; PathBuf::collect on
    // Windows joins components with '\\', which breaks downstream
    // dirstate lookups that store '/'.
    #[cfg(windows)]
    let result = win32::fix_separators(result.as_path());
    Some(result)
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
