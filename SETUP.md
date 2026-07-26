# Setup Guide

Everything runs free: GitHub Actions for the scraper, GitHub Pages for the
website, Cloudflare Workers for the "Run search now" button. ~30 minutes
total, one-time.

---

## 1. Create the GitHub repo

1. Create a new **private** GitHub repo (e.g. `sf-apartment-search`).
2. Upload all files from this project, keeping the folder structure.
3. Push to a branch named `main` (the workflow and worker both assume this).

---

## 2. Google Sheets access (service account)

1. Go to https://console.cloud.google.com/ → create a new project.
2. Enable the **Google Sheets API** for that project.
3. **APIs & Services → Credentials → Create Credentials → Service account**.
4. Open the service account → **Keys** → **Add Key → Create new key → JSON**.
   Keep the downloaded file safe.
5. Create a new Google Sheet (sheets.new). Copy the **Sheet ID** from its URL.
6. In the downloaded JSON, find `"client_email"` and **share your Google
   Sheet with that email address** (Editor access).

---

## 3. Twilio (text messages)

1. Sign up free at https://www.twilio.com/try-twilio.
2. Grab your **Account SID** and **Auth Token** from the console.
3. Get your free trial phone number.
4. Verify your own cell number under **Phone Numbers → Verified Caller IDs**
   (trial accounts can only text verified numbers).

---

## 4. Add GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | Service-account JSON, base64-encoded |
| `GOOGLE_SHEET_ID` | ID from your sheet's URL |
| `GOOGLE_SHEET_URL` | Full sheet URL (used in text messages) |
| `TWILIO_ACCOUNT_SID` | From Twilio console |
| `TWILIO_AUTH_TOKEN` | From Twilio console |
| `TWILIO_FROM_NUMBER` | Your Twilio number, e.g. `+14155551234` |
| `TWILIO_TO_NUMBER` | Your cell number, e.g. `+14155559876` |

Base64-encode the JSON file:
- Mac/Linux: `base64 -i service-account.json`
- Windows PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("service-account.json")) | Set-Clipboard`

---

## 5. Turn on GitHub Pages (the website)

1. Repo → **Settings → Pages**.
2. Under "Build and deployment", set **Source: Deploy from a branch**.
3. Branch: `main`, folder: `/docs`. Save.
4. GitHub gives you a URL like `https://yourname.github.io/sf-apartment-search/`.
   That's your (and your partner's) site — bookmark it.
5. The site reads `docs/listings.json`, which doesn't exist until the
   scraper runs once — see step 7.

---

## 6. Set up the "Run search now" button (Cloudflare Worker)

The button needs a tiny secure backend so your GitHub token isn't exposed
in the public website code. This uses Cloudflare's free tier.

1. Create a **fine-grained GitHub Personal Access Token**:
   - GitHub → Settings → Developer settings → Personal access tokens →
     Fine-grained tokens → Generate new token.
   - Restrict it to **only this repository**.
   - Under permissions, grant **Actions: Read and write**. Nothing else.
2. Sign up free at https://dash.cloudflare.com/sign-up (Workers plan, free tier).
3. **Workers & Pages → Create → Create Worker**. Give it any name
   (e.g. `sf-apartment-trigger`).
4. Paste the contents of `worker/worker.js` into the Worker editor, deploy.
5. Worker → **Settings → Variables and Secrets**, add:
   - `GITHUB_TOKEN` (the token from step 1) — mark as **secret**
   - `GITHUB_REPO` — e.g. `yourname/sf-apartment-search`
6. Copy the Worker's URL (looks like `https://sf-apartment-trigger.yourname.workers.dev`).
7. Open `docs/index.html`, find `RUN_NOW_WORKER_URL = ""` near the top of
   the `<script>` block, and paste the URL in. Also set `GITHUB_ACTIONS_URL`
   to `https://github.com/yourname/sf-apartment-search/actions` as a fallback.
8. Commit and push. The button will now trigger a real run on click.

**Skip this section if you're fine just clicking "Run workflow" in the
GitHub Actions tab directly** — that works with zero extra setup, it's just
one extra click outside the website itself.

---

## 7. Test everything

1. Go to your repo's **Actions** tab → **SF Apartment Search** → **Run
   workflow** (manual trigger, works regardless of whether you set up the
   Worker). Check the run logs.
2. After it finishes, visit your GitHub Pages URL — you should see listings,
   a "last checked" timestamp, and filter chips for standard rentals vs.
   lease takeovers/sublets.
3. Check your phone for the text and your Google Sheet for the rows.
4. If you set up the Worker, click "Run search now" on the site itself and
   confirm a new Action run appears in the Actions tab within a few seconds.

---

## What's covered, and what isn't

**Craigslist** — covers both regular rentals and the sublets/temporary
category, with lease-takeover posts auto-tagged based on keywords
("sublease," "lease takeover," etc.) so the site can filter them separately.

**Property management companies** — this is a plugin system
(`sources/property_managers.py`). Two were evaluated:

- **rentalsinsf.com** — ✅ wired up and working. It's a normal WordPress
  site with listings in the raw page, so it's scraped directly, filtered by
  your price/neighborhood criteria same as everything else.
- **rentsfnow.com (Veritas Investments)** — ⛔ skipped by request. Its
  listings are rendered by JavaScript after the page loads (not present in
  the raw HTML), and its search page has active bot detection that blocked
  a direct fetch outright. A working scraper for it would need a headless
  browser (Playwright) simulating a real browser tab — slower, more
  fragile, and not guaranteed to get past the bot detection either. Say
  the word if you want that built later; it's a bigger, separate piece.

To add another company later: open their listings page, find the CSS
selectors or structural patterns (URL shape, image alt text, price format)
for title/price/sqft/neighborhood, write a new function following the
`scrape_rentalsinsf` example, and register it in `SOURCES`.

**Facebook Marketplace** — intentionally not included. It requires an
authenticated login and has aggressive bot detection; automating it risks
your Facebook account getting flagged. If you want Marketplace data, the
realistic path is a paid third-party data provider (e.g. Apify) that
absorbs that risk on their end — I can wire your site to ingest their
output if you want to go that route.

---

## Notes

- **Schedule:** currently 7am/4pm Pacific — edit the `cron` lines in
  `.github/workflows/apartment-search.yml` to change (UTC, no DST auto-adjust).
- **Neighborhoods/criteria:** edit the constants at the top of `scraper.py`.
- **If Craigslist selectors ever return 0 results:** their markup changed —
  check `scrape_craigslist_category()` in `scraper.py` first.
