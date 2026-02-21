const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export async function uploadVideo(file: File) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/videos/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) throw new Error('Upload failed');
  return response.json();
}

export async function fetchRankedClips(videoId: string) {
  const response = await fetch(`${API_BASE_URL}/clips/${videoId}`);
  if (!response.ok) throw new Error('Failed to fetch clips');
  return response.json();
}
