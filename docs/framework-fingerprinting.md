# Framework Fingerprinting

This feature tests whether feed quality is correlated with the
software that adds feed support or autodiscovery. A likely hypothesis is that
many feeds exist because a CMS, static-site generator, or framework emits them
by default, sometimes without the site administrator actively maintaining them.

The current implementation records conservative platform fingerprints from:

- selected HTTP headers on feed responses
- feed-level generator elements
- HTML `<meta name="generator">`
- common HTML asset/path markers

For HTML pages, the report tracks both how often fingerprinted pages expose
RSS/Atom autodiscovery and the quality of parsed feeds discovered from those
fingerprinted source pages.

## Research Questions

- Which frameworks or CMSs commonly emit feed autodiscovery links?
- Which frameworks or CMSs commonly expose RSS or Atom feed URLs directly?
- Are framework-generated feeds more likely to be parseable, active, stale, or
  zero-entry?
- Do frameworks tend to emit duplicate feed variants, such as RSS and Atom links
  with the same internal title and link?
- Are language signals better or worse for framework-generated feeds?

## Current Signals

HTTP response headers:

- `Server`
- `X-Powered-By`
- `X-Generator`
- Drupal cache headers
- cache/CDN headers when they strongly imply a platform

HTML response content:

- `<meta name="generator">`
- common asset paths, such as `/wp-content/`, `/sites/default/`, or framework
  build assets

Feed response content:

- `<generator>` in Atom
- RSS `<generator>`

## Candidate Signals Not Yet Implemented

- feed URL patterns, entry link patterns, and namespace choices
- `Link` headers
- WebSub hub/self links
- RSS generator-like extension elements
- duplicate feed variant rates by source framework

## Data Model Direction

The implementation intentionally records bounded fingerprints, not raw headers
or raw HTML. A richer future model could carry:

- `framework`: normalized label, such as `wordpress`, `ghost`, `drupal`,
  `jekyll`, `hugo`, or `unknown`
- `source`: `http_header`, `html_meta`, `html_path`, `feed_generator`, or
  `url_pattern`
- `confidence`: `high`, `medium`, or `low`
- `evidence`: a short normalized token, not full content

At report time, aggregate by fingerprint and compare:

- pages with autodiscovery
- active/recent share
- zero-entry share
- mean operational quality
- duplicate feed variant rate on multi-feed pages

## Cautions

Framework detection will be noisy. The report should frame these as
fingerprints, not authoritative software inventory. Prefer high-confidence
signals in headline tables and keep low-confidence signals available only for
debugging or exploratory analysis.
