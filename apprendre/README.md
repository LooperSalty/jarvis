# Apprendre les IA + ameliorer Jarvis

Ce dossier est ton parcours pour passer de "j'utilise un LLM" a "je comprends et j'ameliore un LLM". Quatre etapes, du theorique au tres concret sur TON Jarvis.

## Vue d'ensemble

| # | Fichier | Niveau | Ce que tu apprends | Ce qui s'ameliore sur Jarvis |
|---|---------|--------|---------------------|------------------------------|
| 0 | (`main2.py`) | basique | prompt engineering, tools | deja fait |
| 1 | `01_mini_gpt.py` | fondations | comment marche un transformer | rien (theorique) |
| 2 | `02_dspy_optimiser_prompt.py` | optim auto | comment optimiser un prompt avec un solveur | system prompt de Jarvis ameliore avec ses vraies conversations |
| 3 | `03_lora_finetune_qwen.py` | fine-tuning | comment specialiser un LLM avec LoRA | qwen2.5 entraine sur ton style et tes preferences |
| 4 | `04_jarvis_apprend_de_lui_meme.py` | continu | boucle auto-amelioration sur tes vraies conversations | declenche auto DSPy + LoRA quand seuils atteints |

**Ordre conseille** : 1 -> 2 -> 3. Le 1 te donne la theorie pour comprendre les 2 et 3.

## Etape 1 — Mini-GPT from scratch

```powershell
pip install torch
python apprendre\01_mini_gpt.py
```

~280 lignes, commentees en francais. Construit un transformer minimal (~1M parametres), l'entraine sur un petit corpus, et genere du texte. Tu y vois explicitement :

- la **tokenisation** (texte -> entiers)
- les **embeddings** (entiers -> vecteurs)
- la **self-attention** (chaque token regarde les autres)
- le **bloc transformer** (attention + feed-forward + residuals)
- la **boucle d'entrainement** (forward, loss, backward, step)
- la **generation autoregressive** (sample token apres token)

Ca tourne sur CPU en quelques minutes. Sur GPU c'est instantane.

A la fin de ce fichier tu sais ce qui se passe a l'interieur de qwen2.5 quand tu lui parles.

## Etape 2 — Optimiser le system prompt de Jarvis avec DSPy

```powershell
pip install dspy-ai
python apprendre\02_dspy_optimiser_prompt.py
```

DSPy traite un prompt comme un "programme" qu'on optimise automatiquement a partir d'exemples + d'une metrique. Le script :

1. Charge ton `jarvis_historique.json` (les conversations reelles)
2. Definit une metrique simple (ex: la reponse est en francais ET concise ET pas de phrase creuse)
3. Lance `BootstrapFewShot` qui essaie plusieurs variantes du prompt et garde la meilleure
4. Sauve le prompt optimise dans `apprendre/prompt_optimise.txt`

Tu peux ensuite remplacer le contenu de `_prompt_ollama_systeme()` par le prompt optimise. Mesure d'amelioration : avant/apres sur 20 questions tests.

## Etape 3 — Fine-tuner qwen2.5 sur tes conversations (LoRA)

```powershell
pip install torch transformers peft datasets accelerate trl bitsandbytes
python apprendre\03_lora_finetune_qwen.py
```

LoRA (**Lo**w **R**ank **A**daptation) entraine seulement ~0.1% des poids du modele original (au lieu des 7.6 milliards de qwen2.5:7b). Resultat : ca rentre sur un GPU consumer (8-12 GB VRAM) au lieu de necessiter un cluster.

Le script :

1. Charge `jarvis_historique.json` et le formate en dataset HuggingFace (`{user, assistant}`)
2. Charge qwen2.5-7B avec quantization 4-bit (~4 GB VRAM)
3. Y attache des adapters LoRA (matrices a entrainer)
4. Lance le Trainer pour quelques epochs
5. Sauve les adapters dans `apprendre/lora_jarvis/`
6. Genere une reponse de test avec et sans LoRA pour comparer

Tu peux ensuite servir ce modele via Ollama (apres conversion en GGUF) ou via vLLM directement.

**Sans GPU NVIDIA tu peux quand meme experimenter** avec un modele plus petit (qwen2.5:0.5b ou llama3.2:1b) — change `MODEL_ID` en haut du script. L'apprentissage est valable, juste la qualite finale plus modeste.

## Pre-requis communs

- Python >= 3.10
- Pour GPU: drivers NVIDIA + CUDA installes (ou laisse torch en CPU mode)
- Patience pour le premier `pip install torch` (~2.5 GB de download)

## Pour aller plus loin

- **nanoGPT** de Karpathy (https://github.com/karpathy/nanoGPT) : version industrielle de l'etape 1
- **Cours "Neural Networks: Zero to Hero"** de Karpathy : tout reprendre des bases (4h video)
- **The Annotated Transformer** (https://nlp.seas.harvard.edu/annotated-transformer/) : papier "Attention is All You Need" code + explique
- **LLM University de Cohere** : parcours pour comprendre les LLM modernes
- **DSPy docs** (https://dspy.ai) : optimisation declarative de prompts
- **PEFT docs** (https://huggingface.co/docs/peft) : LoRA, QLoRA, et autres methodes d'entrainement efficient

## Etape 4 — Boucle d'auto-amelioration en continu

```powershell
# Une seule passe (analyse historique + optim si seuils atteints)
python apprendre\04_jarvis_apprend_de_lui_meme.py --once

# Mode boucle (poll toutes les 60s, lance optim quand assez de nouveaux echanges)
python apprendre\04_jarvis_apprend_de_lui_meme.py
```

Connecte tout ce qu'on a vu : surveille `jarvis_historique.json`, score chaque
reponse, garde les bonnes, lance DSPy automatiquement, declenche LoRA si tres
gros volume. Le prompt optimise est ecrit dans `apprendre/prompt_actif.txt`.

Aucune dep ML obligatoire pour la passe scoring + dataset. DSPy et LoRA sont
appeles seulement s'ils sont installes et si les seuils sont atteints.

Pour brancher ce prompt sur Jarvis, tu peux dans `_prompt_ollama_systeme()` de
`main2.py` ajouter au debut :
```python
from pathlib import Path
p = Path(__file__).parent / "apprendre" / "prompt_actif.txt"
if p.exists():
    return p.read_text(encoding="utf-8")
```

## Et apres ?

Une fois que tu as fait les 4 etapes :

1. Tu as compris l'archi transformer (etape 1)
2. Tu sais optimiser un prompt automatiquement (etape 2)
3. Tu sais specialiser un LLM avec LoRA (etape 3)
4. Tu as une boucle qui rend Jarvis meilleur tout seul (etape 4)

C'est exactement ce que fait OpenJarvis avec son "learning loop" plus formel.
Tu peux l'utiliser via `jarvis optimize skills --policy dspy` une fois tes
traces accumulees.

Bon voyage.
