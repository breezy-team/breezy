//! Hook infrastructure: hook point callbacks, the hooks installed before
//! their hook point exists, and the hook documentation.

/// Assemble the documentation block for a hook point.
///
/// `name` is the hook name, `introduced`/`deprecated` are the already-formatted
/// version strings (or `None`), and `doc` is the hook's description. The result
/// is terminated with a newline. The description is wrapped at 70 columns
/// without breaking long words.
pub fn hookpoint_docs(
    name: &str,
    introduced: Option<&str>,
    deprecated: Option<&str>,
    doc: &str,
) -> String {
    let mut strings: Vec<String> = Vec::new();
    strings.push(name.to_string());
    strings.push("~".repeat(name.chars().count()));
    strings.push(String::new());
    let introduced_string = introduced.unwrap_or("unknown");
    strings.push(crate::i18n::gettext("Introduced in: %s").replacen("%s", introduced_string, 1));
    if let Some(dep) = deprecated {
        strings.push(crate::i18n::gettext("Deprecated in: %s").replacen("%s", dep, 1));
    }
    strings.push(String::new());

    strings.extend(crate::utextwrap::wrap_like_python(doc, 70, false));
    strings.push(String::new());
    strings.join("\n")
}

/// Assemble the combined documentation for a hooks collection.
///
/// `class_name` heads the block (underlined with ``-``); `hook_docs` are the
/// per-hook-point documentation blocks in sorted order. The pieces are joined
/// with newlines.
pub fn hooks_docs(class_name: &str, hook_docs: Vec<String>) -> String {
    let mut parts = vec![
        class_name.to_string(),
        "-".repeat(class_name.chars().count()),
        String::new(),
    ];
    parts.extend(hook_docs);
    parts.join("\n")
}

/// A callback installed on a hook point.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Callback<P> {
    /// A callable object.
    Object(P),
    /// A callable that is imported from `module` when the hook point fires.
    Lazy {
        /// The module defining the callable.
        module: String,
        /// The (possibly dotted) name of the callable in that module.
        member: String,
    },
}

/// A callback with the label it is shown with.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Installed<P> {
    /// The callback.
    pub callback: Callback<P>,
    /// The label, if any.
    pub label: Option<String>,
    id: u64,
}

impl<P> Installed<P> {
    fn clone_with(&self, clone: &impl Fn(&P) -> P) -> Self {
        Installed {
            callback: match &self.callback {
                Callback::Object(p) => Callback::Object(clone(p)),
                Callback::Lazy { module, member } => Callback::Lazy {
                    module: module.clone(),
                    member: member.clone(),
                },
            },
            label: self.label.clone(),
            id: self.id,
        }
    }
}

/// The callbacks of a hook point.
///
/// Clones share the list: callbacks installed lazily before a hook point
/// exists are kept in a list that the hook point takes over when it is
/// created.
#[derive(Debug)]
pub struct CallbackList<P>(std::sync::Arc<std::sync::Mutex<Vec<Installed<P>>>>);

impl<P> Clone for CallbackList<P> {
    fn clone(&self) -> Self {
        CallbackList(self.0.clone())
    }
}

impl<P> Default for CallbackList<P> {
    fn default() -> Self {
        CallbackList(Default::default())
    }
}

/// No callback with a label was installed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NoSuchLabel(pub Option<String>);

impl std::fmt::Display for NoSuchLabel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match &self.0 {
            Some(label) => write!(f, "No entry with label '{label}'"),
            None => write!(f, "No entry with label None"),
        }
    }
}

impl std::error::Error for NoSuchLabel {}

