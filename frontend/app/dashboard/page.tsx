'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

type UploadResponse = {
  video_id: string;
  job_id: string;
  status: string;
};

type JobStatusResponse = {
  job_id: string;
  video_id: string;
  status: string;
  progress_percent: number;
  clips_completed: number;
  clips_expected: number;
  error?: string | null;
};

type ClipOut = {
  id: string;
  start_sec: number;
  end_sec: number;
  virality_score: number;
  vertical_url: string;
};

type ClipListResponse = {
  video_id: string;
  clips: ClipOut[];
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
const USER_EMAIL = process.env.NEXT_PUBLIC_TEST_EMAIL ?? 'free-user@example.com';

export default function Dashboard() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [clips, setClips] = useState<ClipOut[]>([]);
  const [error, setError] = useState<string>('');

  const progressLabel = useMemo(() => {
    if (!job) return 'Waiting for upload';
    if (job.status === 'queued') return 'Queued';
    if (job.status === 'running') return 'Processing with AI';
    if (job.status === 'done') return 'Completed';
    return 'Failed';
  }, [job]);

  useEffect(() => {
    if (!job || (job.status !== 'queued' && job.status !== 'running')) return;

    const interval = window.setInterval(async () => {
      const res = await fetch(`${API_BASE_URL}/jobs/${job.job_id}`);
      if (!res.ok) return;
      const latest = (await res.json()) as JobStatusResponse;
      setJob(latest);

      if (latest.status === 'done') {
        const clipRes = await fetch(`${API_BASE_URL}/clips/${latest.video_id}`);
        if (clipRes.ok) {
          const data = (await clipRes.json()) as ClipListResponse;
          setClips(data.clips);
        }
      }
      if (latest.status === 'done' || latest.status === 'failed') {
        window.clearInterval(interval);
      }
    }, 3000);

    return () => window.clearInterval(interval);
  }, [job]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) return;

    setUploading(true);
    setError('');
    setClips([]);
    setJob(null);

    try {
      const form = new FormData();
      form.append('file', file);

      const res = await fetch(`${API_BASE_URL}/videos/upload`, {
        method: 'POST',
        body: form,
        headers: { 'x-user-email': USER_EMAIL },
      });

      if (!res.ok) {
        const body = await res.json();
        throw new Error(body?.detail ?? 'Upload failed');
      }

      const upload = (await res.json()) as UploadResponse;
      const statusRes = await fetch(`${API_BASE_URL}/jobs/${upload.job_id}`);
      if (statusRes.ok) {
        setJob((await statusRes.json()) as JobStatusResponse);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col gap-8 p-6 md:p-10">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold">JusClipIt Dashboard</h1>
        <p className="text-sm text-zinc-600">
          Upload a video and generate AI clips between 30 seconds and 3 minutes.
        </p>
      </header>

      <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-zinc-200 p-5">
        <input
          type="file"
          accept="video/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm"
        />
        {!file && <p className="text-sm text-zinc-500">Please select a video file to upload.</p>}
        <button
          type="submit"
          disabled={!file || uploading}
          className="rounded-md bg-black px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-zinc-400"
        >
          {uploading ? 'Uploading...' : 'Upload and Create Clips'}
        </button>
      </form>

      {job ? (
        <section className="space-y-3 rounded-xl border border-zinc-200 p-5">
          <div className="flex items-center justify-between text-sm">
            <span>{progressLabel}</span>
            <span>{job.progress_percent}%</span>
          </div>
          <div className="h-3 w-full overflow-hidden rounded-full bg-zinc-200">
            <div
              className="h-full bg-emerald-500 transition-all duration-500"
              style={{ width: `${job.progress_percent}%` }}
            />
          </div>
          <p className="text-xs text-zinc-500">
            {job.clips_completed} / {job.clips_expected} clips rendered
          </p>
          {job.error ? <p className="text-sm text-red-600">{job.error}</p> : null}
        </section>
      ) : null}

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      {clips.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Generated Clips</h2>
          <div className="space-y-2">
            {clips.map((clip) => (
              <a
                key={clip.id}
                href={clip.vertical_url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-lg border border-zinc-200 p-4 hover:bg-zinc-50"
              >
                <p className="font-medium">
                  {clip.start_sec}s - {clip.end_sec}s
                </p>
                <p className="text-sm text-zinc-600">Virality: {clip.virality_score}</p>
              </a>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
