# Feature Specification: Phase 2 — Product Completion

**Feature Branch**: `003-phase2-completion`
**Created**: 2026-04-21
**Status**: Draft
**Platform**: Web
**Input**: User description: "Phase 2 completion: source registration wizard, file upload, chat SSE streaming, LLM settings, company policy admin, users management, profile page"

## User Scenarios & Testing _(mandatory)_

### User Story 1 — Admin Registers a Knowledge Source via Guided Wizard (Priority: P0)

An administrator wants to connect a new knowledge source (a database, a set of files, a web page, or a third-party integration) to the system. Today the only way to do this is to type raw configuration JSON into a textarea — an approach that only a developer can use. The wizard replaces this with a step-by-step guided form tailored to each source type.

**Why this priority**: Without a working source registration flow, no knowledge ever enters the system. Every other feature depends on sources existing. The current JSON textarea is unusable by non-technical admins, making the product functionally broken for its intended audience.

**Independent Test**: An admin with no technical background can open the "Add Source" wizard, select "PostgreSQL", fill in host/port/database/credentials, see a generated description, configure sync settings, and save — all without reading any documentation. The source then appears in the sources list with a "pending" status.

**Acceptance Scenarios**:

1. **Given** an admin is on the Sources page, **When** they click "Add Source", **Then** they see a grid of source type cards (databases, files, web, integrations) and no JSON input.
2. **Given** an admin selects a database source type, **When** they reach the connection details step, **Then** they see labelled fields (host, port, database name, username, password, SSL mode) specific to that database — not a generic form.
3. **Given** an admin selects a file source type (PDF, Word, Excel, CSV, etc.), **When** they reach the connection details step, **Then** they see a drag-and-drop upload area that accepts multiple files up to 50 MB each and shows per-file upload progress.
4. **Given** an admin clicks "Test Connection", **When** the system checks reachability, **Then** a success or failure indicator appears inline without navigating away from the step.
5. **Given** connection details are confirmed, **When** the system inspects the source, **Then** an AI-generated natural language description appears in an editable field the admin can refine before proceeding.
6. **Given** an admin completes all steps and clicks "Create Source", **When** the form is submitted, **Then** they are redirected to the source detail page, a success notification appears, and a background sync job starts immediately.
7. **Given** an admin uploads files, **When** the files are transferred, **Then** the file bytes travel directly from the browser to object storage — they never pass through the application server.

---

### User Story 2 — Employee Has a Real-Time AI Conversation (Priority: P0)

An employee types a question into the chat interface and receives a streaming answer drawn from the company's connected knowledge sources, with citations showing exactly where each piece of information came from. If the question is ambiguous, the AI asks a clarifying follow-up before answering. If the question violates company policy, the AI declines gracefully.

**Why this priority**: Real-time conversational Q&A is the entire value proposition of the product. Without streaming responses and working citations, users see a blank screen or a broken experience.

**Independent Test**: An authenticated employee can open the chat, type "What is our parental leave policy?", and see the answer stream in word by word. After the response, numbered citation markers link to the source documents. The full interaction takes under 30 seconds on a standard connection.

**Acceptance Scenarios**:

1. **Given** an employee is on the chat page, **When** they type a message and press Send, **Then** the response begins appearing on screen within 3 seconds, streaming incrementally until complete.
2. **Given** a response is streaming, **When** the employee clicks the Stop button, **Then** streaming halts immediately and the partial response is preserved.
3. **Given** a response includes sourced content, **When** the response finishes streaming, **Then** numbered citation markers appear inline and a collapsible citation panel lists each source with its name and a quoted excerpt.
4. **Given** the AI needs more information, **When** a clarification request arrives, **Then** streaming pauses and a distinct card appears with the AI's question and an input field for the employee to reply.
5. **Given** a message violates company policy, **When** the guardrail triggers, **Then** a clearly styled notice appears explaining the request cannot be answered — no partial answer is shown.
6. **Given** an employee has multiple chat sessions, **When** they switch between sessions, **Then** the full message history of the selected session loads correctly.
7. **Given** an employee creates a new session, **When** they select specific sources before sending a message, **Then** the AI draws answers only from those sources.

