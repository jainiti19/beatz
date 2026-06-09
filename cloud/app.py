import modal
import subprocess
import re
import shutil
from pathlib import Path

app = modal.App("beatznbox")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "curl")
    .run_commands("curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs")
    .pip_install("demucs", "yt-dlp", "torch", "torchaudio", "fastapi[standard]")
)

volume = modal.Volume.from_name("beatznbox-stems", create_if_missing=True)


@app.function(image=image, gpu="T4", timeout=600, volumes={"/stems": volume})
def process_song(query: str) -> dict:
    work_dir = Path("/tmp/work")
    work_dir.mkdir(exist_ok=True)

    if query.startswith("search:"):
        dl_url = f"ytsearch:{query[7:]}"
    elif "youtube.com" in query or "youtu.be" in query:
        dl_url = query
    else:
        dl_url = f"ytsearch:{query}"

    # Get title
    try:
        result = subprocess.run(
            ["yt-dlp", "--js-runtimes", "nodejs", "--get-title", "--no-playlist", dl_url],
            capture_output=True, text=True, timeout=30
        )
        title = result.stdout.strip().split("\n")[0]
        song_name = re.sub(r'[^a-zA-Z0-9 ]', '', title).replace(' ', '_')[:40]
    except:
        song_name = "unknown_song"
    if not song_name:
        song_name = "unknown_song"

    # Check cache
    stem_dir = Path(f"/stems/{song_name}")
    if stem_dir.exists() and (stem_dir / "vocals.wav").exists():
        return {"status": "ready", "name": song_name,
                "stems": ["vocals.wav", "drums.wav", "bass.wav", "other.wav"]}

    # Download
    audio_path = work_dir / "audio.mp3"
    dl_result = subprocess.run([
        "yt-dlp", "--js-runtimes", "nodejs", "-x", "--audio-format", "mp3",
        "--audio-quality", "0", "--no-playlist", "-o", str(audio_path), dl_url
    ], capture_output=True, text=True, timeout=120)

    if not audio_path.exists():
        return {"status": "error", "message": f"Download failed: {dl_result.stderr[-200:] if dl_result.stderr else 'no output'}"}

    # Demucs
    out_dir = work_dir / "separated"
    subprocess.run([
        "python3", "-m", "demucs", "-n", "htdemucs",
        "--out", str(out_dir), str(audio_path)
    ], timeout=300)

    htdemucs_dir = out_dir / "htdemucs"
    if not htdemucs_dir.exists():
        return {"status": "error", "message": "Separation failed"}

    sub_dirs = list(htdemucs_dir.iterdir())
    if not sub_dirs:
        return {"status": "error", "message": "No stems produced"}

    source_dir = sub_dirs[0]
    stem_dir.mkdir(parents=True, exist_ok=True)
    stems = []
    for stem_file in source_dir.glob("*.wav"):
        shutil.copy2(stem_file, stem_dir / stem_file.name)
        stems.append(stem_file.name)

    volume.commit()
    return {"status": "ready", "name": song_name, "stems": stems}


@app.function(image=modal.Image.debian_slim().pip_install("fastapi[standard]"), volumes={"/stems": volume})
def get_stem(song_name: str, stem_name: str) -> bytes:
    stem_path = Path(f"/stems/{song_name}/{stem_name}")
    return stem_path.read_bytes() if stem_path.exists() else b""


@app.function(image=modal.Image.debian_slim().pip_install("fastapi[standard]"), volumes={"/stems": volume})
def list_songs() -> list:
    stems_dir = Path("/stems")
    if not stems_dir.exists():
        return []
    return [d.name for d in sorted(stems_dir.iterdir())
            if d.is_dir() and (d / "vocals.wav").exists()]


# --- Web API for Android app ---

@app.function(image=image, gpu="T4", timeout=600, volumes={"/stems": volume})
@modal.fastapi_endpoint(method="POST")
def api_process(request: dict) -> dict:
    query = request.get("query", "")
    if not query:
        return {"status": "error", "message": "No query provided"}
    return process_song.local(query)


@app.function(image=modal.Image.debian_slim().pip_install("fastapi[standard]"), volumes={"/stems": volume})
@modal.fastapi_endpoint(method="GET")
def api_stems(song_name: str, stem: str):
    from starlette.responses import Response
    stem_path = Path(f"/stems/{song_name}/{stem}")
    if stem_path.exists():
        return Response(
            content=stem_path.read_bytes(),
            media_type="audio/wav",
            headers={"Content-Disposition": f"attachment; filename={stem}"}
        )
    return Response(content=b"Not found", status_code=404)


@app.function(image=modal.Image.debian_slim().pip_install("fastapi[standard]"), volumes={"/stems": volume})
@modal.fastapi_endpoint(method="GET")
def api_list() -> list:
    return list_songs.local()
