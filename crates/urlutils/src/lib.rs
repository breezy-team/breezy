use lazy_static::lazy_static;
use regex::Regex;
use std::collections::HashMap;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};

lazy_static! {
    static ref URL_SCHEME_RE: Regex =
        Regex::new(r"^(?P<scheme>[^:/]{2,}):(//)?(?P<path>.*)$").unwrap();
    static ref URL_HEX_ESCAPES_RE: Regex = Regex::new(r"(%[0-9a-fA-F]{2})").unwrap();
}

#[derive(Debug)]
pub enum Error {
    AboveRoot(String, String),
    SubsegmentMissesEquals(String),
    UnsafeCharacters(char),
    IoError(std::io::Error),
    SegmentParameterKeyContainsEquals(String, String),
    SegmentParameterContainsComma(String, Vec<String>),
    NotLocalUrl(String),
    InvalidUNCUrl(String),
    UrlNotAscii(String),
    InvalidWin32LocalUrl(String),
    InvalidWin32Path(String),
    UrlTooShort(String),
    PathNotChild(String, String),
}

type Result<K> = std::result::Result<K, Error>;

/// Split a URL into its parent directory and a child directory.
///
/// Args:
///   url: A relative or absolute URL
///   exclude_trailing_slash: Strip off a final '/' if it is part
///     of the path (but not if it is part of the protocol specification)
///
/// Returns: (parent_url, child_dir).  child_dir may be the empty string if
///     we're at the root.
pub fn split(url: &str, exclude_trailing_slash: bool) -> (String, String) {
    let (scheme_loc, first_path_slash) = find_scheme_and_separator(url);

    if first_path_slash.is_none() {
        // We have either a relative path, or no separating slash
        if scheme_loc.is_none() {
            // Relative path
            let mut url = url;
            if exclude_trailing_slash && url.ends_with('/') {
                url = &url[..url.len() - 1];
            }
            let split = url.rsplit_once('/').map(|(head, tail)| {
                if head.is_empty() {
                    ("/", tail)
                } else {
                    (head, tail)
                }
            });
            match split {
                None => return (String::new(), url.to_string()),
                Some((head, tail)) => return (head.to_string(), tail.to_string()),
            }
        } else {
            // Scheme with no path
            return (url.to_string(), String::new());
        }
    }

    // We have a fully defined path
    let url_base = &url[..first_path_slash.unwrap()]; // http://host, file://
    let mut path = &url[first_path_slash.unwrap()..]; // /file/foo

    #[cfg(target_os = "win32")]
    if url.starts_with("file:///") {
        // Strip off the drive letter
        // url_base is currently file://
        // path is currently /C:/foo
        let (url_base, path) = extract_drive_letter(url_base, path);
        // now it should be file:///C: and /foo
    }

    if exclude_trailing_slash && path.len() > 1 && path.ends_with('/') {
        path = &path[..path.len() - 1];
    }
    let split = path.rsplit_once('/').map(|(head, tail)| {
        if head.is_empty() {
            ("/", tail)
        } else {
            (head, tail)
        }
    });
    match split {
        None => (url_base.to_string(), path.to_string()),
        Some((head, tail)) => (url_base.to_string() + head, tail.to_string()),
    }
}

/// Find the scheme separator (://) and the first path separator
///
/// This is just a helper functions for other path utilities.
/// It could probably be replaced by urlparse
pub fn find_scheme_and_separator(url: &str) -> (Option<usize>, Option<usize>) {
    if let Some(m) = URL_SCHEME_RE.captures(url) {
        let scheme = m.name("scheme").unwrap().as_str();
        let path = m.name("path").unwrap().as_str();

        // Find the path separating slash
        // (first slash after the ://)
        if let Some(first_path_slash) = path.find('/') {
            (
                Some(scheme.len()),
                Some(first_path_slash + m.name("path").unwrap().start()),
            )
        } else {
            (Some(scheme.len()), None)
        }
    } else {
        (None, None)
    }
}

pub fn is_url(url: &str) -> bool {
    // Tests whether a URL is in actual fact a URL.
    URL_SCHEME_RE.is_match(url)
}

