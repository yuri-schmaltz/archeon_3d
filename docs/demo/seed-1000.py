"""Seed 1000 jobs in the demo DB covering every existing combination."""
import sqlite3
import json
import os
import uuid
import random
from datetime import datetime, timedelta, timezone

random.seed(42)  # deterministic

SAVE_DIR = "/tmp/polyforge-saves"
os.makedirs(SAVE_DIR, exist_ok=True)

fake_glb_pool = []
for i in range(20):
    p = os.path.join(SAVE_DIR, f"pool_{i:02d}.glb")
    size = random.randint(1024, 100_000)
    with open(p, "wb") as f:
        f.write(b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * size)
    fake_glb_pool.append(p)

PROMPTS = [
    "a small red ceramic cube with rounded edges",
    "a chrome gear with 16 teeth, machined finish",
    "a low-poly tree stump, isometric view, game asset",
    "a smooth stone with subtle moss patches, photorealistic",
    "an ornate brass key, victorian style, detailed engravings",
    "a clay teapot with bamboo handle, wabi-sabi aesthetic",
    "a hovering sci-fi crate with cyan light strips",
    "a teapot with intricate handle, photorealistic render",
    "a Victorian clockwork mechanism, exposed gears",
    "an abstract sculpture, mid-century modern, brutalist",
    "a futuristic helmet with glowing visor lines",
    "a low-poly mushroom, stylized for mobile game",
    "a rough-hewn stone axe, medieval fantasy prop",
    "a polished obsidian dagger, magical RPG weapon",
    "a wicker basket, woven pattern, photorealistic",
    "an old wooden chest, iron bands, fantasy loot",
    "a brass compass with engraved needle, steampunk",
    "a glass potion bottle, glowing green liquid",
    "a wooden spoon, hand-carved, kitchen utensil",
    "a clay vase, geometric patterns, art deco",
    "a metal padlock, vintage, rusted",
    "a paper origami crane, white, simple",
    "a leather-bound book, embossed cover, magical tome",
    "a metal lantern, hanging, with chain",
    "a stone fountain, three-tiered, garden ornament",
    "a ceramic bowl, blue glaze, asian-inspired",
    "a rusted iron key, ornate bow, victorian",
    "a wooden treasure chest, gold trim, fantasy RPG",
    "a brass astrolabe, intricate engravings, antique",
    "a stone gargoyle, gothic, perched on ledge",
]

IMAGE_LABELS = [
    "1024x1024 PNG (mountain landscape)",
    "800x800 PNG (car front view)",
    "512x512 JPG (face close-up)",
    "1024x1024 PNG (sneaker side view)",
    "768x768 PNG (car concept art)",
    "640x480 JPG (product shot)",
    "1024x1024 PNG (character design)",
    "800x800 PNG (architecture)",
    "1024x1024 PNG (mountain scene)",
    "512x512 PNG (logo 3D mockup)",
]

MULTIVIEW_LABELS = [
    "upload: 4-view 512x512 set (chair)",
    "upload: 4-view set (vehicle concept)",
    "upload: 4-view set (lamp)",
    "upload: 4-view set (teapot)",
    "upload: 4-view 1024x1024 set (architectural model)",
]

TEXTURE_MESH_LABELS = [
    "re-texture: matte black finish on base mesh",
    "re-texture: brushed steel on faucet mesh",
    "re-texture: rusted iron on lamp mesh",
    "re-texture: wood grain on sphere",
    "re-texture: marble finish on column",
    "re-texture: chrome plating on faucet",
    "re-texture: gold leaf on statue",
    "re-texture: terracotta on planter",
]

ERROR_MESSAGES = [
    "name 'BackgroundRemover' is not defined",
    "CUDA out of memory. Tried to allocate 4.20 GiB",
    "Model checkpoint not found at /checkpoints/hunyuan3d.safetensors",
    "Inference timeout after 600s",
    "User cancelled the request",
    "Invalid image format: expected PNG/JPEG/WEBP",
    "Image resolution too low (min 256x256)",
    "Input image dimensions must be square",
    "Failed to load texture: file not accessible",
    "Maximum prompt length exceeded (256 tokens)",
    "Rate limit exceeded: 120 jobs/minute",
    "Disk full: cannot write output mesh",
]