impl<P> CallbackList<P> {
    /// An empty list.
    pub fn new() -> Self {
        Self::default()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Vec<Installed<P>>> {
        // Every mutation is a single Vec operation, so a panic while locked
        // leaves nothing half done.
        self.0.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Install `callback` with `label`.
    pub fn push(&self, callback: Callback<P>, label: Option<String>) {
        static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let id = NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        self.lock().push(Installed {
            callback,
            label,
            id,
        });
    }

    /// Remove every callback labelled `label`.
    pub fn uninstall(&self, label: Option<&str>) -> Result<(), NoSuchLabel> {
        let mut callbacks = self.lock();
        let before = callbacks.len();
        callbacks.retain(|c| c.label.as_deref() != label);
        if callbacks.len() == before {
            return Err(NoSuchLabel(label.map(str::to_string)));
        }
        Ok(())
    }

    /// The number of callbacks.
    pub fn len(&self) -> usize {
        self.lock().len()
    }

    /// Whether there are no callbacks.
    pub fn is_empty(&self) -> bool {
        self.lock().is_empty()
    }

    /// Whether `other` is this list rather than a copy.
    pub fn same_list(&self, other: &Self) -> bool {
        std::sync::Arc::ptr_eq(&self.0, &other.0)
    }

    /// Apply `f` to each callback, in installation order, replacing it with
    /// the callback `f` returns (to remember an imported lazy callback).
    /// `clone` copies a callback object.
    ///
    /// The list is not locked while `f` runs, so `f` may install callbacks;
    /// those are not visited.
    pub fn for_each<E>(
        &self,
        clone: impl Fn(&P) -> P,
        mut f: impl FnMut(&Installed<P>) -> Result<Option<Callback<P>>, E>,
    ) -> Result<(), E> {
        for installed in self.snapshot(clone) {
            if let Some(replacement) = f(&installed)? {
                let mut callbacks = self.lock();
                if let Some(entry) = callbacks.iter_mut().find(|c| c.id == installed.id) {
                    entry.callback = replacement;
                }
            }
        }
        Ok(())
    }

    /// The installed callbacks, in installation order; `clone` copies a
    /// callback object.
    pub fn snapshot(&self, clone: impl Fn(&P) -> P) -> Vec<Installed<P>> {
        self.lock().iter().map(|c| c.clone_with(&clone)).collect()
    }
}

/// The key of a lazily installed hook: the module and (dotted) name of the
/// hooks object, and the hook name.
pub type LazyHookKey = (String, String, String);

/// Callbacks installed on hook points by name, before the hooks objects that
/// define them exist.
#[derive(Debug)]
pub struct LazyHooks<P> {
    lists: std::collections::BTreeMap<LazyHookKey, CallbackList<P>>,
}

impl<P> Default for LazyHooks<P> {
    fn default() -> Self {
        LazyHooks {
            lists: Default::default(),
        }
    }
}

impl<P> LazyHooks<P> {
    /// An empty table.
    pub fn new() -> Self {
        Self::default()
    }

    /// The callbacks for `key`, creating an empty list if there is none.
    pub fn list(&mut self, key: &LazyHookKey) -> CallbackList<P> {
        self.lists.entry(key.clone()).or_default().clone()
    }

    /// The keys with callbacks lists.
    pub fn keys(&self) -> impl Iterator<Item = &LazyHookKey> {
        self.lists.keys()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hookpoint_docs_wrap_like_python() {
        // textwrap.wrap(doc, break_long_words=False) fills lines greedily.
        let doc = "Called after creating a command object to allow modifications \
                   such as adding or removing options, docs etc. Called with the \
                   new breezy.commands.Command object.";
        assert_eq!(
            "extend_command\n~~~~~~~~~~~~~~\n\nIntroduced in: 1.13\n\n\
             Called after creating a command object to allow modifications such as\n\
             adding or removing options, docs etc. Called with the new\n\
             breezy.commands.Command object.\n",
            hookpoint_docs("extend_command", Some("1.13"), None, doc)
        );
    }

    #[test]
    fn hooks_docs_assembly() {
        // No hook points: just the heading.
        assert_eq!(
            hooks_docs("BranchHooks", vec![]),
            "BranchHooks\n-----------\n"
        );
        // With hook points: heading then each block joined by newlines.
        assert_eq!(
            hooks_docs("XHooks", vec!["a\n~\n".to_string(), "b\n~\n".to_string()]),
            "XHooks\n------\n\na\n~\n\nb\n~\n"
        );
    }

    #[test]
    fn docs_introduced_only() {
        let doc = "Invoked after changing the tip of a branch object. Called with \
                   a breezy.branch.PostChangeBranchTipParams object";
        assert_eq!(
            hookpoint_docs("post_tip_change", Some("0.15"), None, doc),
            "post_tip_change\n\
             ~~~~~~~~~~~~~~~\n\
             \n\
             Introduced in: 0.15\n\
             \n\
             Invoked after changing the tip of a branch object. Called with a\n\
             breezy.branch.PostChangeBranchTipParams object\n",
        );
    }

    #[test]
    fn docs_unknown_introduced() {
        let out = hookpoint_docs("foo", None, None, "no docs");
        assert!(out.contains("Introduced in: unknown\n"));
    }

    #[test]
    fn docs_deprecated_line() {
        let out = hookpoint_docs("foo", Some("1.0"), Some("2.0"), "no docs");
        assert!(out.contains("Introduced in: 1.0\n"));
        assert!(out.contains("Deprecated in: 2.0\n"));
    }
}

/// A builtin hook point: the module and member holding it, and the factory
/// class that builds its empty ``Hooks``.
pub struct KnownHookDef {
    /// The module the hook point lives in.
    pub module: &'static str,
    /// The member name of the hook point within that module.
    pub member: &'static str,
    /// The factory (a ``Hooks`` subclass) that builds the empty hooks.
    pub factory: &'static str,
}

/// The builtin hook points registered in ``known_hooks``, in definition order.
pub fn builtin_known_hooks() -> &'static [KnownHookDef] {
    macro_rules! hook {
        ($module:expr, $member:expr, $factory:expr) => {
            KnownHookDef {
                module: $module,
                member: $member,
                factory: $factory,
            }
        };
    }
    &[
        hook!("breezy.branch", "Branch.hooks", "BranchHooks"),
        hook!("breezy.controldir", "ControlDir.hooks", "ControlDirHooks"),
        hook!("breezy.commands", "Command.hooks", "CommandHooks"),
        hook!("breezy.config", "ConfigHooks", "_ConfigHooks"),
        hook!("breezy.info", "hooks", "InfoHooks"),
        hook!("breezy.lock", "Lock.hooks", "LockHooks"),
        hook!("breezy.merge", "Merger.hooks", "MergeHooks"),
        hook!("breezy.msgeditor", "hooks", "MessageEditorHooks"),
        hook!(
            "breezy.mutabletree",
            "MutableTree.hooks",
            "MutableTreeHooks"
        ),
        hook!(
            "breezy.bzr.smart.client",
            "_SmartClient.hooks",
            "SmartClientHooks"
        ),
        hook!(
            "breezy.bzr.smart.server",
            "SmartTCPServer.hooks",
            "SmartServerHooks"
        ),
        hook!("breezy.status", "hooks", "StatusHooks"),
        hook!("breezy.transport", "Transport.hooks", "TransportHooks"),
        hook!(
            "breezy.version_info_formats.format_rio",
            "RioVersionInfoBuilder.hooks",
            "RioVersionInfoBuilderHooks"
        ),
        hook!(
            "breezy.merge_directive",
            "BaseMergeDirective.hooks",
            "MergeDirectiveHooks"
        ),
    ]
}

#[cfg(test)]
mod known_hook_tests {
    use super::*;

    #[test]
    fn builtin_known_hooks_table() {
        let hooks = builtin_known_hooks();
        assert_eq!(15, hooks.len());
        assert_eq!("breezy.branch", hooks[0].module);
        assert_eq!("Branch.hooks", hooks[0].member);
        assert_eq!("BranchHooks", hooks[0].factory);
        // Command.hooks is the entry the command machinery depends on.
        let cmd = hooks.iter().find(|h| h.factory == "CommandHooks").unwrap();
        assert_eq!("breezy.commands", cmd.module);
        assert_eq!("Command.hooks", cmd.member);
    }

    fn labels(list: &CallbackList<u32>) -> Vec<Option<String>> {
        list.snapshot(|p| *p).into_iter().map(|c| c.label).collect()
    }

    #[test]
    fn callback_list_install_and_uninstall() {
        let list = CallbackList::new();
        list.push(Callback::Object(1), Some("a".to_string()));
        list.push(Callback::Object(2), None);
        list.push(Callback::Object(3), Some("a".to_string()));
        assert_eq!(3, list.len());
        list.uninstall(Some("a")).unwrap();
        assert_eq!(vec![None], labels(&list));
        assert_eq!(
            Err(NoSuchLabel(Some("a".to_string()))),
            list.uninstall(Some("a"))
        );
        list.uninstall(None).unwrap();
        assert!(list.is_empty());
    }

    #[test]
    fn callback_list_for_each_replaces() {
        let list = CallbackList::new();
        list.push(
            Callback::Lazy {
                module: "m".to_string(),
                member: "f".to_string(),
            },
            None,
        );
        list.push(Callback::Object(2), None);
        let mut seen = Vec::new();
        list.for_each(
            |p| *p,
            |installed| -> Result<_, ()> {
                seen.push(installed.callback.clone());
                Ok(match installed.callback {
                    Callback::Lazy { .. } => Some(Callback::Object(1)),
                    Callback::Object(_) => None,
                })
            },
        )
        .unwrap();
        assert_eq!(2, seen.len());
        assert_eq!(
            vec![Callback::Object(1), Callback::Object(2)],
            list.snapshot(|p| *p)
                .into_iter()
                .map(|c| c.callback)
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn lazy_hooks_share_lists() {
        let mut lazy: LazyHooks<u32> = LazyHooks::new();
        let key = ("m".to_string(), "C.hooks".to_string(), "h".to_string());
        let first = lazy.list(&key);
        first.push(Callback::Object(1), None);
        let second = lazy.list(&key);
        assert!(first.same_list(&second));
        assert_eq!(1, second.len());
        assert_eq!(vec![&key], lazy.keys().collect::<Vec<_>>());
    }
}
