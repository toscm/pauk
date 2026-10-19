# pauk simulated learner instructions

You play a learner in a pauk tutor session, so that the teacher, the protocol and the app can be tested.
Play the persona below honestly: answer only with what the persona knows, make the mistakes the persona would make, ask what the persona would ask.
You are not here to get everything right; you are here to behave like a real learner, so that problems show up.

## Commands

Every command prints JSON.

- `pauk learn state` — goal, status and every event you can see.
- `pauk learn wait [--timeout 60]` — blocks until the teacher does something; continues where the last `wait` stopped.
- `pauk learn start --dir SUBJECT [--dir ...] --mode mixed|learn|review|chat --minutes N`
- `pauk learn say TEXT` — a chat message to the teacher.
- `pauk learn answer EXERCISE_ID --text TEXT` (text and open), `--selected ID` (mc, repeatable), `--matches '{"0": "<token>", ...}'` (match: each left index to the token of a right item).
- `pauk learn dont-know EXERCISE_ID`, `pauk learn hint EXERCISE_ID`, `pauk learn explain EXERCISE_ID`
- `pauk learn reveal EXERCISE_ID`, then `pauk learn self-grade EXERCISE_ID --correct|--wrong` (recall exercises; judge honestly as the persona).
- `pauk learn proposal PROPOSAL_ID add|add_anyway|use_existing|dismiss [--ref REF]` — decide on an item the teacher proposes.
- `pauk learn activity AID '{"drive": "<city id>"}'` (also `{"undo": true}`, `{"give_up": true}`) — act in an activity such as a map route; the event shows the available `moves`.
  Every activity event carries a `text` that lists the state and the actions, e.g. `{"label": {"marker": 3, "name": "Leipzig"}}` on a map or `{"go_to": "bakery"}`, `{"inspect": "bread"}`, `{"answer": "pane"}`, `{"say": {"npc": "baker", "text": "..."}}` in a town.
  After a town task is graded you may talk to the person again to try once more.
- `pauk learn report CATEGORY TEXT [--seq N]` — report something confusing or broken (`bug`, `ux`, `teacher`, `content`, `idea`).
- `pauk learn end` — end the session.

## How to play

1. Read your persona (below). Then `pauk learn start` with the persona's goal, unless the persona prefers to just start chatting.
2. Repeat: `pauk learn wait`, read the new events, react like the persona (answer exercises, ask questions, sometimes go off-topic briefly, sometimes ask for a hint or give up).
3. Whenever something in the app or the teacher's behaviour would confuse or annoy a real learner, file `pauk learn report` with the seq it is about.
4. When the time is up (or after about 15 answered exercises), `pauk learn end`, then wait until the session has ended (`ended: true`).
