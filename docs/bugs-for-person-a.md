# B6 go-live: bugs and findings for Person A

Found while switching `/documents` and `/query` off mock mode (2026-10-10).
Setup: `RELIRAG_Network_Security_Benchmark.pdf` ingested as document 8 (41 pages, 80 chunks),
`SIMILARITY_GATE` unset (default 0.30), `CLAUDE_MODEL=claude-sonnet-4-5`.

## 1. Answers contain Markdown, shown as literal `**` in the UI

- **Question:** `What is the main difference between TCP and UDP?` (`document_ids: [8]`)
- **Request:** `POST /query` → `query_id: 7`, `status: ANSWERED`, `citations: [1]`
- **Response `final_answer` (exact):**

  ```
  The main difference between TCP and UDP is that **TCP provides a reliable, ordered byte stream using connection establishment, sequence numbers, acknowledgements, retransmission, and flow control**, while **UDP sends independent datagrams without built-in delivery guarantees or ordering** [1].
  ```

- **Expected:** plain text (the answer card renders text, not Markdown).
- **Suggested fix:** add "Answer in plain text without Markdown formatting" to `SYSTEM_PROMPT` in
  `backend/app/services/generator.py`. Content and citation are otherwise correct.

## 2. Similarity gate cannot reject on-topic out-of-scope questions

`python backend/calibrate_gate.py --questions <benchmark covered + out_of_scope> --doc-ids 8`
(no Claude calls) gives:

| question | category | top-1 similarity |
|---|---|---|
| Which firewall rule is currently blocking my laptop? | out_of_scope | 0.5538 |
| What is the current password for my university Wi-Fi? | out_of_scope | 0.5144 |
| Did my network have an outage yesterday at 3 PM? | out_of_scope | 0.3874 |
| What is the exact IP address of my college router? | out_of_scope | 0.3477 |
| Who won yesterday's cricket match? | out_of_scope | 0.1910 |
| What is the difference between authentication and authorization? | covered (lowest) | 0.4317 |

- Lowest covered score 0.4317 < highest out-of-scope 0.5538: **no gate value separates them**.
- At 0.30, all 13 covered questions pass and only the cricket question is blocked by the gate.
- Q17–Q20 therefore reach Claude and depend on the generator's `INSUFFICIENT_EVIDENCE` refusal.
  This path was **not verified** during go-live; please run Q17–Q20 through `POST /query` and
  confirm they come back `INSUFFICIENT_EVIDENCE`.
- The A6 placeholder suggestion (0.19, from `test.pdf`) is not valid for this document; keep 0.30
  or recalibrate.

## 3. Chunk text includes the PDF page header

Every retrieved chunk starts with the page header, e.g.
`RELI-RAG Benchmark Reference • Demo dataset Page 4 03. TCP and UDP ...`.
It's shown in the Evidence Explorer and is embedded with the content. Low priority; consider
stripping repeated headers/footers in `extract_pages()`.

## 4. Minor API contract notes (no action needed for go-live)

- `POST /documents/upload` returns no `uploaded_at` (`GET /documents` does). The frontend
  uses the client time for the new row until the list is reloaded.
- `POST /query` is one request, so the UI's "Retrieving…" / "Generating…" stages are
  time-based (switches after 800 ms), not reported by the backend.
