//! The zakvaska desktop app.
//!
//! zakvaska is a small web server (the Python in `app/`) and this is the thin
//! native shell around it: it starts the server, shows its pages in a window,
//! and stays in the system tray when the window is closed so that feeding and
//! bake alerts still arrive, as native notifications.
//!
//! What lives here and nowhere else:
//!   * where the notebook is kept: the user's own app-data folder;
//!   * the tray icon and its menu;
//!   * turning alerts the server has fired into native notifications.
//!
//! Deciding *when* an alert fires is still entirely the server's job. This
//! only asks it, twice a minute, what is showing.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::DownloadEvent;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as _};
use tauri_plugin_notification::NotificationExt as _;
use tauri_plugin_opener::OpenerExt as _;

/// The port the app has always used, kept so bookmarks keep working. If
/// something else already has it, any free port will do.
const PREFERRED_PORT: u16 = 8420;
/// How long a first start may take. An unsigned app's first launch is slow
/// on macOS while the system checks every file in it.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);
const ALERT_POLL: Duration = Duration::from_secs(20);
/// Passed by the "start at login" entry, so logging in does not throw a
/// window at you: the app just appears in the tray.
const HIDDEN_FLAG: &str = "--hidden";

/// Added to the browser's name so the pages can tell they are inside the
/// desktop app. `app.js` looks for it and leaves notifications to the shell
/// rather than offering the browser's own as well.
const AGENT_MARK: &str = "ZakvaskaDesktop";

struct Server {
    child: Mutex<Option<Child>>,
    base: String,
    data_dir: PathBuf,
}

