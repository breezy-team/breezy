use std::collections::HashMap;
use std::path::{Component, Path, PathBuf};

pub mod win32 {
    use lazy_static::lazy_static;
    use regex::Regex;
    use std::path::{Path, PathBuf};

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
}

pub mod posix {
    use std::collections::HashMap;
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
                    path = PathBuf::from("/");
                }
                Component::CurDir | Component::Prefix(_) => {}
                Component::ParentDir => {
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
}

pub fn abspath(path: &Path) -> Result<PathBuf, std::io::Error> {
    #[cfg(windows)]
    return win32::abspath(path);

    #[cfg(not(windows))]
    return posix::abspath(path);
}

pub fn normpath<P: AsRef<Path>>(path: P) -> PathBuf {
    let mut stack = Vec::new();

    for component in path.as_ref().components() {
        match component {
            Component::Prefix(_) => {
                stack.clear();
                stack.push(component.as_os_str());
            }
            Component::RootDir => {
                stack.clear();
                stack.push(component.as_os_str());
            }
            Component::CurDir => {}
            Component::ParentDir => {
                if stack.len() > 1 {
                    stack.pop();
                }
            }
            Component::Normal(c) => {
                stack.push(c);
            }
        }
    }

    let mut result = PathBuf::new();
    for c in stack {
        result.push(c);
    }
    result
}

#[cfg(not(windows))]
pub const MIN_ABS_PATHLENGTH: usize = 1;

#[cfg(windows)]
pub const MIN_ABS_PATHLENGTH: usize = 3;

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

pub fn realpath(f: &Path) -> std::io::Result<PathBuf> {
    #[cfg(windows)]
    return win32::realpath(f);

    #[cfg(not(windows))]
    return posix::realpath(f);
}
