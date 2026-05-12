# Web Feed Survey: CC-MAIN-2026-12

Percentages describe this Common Crawl result set, not the entire Web. Common Crawl reflects what its crawler fetched, what sites allowed, and the response-type prefilter and Tranco list/sample limits for this run. Site counts and TOP_N scoping use the Tranco subdomain-inclusive list, normalized to registrable sites with the Public Suffix List, including private suffixes for hosted sub-sites.

## Method Notes

| Term | Meaning |
| --- | --- |
| Feed URLs checked | Every URL that the pipeline treated as a feed candidate and attempted to fetch or parse. |
| Successfully parsed feeds | RSS/Atom responses that parsed without error. JSON Feed is not counted as a feed format in this report. |
| Feeds within freshness cutoff | Parsed feeds with a usable newest-entry date or feed-level updated date within 365 days. |
| Freshness age | Computed relative to the response time for the crawl or fetch record, falling back to report generation time only if that timestamp is unavailable. |
| High-quality feeds | Parsed feeds with operational quality > 0.5. This is not an editorial score; it separates feeds that look recent and usable from abandoned, sparse, or low-metadata feeds while keeping both groups visible. Severe repeated/default-looking entry metadata can cap the score. |

## Run Summary

Parse percentages use feed URLs checked as the denominator.

| Metric | Value |
| --- | --- |
| Responses processed | 425,459,512 |
| Responses analyzed further | 418,120,515 |
| HTML pages processed | 416,036,676 |
| Unique analyzed sites | 196,598 |
| Feed URLs checked | 543,577 |
| Sniffed feeds | 232,910 (RSS 212,171; Atom 18,253) |
| Successfully parsed feeds | 534,195 |
| Broken/unparseable checks | 9,382 |
| Parse success rate | 98.3% |

## Autodiscovery

Autodiscovery coverage and link relation usage. Link relation counts include only HTML `<link>` elements with an RSS, Atom, or RDF feed XML media type; unrelated uses of `rel=alternate` are not counted. Parenthetical page percentages use HTML pages processed as the denominator. Site percentages use unique analyzed registrable sites.

| Metric | Value |
| --- | --- |
| Pages with feed links | 81,943,367 (19.70%) |
| Sites with feed links | 70,636 (35.93%) |
| Feed rel=alternate pages | 81,940,235 |
| Feed rel=feed pages | 12,796 |
| Pages using both relations | 9,664 |
| Pages with a multi-rel link | 9,546 |
| Multi-rel links | 16,977 |
| Multi-feed pages sampled | 24,317 |
| Duplicate feed variant pages | 127 |

### Duplicate Feed Format Pairs

| Coincident formats | Pages |
| --- | --- |
| rss2.0 and rss2.0 | 181 |
| atom10 and rss2.0 | 100 |
| atom10 and rss10 | 13 |
| rss10 and rss2.0 | 8 |
| atom10 and atom10 | 5 |

### Autodiscovery Usage by HTML Platform

Rows show known, conservatively detected platform hints in analyzed HTML responses. The unknown row means no recognized page-side fingerprint. Parenthetical percentages use HTML pages in that row as the denominator.

| Fingerprint | HTML pages | Pages with autodiscovery |
| --- | --- | --- |
| unknown | 353,974,158 | 53,145,055 (15.0%) |
| wordpress | 45,450,449 | 26,802,369 (59.0%) |
| drupal | 13,190,628 | 758,470 (5.8%) |
| shopify | 1,097,732 | 99,423 (9.1%) |
| joomla | 930,240 | 203,428 (21.9%) |
| substack | 490,567 | 389,821 (79.5%) |
| wix | 430,723 | 82,752 (19.2%) |
| blogger | 335,807 | 305,603 (91.0%) |
| ghost | 229,434 | 218,332 (95.2%) |
| squarespace | 20,798 | 1,017 (4.9%) |
| medium | 2,994 | 41 (1.4%) |

## Feed Availability and Freshness

