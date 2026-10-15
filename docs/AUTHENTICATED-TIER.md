# The authenticated tier — bring your own accounts

Some of the highest-value terrain sits behind a login: Instagram profile pages,
Facebook pages, membership forums, and inboxes that receive verification codes.
The authenticated tier lets Trailhead read that terrain **without ever touching
your passwords** — you sign in once, in a browser you control, and the tool
rides the session from there.

Two independent parts — use either or both:

| Part | Buys you | Needs |
|---|---|---|
| **1. Persistent browser session** | Instagram profile pages, Facebook pages, any login-walled page | A browser server with a saved profile + remote screen |
| **2. Mailbox access (Gmail API)** | Verification/recovery codes, inbox research | A one-time OAuth setup |

Without either, Trailhead runs entirely on public routes — nothing breaks,
those lanes just reach less.

---

## Part 1 — the persistent browser session

### What it is

A small browser server that runs on your machine with three properties:

1. **A persistent profile** — cookies survive restarts (saved on graceful close).
2. **A remote screen** — a web page where you can see and click the browser
   yourself (noVNC).
3. **A local API** — so Trailhead can open pages in that profile and read them.

The reference implementation is **Camofox** (an anti-detection browser server
with VNC). Any setup with the same three properties works.

### Set it up (reference: Camofox)

```bash
mkdir -p ~/camofox && cd ~/camofox
npm install @askjo/camofox-browser

# Run it — pick your own ports and a strong password of your choosing:
CAMOFOX_PORT=9377 \
ENABLE_VNC=1 NOVNC_PORT=9378 \
VNC_PASSWORD='choose-a-strong-password' \
VNC_RESOLUTION=1920x1080 \
node node_modules/@askjo/camofox-browser/server.js
```

For an always-on setup, wrap it in a systemd user unit:

```ini
[Unit]
Description=Camofox Browser Server
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/camofox
ExecStart=/usr/bin/node node_modules/@askjo/camofox-browser/server.js
Restart=always
RestartSec=3
Environment=CAMOFOX_PORT=9377
Environment=ENABLE_VNC=1
Environment=NOVNC_PORT=9378
Environment=VNC_PASSWORD=choose-a-strong-password
Environment=VNC_RESOLUTION=1920x1080
Environment=BROWSER_IDLE_TIMEOUT_MS=86400000

[Install]
WantedBy=default.target
```

> **Exposure note:** the VNC screen is a live browser holding your logged-in
> sessions. Bind it to `127.0.0.1` by default; if you need remote access, put
> it on a private network (VPN/mesh), never the open internet.

### Sign in (once, with your own fingers)

1. Open the remote screen: `http://127.0.0.1:9378/vnc.html` (password = the
   one you chose).
2. Log into Instagram, Facebook, or any site you want covered — your
   credentials, typed by you, in the browser.
3. **Close the browser gracefully** so the profile saves its cookies.
4. Verify persistence: reopen and confirm you're still logged in.

### Point Trailhead at it

```bash
export TRAILHEAD_CAMOFOX_API=http://127.0.0.1:9377
export TRAILHEAD_CAMOFOX_USER=my-browser        # any name; identifies your profile
```

Put these in your shell profile (or the `hermes-trailhead` wrapper script) to
make them permanent. With them unset, the tier skips silently.

### Verify the tier is live

```bash
hermes-trailhead score --live
# instagram row should show:  [session tier: http 200]
```

Then extract a public Instagram profile — you should get the full page
(follower count, bio, post count), not just a caption.

### Good to know

- **Sessions persist across restarts** (saved on graceful close); if a site
  logs you out, reopen the screen and sign in again — ten seconds.
- **Logout = instant revoke.** Sign out of any site in the browser to cut that
  access immediately.
- **The agent never sees your passwords.** By design, the tooling refuses
  agent-typed secrets; fills happen only through your own hands or a masked
  vault prompt.
- **2FA:** if a site uses an authenticator app, the Hermes vault can hold the
  TOTP seed so codes can be generated server-side without ever entering a
  conversation. Sites that demand an emailed code pair well with Part 2.

---

## Part 2 — mailbox access (Gmail API)

### What it buys

- **Verification and recovery codes** — the email leg of logins and account
  recovery, readable automatically (with your consent) so codes never enter a
  chat.
- **Inbox research** — searchable mail for workflows and audits.

### Set it up (one time, ~15 minutes)

1. **Google Cloud Console** → create (or pick) a project →
   **APIs & Services → Library** → enable **Gmail API**.
2. **OAuth consent screen** → External → add yourself as a test user.
3. **Credentials → Create OAuth client ID → Desktop app** → save the
   `client_id` and `client_secret` to a local file (e.g.
   `~/.config/my-gmail-client.json`, `chmod 600`).
4. **Authorize once** — run your OAuth tool of choice and complete the consent
   in a browser. Scopes: `gmail.readonly` (required), `gmail.send` /
   `gmail.modify` (optional, only if you want send/label powers).
5. The token lands in a local file. Nothing is transmitted anywhere except to
   Google itself.

**Hermes users:** the `google-workspace` skill automates all of this
(`setup.py --client-secret … --auth-url … --auth-code …`) and provides
`google_api.py gmail search "…"` for reading. You can also hand the
`client_id`/`client_secret` to Hermes and let it drive the flow — the values
are stored locally, never echoed into conversations.

### Security

- Token lives on your machine only; revoke anytime at
  `myaccount.google.com → Security → Third-party access`.
- Trailhead itself reads mail only if you wire it (e.g. through your agent);
  the mailbox is a separate grant from the browser session.

---

## How Trailhead uses the session

- **Short-lived tabs:** for each page the tier opens a tab in your profile,
  extracts title/description/body text, and closes it again.
- **Lane order:** public routes run first where they work (e.g. Instagram
  embeds for posts/reels); the session tier covers what they can't (profile
  pages, login-walled content).
- **Silent fallback:** env vars unset → tier disabled → public routes only,
  with the caveats reported honestly.

## Security model (the short version)

1. **Passwords never touch the agent.** You type them into the browser screen;
   the tooling refuses agent-typed secrets by design.
2. **Sessions are local files.** Delete the profile directory or log out —
   access is gone.
3. **Codes are read, not typed.** Mailbox access lets the agent *see* codes
   with your consent; nothing secret enters a conversation or a repo.
4. **Nothing in the repo.** No credentials, cookies, tokens, or identifiers
   ship with the tool — verified by a sweep on every release.
