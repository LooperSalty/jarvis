"""ModelAdvisor — Quel modele LLM local choisir pour ton PC ?

Detecte ton CPU/RAM/GPU+VRAM, te demande ton usage (chat, code, vision, RAG...),
et recommande les meilleurs modeles open-weight a installer (via Ollama).

Build .exe : python -m PyInstaller --onefile --windowed --name ModelAdvisor model_advisor.py
"""

from __future__ import annotations

import platform
import re
import subprocess
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

# ============================================================
# Detection materielle
# ============================================================

def detect_ram_gb() -> float:
    """Retourne la RAM totale en Go. Win11 deprecie wmic -> ctypes en priorite."""
    sys = platform.system()
    if sys == "Windows":
        # Voie 1 : ctypes GlobalMemoryStatusEx (toujours dispo, plus fiable que wmic)
        try:
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass
        # Voie 2 : wmic (peut rater sur Win11 sans Windows-Management-Framework)
        try:
            output = subprocess.check_output(
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                text=True, stderr=subprocess.DEVNULL, timeout=5,
            )
            for line in output.split("\n"):
                line = line.strip()
                if line.isdigit():
                    return round(int(line) / (1024 ** 3), 1)
        except Exception:
            pass
    elif sys == "Linux":
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return round(int(line.split()[1]) / (1024 ** 2), 1)
        except Exception:
            pass
    elif sys == "Darwin":
        try:
            output = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"],
                text=True, timeout=5,
            )
            return round(int(output.strip()) / (1024 ** 3), 1)
        except Exception:
            pass
    return 0.0


def detect_gpus() -> list[tuple[str, float]]:
    """Retourne la liste des GPU detectes : [(nom, vram_gb), ...]."""
    gpus: list[tuple[str, float]] = []

    # 1) NVIDIA via nvidia-smi (fiable, donne la vraie VRAM)
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
        for line in output.strip().split("\n"):
            if "," in line:
                name, mem_mb = line.split(",", 1)
                try:
                    vram_gb = round(int(mem_mb.strip()) / 1024, 1)
                    gpus.append((name.strip(), vram_gb))
                except ValueError:
                    continue
        if gpus:
            return gpus
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2) Mac Apple Silicon : pas de GPU dedie, VRAM = RAM unifiee
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        ram_gb = detect_ram_gb()
        gpus.append(("Apple Silicon (memoire unifiee)", ram_gb * 0.7))
        return gpus

    # 3) Fallback Windows : wmic Win32_VideoController (VRAM souvent fausse > 4GB)
    if platform.system() == "Windows":
        try:
            output = subprocess.check_output(
                ["wmic", "path", "Win32_VideoController", "get",
                 "Name,AdapterRAM", "/format:list"],
                text=True, stderr=subprocess.DEVNULL, timeout=5,
            )
            entries = re.findall(
                r"AdapterRAM=(\d+)\s+Name=([^\r\n]+)",
                output,
            )
            for ram_bytes, name in entries:
                try:
                    vram_gb = round(int(ram_bytes) / (1024 ** 3), 1)
                    if not name.strip().startswith("Microsoft"):
                        gpus.append((name.strip(), vram_gb))
                except ValueError:
                    continue
        except Exception:
            pass

    return gpus or [("Aucun GPU dedie detecte (CPU seulement)", 0.0)]


def detect_cpu() -> str:
    name = platform.processor() or platform.machine()
    return name or "CPU inconnu"


def detect_cpu_cores() -> int:
    try:
        import os as _os
        return _os.cpu_count() or 0
    except Exception:
        return 0


# ============================================================
# Base de modeles (curated, mis a jour 2026)
# ============================================================

@dataclass
class Model:
    name: str
    size_gb: float        # taille du fichier modele (Q4 quant)
    min_vram_gb: float    # VRAM necessaire pour full GPU offload
    min_ram_gb: float     # RAM necessaire en CPU-only
    use_cases: set[str]
    install: str          # commande Ollama
    why: str              # description courte


USE_CASES: dict[str, str] = {
    "chat": "Conversation generale (FR/EN)",
    "code": "Generation/completion de code",
    "vision": "Multimodal (analyse d'images)",
    "long_context": "RAG, documents longs (>32k tokens)",
    "creative": "Ecriture creative, brainstorming",
    "francais": "Optimise pour le francais",
}


