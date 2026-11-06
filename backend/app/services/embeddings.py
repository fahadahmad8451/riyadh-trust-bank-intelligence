"""Embeddings — Sprint 1.

Tries, in order (first success wins; the actual choice is recorded):
  1. sentence-transformers "BAAI/bge-m3" (1024-dim) — Design choice,
     but ONLY if it is already cached or RTB_TRY_BGE_M3=1. On this VM
     the 2.2 GB BGE-M3 download stalled at 0 bytes for 4+ minutes
     (2026-11-05), so the fallback below is what actually ran.
  2. sentence-transformers "sentence-transformers/all-MiniLM-L6-v2" (384-dim).
  3. ONNX Runtime + all-MiniLM-L6-v2 ONNX weights (384-dim, no torch).

BGE-M3 query encoding uses the model's recommended instruction prefix.
The chosen model is written to data/vector_store/embedding_config.json
at index time, so the code never claims a model it did not use.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger("rtb.embeddings")

BGE_M3 = "BAAI/bge-m3"
MINILM = "sentence-transformers/all-MiniLM-L6-v2"
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None  # singleton: (kind, model_or_session, name, dim)


def _load_sentence_transformer(name: str):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(name)
    dim = model.get_sentence_embedding_dimension()
    return ("st", model, name, dim)


def _load_onnx_minilm():
    """ONNX MiniLM — no torch needed. Downloads the ONNX model + tokenizer
    from the sentence-transformers/all-MiniLM-L6-v2 repo (onnx/ subfolder)."""
    import numpy as np
    import onnxruntime as ort
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    folder = snapshot_download(repo_id=MINILM, allow_patterns=["onnx/*", "*.json", "*.txt"])
    onnx_path = str(Path(folder) / "onnx" / "model.onnx")
    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    tokenizer = AutoTokenizer.from_pretrained(MINILM)
    return ("onnx", (session, tokenizer), MINILM + " (onnx)", 384)


def _encode_onnx(payload, texts: list[str]):
    import numpy as np

    session, tokenizer = payload
    encoded = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="np")
    outputs = session.run(None, {
        "input_ids": encoded["input_ids"],
        "attention_mask": encoded["attention_mask"],
        "token_type_ids": encoded.get("token_type_ids", np.zeros_like(encoded["input_ids"])),
    })
    last_hidden = outputs[0]
    mask = encoded["attention_mask"][..., None].astype(float)
    summed = (last_hidden * mask).sum(axis=1)
    counts = mask.sum(axis=1)
    emb = summed / np.maximum(counts, 1e-9)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    return emb / np.maximum(norms, 1e-9)


def _bge_m3_cached() -> bool:
    """True if a complete BGE-M3 snapshot is already in the HF cache.
    BGE-M3 is ~2.2 GB; on a slow/flaky connection its download stalls,
    so we only attempt it when it is cached or explicitly requested
    (RTB_TRY_BGE_M3=1) — otherwise every run would hang for minutes."""
    import os

    if os.getenv("RTB_TRY_BGE_M3") == "1":
        return True
    try:
        from huggingface_hub import scan_cache_dir

        for repo in scan_cache_dir().repos:
            if repo.repo_id == BGE_M3 and repo.size_on_disk > 1_000_000_000:
                return True
    except Exception:
        pass
    return False


def get_embedding_model():
    """Return (kind, model, name, dim). Tries BGE-M3 (only if cached or
    RTB_TRY_BGE_M3=1 — see _bge_m3_cached), then MiniLM (torch), then
    ONNX MiniLM. Raises RuntimeError only if all three fail."""
    global _model
    if _model is not None:
        return _model
    attempts = []
    if _bge_m3_cached():
        attempts.append(
            ("BGE-M3 (sentence-transformers)", lambda: _load_sentence_transformer(BGE_M3))
        )
    else:
        logger.warning(
            "BGE-M3 is not cached and RTB_TRY_BGE_M3 is not set — skipping "
            "the 2.2 GB download (it stalled at 0 bytes on this VM) and "
            "using all-MiniLM-L6-v2. Set RTB_TRY_BGE_M3=1 on a machine "
            "with good internet to use BGE-M3 (1024-dim)."
        )
    attempts += [
        ("MiniLM (sentence-transformers)", lambda: _load_sentence_transformer(MINILM)),
        ("MiniLM (ONNX Runtime)", _load_onnx_minilm),
    ]
    errors = []
    for label, loader in attempts:
        try:
            _model = loader()
            logger.info("Embedding model loaded: %s (%s, %d-dim, %s)",
                        _model[2], label, _model[3], _model[0])
            return _model
        except Exception as exc:  # noqa: BLE001 — try the next backend
            errors.append(f"{label}: {exc}")
            logger.warning("Embedding backend failed (%s): %s", label, exc)
    raise RuntimeError("All embedding backends failed:\n" + "\n".join(errors))


def encode_texts(texts: list[str], *, is_query: bool = False) -> "np.ndarray":
    """Encode texts -> L2-normalised float32 array (n, dim)."""
    import numpy as np

    kind, model, name, dim = get_embedding_model()
    if kind == "onnx":
        return _encode_onnx(model, texts).astype("float32")
    if is_query and name == BGE_M3:
        texts = [BGE_QUERY_PREFIX + t for t in texts]
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(emb, dtype="float32")


def encode_query(text: str) -> "np.ndarray":
    return encode_texts([text], is_query=True)[0]


def model_info() -> dict:
    kind, model, name, dim = get_embedding_model()
    return {"model": name, "dim": dim, "backend": kind}


def write_embedding_config(store_dir: Path) -> dict:
    """Record the actually-used model in the vector store directory."""
    info = model_info()
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "embedding_config.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8"
    )
    return info