---

### User Story 3 — Admin Configures AI Pipeline Behaviour (Priority: P1)

An administrator needs to control which AI models power each stage of the answer pipeline (query analysis, answer synthesis, guardrail checks, etc.) and what rules govern acceptable topics. These settings determine answer quality, cost, and compliance — and must be changeable without a code deployment.

**Why this priority**: Without configurable AI settings, the system is locked to defaults that may not match a company's cost targets, compliance requirements, or quality standards. Without a policy editor, admins have no way to enforce topic restrictions.

**Independent Test**: An admin opens the LLM Settings page, changes the synthesizer stage to a different model, clicks "Test Connection", sees a pass result, saves, and the very next chat response uses the updated model. Separately, an admin adds a policy rule ("Never discuss salary ranges"), saves it, and the next policy-violating message is blocked.

**Acceptance Scenarios**:

1. **Given** an admin opens LLM Settings, **When** the page loads, **Then** they see one configuration card for each of the 10 pipeline stages with a plain-English description of what each stage does.
2. **Given** an admin updates a stage's model and clicks "Test Connection", **When** the system validates the configuration, **Then** a pass or fail result appears inline before the admin saves.
3. **Given** an admin saves a stage configuration, **When** the next chat message is processed, **Then** that pipeline stage uses the newly saved model and settings.
4. **Given** an admin opens Company Policy, **When** the page loads, **Then** the current active policy text is displayed in an editable area.
5. **Given** an admin saves an updated policy, **When** the save completes, **Then** the previous policy version is preserved in history and the new version becomes active immediately.
6. **Given** a user sends a message that violates the updated policy, **When** the guardrail checks the message, **Then** the message is blocked and the event is recorded in the guardrail audit log visible to admins.

---

### User Story 4 — Admin Manages Users and Source Access (Priority: P1)

An administrator needs to see all users, invite new ones, control which knowledge sources each user can query, and cancel invitations that have not yet been accepted.

**Why this priority**: Access control is a compliance requirement. Without it, any user can query any source regardless of sensitivity. The current users page has no source access management.

**Independent Test**: An admin opens the Users page, invites a new user by email, then opens that user's detail page and grants them access to two specific sources. The invited user, upon accepting, can only query those two sources in chat.

**Acceptance Scenarios**:

1. **Given** an admin is on the Users page, **When** the page loads, **Then** each user row shows their last login time, number of sources they can access, and an active/inactive status badge.
2. **Given** an admin opens a user's detail page, **When** they navigate to the Source Access tab, **Then** they see a list of all sources with checkboxes or grant/revoke controls per source.
3. **Given** an admin grants a user access to a source, **When** that user next opens the source selector in chat, **Then** the newly granted source appears in their list.
4. **Given** an admin has sent an invitation that has not been accepted, **When** they view the pending invitations table on the Users page, **Then** they can see the email, role, expiry date, and cancel or resend the invitation.
5. **Given** an admin cancels a pending invitation, **When** the recipient later tries to use the invitation link, **Then** they see an expired or invalid invitation message.

---

### User Story 5 — Admin Views Source Status and Sync History (Priority: P1)

An administrator needs to see the health of all connected sources at a glance — which are syncing, which have errors, when each was last synced, and how many documents are indexed. They also need to trigger a manual sync and see the outcome.

**Why this priority**: Without source status visibility, admins cannot diagnose why answers are stale or why a source is returning no results. Without manual sync, they must wait for a scheduled run.

**Independent Test**: An admin opens the Sources list, sees one source with an "error" badge, clicks into it, reads the error detail from the last sync job, corrects the connection details, triggers a manual sync, and watches the status change to "ingesting" then "ready".

