"""
keyframe_selector.py
====================
CLIP-based keyframe selection for VAD reasoning.

Paper basis:
- ReCoVAD / "Sparse Reasoning is Enough" (arXiv:2511.17094, Huang et al.):
  Uses CLIP ViT-B/32 as a lightweight "reflex" stream to filter frames before
  escalating to the heavy VLM. Only visually distinct keyframes reach the 8B model.
- AnyAnomaly (arXiv:2503.04504):
  CLIP cosine-similarity diversity — drop near-duplicate frames, keep frames
  with maximum mutual visual difference.

Architecture in your system
----------------------------
vad-reasoning-worker (separate container, CPU only, no GPU):
  24 JPEG frames downloaded from MinIO
      |
  CLIP ViT-B/32 on CPU  (~2-3 sec for 24 frames)
      |  cosine-similarity max-diversity selection
  8 keyframes
      |
  MiniCPM-V 8B via Ollama  (was 24 frames, now 8)

CLIP singleton is loaded once at worker startup, reused across all jobs.
ViT-B/32: ~350 MB RAM, zero VRAM (CPU inference).
"""

from __future__ import annotations
import logging
import math
from typing import Any

log = logging.getLogger("vad.keyframe_selector")

_CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"
_MIN_KEEP = 3


class CLIPKeyframeSelector:
    """
    Singleton-friendly CLIP diversity selector.

    Load once at worker startup:
        selector = CLIPKeyframeSelector()

    Call per job:
        keys = selector.select(frame_keys, image_bytes_map, budget=8)
    """

    def __init__(self, model_name: str = _CLIP_MODEL_NAME, device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model = None
        self._processor = None
        self._loaded = False
        self._load_error: str | None = None

    def _load(self) -> bool:
        if self._loaded:
            return True
        if self._load_error:
            return False
        try:
            from transformers import CLIPModel, CLIPProcessor
            log.info("Loading CLIP %s on %s ...", self.model_name, self.device)
            self._processor = CLIPProcessor.from_pretrained(self.model_name, cache_dir="/models/vad/clip")
            self._model = CLIPModel.from_pretrained(self.model_name, cache_dir="/models/vad/clip").to(self.device)
            self._model.eval()
            self._loaded = True
            log.info("CLIP loaded OK.")
            return True
        except Exception as e:
            self._load_error = str(e)
            log.warning("CLIP load failed (%s) — falling back to even-spacing.", e)
            return False

    def _embed(self, images_bytes: list[bytes]) -> list[list[float]] | None:
        if not self._load():
            return None
        try:
            from PIL import Image
            import io, torch

            pil_images = []
            for b in images_bytes:
                try:
                    pil_images.append(Image.open(io.BytesIO(b)).convert("RGB"))
                except Exception:
                    pil_images.append(Image.new("RGB", (224, 224)))

            inputs = self._processor(images=pil_images, return_tensors="pt", padding=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                feats = self._model.get_image_features(**inputs)
                feats = feats / feats.norm(dim=-1, keepdim=True).clamp(min=1e-12)

            return feats.cpu().tolist()
        except Exception as e:
            log.warning("CLIP embed failed: %s", e)
            return None

    @staticmethod
    def _min_sim_to_selected(feat: list[float], selected: list[list[float]]) -> float:
        if not selected:
            return -1.0
        return min(sum(a * b for a, b in zip(feat, sf)) for sf in selected)

    def select(
        self,
        frame_keys: list[str],
        image_bytes_map: dict[str, bytes],
        budget: int = 8,
    ) -> list[str]:
        """
        Select up to `budget` keyframes using CLIP cosine-similarity diversity.

        Algorithm (AnyAnomaly + ReCoVAD):
          1. Embed all frames with CLIP ViT-B/32.
          2. Anchor on first + last frame (temporal onset/offset context).
          3. Greedily add the frame most different from all selected frames
             (minimum cosine similarity) until budget is full.
          4. Return in chronological order.
        """
        n = len(frame_keys)
        if n == 0:
            return []
        budget = max(_MIN_KEEP, int(budget))
        if n <= budget:
            return list(frame_keys)

        bytes_list = [image_bytes_map.get(k, b"") for k in frame_keys]
        embeddings = self._embed(bytes_list)

        if embeddings is None:
            return _even_sample(frame_keys, budget)

        # Anchor: first and last frame for temporal context.
        selected_idx: list[int] = []
        for anchor in [0, n - 1]:
            if anchor not in selected_idx:
                selected_idx.append(anchor)
            if len(selected_idx) >= budget:
                break

        selected_feats = [embeddings[i] for i in selected_idx]
        remaining = [i for i in range(n) if i not in selected_idx]

        # Greedy max-diversity fill.
        while len(selected_idx) < budget and remaining:
            best = min(
                remaining,
                key=lambda i: self._min_sim_to_selected(embeddings[i], selected_feats),
            )
            selected_idx.append(best)
            selected_feats.append(embeddings[best])
            remaining.remove(best)

        selected_idx.sort()
        result = [frame_keys[i] for i in selected_idx]
        log.info("CLIP keyframe: %d → %d frames (budget=%d)", n, len(result), budget)
        return result


def _even_sample(keys: list[str], limit: int) -> list[str]:
    n = len(keys)
    if n <= limit:
        return list(keys)
    last = n - 1
    indexes = sorted({round(i * last / (limit - 1)) for i in range(limit)})
    return [keys[i] for i in indexes[:limit]]


_selector: CLIPKeyframeSelector | None = None

def get_selector() -> CLIPKeyframeSelector:
    global _selector
    if _selector is None:
        _selector = CLIPKeyframeSelector(device="cpu")
    return _selector