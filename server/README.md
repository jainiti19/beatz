# Server side

What runs on the Hetzner VPS for the web player. None of this is deployed by
`deploy-web.sh` — that only mirrors `web/`. These files are the record of a
setup that otherwise exists nowhere but the box, and every one of them needs
root, which the `beatznbox` deploy user does not have.

| file | lives on the VPS at | how to apply |
|---|---|---|
| `queue-service.py` | `/opt/beatznbox/queue-service.py` | `scp` as the `beatznbox` user, then restart the unit |
| `beatznbox-queue.service` | `/etc/systemd/system/` | `systemctl daemon-reload && systemctl enable --now beatznbox-queue` |
| `add-cache-header.sh` | `/opt/beatznbox/` | `ssh root@… 'bash /opt/beatznbox/add-cache-header.sh'` |

## Caddyfile

Two edits inside the `beatznbox.wesimplyhome.com` block, both already applied.
Caddy is shared with five other sites, so **always**
`caddy validate --config /etc/caddy/Caddyfile` before `systemctl reload caddy`.

    # song requests and pasted lyrics reach the queue service
    reverse_proxy /api/* 127.0.0.1:8931

    # stems never change under a given name; a replay should cost no network
    @audio path *.mp3
    header @audio Cache-Control public,max-age=604800

A third, from 23 Sep (Music Night, 25 Sep): an `admin` login beside `beatz`,
and the login name passed to the queue service. Applied by
`enable-admin-login.sh` (scp to `/opt/beatznbox/`, then
`ssh -t root@46.224.176.48 bash /opt/beatznbox/enable-admin-login.sh`;
`--rollback` undoes it):

    basic_auth @needsauth {
        beatz <hash>
        admin <hash>
    }
    reverse_proxy /api/* 127.0.0.1:8931 {
        header_up X-Beatz-User {http.auth.user.id}
    }

Only admin logins may POST `/api/playlists`, `/api/presets`, `/api/clips`;
everyone else gets `403 {"error":"read-only","role":"viewer"}`. Admin logins
are `admin` unless `BEATZ_ADMINS=a,b` is set in the unit or
`/opt/beatznbox/admins.txt` lists them one per line. A call straight to
127.0.0.1:8931 from the box (no X-Beatz-User, no X-Forwarded-For) is trusted
as admin, as before. **Order: the Caddy edit before the new
`queue-service.py`; undo in reverse.** Without the `header_up` line Caddy
passes a browser's own X-Beatz-User through, and the new service would
believe it.

Deliberately not `immutable`: `prepare-web.sh` re-encodes to the *same*
filename when a song is reprocessed, so a year-long entry would pin stale audio
with no way to bust it.

## Watching the queue

`scripts/watch-requests.py` runs on the desktop, not here. Start it detached so
it outlives the terminal:

    setsid ~/demucs-env/bin/python scripts/watch-requests.py --interval 60 \
      >> ~/Music/beatz_pipeline/watch-requests.log 2>&1 < /dev/null &

## A note on long commands

Pasting a long `ssh root@… '…'` one-liner into the terminal wraps and breaks it
— twice this has split a flag from its argument or left a filename on its own
line. Put a script on the box and run a short command instead.
