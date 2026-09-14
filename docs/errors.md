# Error Matrix

> **Status: seeded early. This is a Phase 2 deliverable, not a Phase 1 one.**
>
> `PERSON_B_PLAN_v2.md` §5 Phase 2.4 schedules `docs/errors.md` for Weeks 5–7 and requires
> that every case listed here be tested with a forced failure before Phase 2 closes.
> It is written now, during Phase 0/1, because the ten error **codes** are part of the API
> contract that Phase 1 freezes — the codes have to be decided before the routes are written,
> or they get invented ad-hoc at three different call sites.
>
> **What is true today (Phase 1):** the codes below are the authoritative list, and the API
> returns the envelope in §1. **What is not true yet:** the Khmer and English strings are not
> yet in `web/messages/en.json` / `km.json` under `errors.*` — Phase 1's i18n key set stops at
> `common.error.generic`, a single generic fallback. Phase 2.4 adds the per-code keys and wires
> each screen to them. Until then the UI shows `common.error.generic` for every failure.
> **Nothing here has been tested against a forced failure yet.**

---

## 1. The envelope

Every error response from the API, at every status code, has exactly this shape. There is no
second error format anywhere in the system.

```json
{
  "error": {
    "code": "RESUME_TOO_LARGE",
    "message": "Resume exceeds the 5 MB limit.",
    "error_id": "err_01J9Z8K3QW"
  }
}
```

| Field | Type | Purpose |
|---|---|---|
| `code` | `str` | One of the ten values in §2. **This is what the UI switches on** — never parse `message`. |
| `message` | `str` | English, developer-facing. Goes in logs and in the Render dashboard. **Never rendered to the user.** |
| `error_id` | `str` | Unique per occurrence. Shown to the user on unrecoverable errors with a copy button, and logged server-side, so a user can report an error the team can actually find. |

The user-facing string is **never** `error.message`. The UI looks up `code` in the message
catalogue and renders the localized string from §2. A server message can leak a stack trace, a
file path, or an upstream provider's wording; a catalogue string cannot.

### One important exception: a failed analysis is an HTTP 200

`POST /api/analyses` returns `202` and the work happens in a `BackgroundTasks` job. When that
job fails, the failure is not an HTTP error on any request — it is state. `GET /api/analyses/{id}`
returns **HTTP 200** with:

```json
{
  "analysis_id": "an_...",
  "status": "failed",
  "stage": null,
  "match": null,
  "baseline": null,
  "error": { "code": "ENGINE_FAILED", "message": "...", "error_id": "err_..." }
}
```

The polling client must therefore check `status === "failed"` on a 200 response, not just catch
HTTP errors. `ENGINE_FAILED`, `RATE_LIMITED`, and `RESUME_UNREADABLE` can all arrive this way
when they happen after the job is queued. The "HTTP status" column below gives the status for
the *synchronous* request that raises the code; where the code can also surface inside a polled
`failed` analysis, the Trigger column says so.

---

## 2. The matrix

Khmer strings marked **provisional** — see §4.

### `RESUME_BAD_TYPE` — 415 Unsupported Media Type

| | |
|---|---|
| **Trigger** | `POST /api/resumes` receives a file whose extension or sniffed content type is not PDF or DOCX. Caught client-side first by the dropzone's `accept` filter; the server re-checks because a client check is not a security boundary. |
| **English** | This file type isn't supported. Please upload a PDF or DOCX file. |
| **Khmer** | ប្រភេទឯកសារនេះមិនអាចប្រើបានទេ។ សូមផ្ទុកឡើងជា PDF ឬ DOCX។ |
| **Recovery** | Inline error under the dropzone; the dropzone stays open and armed. No page reload. User picks a different file. |
| **i18n key** | `analyze.resume.errorType` *(this one key exists in the Phase 1 catalogue)* |

### `RESUME_TOO_LARGE` — 413 Content Too Large

