//! Native implementations of commands from ``breezy.builtins``.
//!
//! These commands open their working tree through [`crate::workingtree`], so
//! the tree behind the [`WorkingTree`](crate::tree::WorkingTree) trait may be
//! native or implemented in Python, depending on which prober claimed it.

use crate::command::{Command, CommandContext, CommandError, CommandSpec, MatchedArgs};
use crate::option::ParsedOptions;

/// The ``root`` command: shows the tree root directory.
#[derive(Debug, Default)]
pub struct CmdRoot;

impl Command for CmdRoot {
    fn spec(&self) -> CommandSpec {
        CommandSpec {
            help: Some(
                "Show the tree root directory.\n\n\
                 The root is the nearest enclosing directory with a control\n\
                 directory."
                    .to_string(),
            ),
            takes_args: vec!["filename?".to_string()],
            display: true,
            ..CommandSpec::new("root")
        }
    }

    fn run(
        &self,
        ctx: &mut dyn CommandContext,
        _opts: &ParsedOptions,
        args: &MatchedArgs,
    ) -> Result<i32, CommandError> {
        let (tree, _relpath) = crate::workingtree::open_containing(args.scalar("filename"))?;
        writeln!(
            ctx.out(),
            "{}",
            tree.basedir()
                .map_err(crate::controldir::Error::from)?
                .display()
        )?;
        Ok(0)
    }
}

crate::declare_command!(CmdRoot);

/// The hidden ``relpath`` command: shows the path of a file relative to the
/// tree root.
#[derive(Debug, Default)]
pub struct CmdRelpath;

impl Command for CmdRelpath {
    fn spec(&self) -> CommandSpec {
        CommandSpec {
            help: Some("Show path of a file relative to root".to_string()),
            takes_args: vec!["filename".to_string()],
            hidden: true,
            display: true,
            ..CommandSpec::new("relpath")
        }
    }

    fn run(
        &self,
        ctx: &mut dyn CommandContext,
        _opts: &ParsedOptions,
        args: &MatchedArgs,
    ) -> Result<i32, CommandError> {
        let (_tree, relpath) = crate::workingtree::open_containing(args.scalar("filename"))?;
        writeln!(ctx.out(), "{relpath}")?;
        Ok(0)
    }
}

crate::declare_command!(CmdRelpath);

#[cfg(test)]
mod tests {
    use super::*;
    use crate::command::EncodingType;

    #[test]
    fn root_spec() {
        let spec = CmdRoot.spec();
        assert_eq!("root", spec.name);
        assert_eq!(vec!["filename?".to_string()], spec.takes_args);
        assert_eq!(Vec::<String>::new(), spec.aliases);
        assert!(!spec.hidden);
        assert!(spec.display);
        assert_eq!(EncodingType::Strict, spec.encoding_type);
        assert!(spec.options.is_empty());
    }

    #[test]
    fn relpath_spec() {
        let spec = CmdRelpath.spec();
        assert_eq!("relpath", spec.name);
        assert_eq!(vec!["filename".to_string()], spec.takes_args);
        assert!(spec.hidden);
        assert!(spec.display);
        assert_eq!(EncodingType::Strict, spec.encoding_type);
        assert!(spec.options.is_empty());
    }

    #[test]
    fn commands_registered() {
        let registry = crate::registry::command_registry();
        assert!(registry.get("root").is_some());
        assert!(registry.get("relpath").is_some());
    }
}