/// Strip trailing slash, except for root paths.
///
/// The definition of 'root path' is platform-dependent.
/// This assumes that all URLs are valid netloc urls, such that they
/// form:
/// scheme://host/path
/// It searches for ://, and then refuses to remove the next '/'.
/// It can also handle relative paths
/// Examples:
///     path/to/foo       => path/to/foo
///     path/to/foo/      => path/to/foo
///     http://host/path/ => http://host/path
///     http://host/path  => http://host/path
///     http://host/      => http://host/
///     file:///          => file:///
///     file:///foo/      => file:///foo
///     # This is unique on win32 platforms, and is the only URL
///     # format which does it differently.
///     file:///c|/       => file:///c:/
pub fn strip_trailing_slash(url: &str) -> &str {
    if !url.ends_with('/') {
        // Nothing to do
        return url;
    }

    #[cfg(target_os = "windows")]
    if url.starts_with("file://") {
        return win32::strip_local_trailing_slash(url);
    }

    let (scheme_loc, first_path_slash) = find_scheme_and_separator(url);
    if scheme_loc.is_none() {
        // This is a relative path, as it has no scheme
        // so just chop off the last character
        &url[..url.len() - 1]
    } else if first_path_slash.is_none() || first_path_slash.unwrap() == url.len() - 1 {
        // Don't chop off anything if the only slash is the path
        // separating slash
        url
    } else {
        &url[..url.len() - 1]
    }
}

/// Join URL path segments to a URL path segment.
///
/// This is somewhat like osutils.joinpath, but intended for URLs.
///
/// XXX: this duplicates some normalisation logic, and also duplicates a lot of
/// path handling logic that already exists in some Transport implementations.
/// We really should try to have exactly one place in the code base responsible
/// for combining paths of URLs.
pub fn joinpath(base: &str, args: &[&str]) -> Result<String> {
    let mut path = base.split('/').collect::<Vec<&str>>();
    if path.len() > 1 && path[path.len() - 1].is_empty() {
        // If the path ends in a trailing /, remove it.
        path.pop();
    }
    for arg in args {
        if arg.starts_with('/') {
            path = vec![];
        }
        for chunk in arg.split('/') {
            if chunk == "." {
                continue;
            } else if chunk == ".." {
                if path == [""] {
                    return Err(Error::AboveRoot(base.to_string(), args.join("/")));
                }
                path.pop();
            } else {
                path.push(chunk);
            }
        }
    }
    Ok(if path == [""] {
        "/".to_string()
    } else {
        path.join("/")
    })
}

/// Return the last component of a URL.
///
/// Args:
///  url The URL in question
///  exclude_trailing_slash: If the url looks like "path/to/foo/",
///   ignore the final slash and return 'foo' rather than ''
/// Returns:
///   Just the final component of the URL. This can return ''
///   if you don't exclude_trailing_slash, or if you are at the
///   root of the URL.
pub fn basename(url: &str, exclude_trailing_slash: bool) -> String {
    split(url, exclude_trailing_slash).1
}

/// Return the parent directory of the given path.
///
/// Args:
///   url: Relative or absolute URL
///   exclude_trailing_slash: Remove a final slash (treat http://host/foo/ as http://host/foo, but
///   http://host/ stays http://host/)
///
/// Returns: Everything in the URL except the last path chunk
// jam 20060502: This was named dirname to be consistent
// with the os functions, but maybe "parent" would be better
pub fn dirname(url: &str, exclude_trailing_slash: bool) -> String {
    split(url, exclude_trailing_slash).0
}

/// Create a URL by joining sections.
///
/// This will normalize '..', assuming that paths are absolute
/// (it assumes no symlinks in either path)
///
/// If any of *args is an absolute URL, it will be treated correctly.
/// Example:
///     join('http://foo', 'http://bar') => 'http://bar'
///     join('http://foo', 'bar') => 'http://foo/bar'
///     join('http://foo', 'bar', '../baz') => 'http://foo/baz'
pub fn join<'a>(mut base: &'a str, args: &[&'a str]) -> Result<String> {
    if args.is_empty() {
        return Ok(base.to_string());
    }

    let (scheme_end, path_start) = find_scheme_and_separator(base);
    let mut path_start = if scheme_end.is_none() && path_start.is_none() {
        0
    } else if path_start.is_none() {
        base.len()
    } else {
        path_start.unwrap()
    };
    let mut path = base[path_start..].to_string();

    for arg in args {
        let (arg_scheme_end, arg_path_start) = find_scheme_and_separator(arg);
        let arg_path_start = if arg_scheme_end.is_none() && arg_path_start.is_none() {
            0
        } else if arg_path_start.is_none() {
            arg.len()
        } else {
            arg_path_start.unwrap()
        };

        if arg_scheme_end.is_some() {
            base = arg;
            path = arg[arg_path_start..].to_string();
            path_start = arg_path_start;
        } else {
            path = joinpath(path.as_str(), vec![*arg].as_slice())?;
        }
    }

    Ok(base[..path_start].to_string() + &path)
}

