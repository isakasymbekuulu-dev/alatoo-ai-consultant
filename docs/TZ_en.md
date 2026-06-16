# 1. General Information

## 1.1 System name
AI academic advisor "AlaToo GPT" — a conversational system that combines a RIASEC career-interest test and an online consultation over the university knowledge base (RAG).

## 1.2 Purpose
Automate first-line career guidance and reference consultation for applicants and students: help them identify a suitable program and answer questions about programs, admission, faculties, and tuition, grounded in real university materials.

## 1.3 Goals
The system reduces the load on the admissions office by automating typical questions, increases the quality of program choice through the RIASEC test and personalized recommendations, gives university management analytics on applicant interests, and provides multi-channel access (web, messengers) to a single logic.

## 1.4 Scope
University admission campaign, career guidance for school leavers and applicants, information support for students.

# 2. Terms and Abbreviations

RIASEC — J. Holland's model of vocational interests: Realistic, Investigative, Artistic, Social, Enterprising, Conventional. RAG — Retrieval-Augmented Generation, generating an LLM answer grounded in retrieved knowledge-base fragments. LLM — large language model. Embedding — a vector representation of text for semantic search. LangChain — a library for loaders, splitters, prompts and LLM/embedder integration. LangGraph — a library for dialog orchestration as a state graph (nodes and conditional edges). Qdrant — a vector database. Ingestion — the data preparation pipeline: scrape, clean, chunk, metadata, upsert. Holland code — the user's top-3 interest types (e.g., "SAE").

# 3. System Description

The system is a single backend (FastAPI) on top of one dialog graph (LangGraph), to which thin channel adapters connect. The graph routes the user between two branches. The first is career guidance (RIASEC): 60 items (an adaptation of the O*NET Interest Profiler Short Form), a 1-5 Likert scale, scoring across six types, a Holland code, and a mapping of the profile to the university's bachelor programs. The second is online consultation (RAG): answers to questions over the university knowledge base (website plus local PDF/DOCX), grounded in real content, with sources. Test results are attached to the chat session and injected into the LLM context to personalize the consultation.

# 4. Target Architecture

Channels (OpenWebUI, web chat, Telegram, WhatsApp via Twilio, Instagram/Facebook via Meta) connect through a single REST API (FastAPI) to the LangGraph dialog graph (router followed by the riasec, rag, and general nodes). The graph uses Qdrant for vector retrieval and SQLite for logs and test results. A web admin panel exposes dialogs, RIASEC results, graph traces, and analytics. The key principle: channels are thin adapters; all logic lives in one graph and one API.

# 5. Functional Requirements

## 5.1 Career test (RIASEC) — IMPLEMENTED
The system delivers 60 test items in three languages (ru/ky/en); requires the applicant's full name before starting; collects answers on a 1-5 scale and guards against skipped questions; scores six types, computes expressiveness percentages and the Holland code; maps the profile to the university's bachelor programs (top-6 by congruence, weights 3/2/1); shows a results screen (code, six-type bars, leading-type descriptions, recommended programs); exports results to PDF with labels in the selected language; records consent; saves the result to the database immediately on submit, regardless of moving to chat; and offers a "Discuss with the AI consultant" hand-off that auto-starts the conversation.

## 5.2 Online consultation (RAG) — IMPLEMENTED (baseline)
The system accepts a user question through a single API and streams the answer (SSE); performs semantic search of relevant fragments in Qdrant and grounds the LLM answer in them; injects the RIASEC profile (if present) into the context; cites sources where applicable; and, when the user does not know where to apply, offers to take the test via a /test link.

## 5.3 Orchestration (LangGraph) — TO IMPLEMENT
A single state graph with nodes router (intent classification), riasec_node, rag_node, and general_node; conditional transitions based on intent and the presence of a RIASEC profile; preserved streaming of the LLM answer; and logging of each request's route (which nodes ran and in what order) for analytics and debugging.

## 5.4 Knowledge preparation (LangChain ingestion) — TO IMPLEMENT/REFINE
scrape: university website pages (Bright Data) to markdown, local PDF/DOCX to text; clean: extract main text, fix broken characters, deduplicate; chunk: recursive splitting by markdown headings with overlap (LangChain text-splitters); metadata: per chunk — source_url, title, faculty, program, doc_type, lang, updated_at; upsert: batch upload to Qdrant with payload and filter indexes.

## 5.5 Channels — STAGED
OpenWebUI / own web chat (web chat implemented); a Telegram bot (python-telegram-bot) as an adapter to the single API; WhatsApp via Twilio with webhooks; Instagram/Facebook via the Meta Graph API with webhooks.

## 5.6 Web management and analytics (admin) — PARTIAL/TO EXTEND
A list of dialogs (sessions) with channel, message count, time, first question; viewing a full session transcript; viewing RIASEC results (full name, code, percentages, recommended programs); a visualization of the LangGraph graph (nodes and transitions); a routing trace per dialog (which intent the router chose, which nodes the request passed through, which RAG fragments were used); analytics (intent distribution, popular topics, Holland-code distribution, test-to-consultation conversion); and token-protected access.

# 6. Non-functional Requirements

