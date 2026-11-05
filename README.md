# pauk

> [!WARNING]
> A private hobby project, published for convenience and not meant for anyone else.
> No support, no stability guarantee. Use at your own risk.

pauk is a personal teacher that runs on your own machine.
Knowledge lives in plain text files you edit yourself (YAML decks and Markdown items), every answer goes into a learning log pauk appends to, and a Claude teacher (or practice without one) teaches and quizzes you in a small web app that also serves the phones and laptops in your LAN.
There is no database: `docs/files.md` describes every file.

## Install and run

Needs Node.js 24 or newer (it runs the TypeScript sources directly, there is no build step).

    cd app
    npm install
    npm link                         # puts `pauk` on your PATH
    pauk user add NAME --admin --llm --budget 20
    # for the teacher: ANTHROPIC_API_KEY=sk-ant-... in ~/pauk/.env (docs/files.md)
    pauk check                       # validate the knowledge files
    pauk start                       # prints the address, e.g. http://127.0.0.1:8765

The first command creates `~/pauk/config.yaml` with the example decks (`examples/`: the Greek letters and a little Italian) as its source.
Point `sources` there at your own knowledge folders, ideally private git repositories.

On macOS, let pauk run by itself instead of in a terminal:

    pauk service install             # start now, at every login, and again if it dies
    pauk restart                     # after changing code or config.yaml
    pauk service uninstall

This also adds a menu bar item (`app/macos/PaukMenu.swift`, built with `swiftc`): it shows whether pauk runs and at which address, copies or opens that address, restarts or stops pauk, and opens the log `~/pauk/server.log`.
Ctrl+Option+Cmd+P restarts pauk from anywhere.
The service reads the API key from `~/pauk/.env` (a login service does not see your shell's variables).

For the other devices in your LAN set `listen: 0.0.0.0:8765` in `config.yaml`, add a user (`pauk user add guest --llm --budget 5`) and open the printed LAN address on the phone.
From outside your LAN, use Tailscale (or another VPN) rather than opening a port.

Admins can edit an item, add one to a folder or start a new folder right in the browser; pauk writes the change into the deck file and refuses changes that `pauk check` would report.

    npm test                         # unit and flow tests, no API calls
    npm run check                    # type-check everything

## How it works

The code is in `app/`; paths below are relative to it.


- `src/knowledge.ts` reads the source folders into an index (items, cards, aliases, subjects).
- `src/log.ts` reads `users/<name>/log/*.jsonl` and replays it through `src/memory.ts` into item states.
- `src/profile.ts` answers "what is due, what is new" from both.
- `src/session.ts` holds one session: the event stream, open exercises, grading (`src/grader.ts`, `src/text.ts`), practice without a teacher.
- `src/teacher.ts` is the Claude teacher: a tool-use loop whose tools are methods of the session.
- `src/server.ts` serves the app (`public/`) and a small JSON API; events reach the browser as server-sent events.
- `src/edit.ts` writes the decks when an admin edits or adds an item in the browser.
- `src/service.ts` and `macos/PaukMenu.swift`: the login service and the menu bar item (macOS).
- `src/cli.ts`: `pauk start | check | user add | debug | service | restart`.

## Debugging the teacher

### When pauk calls the API

Only when a learner event needs the teacher: the start of a session, a message, an answer (during a drill only the last one), an explanation request, the end.
pauk then runs one turn of the loop in `Teacher.turn`:

1. It appends the new events as one user message (JSON lines) to the conversation.
2. It sends the whole request: system prompt (`src/prompt.md`), the 15 tool definitions (`TOOLS` in `src/teacher.ts`), and every message so far.
3. The model answers with thinking, maybe a few words of text, and tool calls.
4. pauk runs the tools, sends their results back as the next user message, and repeats from 2 until the model stops calling tools.

Revealing a recall card, typing, and practice without a teacher never call the API.

### What is sent

Everything the model sees is in the request: the system prompt, the tools, and the messages.
It never sees your files: it only sees what the tools return, e.g. the 10 items `next_items` picked or the one item `get_item` asked for.
Because the API is stateless, each call repeats the whole conversation; prompt caching (`cache_control` in the request) makes the repeated part cost about a tenth of new input.

### Where to look

- `~/pauk/users/<name>/api/YYYY-MM.jsonl`: one line per API call with time, duration, model, token usage, cost and the month's total.
  With `teacher.debug: true` (the default) the line also holds the full request and response.

- `pauk debug` lists the calls of the last session (numbers made up for illustration):

      #  time      ms  input  cached  written  output    cost  tools
      1  14:03:11  4210   3120       0     2950     410  0.0397  profile next_items
      2  14:03:16  2980    210    2950      380     220  0.0072  say introduce ask

  `input` is billed at the full price, `cached` at a tenth, `written` (stored in the cache) at 1.25 times.
  A healthy session has `cached` growing call by call and small `input`; if `cached` stays 0, something in the prefix changes between calls.

- `pauk debug --call 2` shows that call's newest message (what pauk added), the model's thinking summary, its text and its tool calls.

- `~/pauk/users/<name>/sessions/<id>.jsonl` is the transcript as the browser saw it, one event per line.

- `npm test` includes a run of the loop against a scripted fake client (`test/flow.test.ts`): the place to try changes to the loop without spending money.
