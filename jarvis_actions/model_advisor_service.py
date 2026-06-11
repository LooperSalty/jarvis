"""Service ModelAdvisor pour le dashboard web Jarvis.

Reutilise la logique du sous-projet model_advisor (detection hardware,
base de modeles Ollama, recommandation) cote backend, sans UI Tkinter.

Le sous-projet model_advisor/model_advisor.py est charge via importlib si
present (son import tkinter au niveau module ne cree aucune fenetre). En mode
frozen PyInstaller ou si l'import echoue, on retombe sur la copie vendorisee
ci-dessous : le .exe fonctionne donc sans le sous-projet.

API publique :
- detecter_specs() -> dict
- use_cases_disponibles() -> list[dict]
- recommander(use_cases, specs=None) -> dict
- modeles_installes() -> list[str]
"""

from __future__ import annotations

import importlib.util
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

# Meme defaut que main2.py (OLLAMA_URL ligne ~119), surchageable via .env
_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
_TIMEOUT_OLLAMA = 2.0   # secondes — GET /api/tags
_TIMEOUT_CMD = 5        # secondes — nvidia-smi / wmic / sysctl
_TOP_N = 8              # nombre max de modeles retournes par recommander()

# Empeche le flash de fenetres console quand Jarvis tourne en .exe windowed
# (Jarvis.exe / JarvisWeb.exe sont buildes avec console=False).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# ============================================================
# Import optionnel du sous-projet (source de verite si present)
# ============================================================

_SENTINELLE = object()
_module_cache: object = _SENTINELLE


def _charger_module_externe() -> object | None:
    """Charge model_advisor/model_advisor.py via importlib, ou None.

    Pas de hack sys.path : chargement direct par chemin de fichier.
    Echecs silencieux attendus : fichier absent (mode frozen), tkinter
    indisponible (le module source l'importe en tete de fichier).
    """
    candidats: list[Path] = []
    try:
        # En dev : <repo>/jarvis_actions/.. -> <repo>/model_advisor/model_advisor.py
        candidats.append(Path(__file__).resolve().parent.parent / "model_advisor" / "model_advisor.py")
        if getattr(sys, "frozen", False):
            # En frozen : tente a cote du .exe (rarement present, fallback vendorise sinon)
            candidats.append(Path(sys.executable).resolve().parent / "model_advisor" / "model_advisor.py")
    except Exception:
        pass

    nom_module = "_model_advisor_source"
    for chemin in candidats:
        try:
            if not chemin.is_file():
                continue
            spec = importlib.util.spec_from_file_location(nom_module, chemin)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            # Enregistrement requis AVANT exec_module : @dataclass resout les
            # annotations via sys.modules[cls.__module__] (recette importlib officielle)
            sys.modules[nom_module] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(nom_module, None)
                raise
            print(f"[MODEL-ADVISOR] Base de modeles chargee depuis {chemin}")
            return module
        except Exception as e:
            print(f"[MODEL-ADVISOR] Import du sous-projet impossible ({e}), donnees vendorisees utilisees.")
    return None


def _module_externe() -> object | None:
    """Renvoie le module source (charge une seule fois, cache)."""
    global _module_cache
    if _module_cache is _SENTINELLE:
        _module_cache = _charger_module_externe()
    return _module_cache  # type: ignore[return-value]


# ============================================================
# Donnees vendorisees
# Synchronise depuis model_advisor/model_advisor.py — mettre a jour les deux
# ============================================================

@dataclass(frozen=True)
class Model:
    """Un modele LLM local installable via Ollama."""

    name: str
    size_gb: float        # taille du fichier modele (Q4 quant)
    min_vram_gb: float    # VRAM necessaire pour full GPU offload
    min_ram_gb: float     # RAM necessaire en CPU-only
    use_cases: frozenset[str]
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