**Acceptance Scenarios**:

1. **Given** an admin opens the Sources list, **When** the page loads, **Then** each row shows the source type icon, status badge, mode badge, document count, and last synced time.
2. **Given** an admin clicks "Sync Now" on a source, **When** the job is running, **Then** the button shows a spinner and the status badge updates to "ingesting".
3. **Given** a sync job completes, **When** the admin is still on the page, **Then** the status badge updates automatically (without a full page reload) and a notification shows success or failure.
4. **Given** an admin opens a source detail page, **When** they navigate to the Sync tab, **Then** they see a history table of past sync jobs with timestamps, duration, documents synced, and any error messages.
5. **Given** an admin opens the Overview tab of a source detail, **When** they click "Refresh Description", **Then** the system re-inspects the source and presents a proposed new description for the admin to approve or dismiss.

---

### User Story 6 — User Manages Their Profile (Priority: P2)

A user wants to update their display name, change their password, and control whether citations appear in their chat responses.

**Why this priority**: Profile management is expected hygiene for any authenticated application. It does not block core value delivery but is required for a complete product.

**Independent Test**: A user opens their profile page, updates their full name, changes their password, and toggles citations off. The next chat response shows no citation panel.

**Acceptance Scenarios**:

1. **Given** a user opens their profile page, **When** they update their full name and save, **Then** the new name is displayed in the navigation and persisted across sessions.
2. **Given** a user fills in current password, new password, and confirmation, **When** they submit, **Then** the password is changed and they remain logged in.
3. **Given** a user toggles "Hide Citations", **When** they next receive a chat response, **Then** no citation panel appears even if the response contains sourced content.

---

### Edge Cases

- What happens when an admin starts the source wizard but closes the browser before completing all steps? The partially entered data is not saved; restarting the wizard begins fresh.
- What happens when a file upload to object storage succeeds but the subsequent source creation call fails? The uploaded file is orphaned; the system must not create a broken source record. The admin sees an error and can retry.
- What happens when AI description generation fails during the wizard? The step degrades gracefully — the admin is presented with a blank editable description field and can type their own.
- What happens when a chat stream is interrupted by a network error mid-response? The partial message is marked as incomplete; the session history shows it clearly and the user can ask again.
- What happens when an admin deletes a source that users are actively querying? In-flight queries complete against cached data; future queries no longer include that source.
- What happens when a source's scheduled sync runs while a manual sync is already in progress? The scheduled run is skipped for that cycle; no duplicate jobs run simultaneously.
- What happens when a user's session has no sources selected and all sources are restricted? The system informs the user they have no accessible sources rather than returning an empty answer.
- What happens when an admin saves an LLM config with an invalid API key? The "Test Connection" step catches this before save; saving without testing is allowed but the next pipeline run will surface the error in the source's sync log.

---

## Requirements _(mandatory)_

### Functional Requirements

**Source Registration**

- **FR-001**: Admins MUST be able to register a new knowledge source through a multi-step guided wizard that presents different form fields depending on the selected source type.
- **FR-002**: The wizard MUST support the following source type categories: relational databases (PostgreSQL, MySQL, MS SQL), document databases (MongoDB), file uploads (PDF, Word, Excel, CSV, plain text, Markdown), web URLs, and third-party integrations (Confluence, SharePoint).
- **FR-003**: Each database source type MUST present a "Test Connection" action that verifies reachability and reports success or failure inline without leaving the current step.
- **FR-004**: After connection details are confirmed, the system MUST generate a natural language description of the source's content and present it in an editable field for admin review before proceeding.
- **FR-005**: File uploads MUST support drag-and-drop and file picker interactions, accept multiple files simultaneously, enforce a 50 MB per-file limit, and display per-file upload progress.
- **FR-006**: File bytes MUST travel directly from the browser to object storage using a time-limited pre-authorised upload link; file contents MUST NOT pass through the application server.
- **FR-007**: Admins MUST be able to configure sync mode (manual, scheduled, or delta), a cron-expression schedule with a plain-language preview, retrieval mode (vector search, live query generation, or hybrid), and whether this source may be named in citations.
- **FR-008**: On successful source creation, the system MUST immediately trigger an initial background ingestion job and redirect the admin to the source detail page.