| | |
|---|---|
| **Trigger** | `POST /api/resumes` receives a file over 5 MB. Client-side size check runs first so the user does not wait for a 5 MB upload to be rejected at the end of it. |
| **English** | This file is larger than 5 MB. Try exporting your resume again at a smaller size. |
| **Khmer** | ឯកសាររបស់អ្នកធំជាង 5 MB។ សូមនាំចេញប្រវត្តិរូបរបស់អ្នកម្តងទៀតជាទំហំតូចជាងនេះ។ |
| **Recovery** | Inline error under the dropzone. Suggest re-exporting rather than "compress it" — an entry-level resume is over 5 MB only when it embeds full-resolution images, and re-exporting from Word or Google Docs fixes that. |
| **i18n key** | `analyze.resume.errorSize` *(exists in the Phase 1 catalogue)* |

### `RESUME_UNREADABLE` — 422 Unprocessable Content

| | |
|---|---|
| **Trigger** | The file is a valid PDF or DOCX but no usable text can be extracted. In practice this is almost always a **scanned-image PDF** — a photographed or scanned paper resume with no text layer. Also fires on encrypted/password-protected PDFs and on files whose extracted text is under a minimum character count. **Can also surface inside a polled `failed` analysis** if extraction is deferred to the background job. |
| **English** | We couldn't read any text in this file. If it's a scan or a photo, upload a version where the text can be selected — export to PDF from Word or Google Docs. |
| **Khmer** | យើងមិនអាចអានអត្ថបទក្នុងឯកសារនេះបានទេ។ បើវាជារូបភាពស្កេន សូមផ្ទុកឡើងឯកសារដែលអាចជ្រើសរើសអត្ថបទបាន — នាំចេញជា PDF ពី Word ឬ Google Docs។ |
| **Recovery** | Inline error under the dropzone. The message must name the actual cause; "unreadable file" alone leaves the user re-uploading the same scan. This is the highest-frequency real failure for this user population and deserves the longest message in the catalogue. |
| **i18n key** | `errors.RESUME_UNREADABLE` *(Phase 2)* |

### `JOB_EMPTY` — 422 Unprocessable Content

| | |
|---|---|
| **Trigger** | `POST /api/jobs` receives `{"text": ""}` or whitespace only, receives neither `text` nor `url`, or receives both (the contract is XOR). Also fires when a fetched URL yields a page with no extractable job body. |
| **English** | We need the job post itself. Paste the job description text, or a link to it. |
| **Khmer** | យើងត្រូវការខ្លឹមសារការងារ។ សូមបិទភ្ជាប់អត្ថបទការងារ ឬតំណភ្ជាប់ទៅកាន់វា។ |
| **Recovery** | Inline error under the JD tabs; focus moves to the active tab's input. Submit stays disabled until both inputs are present anyway, so this fires mainly on whitespace-only pastes and on a URL that fetched an empty page. |
| **i18n key** | `errors.JOB_EMPTY` *(Phase 2)* |

### `JOB_URL_BLOCKED` — 422 Unprocessable Content

| | |
|---|---|
| **Trigger** | The submitted URL's host is on the blocklist — `linkedin.com` and `facebook.com` and their subdomains. **This is a deliberate refusal, not a failure.** `PROJECT_SPEC.md` §9 rule 6: never scrape Facebook or LinkedIn — login walls, anti-bot measures, and a ToS violation. A client-side domain check shows this message *before* the request is sent (plan §5 Phase 3.1); the server enforces it as well. |
| **English** | We can't open LinkedIn or Facebook links. Copy the job description text and paste it here instead — that works exactly the same. |
| **Khmer** | យើងមិនអាចបើកតំណពី LinkedIn ឬ Facebook បានទេ។ សូមចម្លងអត្ថបទការងារ រួចបិទភ្ជាប់នៅទីនេះជំនួសវិញ — លទ្ធផលដូចគ្នា។ |
| **Recovery** | Show inline **and** switch the JD tab to `Paste text` with focus in the textarea, so the recovery action is already done for the user. The "that works exactly the same" clause matters: without it the user believes a feature is broken rather than that a path is closed. |
| **i18n key** | `errors.JOB_URL_BLOCKED` *(Phase 2)* |

### `JOB_FETCH_FAILED` — 502 Bad Gateway

