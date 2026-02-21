import { UploadForm } from '@/components/upload-form';

export default function DashboardPage() {
  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="mb-4 text-3xl font-bold">AI Clip Studio</h1>
      <p className="mb-6 text-sm text-gray-600">
        Upload a long-form video. We transcribe, score, and output ranked 9:16 clips.
      </p>
      <UploadForm />
    </main>
  );
}
