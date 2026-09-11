# Images in the terminal

pauk draws pictures directly in the terminal: photos on
multiple-choice and text cards, and the coloured route map on
`route` cards. How crisp they look depends on the terminal, and
on whether you are inside tmux.

## Rendering modes

There are two families of renderer:

- High fidelity: `sixel` and `tgp` (the kitty graphics
  protocol) draw true pixels. They need a terminal that
  supports the protocol — kitty, WezTerm, foot, iTerm2, and
  recent VTE terminals for sixel, among others.

- Universal fallback: `halfcell` draws the image out of
  half-block characters (▀) with foreground/background colours.
  It is lower resolution but works in any terminal that can show
  256 colours, including plain xterm and anything running inside
  tmux. `unicode` is an even more basic variant.

By default the mode is `auto`: pauk picks the best protocol the
terminal advertises. The one exception is tmux — see below.

Set a fixed mode in `~/.config/pauk/config.toml`:

    image_mode = "halfcell"

or for a single run:

    PAUK_IMAGE_MODE=halfcell pauk

Valid values: `auto`, `halfcell`, `sixel`, `tgp`, `unicode`.

## tmux

tmux sits between pauk and your real terminal and, by default,
swallows the escape sequences that sixel and kitty graphics rely
on — so a protocol that works in the bare terminal produces
garbage (or nothing) once tmux is in the way. To stay reliable,
`auto` mode falls back to `halfcell` whenever it detects tmux
(the `$TMUX` environment variable).

If your terminal supports sixel or kitty graphics and you want
the crisp version inside tmux, enable tmux's passthrough and
tell pauk to trust it:

1. Turn on passthrough in `~/.tmux.conf`:

       set -g allow-passthrough on

   Reload with `tmux source-file ~/.tmux.conf` (or start a fresh
   server). Passthrough needs tmux 3.3 or newer.

2. Let pauk use the high-fidelity protocols inside tmux, in
   `~/.config/pauk/config.toml`:

       tmux_image_passthrough = true

   (or force one explicitly, e.g. `image_mode = "sixel"`).

With passthrough off — the safe default — `halfcell` is used and
images always show, just at lower resolution.

## Troubleshooting

- Garbled blocks or leftover escape text where an image should
  be: the chosen protocol is not actually getting through. Set
  `image_mode = "halfcell"` (or unset `tmux_image_passthrough`).

- No image at all: the terminal may lack 256-colour support, or
  the media failed to download. Image display is best-effort —
  the rest of the card still works.

- SSH: rendering happens in your local terminal, so the same
  rules apply as locally. Over SSH *and* tmux, keep the
  `halfcell` default unless you have set up passthrough.
