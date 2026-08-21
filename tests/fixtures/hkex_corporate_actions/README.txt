Static fixtures: HKEX Next Day Disclosure Return text snapshots

Provenance
----------
Both fixtures are text snapshots of OFFICIAL Tencent Next Day Disclosure
Return PDFs published on HKEXnews (public exchange disclosure feed).  The text
was extracted once with pdfplumber (per-page extract_text, page breaks kept
as blank lines, footers preserved) and committed as-is; no values were edited.

- ndd_tencent_ff305_20250613.txt
  Source: HKEXnews NEWS_ID 11713183, file 2025061300897.pdf
          (listedco/listconews/sehk/2025/0613/2025061300897.pdf)
  Form: FF305 v1.3.0 - Next Day Disclosure Return (equity issuer - changes
  in issued shares or treasury shares, share buybacks and/or on-market sales
  of treasury shares); submitted 13 June 2025 by Tencent Holdings Limited.

- ndd_tencent_ff304_20240118.txt
  Source: HKEXnews file 2024011800507.pdf
          (listedco/listconews/sehk/2024/0118/2024011800507.pdf)
  Form: FF304 v1.2.5 - Next Day Disclosure Return (equity issuer - changes
  in issued share capital and/or share buybacks); submitted 18 January 2024
  by Tencent Holdings Limited.

The fixture text intentionally includes the raw extraction artifacts (joined
table cells such as "1,017,000On the Exchange", "Page 1 of 8 v1.3.0" footers)
because the parser must tolerate exactly those.

These files are offline test fixtures only; they are not the collector's
runtime input and carry no price-affecting signal by themselves.
