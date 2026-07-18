//! Provides a shorthand for referring to bugs on a variety of bug trackers.
//!
//! 'commit --fixes' stores references to bugs as a <bug_url> -> <bug_status>
//! mapping in the properties for that revision.
//!
//! However, it's inconvenient to type out full URLs for bugs on the command line,
//! particularly given that many users will be using only a single bug tracker per
//! branch.
//!
//! Thus, this module provides a registry of types of bug tracker (e.g. Launchpad,
//! Trac). Given an abbreviated name (e.g. 'lp', 'twisted') and a branch with
//! configuration information, these tracker types can return an instance capable
//! of converting bug IDs into URLs.

const BUGS_HELP: &str = r#"\
When making a commit, metadata about bugs fixed by that change can be
recorded by using the ``--fixes`` option. For each bug marked as fixed, an
entry is included in the 'bugs' revision property stating '<url> <status>'.
(The only ``status`` value currently supported is ``fixed.``)

The ``--fixes`` option allows you to specify a bug tracker and a bug identifier
rather than a full URL. This looks like::

    bzr commit --fixes <tracker>:<id>

or::

    bzr commit --fixes <id>

where "<tracker>" is an identifier for the bug tracker, and "<id>" is the
identifier for that bug within the bugtracker, usually the bug number.
If "<tracker>" is not specified the ``bugtracker`` set in the branch
or global configuration is used.

Bazaar knows about a few bug trackers that have many users. If
you use one of these bug trackers then there is no setup required to
use this feature, you just need to know the tracker identifier to use.
These are the bugtrackers that are built in:

  ============================ ============ ============
  URL                          Abbreviation Example
  ============================ ============ ============
  https://bugs.launchpad.net/  lp           lp:12345
  http://bugs.debian.org/      deb          deb:12345
  http://bugzilla.gnome.org/   gnome        gnome:12345
  ============================ ============ ============

For the bug trackers not listed above configuration is required.
Support for generating the URLs for any project using Bugzilla or Trac
is built in, along with a template mechanism for other bugtrackers with
simple URL schemes. If your bug tracker can't be described by one
of the schemes described below then you can write a plugin to support
it.

If you use Bugzilla or Trac, then you only need to set a configuration
variable which contains the base URL of the bug tracker. These options
can go into ``breezy.conf``, ``branch.conf`` or into a branch-specific
configuration section in ``locations.conf``.  You can set up these values
for each of the projects you work on.

Note: As you provide a short name for each tracker, you can specify one or
more bugs in one or more trackers at commit time if you wish.

Launchpad
---------

Use ``bzr commit --fixes lp:2`` to record that this commit fixes bug 2.

bugzilla_<tracker>_url
----------------------

If present, the location of the Bugzilla bug tracker referred to by
<tracker>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    bugzilla_squid_url = http://bugs.squid-cache.org

would allow ``bzr commit --fixes squid:1234`` to mark Squid's bug 1234 as
fixed.

trac_<tracker>_url
------------------

If present, the location of the Trac instance referred to by
<tracker>. This option can then be used together with ``bzr commit
--fixes`` to mark bugs in that tracker as being fixed by that commit. For
example::

    trac_twisted_url = http://www.twistedmatrix.com/trac

would allow ``bzr commit --fixes twisted:1234`` to mark Twisted's bug 1234 as
fixed.

bugtracker_<tracker>_url
------------------------

If present, the location of a generic bug tracker instance referred to by
<tracker>. The location must contain an ``{id}`` placeholder,
which will be replaced by a specific bug ID. This option can then be used
together with ``bzr commit --fixes`` to mark bugs in that tracker as being
fixed by that commit. For example::

    bugtracker_python_url = http://bugs.python.org/issue{id}

would allow ``bzr commit --fixes python:1234`` to mark bug 1234 in Python's
Roundup bug tracker as fixed, or::

    bugtracker_cpan_url = http://rt.cpan.org/Public/Bug/Display.html?id={id}

