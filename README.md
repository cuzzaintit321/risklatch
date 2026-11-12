![RiskLatch](assets/cover.png)

# RiskLatch v1.0 — single-organization prototype

Run `./setup.sh` on a Docker Compose host with OpenSSL. Open http://localhost:8125 (or use SSH port forwarding). The generated admin password is printed and stored in .env. For HTTPS deployment set SECURE_COOKIE=1 and configure your reverse proxy. Do not expose plain HTTP. Back up the named data volume securely.

Workflow: add vendor, share private upload URL, upload PDF, manually verify original policy and endorsements, record review decision and limits. The dashboard recomputes document checklist status and flags approved COIs expiring within 30 days. A checklist clearance is not legal authorization to pay. Lien waivers are not invoice-specific in this prototype.

This is a single-tenant prototype using SQLite, Flask and PDF text extraction, not OCR. No email/SMS sending, scheduled reminders, accounting integrations, billing, automated verification, multi-user access, malware scanning or production security audit. Do not upload real W-9s or other sensitive documents until encryption, access controls, retention, scanning, rate limiting, audit hardening and security review are implemented. Upload links are reusable bearer credentials until rotated. Use synthetic documents for evaluation. No legal or insurance advice.

## v2.0 operations
Open `/operations` after signing in. Create projects, assign vendors, configure vendor insurance and license requirements, review invoices, export compliance CSV and generate reminder drafts. Email sending requires SMTP_HOST, SMTP_PORT, SMTP_FROM, optional SMTP_USER/SMTP_PASSWORD and HTTPS PUBLIC_BASE_URL in .env. Reminders are manually generated and sent. Invoice decisions are advisory and require human review. No accounting integration or automated insurance verification is included. Single organization only; use synthetic data until security review. Back up existing data before upgrading. Existing SubClear Docker volume is not automatically migrated when renaming the Compose project; preserve the original volume explicitly if needed.