Sites with feeds found counts unique registrable sites that host at least one successfully parsed feed URL.

| Stage | Count | Share |
| --- | --- | --- |
| Sites with feeds found | 13,796 | 7.02% of analyzed sites |
| Feed URLs checked | 543,577 | 100.0% of feed URLs checked |
| Parsed RSS/Atom | 534,195 | 98.3% of feed URLs checked |
| Freshness signal within cutoff | 203,483 | 37.4% of feed URLs checked |
| Active with entries | 141,380 | 26.0% of feed URLs checked |

## Formats and Quality

RSS-family feeds: 412,014. Atom feeds: 122,181. Denominator: successfully parsed feeds. Parenthetical quality percentages in the format table use feeds in that format as the denominator. The quality split is an operational filter: feeds with score > 0.5 have a usable freshness signal and enough basic entry/feed metadata to look usable, while lower-scoring feeds remain included in the all-feeds columns so abandoned or sparse feeds still affect the totals.

| Metric | Value |
| --- | --- |
| Mean operational quality, 0-1 score | 0.225 |
| Mean among feeds within freshness cutoff | 0.590 |
| Undated parsed feeds | 57,319 |
| Stale parsed feeds | 273,393 |
| Feeds with repeated entry titles | 54,426 |
| Feeds with default entry titles | 95 |
| Feeds with repeated entry links | 63,440 |

Quality percentages in the format table use feeds in that format as the denominator.

| Format | Count | Quality > 0.5 | Mean quality |
| --- | --- | --- | --- |
| rss1.0 | 2 | 2/2 (100.0%) | 0.732 |
| rss0.93 | 1 | 1/1 (100.0%) | 0.682 |
| rss | 5 | 5/5 (100.0%) | 0.622 |
| rss0.92 | 3,224 | 1,220/3,224 (37.8%) | 0.287 |
| rss2.0 | 378,287 | 92,687/378,287 (24.5%) | 0.230 |
| rss10 | 28,256 | 6,608/28,256 (23.4%) | 0.217 |
| atom10 | 122,181 | 19,940/122,181 (16.3%) | 0.209 |
| rss0.91 | 2,217 | 368/2,217 (16.6%) | 0.150 |
| rss2.00 | 18 | 1/18 (5.6%) | 0.052 |
| rss.92 | 4 | 0/4 (0.0%) | 0.000 |

## Extensions

Parenthetical percentages in the all-feeds column use successfully parsed feeds as the denominator. The quality column shows prevalence among 120,832 high-quality feeds.

