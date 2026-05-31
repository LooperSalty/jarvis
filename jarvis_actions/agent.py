"""Agent IA Jarvis avec Gemini Function Calling.

Permet a Jarvis de raisonner par lui-meme : on declare la liste des actions
qu'il sait faire (tools), Gemini decide quoi appeler en fonction de la requete
utilisateur, on execute, on lui renvoie le resultat, il continue jusqu'a la
reponse finale.

Usage : await run_agent(client, model_name, system_prompt, user_text, dispatch_fn)

Le dispatch est une callable async(name, args_dict) -> str fournie par
l'appelant. Cela evite les imports circulaires avec main2.py.
"""

from __future__ import annotations

from google.genai import types

# ============================================================
# Definition des tools (fonction-declarations Gemini)
# ============================================================

TOOLS = [
    types.Tool(function_declarations=[
        # --- Conversation finale ---
        types.FunctionDeclaration(
            name="respond",
            description=(
                "Repond directement a l'utilisateur sans aucune action systeme. "
                "A utiliser pour les questions de conversation, les explications, "
                "les confirmations, ou quand toutes les actions necessaires "
                "ont ete executees. Termine la session agent."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "text": types.Schema(
                        type=types.Type.STRING,
                        description="Le texte a dire a l'utilisateur (court, naturel, en francais).",
                    ),
                },
                required=["text"],
            ),
        ),

        # --- Domotique (Meross) ---
        types.FunctionDeclaration(
            name="toggle_light",
            description="Allume ou eteint la prise connectee Meross (toggle automatique selon l'etat actuel).",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="set_light",
            description="Force l'etat de la prise Meross (true=allume, false=eteinte).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"on": types.Schema(type=types.Type.BOOLEAN)},
                required=["on"],
            ),
        ),

        # --- Audio / Media (touches Win32 globales) ---
        types.FunctionDeclaration(
            name="media_control",
            description="Controle le lecteur media actif (Spotify, YouTube, VLC, etc.) via les touches media Windows.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "action": types.Schema(
                        type=types.Type.STRING,
                        enum=["play_pause", "next", "previous"],
                    ),
                },
                required=["action"],
            ),
        ),
        types.FunctionDeclaration(
            name="set_volume",
            description="Modifie le volume systeme Windows.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "action": types.Schema(
                        type=types.Type.STRING,
                        enum=["up", "down", "max", "min", "mute"],
                    ),
                    "steps": types.Schema(
                        type=types.Type.INTEGER,
                        description="Nombre de crans (chaque cran = 2%, defaut 5). Ignore pour mute/max/min.",
                    ),
                },
                required=["action"],
            ),
        ),
        types.FunctionDeclaration(
            name="play_music",
            description="Lance Spotify sur la playlist Liked Songs et clique le bouton Play vert. Active le shuffle si demande.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "shuffle": types.Schema(type=types.Type.BOOLEAN),
                },
            ),
        ),

        # --- Apps / Fenetres ---
        types.FunctionDeclaration(
            name="open_app",
            description=(
                "Ouvre ou ramene au premier plan une application Windows. "
                "Connait : chrome, firefox, edge, vscode, discord, spotify, steam, "
                "obsidian, notepad, calculatrice, explorer, terminal, paint, "
                "task manager. Cherche aussi dans le menu Demarrer."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"name": types.Schema(type=types.Type.STRING)},
                required=["name"],
            ),
        ),
        types.FunctionDeclaration(
            name="close_active_window",
            description="Ferme la fenetre actuellement au premier plan (Alt+F4).",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="lock_pc",
            description="Verrouille Windows (ecran de connexion).",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="screenshot",
            description="Prend une capture d'ecran et la sauve dans Pictures/Jarvis/.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="screens_off",
            description="Eteint les ecrans (mise en veille DPMS, le PC reste allume).",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),

        # --- Navigateur Chromium pilote (Playwright) ---
        types.FunctionDeclaration(
            name="browser_navigate",
            description=(
                "Ouvre une URL ou un site connu dans le Chromium pilote par Jarvis. "
                "Sites connus : youtube, google, gmail, amazon, github, twitter, "
                "wikipedia, chatgpt, claude, gemini, etc. Aussi : URLs completes."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"site_or_url": types.Schema(type=types.Type.STRING)},
                required=["site_or_url"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_search",
            description="Lance une recherche dans Google, YouTube ou Amazon (selon le moteur choisi).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "engine": types.Schema(
                        type=types.Type.STRING,
                        enum=["google", "youtube", "amazon"],
                    ),
                    "query": types.Schema(type=types.Type.STRING),
                },
                required=["engine", "query"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_click",
            description="Clique sur un element du navigateur dont le texte/label visible est donne.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"text": types.Schema(type=types.Type.STRING)},
                required=["text"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_read_page",
            description="Lit le contenu principal de la page web actuellement ouverte (article, main content). Tronque a 1500 chars.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="browser_close",
            description="Ferme le navigateur Chromium pilote par Jarvis.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),

        # --- Recherche YouTube directe (joue plein ecran) ---
        types.FunctionDeclaration(
            name="play_youtube",
            description="Cherche sur YouTube et lance la 1ere video en plein ecran dans le navigateur par defaut.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"query": types.Schema(type=types.Type.STRING)},
                required=["query"],
            ),
        ),

        # --- Mini-fenetre Jarvis ---
        types.FunctionDeclaration(
            name="hide_orb",
            description="Cache la mini-fenetre orbe de Jarvis (utiliser quand l'utilisateur dit 'cache toi' / 'disparais').",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
    ]),
]


