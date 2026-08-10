# C05R bounded modern-alternative settlement

Status: **Lin replaces Mill for v1, pre-freeze only.** This is a source decision, not gold and not a source freeze.

The search was deliberately limited to three real modern single-source candidates and the reconciled baseline, Mill's *Utilitarianism*, Chapter II, Project Gutenberg #11224. No slot redesign was attempted.

| Candidate | Objection/reply structure | Machine-readable full text | Authority and provenance | Rights | R13 | Settlement |
|---|---|---|---|---|---|---|
| John Stuart Mill, *Utilitarianism*, Chapter II, PG #11224 | Dense sequence of stated objections and replies | Clean UTF-8 | Canonical primary work; stable PG record | Public domain in the US | Expected to pass | Strong baseline, but adds a fourth older-English core source alongside James, Woolf, and Darwin |
| Yao Lin, “Philosophy as a Normative Discipline,” *Philosophy* (2026), DOI `10.1017/S0031819126101430` | Section 3 names and answers the “Professional View Objection” and “Boundary Policing Objection” | Complete publisher PDF acquired | Peer-reviewed primary philosophical argument, Cambridge University Press | CC BY 4.0 | **Pass:** 24 pages, 66,983 extractable characters, 19,132 estimated tokens, 20/20 exact spans | **Selected** |
| Michael Vollmer, “In defence of object-given reasons,” *Philosophical Studies* (2024), DOI `10.1007/s11098-024-02109-7` | Multiple explicit challenges and replies | Full Springer HTML/PDF located | Peer-reviewed primary philosophical argument | CC BY 4.0 | Not run because Lin already cleared the bounded comparison | Viable reserve |
| Rima Basu, “Bullshit philosophy,” *Synthese* (2025), DOI `10.1007/s11229-025-05198-x` | Four explicit objections and replies | Publisher full text exists, but local automated retrieval returned a challenge document | Peer-reviewed primary philosophical argument | CC BY 4.0 | Not run on a real article file | Viable only after clean acquisition |

Lin is materially better overall than Mill for this suite: it preserves the exact intra-source voice-attribution behavior, has unusually explicit named objection/reply structure, is recent scholarly primary prose, is legally practical, and has already passed the production-parser R13 gate. Mill remains the documented reconciled baseline, not a rejected historical mistake.

The selected Research Brief is pinned in `pinned-case-configs.json`. No expected answer or gold atom is defined here.