MODELS: tuple[Model, ...] = (
    # -------- Tiny (<=4 GB VRAM) --------
    Model("llama3.2:3b", 2.0, 4.0, 6.0, frozenset({"chat", "creative", "francais"}),
          "ollama pull llama3.2:3b",
          "Petit/rapide. Bon FR. Ideal sans GPU dedie."),
    Model("qwen2.5:3b", 1.9, 4.0, 6.0, frozenset({"chat", "code"}),
          "ollama pull qwen2.5:3b",
          "Code OK pour sa taille. Tres rapide."),
    Model("phi-3.5-mini", 2.5, 4.5, 7.0, frozenset({"chat", "code"}),
          "ollama pull phi3.5",
          "Microsoft. Etonnant en raisonnement/code pour 3.8B."),

    # -------- Small (4-8 GB VRAM) --------
    Model("llama3.1:8b", 4.7, 8.0, 12.0, frozenset({"chat", "creative", "long_context", "francais"}),
          "ollama pull llama3.1:8b",
          "Reference 8B. Bon FR. Contexte 128k."),
    Model("qwen2.5:7b", 4.7, 7.5, 11.0, frozenset({"chat", "code", "long_context"}),
          "ollama pull qwen2.5:7b",
          "Excellent rapport qualite/poids. Tres bon en code."),
    Model("mistral:7b", 4.4, 7.0, 11.0, frozenset({"chat", "creative", "francais"}),
          "ollama pull mistral:7b",
          "Mistral FR natif. Leger, ecriture fluide."),
    Model("mistral-nemo:12b", 7.1, 12.0, 18.0, frozenset({"chat", "creative", "long_context", "francais"}),
          "ollama pull mistral-nemo:12b",
          "Mistral x NVIDIA. 128k contexte. Excellent FR."),
    Model("qwen2.5-coder:7b", 4.7, 7.5, 11.0, frozenset({"code"}),
          "ollama pull qwen2.5-coder:7b",
          "Code-specialise. Plus efficace que llama pour generer du code."),
    Model("deepseek-coder-v2:lite", 8.9, 10.0, 14.0, frozenset({"code"}),
          "ollama pull deepseek-coder-v2:lite",
          "16B MoE actif 2.4B. Excellent code/VRAM."),
    Model("llava:7b", 4.7, 8.0, 12.0, frozenset({"vision", "chat"}),
          "ollama pull llava:7b",
          "Vision+texte. Decrit images, screenshots, photos."),

    # -------- Medium (8-16 GB VRAM) --------
    Model("qwen2.5:14b", 9.0, 14.0, 20.0, frozenset({"chat", "code", "long_context"}),
          "ollama pull qwen2.5:14b",
          "Sweet spot 14B. Raisonnement superieur a la classe 7B."),
    Model("qwen2.5-coder:14b", 9.0, 14.0, 20.0, frozenset({"code"}),
          "ollama pull qwen2.5-coder:14b",
          "Top tier code 14B. Rivalise avec GPT-4o-mini en code."),
    Model("codellama:13b", 7.4, 13.0, 19.0, frozenset({"code"}),
          "ollama pull codellama:13b",
          "Meta code-specialise. Classique fiable."),
    Model("llama3.2-vision:11b", 7.9, 12.0, 18.0, frozenset({"vision", "chat"}),
          "ollama pull llama3.2-vision:11b",
          "Vision multimodale officielle Meta."),
    Model("gemma2:9b", 5.5, 10.0, 14.0, frozenset({"chat", "creative", "francais"}),
          "ollama pull gemma2:9b",
          "Google. Conversation polie, bon FR."),

    # -------- Large (16-24 GB VRAM) --------
    Model("qwen2.5:32b", 19.0, 22.0, 32.0, frozenset({"chat", "code", "long_context"}),
          "ollama pull qwen2.5:32b",
          "Premier vrai modele 'serieux' utilisable localement."),
    Model("qwen2.5-coder:32b", 19.0, 22.0, 32.0, frozenset({"code"}),
          "ollama pull qwen2.5-coder:32b",
          "Un des meilleurs modeles code open-weight existants."),
    Model("codestral:22b", 13.0, 16.0, 24.0, frozenset({"code", "long_context"}),
          "ollama pull codestral:22b",
          "Mistral code. Excellent en completion FIM. Contexte 32k."),
    Model("llava:34b", 20.0, 22.0, 32.0, frozenset({"vision", "chat"}),
          "ollama pull llava:34b",
          "Vision haute qualite."),
    Model("command-r:35b", 20.0, 24.0, 36.0, frozenset({"chat", "long_context"}),
          "ollama pull command-r:35b",
          "Cohere. Specialise RAG/agents. Contexte 128k."),

    # -------- XL (>=24 GB VRAM ou Mac M3+ 64GB) --------
    Model("llama3.3:70b", 40.0, 40.0, 60.0, frozenset({"chat", "code", "creative", "long_context"}),
          "ollama pull llama3.3:70b",
          "70B. Tres proche GPT-4o pour le general. Multi-GPU ou Mac M3 Max+."),
    Model("qwen2.5:72b", 41.0, 42.0, 64.0, frozenset({"chat", "code", "long_context"}),
          "ollama pull qwen2.5:72b",
          "72B. Excellent en code et raisonnement. Multi-GPU/Mac haut de gamme."),
)