/// Split the subsegment of the last segment of a URL.
///
///Args:
///  url: A relative or absolute URL
///Returns: (url, subsegments)
pub fn split_segment_parameters_raw(url: &str) -> (&str, Vec<&str>) {
    // GZ 2011-11-18: Dodgy removing the terminal slash like this, function
    // operates on urls not url+segments, and Transport classes
    // should not be blindly adding slashes in the first place.
    let lurl = strip_trailing_slash(url);
    let segment_start = lurl.rfind('/').map_or_else(|| 0, |i| i + 1);
    if !lurl[segment_start..].contains(',') {
        return (url, vec![]);
    }
    let mut iter = lurl[segment_start..].split(',');
    let first = iter.next().unwrap();
    (
        &lurl[..segment_start + first.len()],
        iter.map(|s| s.trim()).collect(),
    )
}

/// Split the segment parameters of the last segment of a URL.
///
/// Args:
///   url: A relative or absolute URL
/// Returns: (url, segment_parameters)
pub fn split_segment_parameters(
    url: &str,
) -> Result<(&str, std::collections::HashMap<&str, &str>)> {
    let (base_url, subsegments) = split_segment_parameters_raw(url);
    let parameters = subsegments
        .iter()
        .map(|subsegment| {
            subsegment
                .split_once('=')
                .ok_or_else(|| Error::SubsegmentMissesEquals(subsegment.to_string()))
                .map(|(key, value)| (key.trim(), value.trim()))
        })
        .collect::<Result<HashMap<&str, &str>>>()?;
    Ok((base_url, parameters))
}

/// Strip the segment parameters from a URL.
///
/// Args:
///   url: A relative or absolute URL
/// Returns: url
pub fn strip_segment_parameters(url: &str) -> &str {
    split_segment_parameters_raw(url).0
}

/// Create a new URL by adding subsegments to an existing one.
///
/// This adds the specified subsegments to the last path in the specified
/// base URL. The subsegments should be bytestrings.
///
/// Note: You probably want to use join_segment_parameters instead.
pub fn join_segment_parameters_raw(base: &str, subsegments: &[&str]) -> Result<String> {
    if subsegments.is_empty() {
        return Ok(base.to_string());
    }

    for subsegment in subsegments {
        if subsegment.contains(',') {
            return Err(Error::SegmentParameterContainsComma(
                base.to_string(),
                subsegments.iter().map(|s| s.to_string()).collect(),
            ));
        }
    }

    Ok(format!("{},{}", base, subsegments.join(",")))
}

/// Create a new URL by adding segment parameters to an existing one.
///
/// The parameters of the last segment in the URL will be updated; if a
/// parameter with the same key already exists it will be overwritten.
///
/// Args:
///   url: A URL, as string
///    parameters: Dictionary of parameters, keys and values as bytestrings
pub fn join_segment_parameters(url: &str, parameters: &HashMap<&str, &str>) -> Result<String> {
    let (base, existing_parameters) = split_segment_parameters(url)?;
    let mut new_parameters = existing_parameters.clone();

    for (key, value) in parameters {
        if key.contains('=') {
            return Err(Error::SegmentParameterKeyContainsEquals(
                url.to_string(),
                key.to_string(),
            ));
        }

        new_parameters.insert(key, value);
    }

    let mut items: Vec<_> = new_parameters.iter().collect();
    items.sort_by(|a, b| a.0.cmp(b.0));

    let sorted_parameters: Vec<_> = items
        .iter()
        .map(|(key, value)| format!("{}={}", key, value))
        .collect();

    join_segment_parameters_raw(
        base,
        &sorted_parameters
            .iter()
            .map(|s| s.as_str())
            .collect::<Vec<_>>(),
    )
}