| | |
|---|---|
| **Trigger** | The URL is allowed but could not be turned into a job post: DNS failure, connection timeout, non-2xx response, a login wall on an allowed domain, a robots.txt disallow, or a page whose main content could not be extracted. 502 rather than 400 because the fault is upstream, not in the user's request. |
| **English** | We couldn't open that link. Copy the job description text and paste it here instead. |
| **Khmer** | យើងមិនអាចបើកតំណនោះបានទេ។ សូមចម្លងអត្ថបទការងារ រួចបិទភ្ជាប់នៅទីនេះជំនួសវិញ។ |
| **Recovery** | Same as `JOB_URL_BLOCKED`: switch to the `Paste text` tab with focus in the textarea. Deliberately does **not** offer a retry button — a page behind a login wall will not be there on the second attempt either, and a retry that always fails is worse than no retry. |
| **i18n key** | `errors.JOB_FETCH_FAILED` *(Phase 2)* |

### `ANALYSIS_NOT_FOUND` — 404 Not Found

| | |
|---|---|
| **Trigger** | `GET /api/analyses/{id}` for an id that does not exist. In Phase 1 this is common and expected: the mock store is **in-memory** (`api/store.py`), so every API restart — including every Render cold start after a sleep — drops all analyses. A bookmarked or shared results URL will 404. |
| **English** | We couldn't find this analysis. Results aren't saved permanently yet — start a new analysis to see fresh results. |
| **Khmer** | យើងរកមិនឃើញការវិភាគនេះទេ។ លទ្ធផលមិនត្រូវបានរក្សាទុករយៈពេលយូរនៅឡើយទេ — សូមចាប់ផ្តើមការវិភាគថ្មី។ |
| **Recovery** | Full-page state on `/[locale]/results/[id]`, not a toast — the page has nothing else to show. Primary action returns to `/[locale]/analyze`. **Revisit this string when Supabase persistence lands at CP2 (Phase 2.5):** "aren't saved permanently yet" becomes wrong once matches are persisted, and the message becomes a plain "this link has expired or never existed." |
| **i18n key** | `errors.ANALYSIS_NOT_FOUND` *(Phase 2)* |

### `ENGINE_FAILED` — 500 Internal Server Error *(usually delivered as `status: "failed"` on a 200)*

| | |
|---|---|
| **Trigger** | The background analysis job raised. Covers an LLM returning unparseable JSON after its retry, a Pydantic `ValidationError` when the engine output violates the schema's traceability or scope-inflation rules, an engine exception, or a worker OOM on Render's 512 MB free instance. **Normally reaches the user through `GET /api/analyses/{id}` with `status: "failed"` at HTTP 200**, since the failure happens after `202 Accepted`. |
| **English** | The analysis didn't finish. Try again — if it keeps failing, send us this error id. |
| **Khmer** | ការវិភាគមិនបានបញ្ចប់ទេ។ សូមព្យាយាមម្តងទៀត — បើនៅតែបរាជ័យ សូមផ្ញើលេខសម្គាល់កំហុសនេះមកយើង។ |
| **Recovery** | Replace the progress stepper with an error card carrying a **Retry** button (re-POSTs `/api/analyses` with the same `resume_id` and `job_id`, so the user does not re-upload) and the `error_id` with a **Copy** button. Retry is safe here: the inputs are already stored and the failure is usually transient. |
| **i18n key** | `errors.ENGINE_FAILED` *(Phase 2)*; buttons reuse `common.action.retry` and `common.action.copy` |

### `RATE_LIMITED` — 429 Too Many Requests

| | |
|---|---|
| **Trigger** | Two distinct sources, one code. (a) The Anthropic API returns 429 to our engine — the likely case, and the one that will bite during a demo if several people run analyses at once. (b) Our own per-client throttle rejects a request. **Can arrive synchronously on any POST, or inside a polled `failed` analysis** when (a) happens mid-job. |
| **English** | Too many requests right now. Wait about a minute and try again. |
| **Khmer** | មានសំណើច្រើនពេកនៅពេលនេះ។ សូមរង់ចាំប្រហែលមួយនាទី រួចព្យាយាមម្តងទៀត។ |
| **Recovery** | Retry button, disabled for 60 s with a visible countdown so the user is not invited to hammer a limit that is already exceeded. Honour a `Retry-After` header when the upstream sends one. |
| **i18n key** | `errors.RATE_LIMITED` *(Phase 2)* |

