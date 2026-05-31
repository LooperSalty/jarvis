"""01_mini_gpt.py — un transformer minimal de A a Z, commente en francais.

Objectif pedagogique : comprendre exactement comment qwen2.5 / GPT / llama
fonctionnent sous le capot. On entraine un mini-modele (~1M parametres) sur
un petit corpus, puis on lui fait generer du texte.

Inspire de nanoGPT (Karpathy) mais simplifie au maximum et en francais.

Usage:
    pip install torch
    python apprendre/01_mini_gpt.py

Ca tourne sur CPU en quelques minutes. Sur GPU c'est instantane.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F


# =============================================================================
# 0. HYPER-PARAMETRES — toutes les manettes du modele en un seul endroit
# =============================================================================

# --- Donnees ---
CORPUS_URL = (
    "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/"
    "tinyshakespeare/input.txt"
)
CORPUS_PATH = Path(__file__).parent / "_tinyshakespeare.txt"
TRAIN_RATIO = 0.9  # 90% train, 10% validation

# --- Architecture ---
BLOCK_SIZE = 128         # taille du contexte (combien de tokens passes le modele voit)
BATCH_SIZE = 32          # nombre de sequences traitees en parallele
N_EMBED = 128            # dimension des vecteurs d'embedding
N_HEAD = 4               # nombre de tetes d'attention (multi-head)
N_LAYER = 4              # nombre de blocs transformer empiles
DROPOUT = 0.1            # taux de dropout (regularisation)

# --- Entrainement ---
LR = 3e-4                # learning rate (taille des pas de gradient)
MAX_ITERS = 3000         # nombre d'iterations d'entrainement
INTERVAL_VALIDATION = 500  # frequence d'evaluation sur validation
ITERS_VALIDATION = 50    # nombre de batches pour estimer la loss val
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Reproductibilite
torch.manual_seed(1337)


# =============================================================================
# 1. DONNEES — on prend un petit corpus et on construit un tokenizer character-level
# =============================================================================
#
# Un LLM ne lit pas du texte directement, il lit des entiers (tokens).
# Pour pedagogie, on tokenise au CARACTERE : chaque char unique = un token.
# Les vrais LLMs (qwen, gpt) utilisent un tokenizer BPE plus efficient
# (~50K-150K tokens au lieu de ~70 chars), mais le principe est le meme.

def telecharger_corpus() -> str:
    """Download le corpus si absent, le lit, retourne le texte."""
    if not CORPUS_PATH.exists():
        import urllib.request

        print(f"[data] download {CORPUS_URL} -> {CORPUS_PATH}")
        urllib.request.urlretrieve(CORPUS_URL, CORPUS_PATH)
    return CORPUS_PATH.read_text(encoding="utf-8")


text = telecharger_corpus()
print(f"[data] corpus de {len(text):,} caracteres")

chars = sorted(set(text))
vocab_size = len(chars)
print(f"[data] vocab_size = {vocab_size} (caracteres uniques)")

# Tokenizer : char <-> int. Plus simple possible.
stoi = {ch: i for i, ch in enumerate(chars)}
itos = {i: ch for ch, i in stoi.items()}


def encoder(s: str) -> list[int]:
    """Texte -> liste d'entiers."""
    return [stoi[c] for c in s]


def decoder(ids: list[int]) -> str:
    """Entiers -> texte."""
    return "".join(itos[i] for i in ids)


# On encode tout le corpus en un gros tensor 1D
data = torch.tensor(encoder(text), dtype=torch.long)
n_train = int(TRAIN_RATIO * len(data))
train_data, val_data = data[:n_train], data[n_train:]
print(f"[data] train = {len(train_data):,} tokens, val = {len(val_data):,} tokens")


def get_batch(split: str):
    """Tire BATCH_SIZE sequences aleatoires de longueur BLOCK_SIZE.

    Retourne (x, y) ou y est x decale d'un cran a droite.
    Le modele apprendra : "etant donne x[:t], predis x[t]" (next-token prediction).
    """
    src = train_data if split == "train" else val_data
    # On pioche BATCH_SIZE indices de depart aleatoires
    ix = torch.randint(len(src) - BLOCK_SIZE, (BATCH_SIZE,))
    x = torch.stack([src[i : i + BLOCK_SIZE] for i in ix])
    y = torch.stack([src[i + 1 : i + BLOCK_SIZE + 1] for i in ix])
    return x.to(DEVICE), y.to(DEVICE)


