"""03_lora_finetune_qwen.py — fine-tuner qwen2.5 sur tes conversations Jarvis.

Objectif : specialiser un LLM pre-entraine sur TON style de reponses, sans
re-entrainer les ~7.6 milliards de poids. On utilise LoRA = on ajoute de petites
matrices "adapter" entrainables (~0.1% des params) qu'on multiplie aux poids
originaux. Le modele de base reste fige.

Pourquoi LoRA :
- Tient sur un GPU consumer (8-16 GB VRAM)
- Entrainement en quelques heures au lieu de jours
- L'adapter fait quelques MB seulement, swap-able a chaud
- On peut empiler plusieurs LoRAs (ex: un pour le francais + un pour le code)

Usage :
    pip install torch transformers peft datasets accelerate trl bitsandbytes
    python apprendre/03_lora_finetune_qwen.py

Ce script suppose un GPU NVIDIA. Sans GPU, change MODEL_ID en
'Qwen/Qwen2.5-0.5B-Instruct' pour un modele 15x plus petit qui tourne sur CPU
(qualite finale plus modeste mais le principe d'apprentissage est le meme).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from trl import SFTConfig, SFTTrainer


# =============================================================================
# 0. CONFIGURATION
# =============================================================================

ROOT = Path(__file__).parent.parent
HISTORIQUE_PATH = ROOT / "jarvis_historique.json"
SAVE_DIR = Path(__file__).parent / "lora_jarvis"

# Modele de base. Pour CPU/petit GPU : 'Qwen/Qwen2.5-0.5B-Instruct' (~1 GB)
MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"

# Hyperparametres LoRA
LORA_R = 16          # rang des matrices low-rank (plus haut = plus capacite, plus de RAM)
LORA_ALPHA = 32      # facteur de scaling (convention: alpha = 2*r)
LORA_DROPOUT = 0.05

# Hyperparametres d'entrainement
NUM_EPOCHS = 3
LR = 2e-4
BATCH_SIZE = 2       # tres petit a cause du peu de VRAM ; on compense avec gradient_accumulation
GRAD_ACCUM = 4       # batch effectif = BATCH_SIZE * GRAD_ACCUM = 8

# Quantization 4-bit (NF4) pour faire tenir qwen2.5:7b en ~5 GB VRAM
USE_4BIT = True


# =============================================================================
# 1. PREPARER LE DATASET
# =============================================================================
#
# Format attendu par le SFTTrainer : chaque exemple est un dict avec une cle
# 'messages' contenant une liste de {role, content}, type ChatML.
# Le modele apprend a predire les tokens 'assistant' etant donne 'user'.

def construire_dataset() -> Dataset:
    """Charge jarvis_historique.json et le formatte en ChatML."""
    if not HISTORIQUE_PATH.exists():
        print(f"[data] {HISTORIQUE_PATH} introuvable, utilisation du mini-dataset demo.")
        return _dataset_demo()

    raw = json.loads(HISTORIQUE_PATH.read_text(encoding="utf-8"))
    items = raw.get("history") if isinstance(raw, dict) else raw
    if not items:
        return _dataset_demo()

    # On regroupe en paires (user, assistant)
    samples = []
    pending_user = None
    for item in items:
        role = item.get("role", "")
        text = item.get("text") or item.get("content") or ""
        if not text:
            continue
        if role in ("user", "human"):
            pending_user = text
        elif role in ("model", "assistant") and pending_user is not None:
            samples.append({
                "messages": [
                    {"role": "system", "content": "Tu es Jarvis, l'assistant dev personnel de Monsieur. Reponds en francais, concis, direct."},
                    {"role": "user", "content": pending_user},
                    {"role": "assistant", "content": text},
                ]
            })
            pending_user = None

    if len(samples) < 10:
        print(f"[data] Seulement {len(samples)} exemples reels, augmentation avec demo.")
        samples += _dataset_demo_list()

    print(f"[data] {len(samples)} exemples ChatML prepares.")
    return Dataset.from_list(samples)


def _dataset_demo_list() -> list[dict]:
    """Petits exemples si pas d'historique reel."""
    pairs = [
        ("Quelle heure il est ?", "Je n'ai pas l'heure systeme. Si tu veux un timer, dis-le."),
        ("Salut Jarvis, ca va ?", "Pret a coder. Sur quoi on bosse, Monsieur ?"),
        ("Donne-moi un exemple de fonction Python qui inverse une chaine.", "def inverser(s): return s[::-1]"),
        ("C'est quoi un decorateur ?", "Une fonction qui en prend une autre et la wrap pour ajouter du comportement."),
        ("C'est quoi une list comprehension ?", "Une syntaxe concise pour construire une liste : [x*2 for x in range(5)]."),
        ("Comment je debug un None type ?", "Print la variable juste avant la ligne qui plante."),
        ("Donne-moi un fait sur le foot.", "Pele a marque son 1000e but le 19 novembre 1969."),
        ("Tu peux me reveiller a 7h ?", "Je peux pas planifier d'alarme systeme depuis ici. Demande a Windows."),
        ("Comment marche async/await ?", "asyncio gere les coroutines. await suspend, le runtime reprend ailleurs en attendant."),
        ("C'est quoi une closure ?", "Une fonction qui capture des variables de son scope englobant."),
    ]
    return [
        {"messages": [
            {"role": "system", "content": "Tu es Jarvis, l'assistant dev personnel de Monsieur. Reponds en francais, concis, direct."},
            {"role": "user", "content": q},
            {"role": "assistant", "content": r},
        ]}
        for q, r in pairs
    ]


