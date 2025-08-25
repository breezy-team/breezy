use once_cell::sync::Lazy;
use std::collections::HashMap;
use std::fs::File;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::{RwLock, RwLockWriteGuard};

use encoding::all::UTF_8;
use gettext::{Catalog, ParseOptions};

static BACKEND: Lazy<RwLock<Arc<dyn TranslateBackend + Sync + Send>>> =
    Lazy::new(|| RwLock::new(Arc::new(NoopTranslateBackend)));

/// Trait for translation backends.
pub trait TranslateBackend {
    /// Returns the name of the backend.
    fn name(&self) -> &'static str;
    /// Translates a message id.
    fn gettext(&self, msgid: &str) -> String;
    /// Translates a message id with pluralization.
    fn ngettext(&self, msgid: &str, msgid_plural: &str, n: u32) -> String;
    /// Translates a message id for a specific textdomain.
    fn dgettext(&self, textdomain: &str, msgid: &str) -> String;
}

fn find_mo<P: AsRef<Path>>(textdomain: &str, lang: &str, locale_base: P) -> Option<PathBuf> {
    let mut locale = lang;
    let base = locale_base.as_ref();
    let tail: PathBuf = Path::new("LC_MESSAGES").join(format!("{}.mo", textdomain));
    let mut mopath = base.join(locale).join(&tail);
    let mut found = mopath.is_file();
    if !found && locale.contains(".") {
        if let Some((l1, _)) = locale.rsplit_once(".") {
            locale = l1;
            mopath = base.join(locale).join(&tail);
            found = mopath.is_file();
        };
    };
    if !found && locale.contains("_") {
        if let Some((l2, _)) = locale.rsplit_once("_") {
            locale = l2;
            mopath = base.join(locale).join(&tail);
            found = mopath.is_file();
        };
    };
    if found {
        Some(mopath)
    } else {
        None
    }
}

fn open_mo<P: AsRef<Path>>(
    textdomain: &str,
    lang: &str,
    locale_base: P,
) -> Result<File, io::Error> {
    match find_mo(textdomain, lang, &locale_base) {
        Some(mopath) => File::open(mopath),
        None => {
            let msg = format!(
                concat!(
                    "Cannot find compiled message catalog",
                    " for domain \"{}\", language \"{}\" in {}"
                ),
                textdomain,
                lang,
                &locale_base.as_ref().display()
            );
            Err(io::Error::new(io::ErrorKind::NotFound, msg))
        }
    }
}

fn parse<P: AsRef<Path>>(
    textdomain: &str,
    lang: &str,
    locale_base: P,
) -> Result<Catalog, gettext::Error> {
    let mofile = open_mo(textdomain, lang, locale_base);
    match mofile {
        Ok(file) => ParseOptions::new().force_encoding(UTF_8).parse(file),
        Err(err) => Err(gettext::Error::from(err)),
    }
}

struct Domains {
    locale_base: PathBuf,
    lang: String,
    catalogs: HashMap<String, Catalog>,
}

impl Domains {
    fn new() -> Self {
        Domains {
            locale_base: PathBuf::new(),
            lang: String::from("en"),
            catalogs: HashMap::new(),
        }
    }

    fn init<P: AsRef<Path>>(&mut self, lang: &str, locale_base: P) {
        self.lang = String::from(lang);
        self.locale_base = PathBuf::from(locale_base.as_ref());
        self.catalogs.clear();
    }

    fn catalog(&self, textdomain: &str) -> Option<&Catalog> {
        self.catalogs.get(&String::from(textdomain))
    }

    fn load<P: AsRef<Path>>(
        &mut self,
        textdomain: &str,
        locale_base: Option<P>,
    ) -> Result<(), gettext::Error> {
        let mut base = self.locale_base.to_path_buf();
        if let Some(locale_base) = locale_base {
            base = PathBuf::from(locale_base.as_ref());
        };
        let catalog = parse(textdomain, &self.lang, &base)?;
        self.catalogs.insert(String::from(textdomain), catalog);
        Ok(())
    }

    fn clear(&mut self) {
        self.catalogs.clear();
    }
}

static DOMAINS: Lazy<RwLock<Domains>> = Lazy::new(|| RwLock::new(Domains::new()));

/// No-op translation backend.
pub struct NoopTranslateBackend;

impl TranslateBackend for NoopTranslateBackend {
    fn name(&self) -> &'static str {
        "noop"
    }

    fn gettext(&self, msgid: &str) -> String {
        msgid.to_string()
    }

    fn ngettext(&self, msgid: &str, msgid_plural: &str, n: u32) -> String {
        if n == 1 {
            msgid.to_string()
        } else {
            msgid_plural.to_string()
        }
    }

    fn dgettext(&self, _textdomain: &str, msgid: &str) -> String {
        msgid.to_string()
    }
}

/// Disables translation and uses the no-op backend.
pub fn disable() {
    let mut lock = BACKEND.write().unwrap();
    let mut domains = DOMAINS.write().unwrap();
    *lock = Arc::new(NoopTranslateBackend);
    domains.clear();
}

/// Installs the gettext translation backend.
///
/// # Arguments
/// * `lang` - Optional language code.
/// * `locale_base` - Optional base path for locale files.
pub fn install<P: AsRef<Path>>(lang: &str, locale_base: P) -> Result<(), gettext::Error> {
    if BACKEND.read().unwrap().name() == "gettext" {
        return Ok(());
    }
    let catalog = parse("brz", lang, &locale_base)?;
    let backend = GettextTranslateBackend::new(catalog);
    let mut lock = BACKEND.write().unwrap();
    let mut dlock = DOMAINS.write().unwrap();
    *lock = Arc::new(backend);
    dlock.init(lang, &locale_base);
    Ok(())
}

