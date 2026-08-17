# Android and Google Cloud path

Android packaging and cloud deployment follow the local backend milestone. They
should not dictate business rules or create a second backend implementation.

## Android approach

### Family Dashboard

Capacitor is a reasonable first choice because the existing React/Vite UI maps
well to an authenticated dashboard. Required work still includes:

- Secure token storage
- FCM notifications
- Deep links for invitations and alerts
- File selection/camera upload
- Offline and error states
- Android back-button and lifecycle behavior
- Accessibility and large-text testing

### Parent App

Capacitor can produce an early Android build, but production requirements will
need native Android integrations or custom plugins:

- Continuous/realtime microphone sessions
- Background reminders and exact-alarm policy handling
- FCM notification actions
- Health Connect and wearable providers
- Location and SOS flows
- Sensors/fall-detection research
- Battery-optimization behavior across vendors
- Audio focus, Bluetooth and interruption handling
- Offline action queue and recovery

Do not promise that a web-to-APK conversion alone supplies these capabilities.
Run a technical spike before committing to Capacitor versus a more native Parent
App implementation.

## Android security

- Store only short-lived user/session material on the device.
- Use Android Keystore-backed storage for sensitive local tokens.
- Never compile permanent AI, database or service-account credentials into the app.
- Require HTTPS outside local development.
- Verify Firebase tokens and permissions in the backend.
- Consider Play Integrity as an additional abuse signal, not as user authorization.
- Minimize local health data and define cache deletion behavior.

## Cloud environments

Create separate Google Cloud projects for staging and production. Do not rely on
resource-name prefixes inside one project as the only isolation boundary.

### Staging

- Cloud Run API
- Small Cloud SQL PostgreSQL instance
- Private Cloud Storage bucket
- Secret Manager
- Firebase Authentication and FCM
- Cloud Tasks/Scheduler
- Logging, error reporting and budget alerts

### Production

Create only after staging passes functional, security, recovery and cost tests.

## Deployment sequence

1. Select a region supported by required services and document data residency.
2. Create least-privilege service accounts.
3. Store secrets in Secret Manager.
4. Create Cloud SQL with backups and point-in-time recovery.
5. Create private object storage and lifecycle rules.
6. Build the container into Artifact Registry.
7. Deploy database migrations as an explicit controlled step.
8. Deploy Cloud Run with health checks and bounded scaling.
9. Configure tasks, scheduler and notification credentials.
10. Configure custom staging API domain.
11. Run smoke, authorization and failure tests.
12. Promote an immutable build to production.

## API address

- Local: `http://localhost:8000/api/v1`
- Android emulator: `http://10.0.2.2:8000/api/v1`
- Staging: `https://api-staging.gamira.online/api/v1`
- Production: `https://api.gamira.online/api/v1`

The addresses are public configuration. Access is protected by authentication,
authorization, rate limits and server-side policy—not by hiding the URL.

## Production readiness gates

- [ ] No permanent secret appears in an Android/web bundle.
- [ ] Cross-family authorization tests pass.
- [ ] Database backups have been restored in a test.
- [ ] Migrations support safe forward deployment and documented rollback/repair.
- [ ] Logs and alerts exclude tokens and unnecessary health data.
- [ ] Reminder and alert delivery are idempotent and observable.
- [ ] AI outage leaves core safety flows operational.
- [ ] Account export/deletion and consent flows work.
- [ ] App privacy disclosures match actual data collection.
- [ ] Domain, pricing and support/legal information are internally consistent.
- [ ] Budget and model-usage limits are configured.
- [ ] Incident response ownership and escalation contacts are documented.

## References

- [Cloud Run overview](https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run)
- [Cloud SQL for PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/introduction)
- [Secret Manager best practices](https://docs.cloud.google.com/secret-manager/docs/best-practices)
- [Firebase Authentication](https://firebase.google.com/docs/auth)
- [Firebase Cloud Messaging for Android](https://firebase.google.com/docs/cloud-messaging/android/get-started)
- [Gemini Live ephemeral tokens](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens)
- [Android insecure API usage](https://developer.android.com/privacy-and-security/risks/insecure-api-usage)
- [Android Keystore](https://developer.android.com/privacy-and-security/keystore)