| Extension | All parsed feeds | Among 120,832 high-quality feeds |
| --- | --- | --- |
| [dc](https://www.dublincore.org/specifications/dublin-core/dces/):creator | 142,073 (26.6%) | 38,730 (32.1%) |
| [content](https://web.resource.org/rss/1.0/modules/content/):encoded | 59,448 (11.1%) | 23,124 (19.1%) |
| [sy](https://web.resource.org/rss/1.0/modules/syndication/):updatePeriod | 50,606 (9.5%) | 12,441 (10.3%) |
| [sy](https://web.resource.org/rss/1.0/modules/syndication/):updateFrequency | 50,529 (9.5%) | 12,366 (10.2%) |
| [dc](https://www.dublincore.org/specifications/dublin-core/dces/):date | 45,539 (8.5%) | 13,092 (10.8%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):explicit | 30,681 (5.7%) | 14,266 (11.8%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):author | 30,286 (5.7%) | 14,124 (11.7%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):image | 29,996 (5.6%) | 14,013 (11.6%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):owner | 29,466 (5.5%) | 13,840 (11.5%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):name | 28,616 (5.4%) | 13,621 (11.3%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):category | 28,268 (5.3%) | 13,406 (11.1%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):duration | 26,876 (5.0%) | 13,165 (10.9%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):summary | 26,867 (5.0%) | 12,577 (10.4%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):email | 22,625 (4.2%) | 9,672 (8.0%) |
| [itunes](https://podcasters.apple.com/support/823-podcast-requirements):type | 22,511 (4.2%) | 10,902 (9.0%) |

## Feed History and Syndication Signals

Update cadence is inferred from the span between oldest and newest entry dates divided by entry count, when a feed has at least two dated entries. Percentages use feeds with an inferred cadence as the denominator.

| Inferred cadence within | Feeds |
| --- | --- |
| 12 hours | 18.5% |
| 1 day | 23.1% |
| 2 days | 27.8% |
| 1 week | 38.2% |
| 2 weeks | 48.3% |
| 1 month | 58.6% |
| 3 months | 73.5% |
| 1 year | 91.0% |
| All | 100.0% |

269,909 feeds lack enough dated entries to infer cadence.

Feed link relation signals are taken from feed-level Atom links, including Atom links embedded in RSS channels. Self/canonical means rel=self; hub means WebSub/PubSubHubbub discovery; paging/archive cover RFC-style feed paging and archived-feed links.

| Signal | All parsed feeds | Among 120,832 high-quality feeds |
| --- | --- | --- |
| self/canonical URL | 293,773 (55.0%) | 67,874 (56.2%) |
| paging links | 34,939 (6.5%) | 4,240 (3.5%) |
| WebSub/PubSubHubbub hub | 33,941 (6.4%) | 7,818 (6.5%) |
| archive links | 8 (0.0%) | 1 (0.0%) |

## Platform Fingerprints

Rows count known feed generators or platform headers on parsed feeds. Missing fingerprints mean not identified. Parenthetical percentages in the all-feeds column use successfully parsed feeds as the denominator. The quality column shows prevalence among 120,832 high-quality feeds. The final column shows the share of feeds in that fingerprint row that clear the quality threshold.

| Fingerprint | All parsed feeds | Among 120,832 high-quality feeds | Quality within fingerprint |
| --- | --- | --- | --- |
| unknown | 450,091 (84.3%) | 104,636 (86.6%) | 23.2% |
| wordpress | 36,821 (6.9%) | 8,142 (6.7%) | 22.1% |
| drupal | 22,830 (4.3%) | 5,722 (4.7%) | 25.1% |
| blogger | 19,954 (3.7%) | 1,177 (1.0%) | 5.9% |
| joomla | 3,988 (0.7%) | 898 (0.7%) | 22.5% |
| ghost | 237 (0.0%) | 76 (0.1%) | 32.1% |
| substack | 191 (0.0%) | 152 (0.1%) | 79.6% |
| squarespace | 46 (0.0%) | 17 (0.0%) | 37.0% |
| medium | 36 (0.0%) | 11 (0.0%) | 30.6% |
| feedburner | 1 (0.0%) | 1 (0.0%) | 100.0% |

### Autodiscovered Feed Quality by Source Platform

Quality of successfully parsed feeds found through HTML autodiscovery, grouped by recognized platform hints on the source page. The unknown row covers autodiscovered feeds whose source page had no recognized platform fingerprint. Parenthetical percentages use parsed feeds in that source-platform row as the denominator.

| Source platform | Autodiscovered parsed feeds | Quality > 0.5 | Mean quality |
| --- | --- | --- | --- |
| unknown | 72,571 | 18,912/72,571 (26.1%) | 0.247 |
| drupal | 10,721 | 2,734/10,721 (25.5%) | 0.183 |
| wordpress | 9,258 | 3,376/9,258 (36.5%) | 0.322 |
| blogger | 2,330 | 281/2,330 (12.1%) | 0.224 |
| joomla | 636 | 317/636 (49.8%) | 0.384 |
| substack | 180 | 162/180 (90.0%) | 0.768 |
| wix | 49 | 21/49 (42.9%) | 0.350 |
| ghost | 39 | 26/39 (66.7%) | 0.553 |
| shopify | 24 | 15/24 (62.5%) | 0.474 |
| squarespace | 10 | 9/10 (90.0%) | 0.732 |
| medium | 1 | 1/1 (100.0%) | 0.717 |

## Entry Content Profiles

Parenthetical percentages in the all-feeds column use successfully parsed feeds as the denominator. The quality column shows prevalence among 120,832 high-quality feeds.

| Profile | All parsed feeds | Among 120,832 high-quality feeds |
| --- | --- | --- |
| html | 210,747 (39.5%) | 58,025 (48.0%) |
| unknown | 120,849 (22.6%) | 1,401 (1.2%) |
| plain | 119,857 (22.4%) | 38,246 (31.7%) |
| mixed | 77,791 (14.6%) | 22,759 (18.8%) |
| xhtml | 4,951 (0.9%) | 401 (0.3%) |

## Languages

Language-signal counts use successfully parsed feeds as the denominator. Categories can overlap except the no-language row. Multiple entry languages means entries expose more than one language directly, or entry languages differ from the feed/HTTP language inherited by otherwise untagged entries.

| Metric | Feeds |
| --- | --- |
| No language information | 249,759 (46.8%) |
| HTTP Content-Language | 72,201 (13.5%) |
| Feed-level language | 269,430 (50.4%) |
| Entry-level language | 5,698 (1.1%) |
| Both HTTP and feed-level language | 59,294 (11.1%) |
| Mismatching HTTP and feed-level language | 6,806 (1.3%) |
| Multiple entry languages | 5,645 (1.1%) |
| Uses hreflang | 1,343 (0.3%) |

| Language | All parsed feeds | Among 120,832 high-quality feeds |
| --- | --- | --- |
| unknown | 250,463 (46.9%) | 32,683 (27.0%) |
| en | 83,341 (15.6%) | 22,163 (18.3%) |
| en-us | 77,634 (14.5%) | 25,184 (20.8%) |
| ja | 13,340 (2.5%) | 6,038 (5.0%) |
| fr | 11,981 (2.2%) | 3,488 (2.9%) |
| es | 9,764 (1.8%) | 3,208 (2.7%) |
| de | 8,528 (1.6%) | 3,051 (2.5%) |
| ru | 6,420 (1.2%) | 1,841 (1.5%) |
| fr-fr | 5,979 (1.1%) | 1,946 (1.6%) |
| en-gb | 5,843 (1.1%) | 2,214 (1.8%) |
| pt-br | 4,175 (0.8%) | 1,318 (1.1%) |
| de-de | 3,821 (0.7%) | 1,927 (1.6%) |
| pt | 2,801 (0.5%) | 795 (0.7%) |
| cs | 2,740 (0.5%) | 831 (0.7%) |
| utf-8 | 2,543 (0.5%) | 5 (0.0%) |
| it-it | 2,469 (0.5%) | 686 (0.6%) |
| ja-jp | 2,335 (0.4%) | 1,250 (1.0%) |
| zh-tw | 2,328 (0.4%) | 502 (0.4%) |
| es-es | 2,066 (0.4%) | 672 (0.6%) |
| zh-cn | 1,634 (0.3%) | 323 (0.3%) |

## Parse Errors

Error percentages, where shown in the HTML report, use total parse errors as the denominator.

| Error | Count | Error | Count |
| --- | --- | --- | --- |
| XML declaration allowed only at the start of the document | 4,258 | Blank needed here | 100 |
| EntityRef: expecting ';' | 1,137 | Not XML | 97 |
| CData section not finished | 794 | Namespace prefix owl on sameAs is not defined | 77 |
| no element found (line 0) | 364 | Start tag expected | 67 |
| xmlParseEntityRef: no name | 327 | Malformed declaration expecting version | 64 |
| Unknown root tag: div | 286 | Unknown root tag: br | 63 |
| Invalid bytes in character encoding | 188 | Namespace prefix rdf for resource on license is not defined | 52 |
| Unknown root tag: quakeml | 177 | Namespace prefix sn on type is not defined | 46 |
| Opening and ending tag mismatch: title line 4 and feed | 139 | Unknown root tag: entry | 45 |
| Extra content at the end of the document | 104 | Unknown root tag: style | 45 |
