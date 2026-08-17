The honest summary
Gamira is a working local MVP for coordinating care between an older person and their family. The core medication flow works end to end, but it is not yet a production-ready, deployed healthcare product.
Public website                    Gemini Live
(marketing only)                       ↑
                                       │ prototype
Parent App ───────┐                     │
                  ├── Gamira FastAPI ── PostgreSQL
Family Dashboard ┘
Today, SQLite can substitute for PostgreSQL locally. Firebase, push notifications, cloud deployment, billing, reliable SOS delivery, and production AI are still future work.
What is built
1. Gamira backend
The backend is a Python/FastAPI modular monolith with one authoritative database. It exposes roughly 40 API operations covering:
Users and account profiles
Families and memberships
Invitations
Senior/cared-for-person profiles
Medications and recurring schedules
Daily dose events
Taken/skipped confirmation
Non-medication reminders
Health readings
Emergency contacts
Appointments
Family notes
Timeline events
Notification records
The current database has 16 models across identity, medication, care, notifications, and auditing. See [the backend models (line 36)](Z:/Gamira/gamira-backend/app/models/identity.py:36) and [API contract (line 1)](Z:/Gamira/docs/API.md:1).
Important backend behavior:
Every request uses a bearer token.
Firebase token verification is implemented, but no real Firebase project is configured.
Local development uses clearly restricted dev: identities.
Server-side roles are owner, caregiver, family, doctor, and viewer.
Owners, caregivers, and family roles can modify care data.
Doctors and viewers are read-only.
A senior normally remains a viewer but may confirm their own dose.
Cross-family requests return 404 so outsiders cannot discover another family’s records.
Invitation tokens are hashed before storage.
Important changes create audit records.
API errors have stable codes and request IDs.
CORS is restricted to configured clients.
2. Medication care loop
This is the most complete part of the product.
Current flow:
A family member creates a medicine and one or more local dose times.
The backend stores the medicine, schedule, timezone, dosage, instructions, and late/missed windows.
When an app asks for doses, the backend generates missing occurrences for that date.
The Parent App shows those doses.
The senior taps Taken or Skip.
The backend records the result idempotently.
A timeline event is created.
The Family Dashboard sees the updated result.
Timezone handling is strong: a dose scheduled for 8:00 AM remains 8:00 AM locally across daylight-saving changes. Duplicate generation and double taps do not create duplicate outcomes.
The implementation is in [doses.py (line 36)](Z:/Gamira/gamira-backend/app/services/doses.py:36).
3. Family Dashboard
The dashboard is a React/Vite application with protected routes and a shared backend client.
Working features include:
Sign-in using development identities or a pasted Firebase ID token
Dashboard overview using real backend records
Multiple cared-for people
Add, edit, and archive senior profiles
Add and archive medicines
Create schedules while adding medicines
View and confirm doses
Create, edit, complete, and delete routines/reminders
Add health readings and view trends
View timelines
Add and remove emergency contacts
Direct tel: calling
View appointments
View and add family notes
View notification records and mark them opened
Generate care summaries from deterministic counts
Download a client-generated PDF report
Update the signed-in user’s profile, locale, and theme
The “AI Assistant” is not AI today. It answers a small set of questions by counting loaded records and matching keywords. This is deliberately safer than inventing an AI answer before the backend AI permission layer exists. See [AIAssistant.jsx (line 87)](Z:/Gamira/gamira-family-dashboard/src/pages/AIAssistant.jsx:87).
Similarly, “AI Summary” is a reproducible care summary, not model-generated narration.
Not functional in the dashboard:
Smart-home switches
Billing and plan activation
Push delivery
Uploading profile photos
Real support messaging
Creating appointments through the current UI
Inviting family/caregiver accounts through the current UI
General conversational AI
The support screen saves a family note; it does not contact Gamira support.
One privacy consideration: the home weather card requests browser location and sends coordinates to Open-Meteo and BigDataCloud.
4. Parent App
The Parent App is designed for the older person, with larger controls and simpler navigation.
Working features:
Authenticated access to the senior profile linked to the signed-in account
Home screen with real doses, routines, readings, and emergency contact
Taken/skipped dose confirmation
Reminder history
Health reading display and real trend lines
Emergency contact calling and SMS
Display of people who can access the care record
Account profile editing
Nine-language interface support
Theme, voice, language, and accessibility preferences
Gemini Live voice prototype
The care record is intentionally read-only here. Family members maintain medicines, health readings, and emergency contacts in the dashboard. The senior can still confirm their own doses.
SOS currently means “open the phone dialer for the saved primary contact.” It does not:
Contact emergency services
Send an alert in the background
Share location
Escalate if nobody answers
5. Voice prototype
The Parent App has a real Gemini Live audio prototype:
Browser microphone capture
PCM audio streaming
Streaming audio playback
Output transcription
Voice interruption/barge-in
Echo cancellation
Short-lived, one-use Gemini token
A carefully written senior-respectful persona
Multilingual conversational instructions
The permanent Gemini key remains in a local Python token server, not the browser.
However, this is still a development prototype:
The token endpoint has no user authentication.
It only binds locally.
Voice is not connected to Gamira care records or backend tools.
It cannot reliably create reminders, contact family, or confirm medication.
It must not be exposed publicly in its current form.
See [VOICE_CHAT.md (line 1)](Z:/Gamira/gamira-parent-app-original/VOICE_CHAT.md:1).
6. Public website
The public website is a static React/Vite site with:
Home
Features
How It Works
For Families
Pricing
Help Center
Privacy Policy
Terms
Six languages
SEO metadata, sitemap, robots file, and social image
Server-side prerendering of nine routes
It is presentation-only:
Get Started ends at the pricing page.
Plan buttons do not start checkout.
Pricing is hard-coded.
The support form only displays a temporary success state.
Store badges are not connected to real releases.
Some marketing copy currently mentions fall detection, emergency SOS, health monitoring, and plans that the implementation cannot yet deliver. This must be reconciled before launch.
How everything is intended to work in the future
The planned architecture is documented in [ARCHITECTURE.md (line 3)](Z:/Gamira/docs/ARCHITECTURE.md:3) and the ordered work in [ROADMAP.md (line 74)](Z:/Gamira/docs/ROADMAP.md:74).
Authentication and onboarding
Family members sign in through Firebase using email or Google.
Seniors use phone or assisted setup.
The backend verifies Firebase tokens.
A user creates a family or accepts a secure invitation.
A senior profile is created and consent is recorded.
Every app receives only the records allowed by its membership.
The frontend will never be trusted to declare its own role or family.
Reliable reminders
The current read-time dose generation will be replaced by background processing:
A worker creates dose events ahead of time.
Cloud Tasks or a scheduler queues reminders.
Firebase Cloud Messaging sends them to registered devices.
Delivery, opening, failure, and retry states are recorded.
Repeated jobs use deduplication keys.
Missed-dose rules can generate traceable family alerts.
The dose remains visible inside the app even if push delivery fails.
This is the most important immediate backend milestone.
Health records, files, and reports
The existing health-reading system will expand to include:
Authenticated prescription and medical-report uploads
Private Cloud Storage
File-type and malware checks
Device and Health Connect provenance
More complete unit validation
Deterministic weekly summaries
Server-generated PDF reports
Consent, retention, export, and deletion controls
Audited access to sensitive records
Gamira should display recorded data without diagnosing or declaring it safe.
AI and voice
Future AI will operate behind the backend:
Authorized request
  → retrieve minimum permitted records
  → Gemini proposes a structured response/action
  → deterministic policy checks it
  → ask for confirmation when necessary
  → backend executes
  → audit the result