# =============================================================================
# 2. SELF-ATTENTION — l'idee centrale du transformer
# =============================================================================
#
# Pour chaque token a la position t, on veut une representation qui melange
# les infos des tokens precedents (0..t). Pas de la moyenne bete : un melange
# pondere ou les poids dependent du CONTENU des tokens.
#
# 3 vecteurs par token :
#   - query (Q) : "qu'est-ce que je cherche ?"
#   - key   (K) : "qu'est-ce que je contiens ?"
#   - value (V) : "si on me consulte, voici ce que je transmets"
#
# Score d'attention de t vers t' = Q[t] . K[t']  (produit scalaire)
# Plus le produit est grand, plus le token t' est "pertinent" pour t.
# On normalise les scores avec softmax -> probabilites.
# Le nouveau vecteur de t = somme ponderee des V[t'].
#
# Causal mask : on interdit a t de regarder t' > t (sinon le modele tricherait
# pendant l'entrainement en voyant le futur).

class TeteAttention(nn.Module):
    """Une seule tete d'attention causale."""

    def __init__(self, head_size: int):
        super().__init__()
        self.key = nn.Linear(N_EMBED, head_size, bias=False)
        self.query = nn.Linear(N_EMBED, head_size, bias=False)
        self.value = nn.Linear(N_EMBED, head_size, bias=False)
        # Masque triangulaire pour empecher de regarder le futur
        self.register_buffer("tril", torch.tril(torch.ones(BLOCK_SIZE, BLOCK_SIZE)))
        self.dropout = nn.Dropout(DROPOUT)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape  # batch, time, channels
        k = self.key(x)    # (B, T, head_size)
        q = self.query(x)  # (B, T, head_size)
        # Scores : produit scalaire QK normalise par sqrt(d) pour stabilite
        scores = q @ k.transpose(-2, -1) * k.shape[-1] ** -0.5  # (B, T, T)
        # Masquer le futur : on remplace par -inf -> apres softmax = 0
        scores = scores.masked_fill(self.tril[:T, :T] == 0, float("-inf"))
        weights = F.softmax(scores, dim=-1)
        weights = self.dropout(weights)
        v = self.value(x)
        return weights @ v  # (B, T, head_size)


class MultiTeteAttention(nn.Module):
    """Plusieurs tetes d'attention en parallele, puis concatenation + projection.

    Pourquoi plusieurs tetes ? Chaque tete peut apprendre un type de relation
    different (syntaxe, semantique, references coreferentielles, etc.).
    """

    def __init__(self, n_head: int, head_size: int):
        super().__init__()
        self.heads = nn.ModuleList([TeteAttention(head_size) for _ in range(n_head)])
        self.proj = nn.Linear(n_head * head_size, N_EMBED)
        self.dropout = nn.Dropout(DROPOUT)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Concatene la sortie de chaque tete sur la dimension channels
        out = torch.cat([h(x) for h in self.heads], dim=-1)
        out = self.proj(out)
        return self.dropout(out)


# =============================================================================
# 3. FEED-FORWARD — petit MLP applique a chaque position independamment
# =============================================================================
#
# L'attention melange les positions ; le feed-forward TRAITE chaque position.
# C'est typiquement un MLP : Linear -> ReLU -> Linear.
# Le facteur 4 est conventionnel (vient du papier "Attention Is All You Need").

