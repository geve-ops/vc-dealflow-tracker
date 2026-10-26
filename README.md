# Greek Deep Tech Deal-Flow Tracker

A weekly "what changed" tracker for the 69 companies on the [Greek Deep Tech Market Map](https://github.com/geve-ops/greek-deeptech-market-map). It watches three public signals: new job postings, funding news, and GitHub activity. Each run produces a Markdown digest and a static dashboard. Every item links to its source.

Author: Gerald Velas. First digest: 26 October 2026.

| Output | File |
|---|---|
| Watchlist (69 companies, with LinkedIn, GitHub and job sources) | [data/watchlist.csv](data/watchlist.csv) |
| Weekly digests | [digests/](digests/) |
| Dashboard (live) | [geve-ops.github.io/vc-dealflow-tracker](https://geve-ops.github.io/vc-dealflow-tracker/) ([source](docs/index.html)) |
| Raw weekly snapshots | [data/snapshots/](data/snapshots/) |

## How it works

1. **Watchlist.** `data/watchlist.csv` holds the market map rows with `map_status` Include or Borderline (36 + 33 = 69). `company_id` matches the market map dataset.
2. **Enrichment.** `linkedin_url`, `github_org`, `careers_url` and the job source are filled from public pages. Each value has a `*_source` column that says where it came from.
3. **Collection.** Each run calls every signal for every company and saves a dated snapshot in `data/snapshots/YYYY-MM-DD.json`.
4. **Digest.** The newest snapshot is compared with the one before it. Changes go to `digests/YYYY-MM-DD.md` and `docs/index.html`.

## Running it

Python 3.10 or newer. Standard library only, so there is nothing to install.

```
python run.py weekly
```

That collects all signals and writes the digest and the dashboard. Other commands:

```
python run.py build-watchlist --source ../greek-deeptech-market-map/data/greek_deeptech_dataset.csv
python run.py enrich                 # fill empty LinkedIn / GitHub / careers fields
python run.py enrich --only GRDT-037 # one company
python run.py collect --signals github news
python run.py digest                 # rebuild the digest from saved snapshots
```

Open `docs/index.html` in a browser to see the dashboard locally. The live version is served by GitHub Pages from the `docs/` folder on `main` and updates with each weekly run.

GitHub API calls use `GITHUB_TOKEN` if it is set, or the token of a logged-in `gh` CLI. Without a token the API allows 60 requests an hour, which is not enough for a full run.

**Schedule.** [.github/workflows/weekly.yml](.github/workflows/weekly.yml) runs `python run.py weekly` every Monday at 06:00 UTC and commits the new snapshot, digest and dashboard. You can also start it by hand from the Actions tab.

## Signals and their limits

### GitHub activity

- **Source:** GitHub REST API, public repos of the company's organisation.
- **Reported:** new public repos, commits pushed during the week (with a link to the latest commit), and star changes from week to week.
- **Coverage:** 22 of 69 companies have a public GitHub organisation that could be tied to them. Most hardware, biotech and defence companies have none, so no activity here does not mean no work.
- **Limits:**
  - Only public repos are visible.
  - Commits are counted up to 100 per repo per week (shown as "100+").
  - Bots such as Dependabot count as commits.
  - Star changes start from the second run.

### Funding news

- **Source:** Google News RSS search, run twice: in English with funding terms (raises, funding, seed, Series A, acquisition, grant...) and in Greek (χρηματοδότηση, επένδυση, αντλεί, εξαγορά...).
- **Matching:** a headline is kept only if it contains one of the company's `news_terms`. These are exact phrases, editable in the watchlist; overrides for renamed or ambiguous names are in `tracker/watchlist.py`.
- **Tags:**
  - **Funding:** the headline itself uses funding language.
  - **Press:** the name is in the headline and the funding terms appear only in the article body. Expect partnerships, product news and leadership changes here.
- **Limits:**
  - Google News links are redirect links that open the original article.
  - Coverage of small Greek outlets is uneven.
  - Paywalled sources (Sifted, PitchBook, Crunchbase News) often appear late or not at all.
  - Names shared with other firms can still give false matches. Fix these by narrowing `news_terms`.
  - Headlines are not verified figures. Confirm a round from a primary source before adding it to the market map dataset.

### Job postings

- **Job-board APIs (13 companies):** postings come from public job-board APIs (Workable, Ashby, Recruitee, Breezy; Lever, Greenhouse and Personio are also supported). These give exact open roles with links.
- **Careers-page heuristic (marked `*` on the dashboard):** for companies whose own careers page is the only source, the tracker records links whose text looks like a role title and whose URL looks like a single posting.
  - Many careers pages load roles with JavaScript and show nothing to this method. The dashboard then shows "–", not 0.
- **Not covered:**
  - LinkedIn job listings, because LinkedIn has no open API and blocks automated access.
  - Companies with no careers page.
- **Limits:**
  - On the first run only postings dated inside the week count as new.
  - From the second run on, new and closed roles are taken from the difference between snapshots.

## Watchlist columns

| Column | Meaning |
|---|---|
| `company_id`, `company`, `category`, `map_status`, `website` | From the market map dataset. Notes after the website URL are dropped. |
| `linkedin_url`, `linkedin_source` | 64 of 69 filled. 50 come from a link on the company website. The other 14 were found by web search on 26 October 2026 and matched on name, HQ and description. 5 have no company page that could be found; the source column says so. |
| `github_org`, `github_source` | Either linked from the company website, or a GitHub organisation whose profile lists the company's website domain. Name matches alone are not accepted. |
| `careers_url`, `jobs_source`, `jobs_source_ref` | The job board and its account slug, `careers_page` with its URL, or `none` with a reason (for example, a careers page that belongs to an acquiring parent company). |
| `news_terms` | Exact phrases a headline must contain, separated by ` \| `. |

Values set by hand are not overwritten by `enrich` unless you pass `--force`.

## Repo layout

```
run.py                      command line entry point
tracker/watchlist.py        build the watchlist from the market map CSV
tracker/enrich.py           fill LinkedIn, GitHub and job sources
tracker/signals_github.py   GitHub signal
tracker/signals_news.py     funding news signal
tracker/signals_jobs.py     job postings signal
tracker/collect.py          run all signals, save a snapshot
tracker/digest.py           compare snapshots, write the digest and dashboard
tracker/dashboard_template.html
```