AI may summarize verified activity, explain the app, or help phrase reminders. It may not independently diagnose, change medication, expose another family’s data, or suppress an emergency.
Voice tokens will move into the authenticated FastAPI backend. Any voice action—such as confirming a dose—will call the same authorized API used by the screens.
The safety design is described in [AI_SAFETY.md (line 1)](Z:/Gamira/docs/AI_SAFETY.md:1).
SOS and alerts
The planned SOS flow is:
User presses SOS.
Backend durably creates an alert.
Contacts receive notifications or calls through configured providers.
A contact acknowledges it.
Deterministic rules retry or escalate.
Every delivery and acknowledgement is visible.
Location is shared only with explicit consent and a defined duration.
AI can assist with wording but cannot cancel or resolve the alert.
Legal and product review will be required before promising emergency-service integration.
Android applications
The web applications will likely be packaged with Capacitor first, followed by native work where needed.
Android-specific work includes:
Keystore-backed token storage
Firebase push actions
Background reminder handling
Microphone and audio focus
Offline action queues
Deep links
Health Connect
Optional location/SOS integration
Battery-optimization testing
Large-text and screen-reader testing
Play Store privacy and account-deletion requirements
A simple web-to-APK conversion will not provide reliable background care functionality by itself.
Cloud deployment
The target production stack is:
Cloud Run: FastAPI and WebSocket service
Cloud SQL PostgreSQL: authoritative database
Cloud Storage: private files
Secret Manager: credentials
Firebase Authentication: identity
Firebase Cloud Messaging: notifications
Cloud Tasks and Scheduler: background work
Gemini or Vertex AI: AI
Cloud Logging and Error Reporting: operations
Staging and production will be separate projects. Database migrations, backups, restore drills, monitoring, rate limits, budgets, and security tests must be in place before production.
Current readiness and important issues
This is best described as a solid local engineering MVP.
Verified now:
Backend: 34 tests passing
Backend: Ruff and mypy passing
Family Dashboard: lint, type check, and production build passing
Parent App: lint, type check, and production build passing
Website: lint, type check, production build, SSR, and nine-route prerender passing
Important limitations:
Docker is not installed here, so PostgreSQL behavior has not been verified on this machine; backend tests use SQLite.
There are no frontend automated tests or CI/deployment pipelines.
Both app production bundles are large and need code-splitting.
A machine-level DEBUG=release variable currently breaks backend settings unless overridden with a valid boolean.
Dose generation and late/missed calculation happen when doses are requested, so nothing occurs if no screen opens.
Missed doses do not currently create timeline events, which makes report-level missed counts incomplete.
The roadmap says health storage is unbuilt even though part of it now exists.
An inert base44/ configuration remains in the website despite documentation saying Base44 was fully removed.
Backend-on-cloud-infuture is empty; the voice prototype actually lives in the Parent App.
Website and Parent App use different support email domains.
Website promises must be reduced until the corresponding product features exist.