### `INTERNAL` — 500 Internal Server Error

| | |
|---|---|
| **Trigger** | The catch-all. Any unhandled exception in the API that is not one of the nine codes above. If this code appears in production logs it means a case is missing from this table — **treat every `INTERNAL` as a bug report against this document**, and either add a specific code or fix the cause. |
| **English** | Something went wrong on our side. Try again — if it keeps happening, send us this error id. |
| **Khmer** | មានបញ្ហាមួយកើតឡើងនៅខាងយើង។ សូមព្យាយាមម្តងទៀត — បើនៅតែកើតឡើង សូមផ្ញើលេខសម្គាល់កំហុសនេះមកយើង។ |
| **Recovery** | Error card with Retry and a copyable `error_id`. Never renders a stack trace or the server `message` field. |
| **i18n key** | `errors.INTERNAL` *(Phase 2)*, and `common.error.generic` is this string — it is the fallback the UI uses for any code it does not recognise. |

---

## 3. Not an error code: the client-side analysis timeout

Plan §5 Phase 2.3 requires a 120-second ceiling on polling. This is **not** a server error code —
the server may still be working — so it has its own i18n keys, which **do** exist in the Phase 1
catalogue:

| | |
|---|---|
| **Trigger** | `GET /api/analyses/{id}` has been polled every 2 s for 120 s and `status` is still `queued` or `running`. |
| **English** | This is taking longer than usual. |
| **Khmer** | ការវិភាគនេះប្រើពេលយូរជាងធម្មតា។ |
| **Action label (en)** | Keep waiting |
| **Action label (km)** | បន្តរង់ចាំ |
| **Recovery** | Do **not** discard the analysis — offer to keep polling. The most likely cause on the free tier is a Render cold start (30–60 s to wake) stacked on a slow LLM call, and the result usually does arrive. |
| **i18n keys** | `progress.timeout`, `progress.timeoutAction` |

---

## 4. Provenance and open items

**The Khmer strings in this file are provisional and were not written by a Khmer
first-language speaker.** They are placed here so that the Phase 2 implementation has
something concrete to review and correct rather than an empty column. `BRAND.md` §2 check 9
and plan §5 Phase 5.1 (the 45-minute Khmer QA session with two Khmer-first classmates who are
not on the team) are where they get confirmed or replaced. Error messages are read by users
who are already frustrated, so an awkward machine-translated error does more damage than an
awkward machine-translated label — review these first in that session, ahead of the UI chrome.

### Phase 2 checklist, none of it done yet

- [ ] Add `errors.*` keys for all ten codes to `web/messages/en.json` and `web/messages/km.json`.
- [ ] Add a typed `ApiError` in `web/lib/api.ts` that surfaces `code` to callers.
- [ ] Map every code to a UI presentation: inline under a field, full-page state, or error card.
- [ ] **Force each of the ten failures deliberately and screenshot both locales.** Plan §5
      Phase 2.4 requires this; it is what makes this table evidence rather than intention.
      Suggested forcing methods: upload a `.txt` renamed to `.pdf` (`RESUME_BAD_TYPE`), a
      photographed resume (`RESUME_UNREADABLE`), a LinkedIn job URL (`JOB_URL_BLOCKED`), a URL
      on a domain that does not resolve (`JOB_FETCH_FAILED`), a hand-edited analysis id
      (`ANALYSIS_NOT_FOUND`), and a temporary `raise` inside the background task (`ENGINE_FAILED`).
- [ ] Re-word `ANALYSIS_NOT_FOUND` after Supabase persistence lands at CP2.
- [ ] Confirm every message obeys the `BRAND.md` §6 voice rules — no blame, no jargon, and a
      concrete next action in every single one.

---

*Seeded 10 Sep 2026 during Phase 0/1 · Completed in Phase 2 (Weeks 5–7) · Owner: Person B*