# ============================================================
# Boucle agent
# ============================================================

MAX_AGENT_TURNS = 6  # garde-fou contre boucles infinies


async def run_agent(
    client,
    model_name: str,
    system_prompt: str,
    user_text: str,
    dispatch,
    history: list | None = None,
    max_turns: int = MAX_AGENT_TURNS,
) -> str:
    """Lance l'agent IA. Retourne le texte final dit par Jarvis.

    Args:
        client: instance google.genai.Client
        model_name: ex 'gemini-2.5-flash'
        system_prompt: prompt systeme decrivant Jarvis
        user_text: la requete utilisateur
        dispatch: async fn(name: str, args: dict) -> str (resultat tool)
        history: historique optionnel (liste de types.Content)

    Le tool 'respond' termine la boucle.
    """
    import asyncio

    config = types.GenerateContentConfig(
        tools=TOOLS,
        system_instruction=system_prompt,
        temperature=0.6,
    )

    contents: list = list(history) if history else []
    contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    final_text = "Action effectuee."
    for turn in range(max_turns):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            print(f"[AGENT] Echec Gemini turn {turn} : {e}")
            return final_text

        # Inspect function calls
        fcs = getattr(response, "function_calls", None) or []
        if not fcs:
            # Reponse texte pure -> termine
            txt = (response.text or "").strip()
            return txt or final_text

        # Ajoute la reponse model (avec function_call) a l'historique
        # Pour simplifier on ajoute response.candidates[0].content
        try:
            contents.append(response.candidates[0].content)
        except Exception:
            pass

        # Execute chaque function call et envoie le result
        for fc in fcs:
            name = fc.name
            args = dict(fc.args) if fc.args else {}
            print(f"[AGENT] Tool call : {name}({args})")

            if name == "respond":
                # Termine la boucle agent
                return args.get("text") or final_text

            try:
                result = await dispatch(name, args)
            except Exception as e:
                result = f"Erreur execution : {e}"
            print(f"[AGENT] -> {str(result)[:120]}")

            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=name,
                    response={"result": result or "ok"},
                )],
            ))
            # Met a jour le texte final au cas ou la boucle s'arrete
            final_text = str(result or final_text)

    print(f"[AGENT] Max turns ({max_turns}) atteint")
    return final_text
