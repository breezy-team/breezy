use lazy_static::lazy_static;
use regex::Regex;
use std::collections::HashMap;

lazy_static! {
    static ref URL_SCHEME_RE: Regex =
        Regex::new(r"^(?P<scheme>[^:/]{2,}):(//)?(?P<path>.*)$").unwrap();
}

pub enum Error {
    AboveRoot(String, String),
    SubsegmentMissesEquals(String),
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
            if split.is_none() {
                return (String::new(), url.to_string());
            } else {
                let (head, tail) = split.unwrap();
                return (head.to_string(), tail.to_string());
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
        let (url_base, path) = _win32_extract_drive_letter(url_base, path);
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
    if split.is_none() {
        (url_base.to_string(), path.to_string())
    } else {
        let (head, tail) = split.unwrap();
        (url_base.to_string() + head, tail.to_string())
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
        return _win32_strip_local_trailing_slash(url);
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
    if path.len() > 1 && path[path.len() - 1] == "" {
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

    let (mut scheme_end, path_start) = find_scheme_and_separator(base);
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
            scheme_end = arg_scheme_end;
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