def _dataset_demo() -> Dataset:
    return Dataset.from_list(_dataset_demo_list())


# =============================================================================
# 2. CHARGER LE MODELE EN 4-BIT + PREPARER LoRA
# =============================================================================

def charger_modele_et_tokenizer():
    """Charge qwen2.5 quantize en 4-bit + son tokenizer."""
    print(f"[init] chargement de {MODEL_ID}")

    bnb_config = None
    if USE_4BIT and torch.cuda.is_available():
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        print("[init] quantization 4-bit NF4 activee (VRAM ~5 GB pour qwen2.5:7b)")
    else:
        print("[init] mode CPU/full precision (lent + RAM intensive)")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
    )

    if bnb_config is not None:
        model = prepare_model_for_kbit_training(model)

    # Configuration LoRA : on cible les layers qkv + projections (convention pour qwen2)
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)

    # Resume du nombre de params entrainables
    n_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in model.parameters())
    print(
        f"[init] params entrainables : {n_trainable:,} / {n_total:,} "
        f"({100 * n_trainable / n_total:.3f}%)"
    )
    return model, tokenizer


# =============================================================================
# 3. ENTRAINEMENT
# =============================================================================

def entrainer(model, tokenizer, dataset: Dataset):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    # Le SFTTrainer (TRL) prend le format messages et applique le chat template tout seul
    config = SFTConfig(
        output_dir=str(SAVE_DIR),
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        logging_steps=5,
        save_strategy="epoch",
        bf16=torch.cuda.is_available(),
        optim="paged_adamw_8bit" if USE_4BIT and torch.cuda.is_available() else "adamw_torch",
        report_to="none",
        max_seq_length=1024,
        packing=False,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        tokenizer=tokenizer,
        args=config,
    )
    print("\n[train] go")
    trainer.train()
    print("\n[save] sauvegarde des adapters LoRA")
    trainer.save_model(str(SAVE_DIR))
    tokenizer.save_pretrained(str(SAVE_DIR))
    print(f"[save] -> {SAVE_DIR}")


# =============================================================================
# 4. TEST AVANT/APRES — comparer le modele de base et le modele fine-tune
# =============================================================================

def comparer(model_base, model_fine, tokenizer, question: str):
    """Genere une reponse avec base et fine-tune cote a cote."""
    print(f"\n[test] question : {question}")
    msgs = [
        {"role": "system", "content": "Tu es Jarvis, l'assistant dev personnel de Monsieur. Reponds en francais, concis, direct."},
        {"role": "user", "content": question},
    ]
    prompt = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model_base.device)

    with torch.no_grad():
        out_base = model_base.generate(**inputs, max_new_tokens=120, do_sample=False)
        out_fine = model_fine.generate(**inputs, max_new_tokens=120, do_sample=False)

    rep_base = tokenizer.decode(out_base[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
    rep_fine = tokenizer.decode(out_fine[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)

    print(f"  [base ] {rep_base.strip()}")
    print(f"  [fine ] {rep_fine.strip()}")


# =============================================================================
# 5. ORCHESTRATION
# =============================================================================

def main():
    print(f"[init] device cuda dispo : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"[init] gpu : {torch.cuda.get_device_name(0)}, "
              f"vram : {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    dataset = construire_dataset()
    model, tokenizer = charger_modele_et_tokenizer()
    entrainer(model, tokenizer, dataset)

    print(
        "\n[fait] adapter LoRA sauve dans:", SAVE_DIR,
        "\n[fait] tu peux maintenant le charger comme ca :",
        "\n        from peft import PeftModel",
        "\n        base = AutoModelForCausalLM.from_pretrained(MODEL_ID, ...)",
        f"\n        model = PeftModel.from_pretrained(base, '{SAVE_DIR}')",
        "\n[fait] ou exporter en GGUF pour Ollama via llama.cpp/convert-hf-to-gguf.py",
    )


if __name__ == "__main__":
    main()
