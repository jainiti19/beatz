#!/usr/bin/env python3
"""Process song requests queued by the web player.

Polls the VPS queue over the SSH access deploy-web.sh already uses, runs the
normal pipeline for anything new, and publishes the result. Meant to sit
running on the desktop; requests made while it is off are picked up whenever
it next starts, which is what makes this work for both a request shouted
across the room and one Karan files three weeks early.

Completion is recorded by appending an id to a separate done file. The service
only ever appends to the queue and this only ever appends to done, so the two
never write the same file and a half-finished run cannot corrupt either.

Usage:
  watch-requests.py                 # poll forever, 60s apart
  watch-requests.py --once          # drain the queue and exit
  watch-requests.py --interval 30   # poll more often
  watch-requests.py --full          # htdemucs_ft instead of the fast model
"""
import argparse, io, json, os, re, shutil, subprocess, sys, time

HOST = "beatznbox@46.224.176.48"
QUEUE = "/opt/beatznbox/queue/requests.jsonl"
DONE = "/opt/beatznbox/queue/done.txt"
DROP = "/opt/beatznbox/queue/lyrics"
RESULTS = "/opt/beatznbox/queue/results.jsonl"
META = None          # set in main() to <repo>/data/songs-meta.json
LOCAL = False        # --local reads the queue as plain files, for testing
NO_PUBLISH = False   # --no-publish stops before prepare-web/deploy
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEMS = os.path.expanduser("~/Music/karaoke/htdemucs")


def log(msg):
    # Date as well as time: the log is append-only across restarts, and reading
    # a bare clock time led to a wrong diagnosis of why the watcher was down.
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def ssh(*args, check=False):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, *args],
                          capture_output=True, text=True, timeout=60, check=check)


def remote_lines(path):
    """Missing file is not an error — the queue simply has not been used yet."""
    if LOCAL:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [l for l in f.read().splitlines() if l.strip()]
    r = ssh(f"cat {path} 2>/dev/null || true")
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed: {r.stderr.strip()[:120]}")
    return [l for l in r.stdout.splitlines() if l.strip()]


def pending():
    done = set(remote_lines(DONE))
    out = []
    for line in remote_lines(QUEUE):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue                      # a mangled line must not stall the queue
        if e.get("id") and e["id"] not in done:
            out.append(e)
    return out


def lyrics_drops():
    """Words pasted in the player for songs LRCLIB has nothing for.

    Consumed rather than queued: the file is deleted once aligned, so an
    unprocessed drop is always the whole to-do list."""
    if LOCAL:
        if not os.path.isdir(DROP):
            return []
        return sorted(os.listdir(DROP))
    r = ssh(f"ls {DROP} 2>/dev/null || true")
    return sorted(l for l in r.stdout.splitlines() if l.endswith(".txt"))


def take_drop(fname):
    """Read a pasted file and remove it, so a retry cannot double-apply it."""
    remote = f"{DROP}/{fname}"
    if LOCAL:
        path = os.path.join(DROP, fname)
        text = io.open(path, encoding="utf-8").read()
        os.remove(path)
        return text
    r = ssh(f"cat {remote}")
    if r.returncode != 0:
        raise RuntimeError(f"could not read {fname}")
    ssh(f"rm -f {remote}")
    return r.stdout


