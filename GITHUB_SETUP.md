# Running the Teleconnection Monitor on GitHub (nothing to install)

Everything runs on GitHub's computers:

- A scheduled job checks for new model runs twice an hour.
- It computes the indices and stores the results in the repository.
- It publishes the page at `https://<your-username>.github.io/<repo-name>/`.

All of the setup below happens in a web browser.

## 1. Create the repository

1. Sign in at https://github.com, then click **+** (top right) → **New repository**.
2. Name it, e.g. `telemon`. Choose **Public**: scheduled jobs on public repositories have no monthly time limit, and the data is all public model output. Leave every "Initialize" box unchecked, then click **Create repository**.

## 2. Upload the project

1. Unzip `telemon.zip` on your computer.
2. On the new repository's page, click the **uploading an existing file** link.
3. Open the unzipped `telemon` folder. Select **everything inside it** and drag it into the browser:
   - `.github`
   - `pipeline`
   - `web`
   - `README.md`
   - `GITHUB_SETUP.md`

   Drag the contents, not the `telemon` folder itself.
4. Click **Commit changes**.
5. Check that the folder `.github/workflows` now holds `ingest.yml` and `setup.yml`. If it's missing (some browsers skip folders whose names start with a dot), add each file by hand:
   - Click **Add file → Create new file**.
   - Type `.github/workflows/ingest.yml` as the name.
   - Paste in that file's contents from your unzipped copy and commit.
   - Repeat for `setup.yml`.

## 3. Two settings

1. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions**.
2. **Settings → Actions → General → Workflow permissions:** choose **Read and write permissions**, then **Save**.

## 4. Run the one-time setup

1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Setup (run once)** on the left, then **Run workflow → Run workflow**.
3. It takes about 1–1.5 hours. It does three things:
   - Builds the 1991–2020 climatology from the NOAA PSL reanalysis.
   - Seeds 150 days of observed index history.
   - Publishes the page.

   Click the run to watch the log. A green check means it worked.

## 5. Start the ingest

The **Ingest model runs** job starts on its own every 30 minutes. To get data right away, click it → **Run workflow**. The first pass processes the last 36 hours of every model and can take an hour or two, mostly downloading GEFS and EPS. After that, each pass only handles new runs.

**Your page:** `https://<your-username>.github.io/telemon/` (the exact address is in **Settings → Pages**). Bookmark it. If the page is open when a new run lands, it updates by itself within about 5 minutes.

## Day-to-day

- **Turn a model off or lighten the downloads:** edit `pipeline/config.json` in the browser (pencil icon). For example, set `"enabled": false`, or change `"step_hours"`, `"cycles"` or `"aam"`. Then commit; the next pass uses the new settings.
- **Re-process one run:** go to **Actions → Ingest model runs → Run workflow**. Enter a model and a run time such as `2026112300`.
- **Change labels or colors:** edit `web/js/config.js`. The next pass republishes the page.
- **Something broke:** open **Actions**, click the red ❌ run and read the log. GitHub also emails you about failed runs.
- **Timing:** GitHub sometimes starts scheduled jobs 5–30 minutes late, especially at the top of the hour.
- **60-day pause:** GitHub may pause scheduled jobs on a repository with no activity for 60 days. It emails you first; one click in the **Actions** tab turns it back on.

## Where things are stored

- The computed data lives on the `data-store` branch. It is kept as a single snapshot, so the repository doesn't grow; runs older than 60 days are pruned.
- The climatology is attached to the release named `climatology`.
- Nothing is stored on your computer.