# 25% completed, 35% failed, 15% queued, 10% processing, 15% cancelled
STATUS_WEIGHTS = [
    ("completed",  250),
    ("failed",     350),
    ("queued",     150),
    ("processing", 100),
    ("cancelled",  150),
]
status_pool = []
for s, n in STATUS_WEIGHTS:
    status_pool.extend([s] * n)
random.shuffle(status_pool)

def pick_steps():
    bucket = random.choice(["low", "mid", "high"])
    if bucket == "low":  return random.randint(10, 25)
    if bucket == "mid":  return random.randint(30, 55)
    return random.randint(60, 100)

def pick_guidance():
    bucket = random.choice(["low", "mid", "high"])
    if bucket == "low":  return round(random.uniform(2.5, 5.0), 1)
    if bucket == "mid":  return round(random.uniform(5.0, 8.0), 1)
    return round(random.uniform(8.0, 15.0), 1)

def pick_age():
    bucket = random.choice(["recent", "minute", "hour", "old"])
    if bucket == "recent": return random.randint(0, 60)
    if bucket == "minute": return random.randint(60, 300)
    if bucket == "hour":   return random.randint(300, 3600)
    return random.randint(3600, 86400 * 7)

MODE_WEIGHTS = [
    ("text_to_3d",   500),
    ("image_to_3d",  250),
    ("multiview",    100),
    ("texture_mesh", 150),
]
mode_pool = []
for m, n in MODE_WEIGHTS:
    mode_pool.extend([m] * n)
random.shuffle(mode_pool)

db = sqlite3.connect("/tmp/polyforge-demo2.db")
db.execute("PRAGMA journal_mode = WAL")
db.execute("PRAGMA synchronous = OFF")
db.row_factory = sqlite3.Row

db.execute("DELETE FROM jobs")
db.commit()

now = datetime.now(timezone.utc)
rows = []
for i in range(1000):
    status = status_pool[i]
    mode = mode_pool[i]
    age_s = pick_age()
    steps = pick_steps()
    guidance = pick_guidance()
    seed = random.randint(1, 99999)
    texture = random.random() < 0.2

    created_at = (now - timedelta(seconds=age_s)).isoformat()
    if status == "completed":
        completed_at = (now - timedelta(seconds=max(0, age_s - random.randint(5, 60)))).isoformat()
        file_path = random.choice(fake_glb_pool)
        error = None
    elif status == "cancelled":
        completed_at = (now - timedelta(seconds=max(0, age_s - random.randint(2, 30)))).isoformat()
        file_path = None
        error = "Cancelled by user"
    elif status == "failed":
        completed_at = (now - timedelta(seconds=max(0, age_s - random.randint(1, 10)))).isoformat()
        file_path = None
        error = random.choice(ERROR_MESSAGES)
    else:
        completed_at = None
        file_path = None
        error = None

    if mode == "text_to_3d":
        text = random.choice(PROMPTS)
        payload = {"text": text, "steps": steps, "guidance": guidance, "seed": seed, "texture": texture}
    elif mode == "image_to_3d":
        label = random.choice(IMAGE_LABELS)
        payload = {"image": "<base64-data>", "steps": steps, "guidance": guidance, "seed": seed, "texture": texture}
    elif mode == "multiview":
        label = random.choice(MULTIVIEW_LABELS)
        payload = {
            "views": {"front": "<b64>", "back": "<b64>", "left": "<b64>", "right": "<b64>"},
            "steps": steps, "guidance": guidance, "seed": seed, "texture": texture,
        }
    else:
        label = random.choice(TEXTURE_MESH_LABELS)
        text = "matte black finish" if "matte" in label else label.split(": ", 1)[-1] if ": " in label else "wood grain"
        payload = {"mesh": "<base64-data>", "text": text, "steps": steps, "guidance": guidance, "seed": seed, "texture": True}

    uid = str(uuid.uuid4())
    rows.append((uid, status, created_at, completed_at, file_path, error, json.dumps(payload)))

db.execute("BEGIN")
db.executemany(
    "INSERT INTO jobs (uid, status, created_at, completed_at, file_path, error, request_blob) VALUES (?, ?, ?, ?, ?, ?, ?)",
    rows,
)
db.commit()

from collections import Counter
modes_count = Counter(mode_pool)
status_count = Counter(r[1] for r in rows)
print("=== inserted 1000 jobs ===")
print(f"  by status: {dict(status_count)}")
print(f"  by mode:   {dict(modes_count)}")
db.close()
