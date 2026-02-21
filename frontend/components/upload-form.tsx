'use client';

import { useState } from 'react';

import { fetchRankedClips, uploadVideo } from '@/lib/api';

export function UploadForm() {
  const [loading, setLoading] = useState(false);
  const [clips, setClips] = useState<any[]>([]);

  async function handleUpload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fileInput = event.currentTarget.elements.namedItem('video') as HTMLInputElement;
    const file = fileInput.files?.[0];
    if (!file) return;

    setLoading(true);
    try {
      const uploadResult = await uploadVideo(file);
      const ranked = await fetchRankedClips(uploadResult.video_id);
      setClips(ranked.clips);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleUpload} className="space-y-2">
        <input name="video" type="file" accept="video/*" className="block w-full" />
        <button type="submit" disabled={loading} className="rounded bg-black px-4 py-2 text-white">
          {loading ? 'Processing…' : 'Upload & Generate Clips'}
        </button>
      </form>
      <ul className="space-y-2">
        {clips.map((clip) => (
          <li key={clip.id} className="rounded border p-3">
            <p>Score: {clip.virality_score}</p>
            <p>
              Segment: {clip.start_sec}s - {clip.end_sec}s
            </p>
            <a className="text-blue-600 underline" href={clip.vertical_url}>
              View clip
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