would allow ``bzr commit --fixes cpan:1234`` to mark bug 1234 in CPAN's
RT bug tracker as fixed, or::

    bugtracker_hudson_url = http://issues.hudson-ci.org/browse/{id}

would allow ``bzr commit --fixes hudson:HUDSON-1234`` to mark bug HUDSON-1234
in Hudson's JIRA bug tracker as fixed.
"#;

inventory::submit! {
    crate::help::HelpTopic::new(
        crate::help::Section::List,
        "bugs",
        "Bug tracker settings",
        crate::help::HelpContents::Text(BUGS_HELP),
    )
}

/// Errors raised while resolving bug identifiers into URLs or while
/// (de)serialising the ``bugs`` revision property.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// A bug identifier could not be parsed.
    MalformedBugIdentifier {
        /// The identifier that could not be parsed.
        bug_id: String,
        /// Why the identifier was rejected.
        reason: String,
    },
    /// A bug tracker URL template does not contain the ``{id}`` placeholder.
    InvalidBugTrackerUrl {
        /// The tracker's abbreviated name.
        abbreviation: String,
        /// The offending URL template.
        url: String,
    },
    /// A bug URL contains a space and so cannot be encoded.
    InvalidBugUrl {
        /// The offending URL.
        url: String,
    },
    /// A line in the bugs property could not be split into url and status.
    InvalidLineInBugsProperty {
        /// The malformed line.
        line: String,
    },
    /// A bug status is not one of the allowed values.
    InvalidBugStatus {
        /// The unrecognised status.
        status: String,
    },
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::MalformedBugIdentifier { bug_id, reason } => write!(
                f,
                "Did not understand bug identifier {bug_id}: {reason}. \
                 See \"brz help bugs\" for more information on this feature."
            ),
            Error::InvalidBugTrackerUrl { abbreviation, url } => write!(
                f,
                "The URL for bug tracker \"{abbreviation}\" doesn't contain {{id}}: {url}"
            ),
            Error::InvalidBugUrl { url } => write!(f, "Invalid bug URL: {url}"),
            Error::InvalidLineInBugsProperty { line } => {
                write!(f, "Invalid line in bugs property: '{line}'")
            }
            Error::InvalidBugStatus { status } => write!(f, "Invalid bug status: '{status}'"),
        }
    }
}

impl std::error::Error for Error {}

/// Check that a bug id is a plain integer, as required by
/// [`unique_integer_bug_url`] and the Trac/Bugzilla trackers.
pub fn check_integer_bug_id(bug_id: &str) -> Result<(), Error> {
    if bug_id.parse::<i64>().is_err() {
        return Err(Error::MalformedBugIdentifier {
            bug_id: bug_id.to_string(),
            reason: "Must be an integer".to_string(),
        });
    }
    Ok(())
}

/// Check that a bug id has the ``project/id`` shape, where ``id`` is an
/// integer, as required by [`project_integer_bug_url`].
pub fn check_project_integer_bug_id(bug_id: &str) -> Result<(), Error> {
    let Some((_project, id)) = bug_id.rsplit_once('/') else {
        return Err(Error::MalformedBugIdentifier {
            bug_id: bug_id.to_string(),
            reason: "Expected format: project/id".to_string(),
        });
    };
    if id.parse::<i64>().is_err() {
        return Err(Error::MalformedBugIdentifier {
            bug_id: id.to_string(),
            reason: "Bug id must be an integer".to_string(),
        });
    }
    Ok(())
}

/// Build the bug URL for a [`UniqueIntegerBugTracker`]-style tracker by
/// appending the (validated integer) bug id to the base URL.
pub fn unique_integer_bug_url(base_url: &str, bug_id: &str) -> Result<String, Error> {
    check_integer_bug_id(bug_id)?;
    Ok(format!("{base_url}{bug_id}"))
}

