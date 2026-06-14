// Shell Tauri de Jarvis.
//
// Le coeur de Jarvis reste en Python (main2.py : WebSocket, voix, IA, actions,
// MCP, memoire). Tauri ne le remplace pas : il le lance en SIDECAR et affiche
// son interface (servie sur http://localhost:5173) dans une WebView moderne
// (WebView2), a la place du shell PyQt5/QtWebEngine. Il ajoute un icone de
// barre des taches (tray) et masque la fenetre a la fermeture (reste en tray),
// comme jarvis_desktop.py.
//
// Foundation : en dev on lance `python jarvis_core/main2.py` depuis le depot.
// Pour une vraie distribution il faudra embarquer un sidecar Python (Jarvis.exe).

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent, WindowEvent,
};

// Depot Jarvis (le backend Python). A externaliser plus tard (arg/config) pour
// la distribution ; suffisant pour la fondation sur la machine de dev.
const JARVIS_REPO: &str = r"C:\Users\ANAKIN\Desktop\jarvis";
const FRONT_URL: &str = "http://localhost:5173";
const DASHBOARD_URL: &str = "http://localhost:5173/dashboard.html";

// Handle du backend, pour le tuer quand on quitte vraiment l'app.
struct Backend(Mutex<Option<Child>>);

fn backend_pret() -> bool {
    std::net::TcpStream::connect("127.0.0.1:5173").is_ok()
}

// Masque la fenetre console du sous-process backend (sinon un terminal "flashe"
// / reste visible quand l'app GUI lance python ou JarvisWeb.exe). Windows only.
#[cfg(windows)]
fn masquer_console(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}
#[cfg(not(windows))]
fn masquer_console(_cmd: &mut Command) {}

fn lancer_backend() -> Option<Child> {
    // 1) Distribution : JarvisWeb.exe a cote de l'exe Tauri. Il sert frontend/dist/
    //    sur :5173 + WS :8765 sans ouvrir de navigateur (JARVIS_EXTERNAL_SHELL=1),
    //    c'est cette fenetre Tauri qui affiche l'interface.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let jarvis_web = dir.join("JarvisWeb.exe");
            if jarvis_web.exists() {
                let mut cmd = Command::new(&jarvis_web);
                cmd.current_dir(dir).env("JARVIS_EXTERNAL_SHELL", "1");
                masquer_console(&mut cmd);
                return cmd.spawn().ok();
            }
        }
    }
    // 2) Dev : python main2.py depuis le depot (sert dist/ sur :5173, pas de
    //    navigateur ni de fenetre PyQt ; garde voix/IA/actions). Console masquee.
    let mut cmd = Command::new("python");
    cmd.arg(format!(r"{JARVIS_REPO}\jarvis_core\main2.py"))
        .current_dir(JARVIS_REPO)
        .env("JARVIS_NO_BROWSER", "1");
    masquer_console(&mut cmd);
    cmd.spawn().ok()
}

// Tue le backend Python s'il a ete lance par ce shell.
fn tuer_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<Backend>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(child) = guard.as_mut() {
                let _ = child.kill();
            }
        }
    }
}

// Affiche la fenetre principale (en option, charge une URL d'abord).
fn montrer_fenetre(app: &tauri::AppHandle, url: Option<&str>) {
    if let Some(window) = app.get_webview_window("main") {
        if let Some(u) = url {
            if let Ok(parsed) = u.parse() {
                let _ = window.navigate(parsed);
            }
        }
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            // 1) Lance le backend Python s'il ne tourne pas deja.
            if !backend_pret() {
                let child = lancer_backend();
                if let Some(state) = app.try_state::<Backend>() {
                    *state.0.lock().unwrap() = child;
                }
            }

            // 2) Icone de barre des taches (tray) + menu.
            let ouvrir = MenuItem::with_id(app, "ouvrir", "Ouvrir Jarvis", true, None::<&str>)?;
            let dashboard =
                MenuItem::with_id(app, "dashboard", "Configuration (dashboard)", true, None::<&str>)?;
            let quitter = MenuItem::with_id(app, "quitter", "Quitter Jarvis", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&ouvrir, &dashboard, &quitter])?;

            let mut tray = TrayIconBuilder::with_id("jarvis-tray")
                .menu(&menu)
                .tooltip("Jarvis")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "ouvrir" => montrer_fenetre(app, Some(FRONT_URL)),
                    "dashboard" => montrer_fenetre(app, Some(DASHBOARD_URL)),
                    "quitter" => {
                        tuer_backend(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // Clic gauche : bascule la visibilite de la fenetre.
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                montrer_fenetre(app, None);
                            }
                        }
                    }
                });
            // Reutilise l'icone de la fenetre comme icone de tray.
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            // 3) Attend que le serveur frontend reponde, puis charge l'URL et
            //    affiche la fenetre (evite la page d'erreur si le serveur est lent).
            if let Some(window) = app.get_webview_window("main") {
                std::thread::spawn(move || {
                    for _ in 0..120 {
                        if backend_pret() {
                            break;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(500));
                    }
                    if let Ok(url) = FRONT_URL.parse() {
                        let _ = window.navigate(url);
                    }
                    let _ = window.show();
                    let _ = window.set_focus();
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Fermer la fenetre = la masquer (l'app reste en tray, backend vivant).
            // On quitte vraiment via le menu tray "Quitter Jarvis".
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // Filet de securite : tue le backend si l'app se termine.
            if let RunEvent::Exit = event {
                tuer_backend(app);
            }
        });
}