/// Return a path to other from base.
///
/// If other is unrelated to base, return other. Else return a relative path.
/// This assumes no symlinks as part of the url.
pub fn relative_url(base: &str, other: &str) -> String {
    let (_, base_first_slash) = find_scheme_and_separator(base);
    if base_first_slash.is_none() {
        return other.to_string();
    }

    let (_, other_first_slash) = find_scheme_and_separator(other);
    if other_first_slash.is_none() {
        return other.to_string();
    }

    // this takes care of differing schemes or hosts
    let base_scheme = &base[..base_first_slash.unwrap()];
    let other_scheme = &other[..other_first_slash.unwrap()];
    if base_scheme != other_scheme {
        return other.to_string();
    }

    #[cfg(target_os = "windows")]
    if base_scheme == "file://" {
        let base_drive = &base[base_first_slash.unwrap() + 1..base_first_slash.unwrap() + 3];
        let other_drive = &other[other_first_slash.unwrap() + 1..other_first_slash.unwrap() + 3];
        if base_drive != other_drive {
            return other.to_string();
        }
    }

    let mut base_path = &base[base_first_slash.unwrap() + 1..];
    let other_path = &other[other_first_slash.unwrap() + 1..];

    if base_path.ends_with('/') {
        base_path = &base_path[..base_path.len() - 1];
    }

    let mut base_sections: Vec<_> = base_path.split('/').collect();
    let mut other_sections: Vec<_> = other_path.split('/').collect();

    if base_sections == [""] {
        base_sections = Vec::new();
    }
    if other_sections == [""] {
        other_sections = Vec::new();
    }

    let mut output_sections = Vec::new();
    for (b, o) in base_sections.iter().zip(other_sections.iter()) {
        if b != o {
            break;
        }
        output_sections.push(b);
    }

    let match_len = output_sections.len();
    let mut output_sections: Vec<_> = base_sections[match_len..].iter().map(|_x| "..").collect();
    output_sections.extend_from_slice(&other_sections[match_len..]);

    let ret = output_sections.join("/");
    if ret.is_empty() {
        ".".to_string()
    } else {
        ret
    }
}

fn char_is_safe(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.' || c == '~'
}

fn unescape_safe_chars(captures: &regex::Captures) -> String {
    let hex_digits = &captures[0][1..];
    let char_code = u8::from_str_radix(hex_digits, 16).unwrap();
    let character = char::from(char_code);
    if char_is_safe(character) {
        character.to_string()
    } else {
        captures[0].to_uppercase()
    }
}

/// Transform a Transport-relative path to a remote absolute path.
///
/// This does not handle substitution of ~ but does handle '..' and '.'
/// components.
///
/// # Examples
///
///  use breezy_urlutils::combine_paths;
///  assert_eq!("/home/sarah/project/foo", combine_paths("/home/sarah", "project/foo"));
///  assert_eq!("/etc", combine_paths("/home/sarah", "../../etc"));
///  assert_eq!("/etc", combine_paths("/home/sarah", "/etc"));
///
/// # Arguments
///
/// * `base_path` - base path
/// * `relpath` - relative path
///
/// # Returns
///
/// urlencoded string for final path.
pub fn combine_paths(base_path: &str, relpath: &str) -> String {
    let relpath = URL_HEX_ESCAPES_RE
        .replace_all(relpath, unescape_safe_chars)
        .to_string();

    let mut base_parts: Vec<&str> = if relpath.starts_with('/') {
        vec![]
    } else {
        base_path.split('/').collect()
    };

    if base_parts.last() == Some(&"") {
        base_parts.pop();
    }

    for p in relpath.split('/') {
        match p {
            ".." => {
                if let Some(last) = base_parts.last() {
                    if !last.is_empty() {
                        base_parts.pop();
                    }
                }
            }
            "." | "" => (),
            _ => base_parts.push(p),
        }
    }

    let mut path = base_parts.join("/");
    if !path.starts_with('/') {
        path.insert(0, '/');
    }
    path
}