/// Build the bug URL for a [`ProjectIntegerBugTracker`]-style tracker by
/// substituting ``{project}`` and ``{id}`` into the base URL template.
pub fn project_integer_bug_url(
    abbreviation: &str,
    base_url: &str,
    bug_id: &str,
) -> Result<String, Error> {
    check_project_integer_bug_id(bug_id)?;
    let (project, id) = bug_id
        .rsplit_once('/')
        .expect("check_project_integer_bug_id guarantees a '/'");
    if !base_url.contains("{id}") || !base_url.contains("{project}") {
        return Err(Error::InvalidBugTrackerUrl {
            abbreviation: abbreviation.to_string(),
            url: base_url.to_string(),
        });
    }
    Ok(base_url.replace("{project}", project).replace("{id}", id))
}

/// Build the bug URL for a URL-parametrized integer tracker (Trac, Bugzilla):
/// join the configured base URL with the tracker's bug area and append the
/// (validated integer) bug id.
pub fn url_parametrized_integer_bug_url(
    base_url: &str,
    bug_area: &str,
    bug_id: &str,
) -> Result<String, Error> {
    check_integer_bug_id(bug_id)?;
    url_parametrized_bug_url(base_url, bug_area, bug_id)
}

/// Build the bug URL for a URL-parametrized tracker without integer
/// validation: join the base URL with the bug area and append the bug id.
pub fn url_parametrized_bug_url(
    base_url: &str,
    bug_area: &str,
    bug_id: &str,
) -> Result<String, Error> {
    let joined =
        dromedary::urlutils::join(base_url, &[bug_area]).map_err(|e| Error::InvalidBugUrl {
            url: format!("{base_url}: {e:?}"),
        })?;
    Ok(format!("{joined}{bug_id}"))
}

/// Build the bug URL for a generic tracker by substituting ``{id}`` into the
/// configured URL template.
pub fn generic_bug_url(abbreviation: &str, base_url: &str, bug_id: &str) -> Result<String, Error> {
    if !base_url.contains("{id}") {
        return Err(Error::InvalidBugTrackerUrl {
            abbreviation: abbreviation.to_string(),
            url: base_url.to_string(),
        });
    }
    Ok(base_url.replace("{id}", bug_id))
}

/// A bug fix status recorded in the ``bugs`` revision property.
pub const FIXED: &str = "fixed";
/// A related-bug status recorded in the ``bugs`` revision property.
pub const RELATED: &str = "related";

fn is_allowed_status(status: &str) -> bool {
    status == FIXED || status == RELATED
}

/// Encode ``(url, tag)`` pairs into the value of a revision's ``bugs``
/// property: one ``<url> <tag>`` line per pair.
///
/// Returns [`Error::InvalidBugUrl`] if any url contains a space, since a space
/// would make the line ambiguous on decode.
pub fn encode_fixes_bug_urls<'a, I>(bug_urls: I) -> Result<String, Error>
where
    I: IntoIterator<Item = (&'a str, &'a str)>,
{
    let mut lines = Vec::new();
    for (url, tag) in bug_urls {
        if url.contains(' ') {
            return Err(Error::InvalidBugUrl {
                url: url.to_string(),
            });
        }
        lines.push(format!("{url} {tag}"));
    }
    Ok(lines.join("\n"))
}

