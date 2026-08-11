# Music Night — Format Design

## Date: 11 Aug 2026
## Companion to `MUSIC_NIGHT_REQUIREMENTS.md`

---

## Why this document exists

`MUSIC_NIGHT_REQUIREMENTS.md` specifies the **technology** completely — song library,
audio quality, lyrics projection, switching speed. It says nothing about **what the
30–35 people in the room actually do**, minute by minute.

That gap is the real risk, and it shows in one line of the requirements doc:

> *"attendees should feel like they're at a live music session"*

A "live music session" is a **concert frame** — performers perform, an audience
watches. That is a perfectly nice evening. It is also the failure mode: four
confident singers hold the mic and twenty-six people look at their phones. And it
teaches us nothing about whether the *format* works, because a good singer carried it.

Every event that has worked so far — Amazing Race, treasure hunts, Carnival
Splendor, Dhurandhar — worked because of **structured participation**: teams, rules,
rounds, scoring. Nobody ever had to wonder what they were supposed to be doing.

**So: design this as a game with music in it, not a concert with games in it.**

---

## The core problem, stated precisely

Singing in front of people is *exposing*. Throwing a beanbag is not.

At the carnival, 2–3 guests hung back — the least competitive, newest to the group.
At a carnival they could drift between stalls and still be included. At a singalong,
that same group doesn't hang back, they **disappear**. The 10% edge case becomes 50%.

Two design rules follow:

1. **The participation bar must rise gradually.** Never open with the hardest ask.
   Get the room *making noise* long before you ask anyone to *sing*.
2. **Singing must happen as a group before it happens alone.** A team singing two
   lines to a rule is a completely different ask from an individual with a mic.

---

## The mechanic that makes Beatz special

Beatz does stem separation. Nobody's karaoke night can do this. **Stems are a
difficulty dial**, and that turns the song library into a game engine:

| Play only… | Difficulty | Use for |
|---|---|---|
| Vocals (a cappella) | Easy | Warm-up |
| Full mix, 2 seconds | Easy–medium | Warm-up |
| Instrumental (no vocals) | Medium | Mid rounds |
| Bass line only | Hard | High-point rounds |
| Drums only | Very hard | Bonus / tie-break |

This is the "engine" of the evening in the same way bonus gems were the engine of
Carnival Splendor: a simple rule that generates escalating difficulty for free.

---

## Tables are teams

Venue is an Indian restaurant — seated, at separate tables, ambient noise. That
fragments a room, which is normally the enemy of a group event.

**Turn it into the structure: each table is a team.** 5–6 tables, 5–6 teams. No
moving people around, no forced mingling, no awkward "find your group" moment.
Same move as the wristband colours at the carnival — assignment without friction.

Name the tables after songs in the library (Team Chaiyya Chaiyya, Team Kala Chashma).
Costs nothing, sets the tone immediately.

---

## Run of show (~3 hours)

Participation bar rises through every phase. Points accumulate across rounds 1–4.

### Round 1 — "Two Seconds" (20 min) · bar: shout an answer

Play the first two seconds of a song. Tables shout the name. First correct = point.

Open with the unmistakable ones from the library: **Chaiyya Chaiyya, Kala Chashma,
London Thumakda, Badtameez Dil, Ghungroo, Tum Hi Ho, Kal Ho Naa Ho, Tujhe Dekha Toh.**

*Why this is first:* zero exposure, zero skill, instant noise. The whole room is
loud and laughing inside ninety seconds. **This round is doing the most important
work of the night** — nobody sings until the room already sounds like a party.

### Round 2 — "Name That Stem" (20 min) · bar: still just shouting

Same game, harder input. Instrumental = 2 points. Bass line only = 3 points.
Drums only = 5 points and pure comedy.

Dance tracks work best stripped back — **Kala Chashma, Ghagra, Hudd Hudd Dabangg,
London Thumakda**. Ballads on drums alone are near-impossible, which is why they're
worth 5.

*Why second:* the format is already familiar, so difficulty can rise without
anyone needing new instructions.

### Round 3 — Antakshari, table vs table (30 min) · bar: sing, but as a group

Classic rules: last letter of the previous song starts the next. Two lines minimum.
**A cappella — no backing track, no tech, entirely from memory.**

*Why this works:* it needs nothing from Beatz, it's culturally native (zero
explanation for an Indian crowd), and crucially the **table sings together**. The
shy people are covered by four other voices. This is the moment singing enters the
evening, and it enters in the safest possible form.

Rule that matters: **a table can pass twice.** Removes the fear of being stuck.

### Round 4 — "Finish the Line" (15 min) · bar: sing or say, table's choice

Project a lyric with a gap (the Whisper timed-lyrics data already exists for this).
Table completes it. **Allow spoken answers** — a table that says it still scores.
Deliberately generous: the point is to keep everyone in.

**This round carries the most important mechanic of the night — see below.**

### Round 5 — The Open Mic (60–75 min) · bar: sing alone, and now they will