/// Gettext translation backend.
pub struct GettextTranslateBackend {
    catalog: Catalog,
}

impl GettextTranslateBackend {
    fn new(catalog: Catalog) -> Self {
        GettextTranslateBackend { catalog }
    }
}

impl TranslateBackend for GettextTranslateBackend {
    fn name(&self) -> &'static str {
        "gettext"
    }

    fn gettext(&self, msgid: &str) -> String {
        String::from(self.catalog.gettext(msgid))
    }

    fn ngettext(&self, msgid: &str, msgid_plural: &str, n: u32) -> String {
        String::from(self.catalog.ngettext(msgid, msgid_plural, n.into()))
    }

    fn dgettext(&self, textdomain: &str, msgid: &str) -> String {
        let rlock = DOMAINS.read().unwrap();
        let mut wlock: RwLockWriteGuard<'_, Domains>;
        let catalog = match rlock.catalog(textdomain) {
            Some(found) => found,
            None => {
                wlock = DOMAINS.write().unwrap();
                match wlock.load(textdomain, None::<PathBuf>) {
                    Ok(_) => match wlock.catalog(textdomain) {
                        Some(ctlg) => ctlg,
                        None => return String::from(msgid),
                    },
                    Err(_) => return String::from(msgid),
                }
            }
        };
        String::from(catalog.gettext(msgid))
    }
}

/// Translates a message id using the current backend.
pub fn gettext(msgid: &str) -> String {
    let lock = BACKEND.read().unwrap();
    lock.gettext(msgid)
}

/// Translates a message id with pluralization using the current backend.
pub fn ngettext(msgid: &str, msgid_plural: &str, n: u32) -> String {
    let lock = BACKEND.read().unwrap();
    lock.ngettext(msgid, msgid_plural, n)
}

/// Translates a message id for a specific textdomain using the current backend.
pub fn dgettext(textdomain: &str, msgid: &str) -> String {
    let lock = BACKEND.read().unwrap();
    lock.dgettext(textdomain, msgid)
}

/// Installs a translation plugin for a specific textdomain.
///
/// # Arguments
/// * `textdomain` - The textdomain to install.
/// * `locale_base` - Optional base path for locale files.
pub fn install_plugin<P: AsRef<Path>>(
    textdomain: &str,
    locale_base: Option<P>,
) -> Result<(), gettext::Error> {
    if BACKEND.read().unwrap().name() == "gettext" {
        let mut wlock = DOMAINS.write().unwrap();
        wlock.load(textdomain, locale_base)?;
    };
    Ok(())
}

/// Translates each paragraph in the given text separately.
pub fn gettext_per_paragraph(text: &str) -> String {
    let mut result = String::new();
    for paragraph in text.split("\n\n") {
        if !result.is_empty() {
            result.push_str("\n\n");
        }
        result.push_str(&gettext(paragraph));
    }
    result
}

struct ZzzTranslateBackend;

impl ZzzTranslateBackend {
    fn zzz(&self, msgid: &str) -> String {
        ["zzå{{", msgid, "}}"].concat()
    }
}

impl TranslateBackend for ZzzTranslateBackend {
    fn name(&self) -> &'static str {
        "zzz"
    }

    fn gettext(&self, msgid: &str) -> String {
        self.zzz(msgid)
    }

    fn ngettext(&self, msgid: &str, msgid_plural: &str, n: u32) -> String {
        if n == 1 {
            self.zzz(msgid)
        } else {
            self.zzz(msgid_plural)
        }
    }

    fn dgettext(&self, _textdomain: &str, msgid: &str) -> String {
        self.zzz(msgid)
    }
}

/// Installs the Zzz translation backend (for testing).
pub fn install_zzz() {
    let mut lock = BACKEND.write().unwrap();
    *lock = Arc::new(ZzzTranslateBackend);
}

/// Translates a message id using the Zzz backend (for testing).
pub fn zzz(msgid: &str) -> String {
    ZzzTranslateBackend {}.zzz(msgid)
}

struct ZzzTranslateForDocBackend;

impl ZzzTranslateForDocBackend {
    fn zzz(&self, msgid: &str) -> String {
        use regex::Regex;
        let section_pat = Regex::new(r"^:\w+:\n\s+").unwrap();
        let indent_pat = Regex::new(r"^\s+").unwrap();

        if let Some(m) = section_pat.find(msgid) {
            [&msgid[m.start()..m.end()], "zz{{", &msgid[m.end()..], "}}"].concat()
        } else if let Some(m) = indent_pat.find(msgid) {
            [&msgid[m.start()..m.end()], "zz{{", &msgid[m.end()..], "}}"].concat()
        } else {
            return ["zz{{", msgid, "}}"].concat();
        }
    }
}

impl TranslateBackend for ZzzTranslateForDocBackend {
    fn name(&self) -> &'static str {
        "zzz-for-doc"
    }

    fn gettext(&self, msgid: &str) -> String {
        self.zzz(msgid)
    }

    fn ngettext(&self, msgid: &str, msgid_plural: &str, n: u32) -> String {
        if n == 1 {
            self.zzz(msgid)
        } else {
            self.zzz(msgid_plural)
        }
    }

    fn dgettext(&self, _textdomain: &str, msgid: &str) -> String {
        self.zzz(msgid)
    }
}

/// Installs the Zzz-for-doc translation backend (for documentation testing).
pub fn install_zzz_for_doc() {
    let mut lock = BACKEND.write().unwrap();
    *lock = Arc::new(ZzzTranslateForDocBackend);
}
