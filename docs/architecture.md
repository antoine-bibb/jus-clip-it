# JusClipIt Scalable Architecture (Step-by-Step)

## 1) Folder layout

```text
backend/
  app/
    api/routes/      # FastAPI endpoints only (thin controllers)
    core/            # config + db wiring
    models/          # SQLAlchemy entities
    schemas/         # request/response contracts
    services/        # AI, storage, quota domain logic
    workers/         # Celery async processing
frontend/
  app/               # Next.js App Router pages
  components/        # reusable UI components
  lib/               # API clients + shared helpers
docs/
  architecture.md    # this guide
```

## 2) Upload pipeline
1. Client uploads file from `frontend/components/upload-form.tsx`.
2. FastAPI endpoint (`POST /videos/upload`) stores upload metadata + creates a `clip_jobs` row.
3. Celery worker consumes queued job.
4. Worker runs transcript (`Whisper`), segment scoring (`GPT`), then vertical rendering (`ffmpeg`).
5. Ranked clips are persisted with `virality_score` and returned from `GET /clips/{video_id}`.

## 3) Quotas and plans
- Guest: max 2 clips.
- Free: max 5 clips.
- Paid: configurable monthly quota.
- Quota guard belongs in `backend/app/services/quota.py` and must run before enqueueing heavy jobs.

## 4) Production-readiness notes
- Use PostgreSQL for strong consistency and relational querying.
- Use Redis + Celery queues (`video-processing`, `rendering`, `webhooks`) for horizontal scaling.
- Keep FastAPI stateless behind a load balancer.
- Keep workers autoscaled independently from API nodes.
- Store raw videos and generated clips in S3; expose via CloudFront CDN.
- Add Stripe webhooks to mutate entitlements atomically.
- Add auth middleware (Clerk/JWT) and derive user tier from DB.

## 5) Suggested next tasks
- Add Alembic migrations for `users/videos/clips/clip_jobs`.
- Replace AI service placeholders with OpenAI + Whisper API integrations.
- Add ffmpeg render worker for 9:16 crops, captions, and burned subtitles.
- Add observability: OpenTelemetry traces + queue lag dashboards.
- Add integration tests for end-to-end upload -> job -> ranked clips.