/// Make sure that a path string is in fully normalized URL form.
///
/// This handles URLs which have unicode characters, spaces,
/// special characters, etc.
///
/// It has two basic modes of operation, depending on whether the
/// supplied string starts with a url specifier (scheme://) or not.
/// If it does not have a specifier it is considered a local path,
/// and will be converted into a file:/// url. Non-ascii characters
/// will be encoded using utf-8.
/// If it does have a url specifier, it will be treated as a "hybrid"
/// URL. Basically, a URL that should have URL special characters already
/// escaped (like +?&# etc), but may have unicode characters, etc
/// which would not be valid in a real URL.
///
/// Args:
///   url: Either a hybrid URL or a local path
/// Returns: A normalized URL which only includes 7-bit ASCII characters.
pub fn normalize_url(url: &str) -> Result<String> {
    let (scheme_end, path_start) = find_scheme_and_separator(url);

    if scheme_end.is_none() {
        local_path_to_url(url).map_err(Error::IoError)
    } else {
        let prefix = &url[..path_start.unwrap()];
        let path = &url[path_start.unwrap()..];

        // These characters should not be escaped
        const URL_SAFE_CHARACTERS: &[u8] = b"_.-!~*'()/;?:@&=+$,%#";

        let path = path
            .as_bytes()
            .iter()
            .map(|c| {
                if !c.is_ascii_alphanumeric() && !URL_SAFE_CHARACTERS.contains(c) {
                    format!("%{:02X}", c)
                } else {
                    (*c as char).to_string()
                }
            })
            .collect::<String>();
        let path = URL_HEX_ESCAPES_RE.replace_all(path.as_str(), unescape_safe_chars);
        Ok(prefix.to_string() + path.as_ref())
    }
}

pub fn escape(relpath: &[u8], safe: Option<&str>) -> String {
    let mut result = String::new();
    let safe = safe.unwrap_or("/~").as_bytes();
    for b in relpath {
        if char_is_safe(char::from(*b)) || safe.contains(b) {
            result.push(char::from(*b));
        } else {
            result.push_str(&format!("%{:02X}", *b));
        }
    }
    result
}

pub fn unescape(url: &str) -> Result<String> {
    use percent_encoding::percent_decode_str;

    if !url.is_ascii() {
        return Err(Error::UrlNotAscii(url.to_string()));
    }
    Ok(percent_decode_str(url)
        .decode_utf8()
        .map(|s| s.to_string())
        .unwrap_or_else(|_| url.to_string()))
}

pub mod win32 {
    use std::path::{Path, PathBuf};

    /// Convert a local path like ./foo into a URL like file:///C:/path/to/foo
    ///
    /// This also handles transforming escaping unicode characters, etc.
    pub fn local_path_to_url<P: AsRef<Path>>(path: P) -> std::io::Result<String> {
        if path.as_ref().as_os_str() == "/" {
            return Ok("file:///".to_string());
        }
        let win32_path = breezy_osutils::path::win32::abspath(path.as_ref())?;
        let win32_path = win32_path.as_path().to_str().unwrap();
        if win32_path.starts_with("//") {
            Ok(format!(
                "file:{}",
                super::escape(win32_path.as_bytes(), Some("/~"))
            ))
        } else {
            let drive = win32_path.chars().next().unwrap().to_ascii_uppercase();
            Ok(format!(
                "file:///{}:{}",
                drive,
                super::escape(win32_path[2..].as_bytes(), Some("/~"))
            ))
        }
    }

    /// Convert a url like file:///C:/path/to/foo into C:/path/to/foo
    pub fn local_path_from_url(url: &str) -> super::Result<PathBuf> {
        if !url.starts_with("file://") {
            return Err(super::Error::NotLocalUrl(url.to_string()));
        }
        let url = super::strip_segment_parameters(url);
        let win32_url = &url[5..];

        if !win32_url.starts_with("///") {
            if win32_url.len() < 3
                || win32_url.chars().nth(2).unwrap() == '/'
                || "|:".contains(win32_url.chars().nth(3).unwrap())
            {
                return Err(super::Error::InvalidUNCUrl(url.to_string()));
            }
            return Ok(super::unescape(win32_url)?.into());
        }

        // Allow empty paths so we can serve all roots
        if win32_url == "///" {
            return Ok(PathBuf::from("/"));
        }

        // Usual local path with drive letter
        if win32_url.len() < 6
            || !("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".contains(&win32_url[3..=3]))
            || !("|:".contains(win32_url.chars().nth(4).unwrap()))
            || win32_url.chars().nth(5) != Some('/')
        {
            return Err(super::Error::InvalidWin32LocalUrl(url.to_string()));
        }
        Ok(PathBuf::from(format!(
            "{}:{}",
            win32_url[3..=3].to_uppercase(),
            super::unescape(&win32_url[5..])?
        )))
    }

    const WIN32_MIN_ABS_FILEURL_LENGTH: usize = "file:///C:/".len();

