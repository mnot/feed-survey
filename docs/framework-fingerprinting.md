# Framework Fingerprinting Plan

This feature is intended to test whether feed quality is correlated with the
software that adds feed support or autodiscovery. A likely hypothesis is that
many feeds exist because a CMS, static-site generator, or framework emits them
by default, sometimes without the site administrator actively maintaining them.

## Research Questions

- Which frameworks or CMSs commonly emit feed autodiscovery links?
- Which frameworks or CMSs commonly expose RSS or Atom feed URLs directly?
- Are framework-generated feeds more likely to be parseable, active, stale, or
  zero-entry?
- Do frameworks tend to emit duplicate feed variants, such as RSS and Atom links
  with the same internal title and link?
- Are language signals better or worse for framework-generated feeds?

## Candidate Signals

HTTP response headers:

- `Server`
- `X-Powered-By`
- `Link`
- cache/CDN headers when they strongly imply a platform

HTML response content:

- `<meta name="generator">`
- common asset paths, such as `/wp-content/`, `/sites/default/`, or framework
  build assets
- feed autodiscovery URL patterns and titles

Feed response content:

- `<generator>` in Atom
- RSS generator-like extension elements
- feed URL patterns, entry link patterns, and namespace choices

## Suggested Data Model

Add a bounded set of framework evidence to the analysis result, not raw headers
or raw HTML. Each observation should carry:

- `framework`: normalized label, such as `wordpress`, `ghost`, `drupal`,
  `jekyll`, `hugo`, or `unknown`
- `source`: `http_header`, `html_meta`, `html_path`, `feed_generator`, or
  `url_pattern`
- `confidence`: `high`, `medium`, or `low`
- `evidence`: a short normalized token, not full content

At report time, aggregate by framework and compare:

- pages with autodiscovery
- feed URL checks
- parse success rate
- active/recent share
- zero-entry share
- mean operational quality
- duplicate feed variant rate on multi-feed pages

## Cautions

Framework detection will be noisy. The report should frame these as
fingerprints, not authoritative software inventory. Prefer high-confidence
signals in headline tables and keep low-confidence signals available only for
debugging or exploratory analysis.
