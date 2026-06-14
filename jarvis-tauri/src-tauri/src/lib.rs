// Shell Tauri de Jarvis.
//
// Le coeur de Jarvis reste en Python (main2.py : WebSocket, voix, IA, actions,
// MCP, memoire). Tauri ne le remplace pas : il le lance en SIDECAR et affiche
// son interface (servie sur http://localhost:5173) dans une WebView moderne
// (WebView2), a la place du shell PyQt5/QtWebEngine.
//
// Foundation : en dev on lance `python jarvis_core/main2.py` depuis le depot.
// Pour une vraie distribution il faudra embarquer un sidecar Python (Jarvis.exe).

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

// Depot Jarvis (le backend Python). A externaliser plus tard (arg/config) pour
// la distribution ; suffisant pour la fondation sur la machine de dev.
const JARVIS_REPO: &str = r"C:\Users\ANAKIN\Desktop\jarvis";
const FRONT_URL: &str = "http://localhost:5173";

// Handle du backend, pour le tuer a la fermeture de la fenetre.
struct Backend(Mutex<Option<Child>>);

fn backend_pret() -> bool {
    std::net::TcpStream::connect("127.0.0.1:5173").is_ok()
}

fn lancer_backend() -> Option<Child> {
    Command::new("python")
        .arg(format!(r"{JARVIS_REPO}\jarvis_core\main2.py"))
        .current_dir(JARVIS_REPO)
        // Sert le frontend buildé sur :5173 + WS :8765, sans ouvrir de navigateur
        // ni la fenetre PyQt (mode headless cote shell, garde voix/IA/actions).
        .env("JARVIS_NO_BROWSER", "1")
        .spawn()
        .ok()
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
            // 2) Attend que le serveur frontend reponde, puis (re)charge l'URL et
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
            // Tue le backend Python quand la fenetre se ferme.
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<Backend>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