Languages: interface and content in Russian, Kyrgyz, and English. Performance: the first token of a RAG answer within a few seconds under typical load; instant test scoring. Privacy: anonymized transcripts; web-chat history is not shown to other users (session storage); consent is recorded. Security: rate limiting on public endpoints; admin behind a token; no requests for passwords or payment data. Reliability: channel and LLM errors do not crash the system; graceful degradation with a clear user message. Maintainability: single logic in the graph; decisions recorded as ADRs; key logic covered by tests. Deployment: Docker Compose (qdrant plus backend and optional openwebui); deployment to a VPS/droplet.

# 7. Technology Stack

Python; FastAPI (Uvicorn) for the web API; LangGraph for dialog orchestration (StateGraph: router to riasec/rag/general); LangChain for the LLM/knowledge wrapper (loaders, text-splitters, messages/prompts); Qdrant as the vector database (in Docker); BAAI/bge-m3 as the multilingual embedder; an OpenAI-compatible LLM; SQLite for logs and results; an own web chat and test page plus optional OpenWebUI; Bright Data for knowledge scraping; Twilio (WhatsApp), python-telegram-bot (Telegram), and the Meta Graph API for channels; Docker Compose and a DigitalOcean droplet for deployment. Note: Qdrant, LangChain and LangGraph are pip libraries installed into the project environment.

# 8. Data and Storage

SQLite holds: messages(id, ts, session_id, source, user_msg, assistant_msg, sources, consent) — the reply log per session and channel; riasec_results(id, ts, session_id, lang, code, scores, recs, consent, name) — test results including the applicant's full name; and graph_traces(id, ts, session_id, intent, query, steps, n_chunks) — routing traces. Qdrant holds a collection of knowledge-base chunks with payload fields (source_url, title, faculty, program, doc_type, lang, updated_at) and indexes for filtering.

# 9. RAG Ingestion Pipeline

scrape, clean, chunk, metadata, upsert. scrape — Bright Data (bdata scrape / SDK): university website pages to markdown, local PDF/DOCX to text. clean — main-text extraction, encoding repair (ftfy plus regex), deduplication by hash. chunk — LangChain RecursiveCharacterTextSplitter / by markdown headings with overlap; semantic chunking for long pages. metadata — enrich each chunk with metadata. upsert — qdrant-client: batch upload with payload and indexes.

# 10. Web Management Interface (detail)

Extension of the existing admin panel (/admin, token access): Dialogs — a session list, channel/date filters, transcript view. RIASEC results — a table of full name, date, Holland code, percentages, recommended programs, with export. Dialog graph — a static diagram of LangGraph nodes and transitions. Traces — for each dialog: the router intent, the path across nodes, and the RAG fragments used (answer explainability). Analytics — a dashboard: dialog/message counts, intent distribution, top questions, Holland-code distribution, and test-to-chat conversion. The purpose of this section is to let the user control and analyze the LangGraph/LangChain operation directly through the website, without server access.

# 11. Deployment Requirements

Docker Compose with services qdrant, backend (FastAPI), and optional openwebui. Environment variables via .env (LLM/embedder keys, Qdrant, Twilio, Telegram, Meta, admin token). Deployment to a VPS (DigitalOcean droplet); updates via git pull then docker compose up -d --build backend. Database migrations run automatically at startup (idempotent CREATE TABLE IF NOT EXISTS plus ALTER TABLE when new columns appear).

# 12. Work Stages

Stage 1 — infrastructure (Qdrant in Docker, environment, dependencies): done. Stage 2 — RIASEC test (items, scoring, mapping, /test page, full name, PDF): done. Stage 3 — web chat plus baseline RAG plus logging plus admin: done (baseline). Stage 4 — ingestion first pass (scrape-clean-chunk-metadata-upsert): in progress. Stage 5 — LangGraph orchestration (router/riasec/rag/general, streaming): implemented. Stage 6 — LangChain in ingestion (loaders, splitters) used explicitly: implemented. Stage 7 — web management of the graph and analytics (visualization, traces): implemented. Stage 8 — channels: Telegram, then WhatsApp (Twilio), then Meta: staged. Stage 9 — tests, ADRs, documentation: ongoing.

# 13. Acceptance Criteria

The RIASEC test is completed in three languages, the result is saved with the full name and exported to PDF in the interface language. The consultation answers over the university knowledge base with streaming; with a RIASEC profile present, the answer is personalized. A dialog is processed through the LangGraph graph: the trace shows the intent and the path across nodes. Ingestion uses LangChain (loaders/splitters); chunks with metadata are loaded into Qdrant. The admin panel provides the dialog list, transcripts, RIASEC results, the graph diagram, traces, and basic analytics. The system is deployed in Docker on a VPS and is updated via git pull plus a rebuild. Key logic (scoring, the test API, routing) is covered by automated tests.

# 14. Risks and Limitations

RAG quality depends on the completeness and cleanliness of the collected knowledge base (the ingestion stage is critical). Kyrgyz test wordings require validation by a native speaker. The profile-to-program mapping requires alignment with the university's current program list. The move to LangGraph must not break streaming — mandatory streaming check after integration. External API limits (LLM, Twilio, Meta, Bright Data) must be handled with rate limiting and error handling.