**Sources List & Detail**

- **FR-009**: The sources list MUST display for each source: a type icon, name, status badge, mode badge, document count, last synced time, and action buttons (Sync Now, Edit, Delete).
- **FR-010**: The sources list MUST support text search by name and filtering by source category and status.
- **FR-011**: The source detail page MUST provide four tabs: Overview (description, retrieval settings), Sync (schedule, history), Access (per-user grant/revoke), and Settings (connection details, rename, delete).
- **FR-012**: The Sync history tab MUST show each past sync job's start time, duration, documents synced count, and error message if applicable.
- **FR-013**: Admins MUST be able to re-generate a source's AI description at any time; the proposed new description MUST be presented for approval before replacing the current one.

**Chat Interface**

- **FR-014**: Sending a message MUST initiate a real-time streaming response; the first content MUST appear on screen within 3 seconds under normal network conditions.
- **FR-015**: The chat interface MUST display a Stop button while a response is streaming; activating it MUST immediately halt the stream.
- **FR-016**: Responses that include sourced content MUST render numbered citation markers inline and a collapsible panel listing each citation's source name and a quoted excerpt.
- **FR-017**: When the AI requires clarification, a distinct interactive card MUST appear in the message thread with the AI's question and an input for the user's reply; the conversation MUST resume automatically after the user replies.
- **FR-018**: When a message is blocked by a guardrail, a clearly styled notice MUST replace the expected answer; no partial answer MUST be shown.
- **FR-019**: The session sidebar MUST list all of the user's sessions sorted by most recent activity, show a truncated preview of the last message, and support rename and delete actions per session.
- **FR-020**: Users MUST be able to select which sources the AI queries for a given session; "all accessible sources" MUST be the default when no selection is made.

**LLM Settings**

- **FR-021**: Admins MUST be able to view and edit the AI model configuration for each of the 10 pipeline stages individually.
- **FR-022**: Each stage configuration MUST include: provider selection, model identifier, API credentials, temperature, and maximum response length.
- **FR-023**: A "Test Connection" action MUST be available per stage and MUST verify the configuration before the admin saves.
- **FR-024**: The reflector stage MUST have an explicit enable/disable toggle and MUST default to disabled.

**Company Policy**

- **FR-025**: Admins MUST be able to read and update the company policy text through a plain-text editor.
- **FR-026**: Each policy save MUST create a new version; previous versions MUST be preserved and not overwritten.
- **FR-027**: Admins MUST be able to view a paginated audit log of guardrail events including the trigger reason, action taken, and the user who triggered it.
- **FR-028**: Admins MUST be able to view the full original message and the guardrail's decision detail for any individual audit event.

**User Management**

- **FR-029**: The users list MUST display each user's last login time, number of accessible sources, and active/inactive status.
- **FR-030**: Admins MUST be able to grant and revoke a user's access to specific sources from the user detail page.
- **FR-031**: Pending invitations MUST be visible in a separate table on the users list page showing email, assigned role, expiry date, and options to resend or cancel.

**Profile**

- **FR-032**: Users MUST be able to update their display name.
- **FR-033**: Users MUST be able to change their password by providing their current password and a new password with confirmation.
- **FR-034**: Users MUST be able to toggle whether citation panels appear in their chat responses; this preference MUST persist across sessions.

**Navigation**

- **FR-035**: The admin sidebar MUST provide direct navigation to: Dashboard, Sources, Connectors, Users, LLM Configuration, Company Policy, and Health.
- **FR-036**: The chat sidebar MUST show session history grouped by recency (Today, Yesterday, Last 7 days) with New Chat at the top and Profile/Sign Out at the bottom.
- **FR-037**: Both sidebars MUST collapse to icon-only view on narrow screens.

