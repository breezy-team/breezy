use once_cell::sync::Lazy;
use std::path::Path;
use std::sync::Arc;
use std::sync::RwLock;

static BACKEND: Lazy<RwLock<Arc<dyn TranslateBackend + Sync + Send>>> =
    Lazy::new(|| RwLock::new(Arc::new(NoopTranslateBackend)));

pub trait TranslateBackend {
    fn name(&self) -> &'static str;
    fn gettext(&self, msgid: &str) -> String;
    fn ngettext(&self, msgid: &str, msgid_plural: &str, n: u32) -> String;
    fn dgettext(&self, textdomain: &str, msgid: &str) -> String;
}

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

pub fn disable() {
    let mut lock = BACKEND.write().unwrap();
    *lock = Arc::new(NoopTranslateBackend);
}

pub fn install(lang: Option<&str>, locale_base: Option<&Path>) -> Result<(), std::io::Error> {
    if BACKEND.read().unwrap().name() == "gettext" {
        return Ok(());
    }
    gettextrs::textdomain("brz")?;

    if let Some(lang) = lang {
        gettextrs::setlocale(gettextrs::LocaleCategory::LcAll, lang);
    }
    if let Some(locale_base) = locale_base {
        gettextrs::bindtextdomain("brz", locale_base.join("locale"))?;
    }
    gettextrs::bind_textdomain_codeset("brz", "UTF-8")?;
    let mut lock = BACKEND.write().unwrap();
    *lock = Arc::new(GettextTranslateBackend);
    Ok(())
}

pub struct GettextTranslateBackend;

impl TranslateBackend for GettextTranslateBackend {
    fn name(&self) -> &'static str {
        "gettext"
    }

    fn gettext(&self, msgid: &str) -> String {
        gettextrs::gettext(msgid)
    }

    fn ngettext(&self, msgid: &str, msgid_plural: &str, n: u32) -> String {
        gettextrs::ngettext(msgid, msgid_plural, n)
    }

    fn dgettext(&self, textdomain: &str, msgid: &str) -> String {
        gettextrs::dgettext(textdomain, msgid)
    }
}

pub fn gettext(msgid: &str) -> String {
    let lock = BACKEND.read().unwrap();
    lock.gettext(msgid)
}

pub fn ngettext(msgid: &str, msgid_plural: &str, n: u32) -> String {
    let lock = BACKEND.read().unwrap();
    lock.ngettext(msgid, msgid_plural, n)
}

pub fn dgettext(textdomain: &str, msgid: &str) -> String {
    let lock = BACKEND.read().unwrap();
    lock.dgettext(textdomain, msgid)
}

pub fn install_plugin(textdomain: &str, locale_base: Option<&Path>) -> Result<(), std::io::Error> {
    if let Some(locale_base) = locale_base {
        gettextrs::bindtextdomain(textdomain, locale_base.join("locale"))?;
    }
    gettextrs::bind_textdomain_codeset(textdomain, "UTF-8")?;
    Ok(())
}

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

pub fn install_zzz() {
    let mut lock = BACKEND.write().unwrap();
    *lock = Arc::new(ZzzTranslateBackend);
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

pub fn zzz(msgid: &str) -> String {
    ZzzTranslateBackend {}.zzz(msgid)
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

pub fn install_zzz_for_doc() {
    let mut lock = BACKEND.write().unwrap();
    *lock = Arc::new(ZzzTranslateForDocBackend);
}