MODELS: list[Model] = [
    # -------- Tiny (<=4 GB VRAM) --------
    Model("llama3.2:3b", 2.0, 4.0, 6.0, {"chat", "creative", "francais"},
          "ollama pull llama3.2:3b",
          "Petit/rapide. Bon FR. Ideal sans GPU dedie."),
    Model("qwen2.5:3b", 1.9, 4.0, 6.0, {"chat", "code"},
          "ollama pull qwen2.5:3b",
          "Code OK pour sa taille. Tres rapide."),
    Model("phi-3.5-mini", 2.5, 4.5, 7.0, {"chat", "code"},
          "ollama pull phi3.5",
          "Microsoft. Etonnant en raisonnement/code pour 3.8B."),

    # -------- Small (4-8 GB VRAM) --------
    Model("llama3.1:8b", 4.7, 8.0, 12.0, {"chat", "creative", "long_context", "francais"},
          "ollama pull llama3.1:8b",
          "Reference 8B. Bon FR. Contexte 128k."),
    Model("qwen2.5:7b", 4.7, 7.5, 11.0, {"chat", "code", "long_context"},
          "ollama pull qwen2.5:7b",
          "Excellent rapport qualite/poids. Tres bon en code."),
    Model("mistral:7b", 4.4, 7.0, 11.0, {"chat", "creative", "francais"},
          "ollama pull mistral:7b",
          "Mistral FR natif. Leger, ecriture fluide."),
    Model("mistral-nemo:12b", 7.1, 12.0, 18.0, {"chat", "creative", "long_context", "francais"},
          "ollama pull mistral-nemo:12b",
          "Mistral x NVIDIA. 128k contexte. Excellent FR."),
    Model("qwen2.5-coder:7b", 4.7, 7.5, 11.0, {"code"},
          "ollama pull qwen2.5-coder:7b",
          "Code-specialise. Plus efficace que llama pour generer du code."),
    Model("deepseek-coder-v2:lite", 8.9, 10.0, 14.0, {"code"},
          "ollama pull deepseek-coder-v2:lite",
          "16B MoE actif 2.4B. Excellent code/VRAM."),
    Model("llava:7b", 4.7, 8.0, 12.0, {"vision", "chat"},
          "ollama pull llava:7b",
          "Vision+texte. Decrit images, screenshots, photos."),

    # -------- Medium (8-16 GB VRAM) --------
    Model("qwen2.5:14b", 9.0, 14.0, 20.0, {"chat", "code", "long_context"},
          "ollama pull qwen2.5:14b",
          "Sweet spot 14B. Raisonnement superieur a la classe 7B."),
    Model("qwen2.5-coder:14b", 9.0, 14.0, 20.0, {"code"},
          "ollama pull qwen2.5-coder:14b",
          "Top tier code 14B. Rivalise avec GPT-4o-mini en code."),
    Model("codellama:13b", 7.4, 13.0, 19.0, {"code"},
          "ollama pull codellama:13b",
          "Meta code-specialise. Classique fiable."),
    Model("llama3.2-vision:11b", 7.9, 12.0, 18.0, {"vision", "chat"},
          "ollama pull llama3.2-vision:11b",
          "Vision multimodale officielle Meta."),
    Model("gemma2:9b", 5.5, 10.0, 14.0, {"chat", "creative", "francais"},
          "ollama pull gemma2:9b",
          "Google. Conversation polie, bon FR."),

    # -------- Large (16-24 GB VRAM) --------
    Model("qwen2.5:32b", 19.0, 22.0, 32.0, {"chat", "code", "long_context"},
          "ollama pull qwen2.5:32b",
          "Premier vrai modele 'serieux' utilisable localement."),
    Model("qwen2.5-coder:32b", 19.0, 22.0, 32.0, {"code"},
          "ollama pull qwen2.5-coder:32b",
          "Un des meilleurs modeles code open-weight existants."),
    Model("codestral:22b", 13.0, 16.0, 24.0, {"code", "long_context"},
          "ollama pull codestral:22b",
          "Mistral code. Excellent en completion FIM. Contexte 32k."),
    Model("llava:34b", 20.0, 22.0, 32.0, {"vision", "chat"},
          "ollama pull llava:34b",
          "Vision haute qualite."),
    Model("command-r:35b", 20.0, 24.0, 36.0, {"chat", "long_context"},
          "ollama pull command-r:35b",
          "Cohere. Specialise RAG/agents. Contexte 128k."),

    # -------- XL (>=24 GB VRAM ou Mac M3+ 64GB) --------
    Model("llama3.3:70b", 40.0, 40.0, 60.0, {"chat", "code", "creative", "long_context"},
          "ollama pull llama3.3:70b",
          "70B. Tres proche GPT-4o pour le general. Multi-GPU ou Mac M3 Max+."),
    Model("qwen2.5:72b", 41.0, 42.0, 64.0, {"chat", "code", "long_context"},
          "ollama pull qwen2.5:72b",
          "72B. Excellent en code et raisonnement. Multi-GPU/Mac haut de gamme."),
]