class FeedForward(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(N_EMBED, 4 * N_EMBED),
            nn.ReLU(),
            nn.Linear(4 * N_EMBED, N_EMBED),
            nn.Dropout(DROPOUT),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# =============================================================================
# 4. BLOC TRANSFORMER — assemble attention + feed-forward avec connexions residuelles
# =============================================================================
#
# Connexion residuelle (x = x + sublayer(x)) : permet aux gradients de remonter
# meme dans des reseaux profonds. Sans ca, les LLMs profonds ne s'entraineraient
# pas correctement.
#
# LayerNorm : normalise chaque vecteur (moyenne 0, variance 1) pour stabiliser.
# Pre-norm (LayerNorm AVANT chaque sublayer) est la convention moderne.

class BlocTransformer(nn.Module):
    def __init__(self, n_head: int):
        super().__init__()
        head_size = N_EMBED // n_head
        self.attention = MultiTeteAttention(n_head, head_size)
        self.feed_forward = FeedForward()
        self.norm1 = nn.LayerNorm(N_EMBED)
        self.norm2 = nn.LayerNorm(N_EMBED)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Pre-norm + connexion residuelle
        x = x + self.attention(self.norm1(x))
        x = x + self.feed_forward(self.norm2(x))
        return x


# =============================================================================
# 5. MODELE COMPLET — empile les blocs et ajoute embeddings + tete de prediction
# =============================================================================

class MiniGPT(nn.Module):
    def __init__(self):
        super().__init__()
        # Token embedding : convertit chaque ID de char en vecteur de N_EMBED dims
        self.token_embedding = nn.Embedding(vocab_size, N_EMBED)
        # Position embedding : donne au modele l'info de POSITION (sinon il
        # traiterait la sequence comme un sac, sans ordre)
        self.position_embedding = nn.Embedding(BLOCK_SIZE, N_EMBED)
        # Empilage de N_LAYER blocs transformer
        self.blocs = nn.Sequential(*[BlocTransformer(N_HEAD) for _ in range(N_LAYER)])
        self.norm_finale = nn.LayerNorm(N_EMBED)
        # Tete de sortie : projete sur le vocabulaire (logits par token)
        self.tete = nn.Linear(N_EMBED, vocab_size)

    def forward(self, idx: torch.Tensor, cibles: torch.Tensor | None = None):
        B, T = idx.shape
        # Embeddings : token + position s'ajoutent
        tok_emb = self.token_embedding(idx)                       # (B, T, N_EMBED)
        pos_emb = self.position_embedding(torch.arange(T, device=DEVICE))  # (T, N_EMBED)
        x = tok_emb + pos_emb                                     # broadcast -> (B, T, N_EMBED)
        # Passe par tous les blocs transformer
        x = self.blocs(x)
        x = self.norm_finale(x)
        logits = self.tete(x)                                     # (B, T, vocab_size)

        if cibles is None:
            return logits, None
        # Cross-entropy entre logits predits et cibles reelles
        # On reshape pour que F.cross_entropy soit content
        B, T, V = logits.shape
        loss = F.cross_entropy(logits.view(B * T, V), cibles.view(B * T))
        return logits, loss

    @torch.no_grad()
    def generer(self, idx: torch.Tensor, max_new_tokens: int, temperature: float = 1.0):
        """Generation autoregressive : token par token.

        A chaque etape :
        1. Prendre les BLOCK_SIZE derniers tokens (le contexte du modele)
        2. Calculer les logits du dernier token
        3. Diviser par temperature (T<1 = plus deterministe, T>1 = plus aleatoire)
        4. Softmax -> distribution de probas
        5. Sampler un token, l'ajouter a la sequence
        6. Repeter
        """
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -BLOCK_SIZE:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :] / temperature  # dernier token uniquement
            probs = F.softmax(logits, dim=-1)
            next_tok = torch.multinomial(probs, num_samples=1)
            idx = torch.cat([idx, next_tok], dim=1)
        return idx


# =============================================================================
# 6. ENTRAINEMENT — boucle classique : forward, loss, backward, step
# =============================================================================

@torch.no_grad()
def estimer_loss(model: MiniGPT) -> dict:
    """Evalue la loss sur train et val, retourne un dict."""
    model.train(False)  # mode validation : desactive dropout
    out = {}
    for split in ("train", "val"):
        losses = torch.zeros(ITERS_VALIDATION)
        for k in range(ITERS_VALIDATION):
            x, y = get_batch(split)
            _, loss = model(x, y)
            losses[k] = loss.item()
        out[split] = losses.mean().item()
    model.train(True)  # remet le mode entrainement
    return out


def main():
    print(f"[init] device = {DEVICE}")
    model = MiniGPT().to(DEVICE)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[init] modele initialise avec {n_params:,} parametres")

    optimiseur = torch.optim.AdamW(model.parameters(), lr=LR)

    print(f"[train] lance pour {MAX_ITERS} iterations")
    for iteration in range(MAX_ITERS):
        # Validation periodique
        if iteration % INTERVAL_VALIDATION == 0 or iteration == MAX_ITERS - 1:
            losses = estimer_loss(model)
            print(
                f"  iter {iteration:5d} | "
                f"train loss {losses['train']:.4f} | "
                f"val loss {losses['val']:.4f}"
            )

        # Un pas d'entrainement
        x, y = get_batch("train")
        logits, loss = model(x, y)
        optimiseur.zero_grad(set_to_none=True)
        loss.backward()
        optimiseur.step()

    print("\n[generation] avec le modele entraine :")
    print("-" * 60)
    contexte = torch.zeros((1, 1), dtype=torch.long, device=DEVICE)  # commence a 0 (newline)
    sortie = model.generer(contexte, max_new_tokens=500, temperature=0.8)
    print(decoder(sortie[0].tolist()))
    print("-" * 60)
    print(
        "\n[ce que tu viens de voir]\n"
        "  Un modele de quelques millions de parametres entraine sur Shakespeare\n"
        "  en quelques minutes. La loss descend de ~4.2 (random) a ~1.5.\n"
        "  qwen2.5:7b est exactement la meme architecture, juste 1000x plus gros\n"
        "  et entraine sur ~15 trillion de tokens au lieu de 1 million.\n\n"
        "  Maintenant tu peux ouvrir le code de qwen2.5 (huggingface modeling_qwen2.py)\n"
        "  et tu reconnaitras chaque bloc.\n"
    )


if __name__ == "__main__":
    main()
