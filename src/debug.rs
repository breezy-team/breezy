use once_cell::sync::Lazy;
use std::collections::HashSet;
use std::sync::RwLock;

static DEBUG_FLAGS: Lazy<RwLock<HashSet<String>>> = Lazy::new(|| {
    let initial_set = HashSet::new();
    RwLock::new(initial_set)
});

/// Enables a debug flag for runtime debugging.
///
/// Debug flags can be used to enable additional logging or debugging features
/// at runtime without recompiling the code.
///
/// # Arguments
///
/// * `flag` - The name of the debug flag to enable.
pub fn set_debug_flag(flag: &str) {
    let mut lock = DEBUG_FLAGS.write().unwrap();
    lock.insert(flag.to_string());
}

/// Disables a debug flag.
///
/// # Arguments
///
/// * `flag` - The name of the debug flag to disable.
pub fn unset_debug_flag(flag: &str) {
    let mut lock = DEBUG_FLAGS.write().unwrap();
    lock.remove(flag);
}

/// Clears all debug flags.
///
/// This function removes all debug flags that have been set, effectively
/// disabling all runtime debugging features.
pub fn clear_debug_flags() {
    let mut lock = DEBUG_FLAGS.write().unwrap();
    lock.clear();
}

/// Gets the set of currently enabled debug flags.
///
/// # Returns
///
/// Returns a `HashSet` containing the names of all currently enabled debug flags.
pub fn get_debug_flags() -> HashSet<String> {
    let lock = DEBUG_FLAGS.read().unwrap();
    lock.clone()
}

/// Checks if a specific debug flag is enabled.
///
/// # Arguments
///
/// * `flag` - The name of the debug flag to check.
///
/// # Returns
///
/// Returns `true` if the debug flag is enabled, `false` otherwise.
pub fn debug_flag_enabled(flag: &str) -> bool {
    let lock = DEBUG_FLAGS.read().unwrap();
    lock.contains(flag)
}
