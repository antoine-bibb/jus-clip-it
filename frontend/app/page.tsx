import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-lg rounded-xl border border-zinc-200 p-8 text-center">
        <h1 className="text-3xl font-bold">JusClipIt</h1>
        <p className="mt-3 text-sm text-zinc-600">
          Upload a video and let AI generate 30s to 3m short clips.
        </p>
        <Link
          href="/dashboard"
          className="mt-6 inline-flex rounded-md bg-black px-4 py-2 text-sm font-semibold text-white"
        >
          Open Dashboard
        </Link>
      </div>
    </main>
  );
}
