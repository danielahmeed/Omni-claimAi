# Demo guide (3 minutes)

A script for the demo video and for live judging. Record it on the deployed Cloud Run URL with Gemini **live**, so the video shows real AI analysis.

## Before you start

- Deploy with all services (Document AI, Firestore, BigQuery; see [DEPLOYMENT.md](DEPLOYMENT.md)) so **How it works** shows them **Active**. With Firestore, data persists: if earlier test claims are there, clear the `claims`, `claims_ids` and `claims_meta` collections and the bucket's `claims/` folder, so you start from the six sample claims.
- Open **AI settings > Test connection** once. The header pill should say **Gemini live (Vertex AI)**.
- Use a 1366x768 or larger browser window. Close other tabs and notifications.
- Rehearse once. Gemini usually takes 5-25 seconds per claim; don't cut the waiting, just talk over it.

## Script

**0:00-0:20. The problem.**
"Adjusters spend days checking whether a repair bill matches the damage. Inflated bills and recycled photos cost insurers billions. OmniClaim checks the photo against the bill in seconds, with Gemini on Vertex AI, and leaves every non-trivial decision to a human."

**0:20-1:10. Inflated bill (live).**
1. Click **New claim > Inflated repair bill**. Point out that a real photo and a real invoice are attached.
2. Click **Analyze claim**. While it runs: "Document AI reads every line of the invoice. Gemini then gets the photo, the invoice, those lines and the policy wording, and must answer in a fixed JSON schema."
3. On the result:
   - **Photo & findings**: the damage box Gemini drew on the scrape.
   - **Bill line items**: suspension, exhaust and frame lines disallowed, each with a reason.
   - **Decision & letter**: $750 recommended instead of $7,950, and a letter that explains it.
4. "The money and the routing are plain code. Gemini provides the evidence, and the numbers always add up."

**1:10-1:50. Reused photo (live).**
1. Click **New claim > Reused photo > Analyze claim**.
2. Show the critical finding: **Photo already used in another claim**, matching CLM-8977 and CLM-9104. "This is a perceptual-hash search over every earlier claim. It survives resizing and re-compression."
3. Show Gemini's finding that the photo is an old economy hatchback, not the 2024 BMW M4 on the invoice. Point out the policy that started 5 days earlier.
4. Status: **SIU referral**, payment on hold. Show the letter: neutral wording, no tip-off.

**1:50-2:20. Fast lane (live).**
- Click **New claim > Burst pipe (home) > Analyze claim**. It comes back **Auto-approved** with a $2,950 payment.
- "Clean, fully supported claims are paid in seconds. Only claims where every billed line is supported and the risk is low qualify."

**2:20-2:45. Copilot.**
Open **Copilot** on the inflated-bill claim, ask "Which billed lines are not supported by the photo?" and show the answer, grounded in the claim file.

**2:45-3:00. Under the hood.**
Open **How it works**. Gemini on Vertex AI, Document AI, Firestore, BigQuery and Cloud Run are **Active**, and the roadmap items are labeled as roadmap. Close with: "Six Google Cloud services working together, each with a safe fallback; open source with 90 automated tests."

## Questions judges may ask

| Question | Answer |
| --- | --- |
| Is the AI real? | Yes. The analysis log shows the Gemini step with its timing, and the claim header says "Analyzed by Gemini gemini-3.8-flash via Vertex AI". Sample claims are clearly labeled as pre-recorded. |
| How do you stop the model from hallucinating amounts? | Gemini must answer in a strict JSON schema and copy line items exactly. Amounts are validated and capped in code, and every payment is computed in code from the line items. |
| What if Gemini is down? | The claim is still checked (photo reuse, metadata, policy, cost) and goes to an adjuster with a visible notice. A claim whose Gemini call failed is never auto-approved. |
| How does the reused-photo check work? | A 64-bit difference hash of each photo. Two photos whose hashes differ by at most 6 bits count as the same, even after resizing or re-saving. |
| Where do the benchmark numbers come from? | A synthetic 10,000-claim dataset, queried in BigQuery when configured or computed locally otherwise. It stands in for an insurer's claims history. |
| Why both Document AI and Gemini? | Reading and judging are different jobs. The Document AI Invoice Parser reliably extracts every line, amount and invoice number, including from scanned PDFs. Gemini then decides whether the photo supports each line and how the policy applies. If Document AI is unavailable, Gemini reads the bill itself. |
| What happens to the data? | Claims are stored in Firestore and photos and bills in a Cloud Storage bucket. Data survives redeploys, and claim numbers stay unique across instances. |
| Is it secure? | No API keys in the repo or the container: the service account calls Vertex AI. The server serves an allowlist of files, escapes all output, rate-limits AI calls and runs as non-root. See docs/SECURITY.md. |

## Running the demo without Gemini

Without credentials, the four presets replay recorded results for the bundled sample files, labeled "Recorded demo result". The photo reuse, metadata, policy and cost checks still run live. Use this only as a fallback; the video should show Gemini live.
