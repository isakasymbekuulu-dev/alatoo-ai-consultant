# Narration script — AlaToo GPT defense (EN)

> ~10 minutes. Read naturally, one block per slide. Also usable as a NotebookLM source or voiceover script.

## 1. Title / Титул

Good afternoon. My name is Isa. Today I'll tell you the story of AlaToo GPT — an AI academic advisor that helps applicants choose the right program. It's not just a tool; it's a project that started two years ago and grew up with the technology around it.

## 2. 2024 — how it started

Our story starts in 2024. Every admission season the admissions office heard the same question hundreds of times: 'I don't know what to study, what fits me?'. Staff simply could not answer everyone in depth. That gap is where the project was born.

## 3. Problem

The problem has three faces. First, applicants are uncertain — they don't know their own strengths. Second, the wrong choice leads to constant transfers between faculties. Third, the long-term cost: graduates who don't work in their field at all. One weak decision at 17 echoes for years.

## 4. The idea

The idea has two pillars. One: know the student — a career-interest test that builds a personal profile. Two: know the university — an AI consultant that answers factual questions from real university data. Personal plus factual. That combination is the heart of AlaToo GPT.

## 5. 2024 prototype

We did try it in 2024. A first prototype, used during the real admission campaign. But it was limited: testing happened only inside chat, the test itself was a basic Klimov version, the AI had subscription limits, and — most importantly — adoption was low. Back then AI still felt alien to many people, especially to adults. The idea was right; the timing and the tech were not ready yet.

## 6. Turning point

Then time did its work. By 2026 AI is everywhere — in phones, in search, at work. The barrier that blocked us in 2024 — unfamiliarity — is simply gone. People now expect an AI assistant. The technology matured and the limits dropped. So we rebuilt the project properly. This is where the new system begins.

## 7. Goal & objectives

Formally, the goal is to design an AI advising system that guides students to informed decisions. The objectives: identify the decision problem, justify the RIASEC model, design a two-entry system — test and chat, describe the RAG architecture, orchestrate everything with one dialog graph, and compare against the 2024 prototype. These objectives structure the whole work.

## 8. Architecture

Here is how it works. All channels — web, Telegram, WhatsApp, social media — are thin adapters that talk to one API. The API hands the request to a single dialog graph built with LangGraph: a router decides the intent and sends it to the RAG, RIASEC or general node. Knowledge lives in Qdrant; logs, test results and traces live in SQLite. One brain, many doors.

## 9. RIASEC test

The first feature is the career test. It's based on Holland's RIASEC model — six interest types. Sixty questions, adapted from the O*NET profiler, in three languages. The result is a Holland code, like SAE, mapped to concrete Ala-Too programs, and the applicant can download it as a PDF. Here I'll show the live results page.

## 10. AI consultant (RAG)

The second feature is the consultant itself. It answers real questions — programs, admission, tuition — but always grounded in the university's own materials through RAG, so it doesn't invent facts. It streams the answer and cites sources. And if the person took the test, it remembers their profile and gives personal advice. Live demo here.

## 11. LangGraph brain

Under the hood, the dialog is orchestrated by a LangGraph graph. A router classifies each message and routes it to the right node. Every step is recorded as a trace, so we can explain exactly why the system answered the way it did — and easily add new branches later. This is the engineering core of the thesis.

## 12. Control & analytics

And we don't run it blindly. A web dashboard lets us see and steer everything: the routing trace of each dialog, which intents dominate, which Holland codes are most common, and how many people move from the test into a consultation. The system is transparent and measurable.

## 13. Tech stack

The stack is modern and production-oriented: Python and FastAPI for the backend, LangGraph for orchestration, LangChain for preparing the knowledge base, Qdrant as the vector database, multilingual BGE-M3 embeddings, all shipped in Docker on a VPS. Every piece earns its place.

## 14. Results vs 2024

Compared to the 2024 prototype, the difference is night and day. The test went from a basic chat-only Klimov to a real RIASEC instrument. The answers are now grounded in a knowledge base instead of pure LLM guesses. Three languages instead of one. A real orchestration layer. And full analytics where before there was none.

## 15. Try it (QR)

And this isn't a mock-up — it's live right now. You can scan these codes and try it yourself: the consultant on the left, the career test on the right. Real system, real URL.

## 16. Future development

Where do we go next? First, bring the same brain to social-media bots — Telegram, WhatsApp, Instagram. Second, move to a local, on-premise LLM for full independence and data security. Third — and this one keeps the project alive — convenient manual and automatic data updates, so it doesn't go stale in a year. And finally, extend it beyond applicants: features for students, teachers and administration. This is how a project survives and grows.

## 17. Conclusion

To conclude: AlaToo GPT turns a stressful, lonely choice into a guided conversation — personal because of the test, factual because of RAG, and this time at the right moment in technology. The idea from 2024 is now a working, explainable, measurable system. Thank you.

## 18. Thank you

Thank you for your attention. I'm happy to take your questions — and you can try the system yourself right now via this code.