def _max_vram(gpus: list[tuple[str, float]]) -> float:
    return max((g[1] for g in gpus), default=0.0)


def recommend(gpus: list[tuple[str, float]], ram_gb: float,
              use_cases: set[str]) -> list[tuple[Model, str]]:
    """Retourne une liste triee de (Model, raison) compatibles avec
    le hardware ET au moins un use case selectionne."""
    vram = _max_vram(gpus)
    results: list[tuple[Model, float, str]] = []

    for m in MODELS:
        # Filtre use case (au moins un en commun)
        if use_cases and not (m.use_cases & use_cases):
            continue

        # Compatibilite hardware
        gpu_ok = vram >= m.min_vram_gb
        ram_ok = ram_gb >= m.min_ram_gb

        if not gpu_ok and not ram_ok:
            continue

        # Score : prefere GPU offload, puis modele le plus gros possible
        if gpu_ok:
            # Plus le modele est proche de la VRAM dispo, mieux c'est (utilise le hardware)
            score = m.min_vram_gb + 0.5 * len(m.use_cases & use_cases)
            mode = "GPU"
        else:
            # CPU-only : score plus bas car beaucoup plus lent
            score = m.min_vram_gb * 0.3 + 0.3 * len(m.use_cases & use_cases)
            mode = "CPU (lent)"

        reason = f"[{mode}] {m.why}"
        results.append((m, score, reason))

    # Tri descendant par score, top 5
    results.sort(key=lambda x: -x[1])
    return [(m, r) for (m, _, r) in results[:5]]


# ============================================================
# UI Tkinter
# ============================================================

