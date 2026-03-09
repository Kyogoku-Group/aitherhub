# grouping_pipeline.py
import os
import json
import numpy as np
from db_ops import get_all_phase_groups_sync
from db_ops import create_phase_group_sync, update_phase_group_sync

from openai import AzureOpenAI
from decouple import config



# ======================================================
# ENV
# ======================================================

def env(key, default=None):
    return os.getenv(key) or config(key, default=default)


AZURE_OPENAI_KEY = env("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = env("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = env("GPT5_API_VERSION")

EMBED_MODEL = "text-embedding-3-large"

# GROUP_ROOT = "group"
# GROUP_FILE = "groups.json"

def get_group_root(art_root: str, video_id: str):
    return os.path.join(art_root, video_id, "group")

def get_group_file(art_root: str, video_id: str):
    return os.path.join(get_group_root(art_root, video_id), "groups.json")

COSINE_THRESHOLD = 0.88

# Fallback: use main Azure OpenAI endpoint/version if EMBED-specific ones are not set
_raw_endpoint = env("AZURE_OPENAI_ENDPOINT", "")
# Strip /openai/responses?api-version=... suffix if present (embed needs base URL)
_base_endpoint = _raw_endpoint.split("/openai/")[0] if "/openai/" in _raw_endpoint else _raw_endpoint

AZURE_OPENAI_ENDPOINT_EMBED = env("AZURE_OPENAI_ENDPOINT_EMBED") or _base_endpoint
AZURE_OPENAI_API_VERSION_EMBED = env("AZURE_OPENAI_API_VERSION_EMBED") or env("GPT5_API_VERSION", "2025-04-01-preview")

if not AZURE_OPENAI_ENDPOINT_EMBED:
    raise RuntimeError(
        "AZURE_OPENAI_ENDPOINT_EMBED (or AZURE_OPENAI_ENDPOINT) must be set. "
        "Please add it to .env"
    )
if not AZURE_OPENAI_API_VERSION_EMBED:
    raise RuntimeError(
        "AZURE_OPENAI_API_VERSION_EMBED (or GPT5_API_VERSION) must be set. "
        "Please add it to .env"
    )

embed_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT_EMBED,
    api_version=AZURE_OPENAI_API_VERSION_EMBED,
)


# ======================================================
# VECTOR UTILS
# ======================================================

def l2_normalize(v):
    v = np.array(v, dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm == 0:
        return v
    return v / norm


def cosine(a, b):
    return float(np.dot(a, b))


# ======================================================
# STEP 7.1 – EMBEDDING
# ======================================================

def embed_phase_descriptions(phase_units):
    """
    Embed phase_description into vector space.
    Logic giữ nguyên demo_extract_frames.py
    """
    texts = [p["phase_description"] for p in phase_units]

    resp = embed_client.embeddings.create(
        model=EMBED_MODEL,
        input=texts
    )

    for p, e in zip(phase_units, resp.data):
        p["embedding"] = l2_normalize(e.embedding).tolist()

    return phase_units


# ======================================================
# STEP 7.2 – LOAD GLOBAL GROUPS
# ======================================================
def load_global_groups_from_db(user_id: int):
    rows = get_all_phase_groups_sync(user_id)

    groups = []
    for r in rows:
        groups.append({
            "group_id": r["group_id"],
            "centroid": np.array(r["centroid"], dtype=np.float32),
            "size": r["size"],
        })
    return groups


def load_global_groups(art_root: str, video_id: str):
    root = get_group_root(art_root, video_id)
    path = get_group_file(art_root, video_id)

    os.makedirs(root, exist_ok=True)

    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    groups = []
    for g in raw:
        groups.append({
            "group_id": g["group_id"],
            "centroid": np.array(g["centroid"], dtype=np.float32),
            "size": g["size"]
        })

    return groups


def save_global_groups(groups, art_root: str, video_id: str):
    root = get_group_root(art_root, video_id)
    path = get_group_file(art_root, video_id)

    os.makedirs(root, exist_ok=True)

    data = []
    for g in groups:
        data.append({
            "group_id": g["group_id"],
            "centroid": g["centroid"].tolist(),
            "size": g["size"]
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ======================================================
# STEP 7.3 – ASSIGN PHASES TO GROUPS
# ======================================================

# def assign_phases_to_groups(phase_units, groups):
#     """
#     Incremental cosine-based grouping.
#     """
#     for p in phase_units:
#         v = np.array(p["embedding"], dtype=np.float32)

#         best_group = None
#         best_score = -1.0

#         for g in groups:
#             score = cosine(v, g["centroid"])
#             if score > best_score:
#                 best_score = score
#                 best_group = g

#         # JOIN EXISTING GROUP
#         if best_group and best_score >= COSINE_THRESHOLD:
#             n = best_group["size"]
#             new_centroid = (best_group["centroid"] * n + v) / (n + 1)
#             best_group["centroid"] = l2_normalize(new_centroid)
#             best_group["size"] += 1
#             p["group_id"] = best_group["group_id"]

#         # CREATE NEW GROUP
#         else:
#             new_id = len(groups) + 1
#             groups.append({
#                 "group_id": new_id,
#                 "centroid": v,
#                 "size": 1
#             })
#             p["group_id"] = new_id

#     return phase_units, groups

def assign_phases_to_groups(phase_units, groups, user_id: int):
    """
    Incremental cosine-based grouping.
    """
    # compute next group id safely (avoid collision with DB ids)
    # next_group_id = max([g["group_id"] for g in groups], default=0) + 1

    for p in phase_units:
        v = np.array(p["embedding"], dtype=np.float32)

        best_group = None
        best_score = -1.0

        for g in groups:
            score = cosine(v, g["centroid"])
            if score > best_score:
                best_score = score
                best_group = g

        # JOIN EXISTING GROUP
        if best_group and best_score >= COSINE_THRESHOLD:
            n = best_group["size"]
            new_centroid = (best_group["centroid"] * n + v) / (n + 1)
            best_group["centroid"] = l2_normalize(new_centroid)
            best_group["size"] += 1
            p["group_id"] = best_group["group_id"]

        # CREATE NEW GROUP
        else:
            # new_id = next_group_id

            new_id = create_phase_group_sync(
                user_id=user_id,
                centroid=v.tolist(),
                size=1,
            )

            # next_group_id += 1

            groups.append({
                "group_id": new_id,
                "centroid": v,
                "size": 1
            })
            p["group_id"] = new_id

    return phase_units, groups
