"""Suite de tests pytest de Jarvis.

Tests cibles sur la LOGIQUE PURE des modules (pas de reseau, pas de hardware).
Tous les chemins de fichiers sont isoles vers tmp_path via les fixtures de
conftest.py pour ne RIEN ecrire dans le depot.

Les imports lourds (pygame, google.genai, faster-whisper, spotipy, pyaudio,
keyring, openwakeword) sont paresseux dans les modules testes : la suite passe
avec uniquement python-dotenv + requests + numpy + psutil installes.
"""