def main():
    root = tk.Tk()
    root.title("ModelAdvisor — Quel LLM local pour ton PC ?")
    root.geometry("780x680")
    root.configure(bg="#1a1d24")

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TLabel", background="#1a1d24", foreground="#e0e6ed", font=("Segoe UI", 10))
    style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#5dd0ff")
    style.configure("Spec.TLabel", font=("Consolas", 10), foreground="#a8d8ff", background="#0f1218")
    style.configure("TButton", font=("Segoe UI", 11, "bold"), padding=8)
    style.configure("TCheckbutton", background="#1a1d24", foreground="#e0e6ed", font=("Segoe UI", 10))

    # --- Header ---
    ttk.Label(root, text="🤖  ModelAdvisor", style="Header.TLabel").pack(pady=(14, 4))
    ttk.Label(root, text="Detecte ton hardware et recommande les meilleurs LLM locaux.").pack()

    # --- Specs detectees ---
    specs_frame = tk.Frame(root, bg="#0f1218", bd=1, relief="solid")
    specs_frame.pack(fill="x", padx=20, pady=12)

    ttk.Label(specs_frame, text="HARDWARE DETECTE",
              background="#0f1218", foreground="#5dd0ff",
              font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(8, 4))

    cpu = detect_cpu()
    cores = detect_cpu_cores()
    ram = detect_ram_gb()
    gpus = detect_gpus()
    max_vram = _max_vram(gpus)

    specs_text = f" CPU  : {cpu}  ({cores} cores)\n"
    specs_text += f" RAM  : {ram} Go\n"
    for i, (gname, gvram) in enumerate(gpus):
        specs_text += f" GPU{i}: {gname}  ({gvram} Go VRAM)\n"
    specs_text = specs_text.rstrip()

    ttk.Label(specs_frame, text=specs_text, style="Spec.TLabel",
              justify="left").pack(anchor="w", padx=12, pady=(0, 10))

    # --- Use case selection ---
    uc_frame = tk.Frame(root, bg="#1a1d24")
    uc_frame.pack(fill="x", padx=20, pady=4)
    ttk.Label(uc_frame, text="QUEL USAGE ?  (coche un ou plusieurs)",
              foreground="#5dd0ff", font=("Segoe UI", 10, "bold")).pack(anchor="w")

    uc_grid = tk.Frame(uc_frame, bg="#1a1d24")
    uc_grid.pack(fill="x", pady=4)

    uc_vars: dict[str, tk.BooleanVar] = {}
    for i, (key, label) in enumerate(USE_CASES.items()):
        var = tk.BooleanVar(value=(key == "chat"))
        # tk.Checkbutton (non-themed) pour controler explicitement toutes les
        # couleurs — ttk.Checkbutton clam theme a un hover blanc qui devient
        # illisible sur fond sombre.
        cb = tk.Checkbutton(
            uc_grid, text=label, variable=var,
            bg="#1a1d24", fg="#e0e6ed",
            activebackground="#1a1d24", activeforeground="#5dd0ff",
            selectcolor="#0a0d12",      # fond de la case quand cochee
            font=("Segoe UI", 10),
            bd=0, highlightthickness=0,
            cursor="hand2",
            anchor="w",
        )
        cb.grid(row=i // 2, column=i % 2, sticky="w", padx=8, pady=3)
        uc_vars[key] = var

    # --- Results ---
    results_frame = tk.Frame(root, bg="#0a0d12", bd=1, relief="solid")
    results_frame.pack(fill="both", expand=True, padx=20, pady=10)

    results_text = tk.Text(results_frame, bg="#0a0d12", fg="#e0e6ed",
                           font=("Consolas", 10), bd=0, padx=14, pady=12,
                           wrap="word", state="disabled")
    results_text.pack(fill="both", expand=True)

    results_text.tag_configure("title", foreground="#5dd0ff", font=("Segoe UI", 11, "bold"))
    results_text.tag_configure("name", foreground="#9bdfff", font=("Consolas", 11, "bold"))
    results_text.tag_configure("install", foreground="#7dffaf", font=("Consolas", 10))
    results_text.tag_configure("why", foreground="#cfe6ff", font=("Segoe UI", 9, "italic"))
    results_text.tag_configure("warn", foreground="#ffb86b", font=("Segoe UI", 9, "italic"))
    results_text.tag_configure("dim", foreground="#6b7e96", font=("Segoe UI", 9))

    def render_results():
        selected = {k for k, v in uc_vars.items() if v.get()}
        results_text.config(state="normal")
        results_text.delete("1.0", "end")

        if not selected:
            results_text.insert("end", "  Coche au moins un usage en haut.\n", "warn")
            results_text.config(state="disabled")
            return

        recs = recommend(gpus, ram, selected)

        if not recs:
            results_text.insert("end",
                "  Aucun modele compatible avec ton hardware actuel.\n"
                "  Considere LM Studio avec offload CPU/GPU partiel,\n"
                "  ou pousse vers une carte avec plus de VRAM.\n", "warn")
        else:
            results_text.insert("end", f"TOP {len(recs)} POUR TON PC :\n\n", "title")
            for i, (m, reason) in enumerate(recs, 1):
                results_text.insert("end", f"{i}. {m.name}", "name")
                results_text.insert("end", f"   ({m.size_gb} Go disque)\n", "dim")
                results_text.insert("end", f"   {reason}\n", "why")
                results_text.insert("end", f"   $ {m.install}\n\n", "install")

        results_text.insert("end",
            f"\nNote : VRAM detectee = {max_vram} Go, RAM = {ram} Go.\n"
            f"Pour utiliser : installer Ollama (https://ollama.com), puis lancer la commande ci-dessus.",
            "dim")
        results_text.config(state="disabled")

    # Auto-refresh des recommandations a chaque clic sur une checkbox.
    # Plus besoin de cliquer "Recommander" — c'est instantane.
    for var in uc_vars.values():
        var.trace_add("write", lambda *_: render_results())

    # Render initial
    render_results()

    root.mainloop()


if __name__ == "__main__":
    main()