def apply_lyrics(fname):
    name = fname[:-4]
    d = os.path.join(STEMS, name)
    if not os.path.exists(os.path.join(d, "vocals.wav")):
        log(f"  {name}: no stems here, dropping the paste")
        take_drop(fname)
        return False
    text = take_drop(fname)
    lines = [l for l in text.splitlines() if l.strip()]
    log(f"lyrics pasted for {name}: {len(lines)} lines")
    for ext in ("lyrics.txt", "lyrics_timed.json"):
        f = os.path.join(d, ext)
        if os.path.exists(f):
            shutil.copy(f, f + ".pasted-over.bak")
    io.open(os.path.join(d, "lyrics.txt"), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")
    r = subprocess.run([os.path.expanduser("~/demucs-env/bin/python"),
                        os.path.join(REPO, "scripts/align-lyrics.py"), d, "--force"],
                       capture_output=True, text=True)
    ok = os.path.exists(os.path.join(d, "lyrics_timed.json"))
    log(f"  aligned: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'no output'}")
    return ok


def field(text):
    """Manifest fields are pipe-separated and read line by line, so a pipe or a
    newline in a request would silently shift every later field."""
    return re.sub(r"[|\r\n\t]+", " ", (text or "")).strip()


def mark_done(entry_id):
    if LOCAL:
        with open(DONE, "a", encoding="utf-8") as f:
            f.write(entry_id + "\n")
        return
    ssh(f"printf '%s\\n' {json.dumps(entry_id)} >> {DONE}", check=True)


def post_result(entry_id, state, title=None, note=None):
    """Tell the player how a request ended.

    The queue service only appends to requests.jsonl and only reads this, so a
    laptop that dies mid-write cannot corrupt the queue. Best-effort: failing to
    report must never stop the song being published."""
    rec = {"id": entry_id, "state": state, "title": title, "note": note,
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    line = json.dumps(rec, ensure_ascii=False)
    try:
        if LOCAL:
            with open(RESULTS, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            ssh(f"printf '%s\\n' {json.dumps(line)} >> {RESULTS}", check=True)
    except Exception as e:
        log(f"  could not post result for {entry_id}: {e}")


def resolved_title(name):
    """What LRCLIB actually matched, written by fetch-lyrics-lrclib.py.

    The request only ever carried what someone typed, and that string became
    the directory and therefore the title. This is the real name."""
    try:
        with open(os.path.join(STEMS, name, "match.json"), encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        # Three, not two: every caller unpacks three, and a song with no
        # match.json is the COMMON case -- anything separated before match.json
        # existed, and anything published straight from the library without
        # reprocessing. Returning a short tuple here wedged the whole queue.
        return None, None, None
    return m.get("trackName"), m.get("artistName"), m.get("albumName")


def _norm(s):
    return " ".join((s or "").lower().split())


def record_meta(name, title, artist, album=None):
    """Fold the resolved title into data/songs-meta.json.

    Never overwrites an entry that already has a title - a hand-corrected name
    outranks whatever LRCLIB thinks."""
    if not META or not title:
        return
    try:
        with open(META, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return
    cur = meta.get(name)
    if isinstance(cur, dict) and cur.get("title"):
        return
    entry = cur if isinstance(cur, dict) else {}
    entry["title"] = title
    if artist and not entry.get("singers"):
        entry["singers"] = [a.strip() for a in artist.split(",") if a.strip()]
    # LRCLIB's albumName is the soundtrack for a film song, which is the tag
    # the player shows. Only ever fills a blank -- a hand-set film outranks it.
    # For a single the album is just the track name again, and showing a song
    # as its own film reads like a bug, so that case stays empty.
    if album and not entry.get("film") and _norm(album) != _norm(title):
        entry["film"] = album
    entry.setdefault("film", "")
    entry.setdefault("year", None)
    meta[name] = entry
    tmp = META + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, META)
    log(f"  metadata: {name} -> {title!r}")


def run(cmd, **kw):
    log("  $ " + " ".join(os.path.basename(c) for c in cmd[:2]))
    return subprocess.run(cmd, cwd=REPO, **kw)


def sync_r2():
    """Push the new song's stems to R2, so the edge serves it too.

    Best effort on purpose. The player falls back to the origin for anything
    the bucket lacks, so a failure here costs a few seconds on first play and
    nothing else -- it must never hold up a publish or fail a request. The
    common causes are a lapsed wrangler login and no network.
    """
    r = run(["./scripts/sync-stems-r2.sh"], capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    log(f"  r2 sync: {tail[-1] if tail else 'no output'}"
        + ("" if r.returncode == 0 else "  (FAILED — the edge will miss this song"
                                        " until sync-stems-r2.sh is re-run)"))


def process(entry, fast):
    name = entry["name"]
    title = field(entry.get("song"))
    artist = field(entry.get("detail"))
    # YouTube wants everything; LRCLIB wants the title alone with the artist
    # passed separately, so the manifest keeps them in different fields.
    search = " ".join(x for x in (title, artist) if x)
    log(f"processing {name!r} (asked by {entry.get('who') or 'someone'}): {search}")

    if os.path.exists(os.path.join(STEMS, name, "vocals.wav")):
        log("  already in the library — publishing without reprocessing")
        post_result(entry["id"], "duplicate", title=title)
    else:
        manifest = os.path.join(REPO, ".request-manifest.txt")
        with open(manifest, "w", encoding="utf-8") as f:
            f.write(f"{name} | {search} | {title} | {artist}\n")
        cmd = ["./scripts/add-songs.sh", manifest]
        if fast:
            cmd.append("--fast")
        r = run(cmd, capture_output=True, text=True)
        os.remove(manifest)
        tail = "\n".join(r.stdout.strip().splitlines()[-4:])
        log(f"  add-songs: {tail}")
        if not os.path.exists(os.path.join(STEMS, name, "vocals.wav")):
            # Leave it un-done so a later run can retry — a failed download is
            # usually the search string, and that is worth a human look.
            log(f"  FAILED: no stems for {name}, leaving it queued")
            post_result(entry["id"], "failed",
                        note="Try again with the film or singer added.")
            return False

    if NO_PUBLISH:
        log("  --no-publish: stems are ready, not publishing")
        return True
    # Before prepare-web, not after: prepare-web folds songs-meta.json into the
    # player's manifest, so recording the real title afterwards published the
    # typed one and only corrected it when the NEXT song happened to be added.
    real, artist, album = resolved_title(name)
    record_meta(name, real, artist, album)
    if run(["./scripts/prepare-web.sh"], capture_output=True, text=True).returncode != 0:
        log("  prepare-web failed"); return False
    if run(["./scripts/deploy-web.sh"], capture_output=True, text=True).returncode != 0:
        log("  deploy failed"); return False
    sync_r2()
    log(f"  published {name}")
    post_result(entry["id"], "done", title=real or title)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--full", action="store_true",
                    help="use htdemucs_ft (~4x slower, slightly cleaner stems)")
    ap.add_argument("--local", metavar="DIR",
                    help="read the queue from DIR instead of over SSH (testing)")
    ap.add_argument("--no-publish", action="store_true",
                    help="process but skip prepare-web/deploy (testing)")
    a = ap.parse_args()

    global LOCAL, NO_PUBLISH, QUEUE, DONE, DROP, RESULTS, META
    META = os.path.join(REPO, "data/songs-meta.json")
    NO_PUBLISH = a.no_publish
    if a.local:
        LOCAL = True
        QUEUE = os.path.join(a.local, "requests.jsonl")
        DONE = os.path.join(a.local, "done.txt")
        DROP = os.path.join(a.local, "lyrics")
        RESULTS = os.path.join(a.local, "results.jsonl")

    where = QUEUE if LOCAL else f"{HOST}:{QUEUE}"
    log(f"watching {where} every {a.interval}s "
        f"({'htdemucs_ft' if a.full else 'htdemucs --fast'})"
        + ("  [no-publish]" if NO_PUBLISH else ""))
    while True:
        try:
            drops = lyrics_drops()
            changed = False
            for fname in drops:
                try:
                    changed = apply_lyrics(fname) or changed
                except Exception as e:
                    log(f"  lyrics drop {fname} failed: {e}")
            if changed and not NO_PUBLISH:
                run(["./scripts/prepare-web.sh"], capture_output=True, text=True)
                run(["./scripts/deploy-web.sh"], capture_output=True, text=True)
                log("  published pasted lyrics")

            queue = pending()
            if queue:
                log(f"{len(queue)} request(s) waiting")
            for entry in queue:
                try:
                    if process(entry, fast=not a.full):
                        mark_done(entry["id"])
                except Exception as e:
                    log(f"  error on {entry.get('id')}: {e}")
        except Exception as e:
            log(f"poll failed: {e}")
        if a.once:
            return
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