**Connector Scheduling**

- **FR-038**: When a source is saved with a scheduled sync mode and a cron expression, the system MUST automatically register a recurring background job for that source.
- **FR-039**: Updating a source's schedule MUST cancel the previous recurring job and register a new one with the updated expression.
- **FR-040**: Deleting a source MUST cancel any associated recurring background job.

**Empty & Error States**

- **FR-041**: Every list view (sources, users, sessions, sync history) MUST display a contextual empty state with an explanatory message and a primary action button when no items exist.
- **FR-042**: Every page MUST display an inline error message with a retry action when a data-loading call fails; blank pages are not acceptable.
- **FR-043**: The application MUST notify the user with a visible message when browser connectivity is lost.

### Key Entities

- **Source**: A registered knowledge data origin. Has a type (database, file, web, integration), a sync mode and schedule, a status reflecting the last ingestion state, a document count, and a flag controlling whether it may be named in citations.
- **Source Description History**: An append-only record of AI-generated descriptions for a source, preserving previous versions when an admin approves a new one.
- **Chat Session**: A named conversation thread belonging to one user, associated with zero or more sources, containing an ordered list of messages.
- **Chat Message**: A single turn in a session. Has a role (user or assistant), content, optional citation metadata, a message type (normal, clarification request, clarification response, guardrail blocked), and a flag indicating whether streaming was interrupted.
- **LLM Stage Configuration**: The model provider, credentials, and generation parameters for a single named stage in the AI pipeline.
- **Company Policy**: The active plain-language rules injected into the guardrail system. Versioned; each save creates a new record.
- **Guardrail Event**: An audit record created whenever the input or output guardrail triggers. Contains the original message, trigger reason, action taken, and the user responsible.
- **Source Permission**: A relationship granting a specific user access to a specific source.
- **Pending Invitation**: An unsent or unaccepted invitation to join the system, with an email, assigned role, and expiry timestamp.

---

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: An administrator with no technical background can register a new database source end-to-end in under 5 minutes on first use.
- **SC-002**: An administrator with no technical background can register a file-based source by uploading documents in under 3 minutes on first use.
- **SC-003**: A chat response begins appearing on screen within 3 seconds of the user submitting a message under normal network conditions.
- **SC-004**: 100% of chat responses that include sourced content display at least one citation linking back to a named source.
- **SC-005**: Guardrail-blocked messages display a user-facing notice within 3 seconds; no partial answer is ever shown alongside a block notice.
- **SC-006**: An administrator can update the company policy and have it enforced on the very next user message without any system restart.
- **SC-007**: Granting or revoking a user's access to a source takes effect within one minute; the affected user's source selector reflects the change on their next page load.
- **SC-008**: Every list view in the admin interface displays a usable empty state or error state — zero blank pages under any data condition.
- **SC-009**: A source configured for scheduled sync auto-triggers within 2 minutes of its cron expression firing, without any manual intervention.
- **SC-010**: Admins can view the guardrail audit log and open the full detail of any event within 3 clicks from the Company Policy page.

### Assumptions

- The system operates as a single-tenant deployment; multi-tenancy is explicitly out of scope for this phase.
- Users are divided into two roles only: admin and regular user. Fine-grained permission tiers are out of scope.
- LLM provider credentials are entered and stored by admins; end users are never exposed to provider configuration.
- Scheduled sync uses server-side cron scheduling; calendar-based scheduling (e.g. "first Monday of each month") is not required.
- File sources support one upload per source registration; subsequent file versions are handled through a separate sync/re-upload flow out of scope for this phase.
- Answer feedback (thumbs up/down), cross-session memory, BM25 fallback, SAML/OIDC SSO, and audit log export are explicitly deferred to a future phase.