/// Decode the lines of a ``bugs`` revision property into ``(url, status)``
/// pairs.
///
/// Each line must contain exactly a url and an allowed status separated by
/// whitespace; anything else is [`Error::InvalidLineInBugsProperty`] or
/// [`Error::InvalidBugStatus`].
pub fn decode_bug_urls<'a, I>(bug_lines: I) -> Result<Vec<(String, String)>, Error>
where
    I: IntoIterator<Item = &'a str>,
{
    let mut result = Vec::new();
    for line in bug_lines {
        // Mirror Python's ``line.split(None, 2)`` followed by a two-way
        // unpack: whitespace runs collapse, and a line with three or more
        // fields fails the unpack rather than silently dropping the extra.
        let fields: Vec<&str> = line.split_whitespace().collect();
        let [url, status] = fields[..] else {
            return Err(Error::InvalidLineInBugsProperty {
                line: line.to_string(),
            });
        };
        if !is_allowed_status(status) {
            return Err(Error::InvalidBugStatus {
                status: status.to_string(),
            });
        }
        result.push((url.to_string(), status.to_string()));
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unique_integer_appends_id() {
        assert_eq!(
            unique_integer_bug_url("http://bugs.example.com/foo", "1234").unwrap(),
            "http://bugs.example.com/foo1234"
        );
    }

    #[test]
    fn unique_integer_rejects_non_integer() {
        assert_eq!(
            unique_integer_bug_url("http://bugs.example.com/", "red").unwrap_err(),
            Error::MalformedBugIdentifier {
                bug_id: "red".to_string(),
                reason: "Must be an integer".to_string(),
            }
        );
    }

    #[test]
    fn project_integer_substitutes() {
        assert_eq!(
            project_integer_bug_url(
                "github",
                "https://github.com/{project}/issues/{id}",
                "a/b/1234"
            )
            .unwrap(),
            "https://github.com/a/b/issues/1234"
        );
    }

    #[test]
    fn project_integer_rejects_missing_project() {
        assert!(matches!(
            check_project_integer_bug_id("1234"),
            Err(Error::MalformedBugIdentifier { .. })
        ));
    }

    #[test]
    fn generic_requires_id_placeholder() {
        assert_eq!(
            generic_bug_url("foo", "http://x/view.html", "1234").unwrap_err(),
            Error::InvalidBugTrackerUrl {
                abbreviation: "foo".to_string(),
                url: "http://x/view.html".to_string(),
            }
        );
        assert_eq!(
            generic_bug_url("foo", "http://x/{id}/view.html", "ABC-1234").unwrap(),
            "http://x/ABC-1234/view.html"
        );
    }

    #[test]
    fn url_parametrized_joins_area() {
        assert_eq!(
            url_parametrized_integer_bug_url("http://bugs.example.com/trac", "ticket/", "1234")
                .unwrap(),
            "http://bugs.example.com/trac/ticket/1234"
        );
    }

    #[test]
    fn encode_roundtrip() {
        assert_eq!(
            encode_fixes_bug_urls([
                ("http://example.com/bugs/1", "fixed"),
                ("http://example.com/bugs/2", "related"),
            ])
            .unwrap(),
            "http://example.com/bugs/1 fixed\nhttp://example.com/bugs/2 related"
        );
        assert_eq!(encode_fixes_bug_urls([]).unwrap(), "");
    }

    #[test]
    fn encode_rejects_space() {
        assert_eq!(
            encode_fixes_bug_urls([("http://example.com/bugs/ 1", "fixed")]).unwrap_err(),
            Error::InvalidBugUrl {
                url: "http://example.com/bugs/ 1".to_string(),
            }
        );
    }

    #[test]
    fn decode_pairs() {
        assert_eq!(
            decode_bug_urls(["http://example.com/bugs/1 fixed"]).unwrap(),
            vec![("http://example.com/bugs/1".to_string(), "fixed".to_string())]
        );
        assert_eq!(decode_bug_urls([]).unwrap(), Vec::<(String, String)>::new());
    }

    #[test]
    fn decode_rejects_three_fields() {
        assert_eq!(
            decode_bug_urls(["http://example.com/bugs/ 1 fixed"]).unwrap_err(),
            Error::InvalidLineInBugsProperty {
                line: "http://example.com/bugs/ 1 fixed".to_string(),
            }
        );
    }

    #[test]
    fn decode_rejects_bad_status() {
        assert!(matches!(
            decode_bug_urls(["http://example.com/bugs/1 bogus"]),
            Err(Error::InvalidBugStatus { .. })
        ));
    }
}