_ATTRS_MODELE = ("name", "size_gb", "min_vram_gb", "min_ram_gb", "use_cases", "install", "why")


def _donnees_actives() -> tuple[list, dict[str, str]]:
    """Retourne (modeles, use_cases) : sous-projet si charge et valide, sinon vendorise."""
    module = _module_externe()
    if module is not None:
        try:
            modeles = list(module.MODELS)  # type: ignore[attr-defined]
            libelles = dict(module.USE_CASES)  # type: ignore[attr-defined]
            if modeles and all(all(hasattr(m, a) for a in _ATTRS_MODELE) for m in modeles):
                return modeles, libelles
        except Exception as e:
            print(f"[MODEL-ADVISOR] Donnees du sous-projet invalides ({e}), fallback vendorise.")
    return list(MODELS), dict(USE_CASES)


def _evaluer_modele(m: Model, vram: float, ram_gb: float,
                    selection: frozenset[str]) -> tuple[float, bool] | None:
    """Score un modele pour le hardware/usages donnes, ou None si incompatible.

    Meme logique que recommend() du sous-projet :
    prefere le full GPU offload, puis le modele le plus gros possible.
    """
    if selection and not (set(m.use_cases) & selection):
        return None
    gpu_ok = vram >= m.min_vram_gb
    ram_ok = ram_gb >= m.min_ram_gb
    if not gpu_ok and not ram_ok:
        return None
    communs = len(set(m.use_cases) & selection)
    if gpu_ok:
        score = m.min_vram_gb + 0.5 * communs
    else:
        score = m.min_vram_gb * 0.3 + 0.3 * communs
    return score, gpu_ok


def recommend(gpus: list[tuple[str, float]], ram_gb: float,
              use_cases: set[str]) -> list[tuple[Model, str]]:
    """Copie fidele de recommend() du sous-projet (top 5, raisons courtes).

    Conservee pour compatibilite — le dashboard utilise recommander().
    """
    vram = max((g[1] for g in gpus), default=0.0)
    modeles, _ = _donnees_actives()
    results: list[tuple[Model, float, str]] = []
    for m in modeles:
        evaluation = _evaluer_modele(m, vram, ram_gb, frozenset(use_cases))
        if evaluation is None:
            continue
        score, gpu_ok = evaluation
        mode = "GPU" if gpu_ok else "CPU (lent)"
        results.append((m, score, f"[{mode}] {m.why}"))
    results.sort(key=lambda x: -x[1])
    return [(m, r) for (m, _, r) in results[:5]]


# ============================================================
# Detection hardware (cross-platform, jamais d'exception qui sort)
# ============================================================

