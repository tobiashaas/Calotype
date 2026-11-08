//! Automation channel for end-to-end tests in a real Lightroom (opt-in).
//!
//! Lightroom cannot be driven from outside, but the plugin can poll: a test runner puts a
//! command here, the plugin fetches it (`GET /v1/automation/next`), runs it in Lightroom
//! with the same code the menu items use, and posts the result back.
//!
//! Safety: off unless `"automation": true` in bridge.json (the endpoints answer 404),
//! loopback + token like every `/v1` call, and only a fixed list of commands — no code
//! is ever executed from a command.

use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

use serde::Serialize;
use serde_json::Value;

use crate::db::now;

/// Commands the plugin understands (see apps/lr-plugin/Calotype.lrplugin/Automation.lua).
pub const COMMANDS: &[&str] = &[
    "ping",
    "list_photos",
    "develop_settings",
    "set_develop_settings",
    "apply",
    "train",
    "select",
    "straighten_probe",
    "cull",
    "remove_cull_set",
    "retouch_state",
    "remove_retouch",
];

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Command {
    pub id: u64,
    pub command: String,
    pub args: Value,
    /// pending → running (picked up by the plugin) → done
    pub status: String,
    pub ok: Option<bool>,
    pub result: Option<Value>,
    pub created_at: i64,
    pub finished_at: Option<i64>,
}

#[derive(Default)]
struct Inner {
    next_id: u64,
    pending: VecDeque<u64>,
    commands: HashMap<u64, Command>,
    plugin_last_poll: Option<i64>,
}

#[derive(Default)]
pub struct AutomationQueue {
    inner: Mutex<Inner>,
}

impl AutomationQueue {
    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|p| p.into_inner())
    }

    pub fn enqueue(&self, command: &str, args: Value) -> Result<Command, String> {
        if !COMMANDS.contains(&command) {
            return Err(format!(
                "unknown command {command:?}; known: {}",
                COMMANDS.join(", ")
            ));
        }
        let mut inner = self.lock();
        inner.next_id += 1;
        let cmd = Command {
            id: inner.next_id,
            command: command.to_string(),
            args,
            status: "pending".into(),
            ok: None,
            result: None,
            created_at: now(),
            finished_at: None,
        };
        inner.pending.push_back(cmd.id);
        inner.commands.insert(cmd.id, cmd.clone());
        Ok(cmd)
    }

    /// Next pending command for the plugin (marked running), or None.
    pub fn next(&self) -> Option<Command> {
        let mut inner = self.lock();
        inner.plugin_last_poll = Some(now());
        let id = inner.pending.pop_front()?;
        let cmd = inner.commands.get_mut(&id)?;
        cmd.status = "running".into();
        Some(cmd.clone())
    }

    pub fn finish(&self, id: u64, ok: bool, result: Value) -> Option<Command> {
        let mut inner = self.lock();
        let cmd = inner.commands.get_mut(&id)?;
        cmd.status = "done".into();
        cmd.ok = Some(ok);
        cmd.result = Some(result);
        cmd.finished_at = Some(now());
        Some(cmd.clone())
    }

    pub fn get(&self, id: u64) -> Option<Command> {
        self.lock().commands.get(&id).cloned()
    }

    /// Seconds since the plugin last asked for work (None: never).
    pub fn plugin_idle_secs(&self) -> Option<i64> {
        self.lock().plugin_last_poll.map(|t| now() - t)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn commands_flow_through_in_order() {
        let q = AutomationQueue::default();
        assert!(q.enqueue("rm -rf", json!({})).is_err());
        let a = q.enqueue("ping", json!({})).unwrap();
        let b = q.enqueue("list_photos", json!({"limit": 5})).unwrap();
        assert_eq!(q.next().unwrap().id, a.id);
        assert_eq!(q.get(a.id).unwrap().status, "running");
        q.finish(a.id, true, json!({"lr": "15.1"})).unwrap();
        assert_eq!(q.get(a.id).unwrap().result, Some(json!({"lr": "15.1"})));
        assert_eq!(q.next().unwrap().id, b.id);
        assert!(q.next().is_none());
        assert_eq!(q.plugin_idle_secs(), Some(0));
    }
}