fn main() {
    let app = tauri::Builder::default()
        // A second launch brings the first one's window forward instead of
        // starting a second server on the same notebook.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_window(app);
        }))
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![HIDDEN_FLAG]),
        ))
        .setup(|app| {
            let handle = app.handle().clone();
            let server = start_server(&handle)?;
            let base = server.base.clone();
            let log = server.data_dir.join("logs").join("server.log");
            app.manage(server);

            build_window(&handle, &base)?;
            build_tray(&handle)?;

            thread::spawn(move || {
                if wait_until_healthy(&base) {
                    note(&handle, &format!("server ready at {base}"));
                    go_to(&handle, &base, "/");
                    watch_alerts(&handle, &base);
                } else if let Some(window) = handle.get_webview_window("main") {
                    let path = serde_json::to_string(&log.to_string_lossy()).unwrap_or_default();
                    let _ = window.eval(&format!("window.zakvaskaFailed({path})"));
                    let _ = window.show();
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window is not quitting: the server keeps running
            // and alerts keep coming. Quit is in the tray menu.
            if let WindowEvent::CloseRequested { api, .. } = event {
                note(window.app_handle(), "window closed; still running in the tray");
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("zakvaska could not start");

    app.run(|handle, event| match event {
        RunEvent::Exit => stop_server(handle),
        // macOS: clicking the Dock icon while the window is hidden.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_window(handle),
        _ => {}
    });
}

// --- The server ------------------------------------------------------------

fn server_binary(app: &AppHandle) -> Result<PathBuf, Box<dyn std::error::Error>> {
    // For `tauri dev`, where nothing has been bundled yet.
    if let Ok(path) = std::env::var("ZAKVASKA_SERVER_BIN") {
        return Ok(PathBuf::from(path));
    }
    let name = if cfg!(windows) { "zakvaska-server.exe" } else { "zakvaska-server" };
    Ok(app.path().resource_dir()?.join("server").join(name))
}

fn pick_port() -> u16 {
    let preferred = SocketAddr::from(([127, 0, 0, 1], PREFERRED_PORT));
    // Ask whether anything answers there before trying to bind it. Binding
    // alone is not proof: where another program listens on every address
    // (a zakvaska started by hand with ZAKVASKA_HOST=0.0.0.0, say), a bind
    // to 127.0.0.1 can still succeed, and the two would share the port.
    let answered = TcpStream::connect_timeout(&preferred, Duration::from_millis(300)).is_ok();
    if !answered && TcpListener::bind(preferred).is_ok() {
        return PREFERRED_PORT;
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(PREFERRED_PORT)
}

/// Open the server's log for appending, starting a fresh one once it is big.
fn open_log(dir: &Path) -> std::io::Result<fs::File> {
    fs::create_dir_all(dir)?;
    let path = dir.join("server.log");
    if fs::metadata(&path).map(|m| m.len() > 2_000_000).unwrap_or(false) {
        let _ = fs::rename(&path, dir.join("server.log.1"));
    }
    OpenOptions::new().create(true).append(true).open(path)
}

fn start_server(app: &AppHandle) -> Result<Server, Box<dyn std::error::Error>> {
    let data_dir = app.path().app_data_dir()?;
    fs::create_dir_all(&data_dir)?;
    let log = open_log(&data_dir.join("logs"))?;
    let port = pick_port();

    let mut command = Command::new(server_binary(app)?);
    command
        .arg("--exit-with-parent")
        .env("ZAKVASKA_DATA_DIR", &data_dir)
        .env("ZAKVASKA_HOST", "127.0.0.1")
        .env("ZAKVASKA_PORT", port.to_string())
        // Held open and never written to: when this app goes away the pipe
        // closes and the server stops itself. See desktop/server.py.
        .stdin(Stdio::piped())
        .stdout(log.try_clone()?)
        .stderr(log);
    // Feeds are planned on the wall clock, so the server needs to know which
    // wall. Ask the system, unless the user has said otherwise.
    if std::env::var_os("ZAKVASKA_TZ").is_none() {
        if let Ok(zone) = iana_time_zone::get_timezone() {
            command.env("ZAKVASKA_TZ", zone);
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt as _;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let child = command.spawn()?;
    Ok(Server {
        child: Mutex::new(Some(child)),
        base: format!("http://127.0.0.1:{port}"),
        data_dir,
    })
}

fn wait_until_healthy(base: &str) -> bool {
    let started = Instant::now();
    while started.elapsed() < STARTUP_TIMEOUT {
        if ureq::get(&format!("{base}/health"))
            .timeout(Duration::from_secs(3))
            .call()
            .is_ok()
        {
            return true;
        }
        thread::sleep(Duration::from_millis(400));
    }
    false
}

fn stop_server(app: &AppHandle) {
    let Some(server) = app.try_state::<Server>() else { return };
    let Some(mut child) = server.child.lock().ok().and_then(|mut slot| slot.take()) else {
        return;
    };
    // Closing its stdin asks it to finish what it is doing and leave.
    drop(child.stdin.take());
    let asked = Instant::now();
    while asked.elapsed() < Duration::from_secs(4) {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
}

// --- The window --------------------------------------------------------------

fn build_window(app: &AppHandle, base: &str) -> tauri::Result<()> {
    let opener = app.clone();
    let home = Url::parse(base).expect("the server address is a URL");
    let start_hidden = std::env::args().any(|arg| arg == HIDDEN_FLAG);
    let saving: Arc<Mutex<Option<PathBuf>>> = Arc::new(Mutex::new(None));

    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("zakvaska")
        .inner_size(1180.0, 820.0)
        .min_inner_size(380.0, 560.0)
        .visible(!start_hidden)
        .user_agent(&format!(
            "Mozilla/5.0 ({}) AppleWebKit/605.1.15 (KHTML, like Gecko) {AGENT_MARK}/{}",
            if cfg!(windows) { "Windows NT 10.0; Win64; x64" } else { "Macintosh; Intel Mac OS X 10_15_7" },
            app.package_info().version,
        ))
        // An embedded web view saves nothing unless told where. The export
        // (Settings, Backup) and a photo's original go to the Downloads
        // folder under a name that is not already taken, and the folder
        // opens on the file when it has arrived.
        .on_download(move |webview, event| {
            match event {
                DownloadEvent::Requested { destination, .. } => {
                    let name = destination
                        .file_name()
                        .map(|name| name.to_string_lossy().into_owned())
                        .unwrap_or_else(|| "zakvaska-download".into());
                    if let Ok(folder) = webview.path().download_dir() {
                        *destination = free_name(&folder, &name);
                    }
                    if let Ok(mut slot) = saving.lock() {
                        *slot = Some(destination.clone());
                    }
                }
                DownloadEvent::Finished { path, success, .. } => {
                    // Some systems do not say where it went, so remember.
                    let remembered = saving.lock().ok().and_then(|mut slot| slot.take());
                    if let Some(file) = path.or(remembered) {
                        let app = webview.app_handle();
                        if success {
                            note(app, &format!("saved {}", file.display()));
                            let _ = app.opener().reveal_item_in_dir(&file);
                        } else {
                            note(app, &format!("could not save {}", file.display()));
                        }
                    }
                }
                _ => {}
            }
            true
        })
        // The window is for the notebook. A link that leads anywhere else
        // (the GitHub page, a release to download) opens in the real browser.
        .on_navigation(move |url| {
            let ours = url.scheme() == "tauri"
                || url.scheme() == "about"
                || url.host_str() == Some("tauri.localhost")
                || (url.host_str() == home.host_str() && url.port() == home.port());
            if !ours {
                let _ = opener.opener().open_url(url.as_str(), None::<&str>);
            }
            ours
        })
        .build()?;
    Ok(())
}

/// `name` in `folder`, or "name (2)", "name (3)"… if that is taken: a second
/// export on the same minute must not write over the first.
fn free_name(folder: &Path, name: &str) -> PathBuf {
    let first = folder.join(name);
    if !first.exists() {
        return first;
    }
    let (stem, ext) = match name.rsplit_once('.') {
        Some((stem, ext)) => (stem, format!(".{ext}")),
        None => (name, String::new()),
    };
    (2..)
        .map(|n| folder.join(format!("{stem} ({n}){ext}")))
        .find(|candidate| !candidate.exists())
        .unwrap_or(first)
}

fn show_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn go_to(app: &AppHandle, base: &str, path: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let target = serde_json::to_string(&format!("{base}{path}")).unwrap_or_default();
        let _ = window.eval(&format!("window.location.replace({target})"));
    }
}

// --- The tray ----------------------------------------------------------------

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let autostart = app.autolaunch().is_enabled().unwrap_or(false);

    let open = MenuItem::with_id(app, "open", "Open zakvaska", true, None::<&str>)?;
    let updates = MenuItem::with_id(app, "updates", "Check for updates…", true, None::<&str>)?;
    let folder = MenuItem::with_id(app, "folder", "Show notebook folder", true, None::<&str>)?;
    let login = CheckMenuItem::with_id(app, "login", "Start at login", true, autostart, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit zakvaska", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &open,
            &updates,
            &folder,
            &PredefinedMenuItem::separator(app)?,
            &login,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    let mut tray = TrayIconBuilder::with_id("zakvaska")
        .tooltip("zakvaska")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            "open" => show_window(app),
            "updates" => {
                if let Some(server) = app.try_state::<Server>() {
                    go_to(app, &server.base, "/about?check-updates=1#updates");
                }
                show_window(app);
            }
            "folder" => {
                if let Some(server) = app.try_state::<Server>() {
                    let _ = app
                        .opener()
                        .open_path(server.data_dir.to_string_lossy(), None::<&str>);
                }
            }
            "login" => {
                let launcher = app.autolaunch();
                let on = launcher.is_enabled().unwrap_or(false);
                let _ = if on { launcher.disable() } else { launcher.enable() };
                let _ = login.set_checked(launcher.is_enabled().unwrap_or(!on));
            }
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

/// One line in logs/app.log beside the notebook: what the shell did, for
/// the day someone asks why a notification never came.
fn note(app: &AppHandle, line: &str) {
    use std::io::Write as _;
    let Some(server) = app.try_state::<Server>() else { return };
    let path = server.data_dir.join("logs").join("app.log");
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let _ = writeln!(file, "{secs} {line}");
    }
}

// --- Alerts ------------------------------------------------------------------

/// What the server is showing right now, as (id, title, body).
fn showing_alerts(base: &str) -> Option<Vec<(i64, String, String)>> {
    let body: serde_json::Value = ureq::get(&format!("{base}/api/alerts"))
        .timeout(Duration::from_secs(5))
        .call()
        .ok()?
        .into_json()
        .ok()?;
    let alerts = body.get("alerts")?.as_array()?;
    Some(
        alerts
            .iter()
            .filter_map(|alert| {
                let id = alert.get("id")?.as_i64()?;
                let subject = alert.get("subject")?.as_str()?.to_string();
                let when = alert.get("overdue_by").and_then(|v| v.as_str()).unwrap_or("");
                let feed = alert.get("kind").and_then(|v| v.as_str()) == Some("feed_due");
                // The same words the page uses for its own notifications.
                Some(if feed {
                    (id, format!("Feed {subject}"), format!("{subject} is {when}."))
                } else {
                    (id, subject.clone(), format!("Due {when}."))
                })
            })
            .collect(),
    )
}

/// Runs for the life of the app. An alert is announced when it appears in
/// what the server is showing and was not there on the last look, so one
/// that was snoozed and has come back is announced again, and one that is
/// simply still there is not.
fn watch_alerts(app: &AppHandle, base: &str) {
    let mut last: HashSet<i64> = HashSet::new();
    loop {
        if let Some(alerts) = showing_alerts(base) {
            for (id, title, body) in &alerts {
                if !last.contains(id) {
                    let shown = app.notification().builder().title(title).body(body).show();
                    note(app, &match shown {
                        Ok(()) => format!("notified: {title}"),
                        Err(err) => format!("could not notify ({err}): {title}"),
                    });
                }
            }
            last = alerts.into_iter().map(|(id, _, _)| id).collect();
        }
        thread::sleep(ALERT_POLL);
    }
}