def _ram_windows() -> float:
    """RAM totale (Go) sous Windows : ctypes en priorite, wmic en repli."""
    # Voie 1 : ctypes GlobalMemoryStatusEx (toujours dispo, fiable sur Win11)
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
    # Voie 2 : wmic (deprecie Win11, peut etre absent)
    try:
        output = subprocess.check_output(
            ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
            text=True, stderr=subprocess.DEVNULL, timeout=_TIMEOUT_CMD,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
        for line in output.split("\n"):
            line = line.strip()
            if line.isdigit():
                return round(int(line) / (1024 ** 3), 1)
    except Exception:
        pass
    return 0.0


def _ram_linux() -> float:
    """RAM totale (Go) sous Linux via /proc/meminfo."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / (1024 ** 2), 1)
    except Exception:
        pass
    return 0.0


def _ram_macos() -> float:
    """RAM totale (Go) sous macOS via sysctl hw.memsize."""
    try:
        output = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], text=True, timeout=_TIMEOUT_CMD,
        )
        return round(int(output.strip()) / (1024 ** 3), 1)
    except Exception:
        pass
    return 0.0


def _detecter_ram_gb() -> float:
    """RAM totale en Go, 0.0 si indetectable."""
    try:
        systeme = platform.system()
        if systeme == "Windows":
            return _ram_windows()
        if systeme == "Linux":
            return _ram_linux()
        if systeme == "Darwin":
            return _ram_macos()
    except Exception:
        pass
    return 0.0


def _gpus_nvidia() -> list[dict]:
    """GPU NVIDIA via nvidia-smi (donne la vraie VRAM)."""
    gpus: list[dict] = []
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL, timeout=_TIMEOUT_CMD,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
        for line in output.strip().split("\n"):
            if "," in line:
                name, mem_mb = line.split(",", 1)
                try:
                    gpus.append({"name": name.strip(),
                                 "vram_gb": round(int(mem_mb.strip()) / 1024, 1)})
                except ValueError:
                    continue
    except Exception:
        pass
    return gpus


def _gpus_apple(ram_gb: float) -> list[dict]:
    """Apple Silicon : memoire unifiee, ~70% utilisable comme VRAM."""
    try:
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            return [{"name": "Apple Silicon (memoire unifiee)",
                     "vram_gb": round(ram_gb * 0.7, 1)}]
    except Exception:
        pass
    return []


def _gpus_wmic() -> list[dict]:
    """Fallback Windows : wmic Win32_VideoController (VRAM plafonnee a 4 Go)."""
    gpus: list[dict] = []
    try:
        output = subprocess.check_output(
            ["wmic", "path", "Win32_VideoController", "get",
             "Name,AdapterRAM", "/format:list"],
            text=True, stderr=subprocess.DEVNULL, timeout=_TIMEOUT_CMD,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
        entries = re.findall(r"AdapterRAM=(\d+)\s+Name=([^\r\n]+)", output)
        for ram_bytes, name in entries:
            try:
                if not name.strip().startswith("Microsoft"):
                    gpus.append({"name": name.strip(),
                                 "vram_gb": round(int(ram_bytes) / (1024 ** 3), 1)})
            except ValueError:
                continue
    except Exception:
        pass
    return gpus


def _detecter_gpus(ram_gb: float) -> list[dict]:
    """Liste des GPU detectes : [{"name": str, "vram_gb": float}], [] si aucun."""
    try:
        gpus = _gpus_nvidia()
        if gpus:
            return gpus
        gpus = _gpus_apple(ram_gb)
        if gpus:
            return gpus
        if platform.system() == "Windows":
            return _gpus_wmic()
    except Exception:
        pass
    return []


def _cpu_windows() -> str:
    """Nom commercial du CPU via le registre (ProcessorNameString).
    platform.processor() renvoie 'Family 6 Model... GenuineIntel' sous Windows,
    pas le nom commercial — on lit donc le registre directement."""
    try:
        import winreg
        cle = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cle) as k:
            nom, _ = winreg.QueryValueEx(k, "ProcessorNameString")
            if nom:
                return " ".join(str(nom).split())  # normalise les espaces
    except Exception:
        pass
    return ""


def _cpu_linux() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
            for ligne in f:
                if ligne.lower().startswith("model name"):
                    return ligne.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _cpu_macos() -> str:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _detecter_cpu() -> str:
    """Nom commercial du CPU (ex. 'Intel Core i7-13700KF'), cross-platform.
    'CPU inconnu' en dernier recours."""
    try:
        nom = ""
        if sys.platform == "win32":
            nom = _cpu_windows()
        elif sys.platform == "darwin":
            nom = _cpu_macos()
        elif sys.platform.startswith("linux"):
            nom = _cpu_linux()
        # Repli generique : platform.processor() (utile hors des 3 OS ci-dessus).
        nom = nom or platform.processor() or platform.machine()
        # platform.processor() peut renvoyer la chaine 'Family N Model...' brute :
        # on la rejette au profit d'un libelle plus parlant.
        if not nom or nom.lower().startswith("family ") or "genuineintel" in nom.lower():
            return platform.machine() or "CPU inconnu"
        return nom
    except Exception:
        return "CPU inconnu"


def _detecter_coeurs() -> int:
    """Nombre de coeurs logiques, 0 si indetectable."""
    try:
        return os.cpu_count() or 0
    except Exception:
        return 0


def _detecter_os() -> str:
    """Nom + version de l'OS, 'OS inconnu' en dernier recours."""
    try:
        return f"{platform.system()} {platform.release()}".strip() or "OS inconnu"
    except Exception:
        return "OS inconnu"


def detecter_specs() -> dict:
    """Detecte le hardware de la machine. Ne leve jamais d'exception.

    Returns:
        dict: {"os", "cpu", "coeurs", "ram_gb",
               "gpus": [{"name", "vram_gb"}], "vram_max_gb"}
    """
    ram_gb = _detecter_ram_gb()
    gpus = _detecter_gpus(ram_gb)
    try:
        vram_max = max((float(g.get("vram_gb", 0.0)) for g in gpus), default=0.0)
    except Exception:
        vram_max = 0.0
    return {
        "os": _detecter_os(),
        "cpu": _detecter_cpu(),
        "coeurs": _detecter_coeurs(),
        "ram_gb": ram_gb,
        "gpus": gpus,
        "vram_max_gb": vram_max,
    }


# ============================================================
# Ollama : modeles deja installes
# ============================================================

def modeles_installes() -> list[str]:
    """Liste les modeles deja installes via GET /api/tags. [] si Ollama down."""
    try:
        r = requests.get(f"{_OLLAMA_URL}/api/tags", timeout=_TIMEOUT_OLLAMA)
        r.raise_for_status()
        data = r.json()
        modeles = data.get("models", []) if isinstance(data, dict) else []
        return [m["name"] for m in modeles if isinstance(m, dict) and m.get("name")]
    except Exception:
        return []


def _est_installe(commande_install: str, installes: set[str]) -> bool:
    """Vrai si la cible de 'ollama pull <cible>' figure dans les tags installes."""
    try:
        cible = commande_install.split()[-1]
        if cible in installes:
            return True
        if ":" not in cible:
            # ex: 'phi3.5' matche 'phi3.5:latest'
            return any(tag.split(":")[0] == cible for tag in installes)
    except Exception:
        pass
    return False


# ============================================================
# Recommandation pour le dashboard
# ============================================================

def use_cases_disponibles() -> list[dict]:
    """Liste des usages selectionnables : [{"id": str, "label": str}]."""
    try:
        _, libelles = _donnees_actives()
        return [{"id": cle, "label": label} for cle, label in libelles.items()]
    except Exception as e:
        print(f"[MODEL-ADVISOR] use_cases_disponibles erreur : {e}")
        return [{"id": cle, "label": label} for cle, label in USE_CASES.items()]


def _valider_use_cases(use_cases: list[str] | None, libelles: dict[str, str]) -> frozenset[str]:
    """Garde uniquement les ids d'usage connus. Vide = pas de filtre."""
    if not isinstance(use_cases, (list, tuple, set, frozenset)):
        return frozenset()
    valides = {u for u in use_cases if isinstance(u, str) and u in libelles}
    inconnus = {u for u in use_cases if isinstance(u, str)} - valides
    if inconnus:
        print(f"[MODEL-ADVISOR] Usages inconnus ignores : {sorted(inconnus)}")
    return frozenset(valides)


def _extraire_hardware(specs: dict) -> tuple[float, float]:
    """Extrait (vram_max_gb, ram_gb) d'un dict specs, tolere les champs absents."""
    vram, ram = 0.0, 0.0
    try:
        ram = float(specs.get("ram_gb", 0.0) or 0.0)
    except Exception:
        pass
    try:
        vram = float(specs.get("vram_max_gb", 0.0) or 0.0)
        if vram <= 0.0:
            gpus = specs.get("gpus", []) or []
            vram = max((float(g.get("vram_gb", 0.0)) for g in gpus
                        if isinstance(g, dict)), default=0.0)
    except Exception:
        pass
    return vram, ram


def _construire_raison(m: Model, gpu_ok: bool, vram: float, ram_gb: float,
                       selection: frozenset[str], libelles: dict[str, str]) -> str:
    """Raison en francais expliquant le score d'un modele."""
    if gpu_ok:
        base = f"tient dans tes {vram:g} Go de VRAM (full GPU)"
    else:
        base = (f"depasse ta VRAM ({vram:g} Go), tournera sur CPU "
                f"avec tes {ram_gb:g} Go de RAM (lent)")
    communs = sorted(set(m.use_cases) & selection)
    if communs:
        noms = ", ".join(libelles.get(u, u) for u in communs)
        base += f", pertinent pour : {noms}"
    return f"{base}. {m.why}"


def _formater_modele(m: Model, score: float, gpu_ok: bool, vram: float,
                     ram_gb: float, selection: frozenset[str],
                     libelles: dict[str, str], installes: set[str]) -> dict:
    """Construit le dict d'un modele recommande pour le dashboard."""
    return {
        "name": m.name,
        "taille_gb": m.size_gb,
        "vram_necessaire_gb": m.min_vram_gb,
        "usages": sorted(m.use_cases),
        "score": round(score, 2),
        "raison": _construire_raison(m, gpu_ok, vram, ram_gb, selection, libelles),
        "commande_install": m.install,
        "installe": _est_installe(m.install, installes),
    }


def recommander(use_cases: list[str], specs: dict | None = None) -> dict:
    """Recommande les meilleurs modeles locaux pour le hardware et les usages.

    Args:
        use_cases: ids d'usage (cf. use_cases_disponibles()). Vide = tous.
        specs: dict au format detecter_specs(), ou None pour auto-detection.

    Returns:
        dict: {"specs": dict, "modeles": [dict, ...]} — top 8 max, tries par
        score decroissant. Ne leve jamais d'exception.
    """
    try:
        if not isinstance(specs, dict):
            specs = detecter_specs()
        modeles, libelles = _donnees_actives()
        selection = _valider_use_cases(use_cases, libelles)
        vram, ram_gb = _extraire_hardware(specs)
        installes = set(modeles_installes())

        resultats: list[dict] = []
        for m in modeles:
            evaluation = _evaluer_modele(m, vram, ram_gb, selection)
            if evaluation is None:
                continue
            score, gpu_ok = evaluation
            resultats.append(_formater_modele(m, score, gpu_ok, vram, ram_gb,
                                              selection, libelles, installes))
        resultats.sort(key=lambda d: -d["score"])
        return {"specs": specs, "modeles": resultats[:_TOP_N]}
    except Exception as e:
        print(f"[MODEL-ADVISOR] recommander erreur : {e}")
        return {"specs": specs if isinstance(specs, dict) else {}, "modeles": []}


if __name__ == "__main__":
    # Test manuel rapide : python jarvis_actions/model_advisor_service.py
    import json

    specs_test = detecter_specs()
    print(json.dumps(specs_test, indent=2, ensure_ascii=False))
    reco = recommander(["code", "chat"], specs_test)
    for modele in reco["modeles"]:
        print(f"- {modele['name']} (score {modele['score']}, "
              f"installe={modele['installe']}) : {modele['raison']}")