Beatz karaoke preset, lyrics projected, Karan anchoring. Announce the table scores
and the winner *before* this starts, so the competition closes and the music opens.

By now the room has been loud for ninety minutes, everyone has already sung in a
team, and nobody is cold. **This is the same evening that would have died at 8pm
if you'd opened with it.**

### Round 6 — Full tracks, dancing (open-ended)

Vocals back in, dance numbers, no structure. Let it become a party.

---

## The mechanic that kills dead air

**During Round 4, every table nominates one singer and one song from the library
for the Open Mic.** Written on a card, handed in.

This is the single most valuable idea in this document. It means:

- By the time the mic is live there is **already a queue** — no "who wants to go
  first?" silence, which is the moment these evenings die.
- Going up was a **team decision, not an act of individual bravery.** Completely
  different psychological ask.
- Every table is invested in at least one performance, so nobody's on their phone.
- The setlist builds itself from what people actually want to sing.

The requirements doc lists "participant song requests" as a *nice-to-have*. It is
not a nice-to-have. **It is the load-bearing mechanic of the second half.**

---

## De-risk first: the 10-person living room test

Do this before booking anything. Eight to ten people, Karan, one evening, no venue,
no budget, laptop and a TV.

**Test only the three risky things:**

1. **Round 1** — does the room get loud fast? If the warm-up doesn't work at 10
   people it will not work at 35.
2. **Round 3** — will people actually sing in teams? Watch the quietest person in
   the room. They are the whole experiment.
3. **The Round 4 → Round 5 transition** — with nominations in hand, does someone
   sing solo without being begged? **This is the make-or-break.**

Don't test the tech here. Test whether people play.

**Read the result honestly:** if the quietest person sang in Round 3 and someone
went up in Round 5 unprompted, the format works and scale only makes it better.
If Round 5 needed pleading at 10 people, it will be worse at 35 — and the fix is
more structure, not more encouragement.

---

## Watch: don't let it become Karan's gig

Karan is a real asset — a lead singer means there is never dead air, and he can
rescue any moment. That is exactly why it's a risk.

If Karan performs and others watch, the night succeeds and the **product fails** —
because it proves a good singer draws a crowd, which we already knew. For this to
be a repeatable experience business, the format has to carry the room without a star.

Give him a defined job: **host and anchor, not headliner.** He opens Round 5 to set
the standard, closes it, and rescues gaps — and stays off the mic in between.

---

## Library housekeeping

38 processed songs is a strong base. Small cleanup:

- **`AWESOME__Ninjago_Tribute_TheFold`** and **`Rise_and_Whip_Ninjago`** — Lego
  Ninjago tracks. Not Bollywood night material; exclude from the event playlist.
- **`Tum_Hi_Ho`** and **`Tum_Hi_Ho_Aashiqui_2_Full_Song_With_Lyri`** — the same
  song twice. Keep the better-sounding stems, drop the other.
- Several folder names are truncated mid-title (`Mere_Rashke_Qamar_Song_With_Lyrics__Baad`,
  `Toh_Phir_Aao_Video_Song_4K__Awarapan_Mov`). Fine internally, but they must show
  as clean titles on the projected screen.

That leaves **~35 usable tracks** — comfortably enough. The genre spread is good:
dance (Ghagra, Kala Chashma, London Thumakda, Badtameez Dil, Munni Badnaam),
ballads (Tum Hi Ho, Channa Mereya, Agar Tum Saath Ho, Kabira), classics (Neele
Neele Ambar Par, Kya Khoob Lagti Ho, Tujhe Dekha Toh), sufi (Kun Faya Kun,
Afreen Afreen, Mere Rashke Qamar). Rounds 1–2 need recognisable *openings*;
Round 5 needs *singable* ones. Both are covered.

---

## Status against the original timeline

The requirements doc planned: *Jun–Jul* process songs + build lyrics page,
*Jul–Aug* full setup test and 1–2 dry runs with Karan, *Aug* fix issues, *Sep* event.

As of 11 Aug: songs are processed (38) and the web lyrics page exists with timed
auto-scroll. **No evidence the PA/mic/screen dry run or the dry runs with Karan
have happened.** The audio-quality checklist — PA test, clipping, volume
normalisation across tracks, transition clicks — is all still open, and it is the
one thing that cannot be fixed on the night.

If the event moves to October, that buys real time for both the dry run and the
format test. If it stays in September, the PA test is the highest-priority
technical task and should happen in the same session as the living-room format test.

---

## Summary

| | |
|---|---|
| **The risk** | A concert with a passive audience, and no learning about the format |
| **The fix** | A game with music in it; participation bar rises every round |
| **The engine** | Stems as a difficulty dial — nobody else can do this |
| **The structure** | Tables are teams |
| **The critical mechanic** | Teams nominate singer + song during Round 4, before the mic goes live |
| **Karan's role** | Anchor and host, not headliner |
| **Next action** | 10-person living-room test of Rounds 1, 3 and the 4→5 transition |