    pub fn extract_drive_letter(url_base: &str, path: &str) -> super::Result<(String, String)> {
        if path.len() < 4
            || !":|".contains(path.chars().nth(2).unwrap())
            || path.chars().nth(3).unwrap() != '/'
        {
            return Err(super::Error::InvalidWin32Path(path.to_owned()));
        }
        let url_base = url_base.to_owned() + &path[0..3];
        let path = &path[3..];
        Ok((url_base, path.to_owned()))
    }

    pub fn strip_local_trailing_slash(url: &str) -> String {
        if url.len() > WIN32_MIN_ABS_FILEURL_LENGTH {
            url[..url.len() - 1].to_owned()
        } else {
            url.to_owned()
        }
    }
}

pub mod posix {
    use std::os::unix::ffi::OsStrExt;
    use std::path::{Path, PathBuf};

    /// Convert a local path like ./foo into a URL like file:///path/to/foo
    ///
    /// This also handles transforming escaping unicode characters, etc.
    pub fn local_path_to_url<P: AsRef<Path>>(path: P) -> std::io::Result<String> {
        let abs_path = breezy_osutils::path::posix::abspath(path.as_ref())?;
        let escaped_path = super::escape(abs_path.as_path().as_os_str().as_bytes(), Some("/~"));
        Ok(format!("file://{}", escaped_path))
    }

    const FILE_LOCALHOST_PREFIX: &str = "file://localhost";
    const PLAIN_FILE_PREFIX: &str = "file:///";

    pub fn local_path_from_url(url: &str) -> std::result::Result<PathBuf, super::Error> {
        let url = super::strip_segment_parameters(url);
        let path = if let Some(suffix) = url.strip_prefix(FILE_LOCALHOST_PREFIX) {
            suffix
        } else if url.starts_with(PLAIN_FILE_PREFIX) {
            &url[PLAIN_FILE_PREFIX.len() - 1..]
        } else {
            return Err(super::Error::NotLocalUrl(url.to_string()));
        };
        Ok(PathBuf::from(super::unescape(path)?))
    }
}

pub fn local_path_to_url<P: AsRef<Path>>(path: P) -> std::io::Result<String> {
    #[cfg(target_os = "win32")]
    return Ok(win32::local_path_to_url(path)?);
    #[cfg(unix)]
    return posix::local_path_to_url(path);
}

pub fn local_path_from_url(url: &str) -> Result<PathBuf> {
    #[cfg(target_os = "win32")]
    return Ok(win32::local_path_from_url(url)?);
    #[cfg(unix)]
    return posix::local_path_from_url(url);
}

/// Derive a TO_LOCATION given a FROM_LOCATION.
///
/// The normal case is a FROM_LOCATION of http://foo/bar => bar.
/// The Right Thing for some logical destinations may differ though
/// because no / may be present at all. In that case, the result is
/// the full name without the scheme indicator, e.g. lp:foo-bar => foo-bar.
/// This latter case also applies when a Windows drive
/// is used without a path, e.g. c:foo-bar => foo-bar.
/// If no /, path separator or : is found, the from_location is returned.
pub fn derive_to_location(from_location: &str) -> String {
    let from_location = strip_segment_parameters(from_location);
    if let Some(separator_index) = from_location.rfind('/') {
        let basename = &from_location[separator_index + 1..];
        return basename.trim_end_matches("/\\").to_string();
    } else if let Some(separator_index) = from_location.find(':') {
        return from_location[separator_index + 1..].to_string();
    } else {
        return from_location.to_string();
    }
}

#[cfg(target_os = "win32")]
pub const MIN_ABS_FILEURL_LENGTH: usize = "file:///C:".len();

#[cfg(not(target_os = "win32"))]
pub const MIN_ABS_FILEURL_LENGTH: usize = "file:///".len();

/// Compute just the relative sub-portion of a url
///
/// This assumes that both paths are already fully specified file:// URLs.
pub fn file_relpath(base: &str, path: &str) -> Result<String> {
    if base.len() < MIN_ABS_FILEURL_LENGTH {
        return Err(Error::UrlTooShort(base.to_string()));
    }
    let base: PathBuf = breezy_osutils::path::normpath(local_path_from_url(base)?);
    let path: PathBuf = breezy_osutils::path::normpath(local_path_from_url(path)?);

    let relpath = breezy_osutils::path::relpath(base.as_path(), path.as_path());
    if relpath.is_none() {
        return Err(Error::PathNotChild(
            path.display().to_string(),
            base.display().to_string(),
        ));
    }

    Ok(escape(relpath.unwrap().as_os_str().as_bytes(), None))
}
