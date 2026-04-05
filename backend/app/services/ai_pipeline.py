from __future__ import annotations

import json
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from openai import OpenAI

from app.core.config import settings


@dataclass
class WordTiming:
    start_time: float
    end_time: float
    word: str


@dataclass
class TranscriptSegment:
    start_time: float
    end_time: float
    text: str
    words: list[WordTiming]


@dataclass
class RankedClip:
    start_time: float
    end_time: float
    virality_score: float
    reasoning: str
    suggested_title: str
    suggested_caption: str


@dataclass
class RenderedClipOutput:
    tiktok_path: str
    reels_path: str
    shorts_path: str
    final_vertical_path: str
    frame_coordinate_map_path: str
    duration: float
    resolution: str


def _openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise ValueError('OPENAI_API_KEY is required for AI clipping pipeline.')
    return OpenAI(api_key=settings.openai_api_key)


def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'Command failed: {" ".join(cmd)}\n{result.stderr.strip()}')
    return result


def extract_audio(video_file_path: str) -> str:
    video_path = Path(video_file_path)
    if not video_path.exists():
        raise FileNotFoundError(f'Video file not found: {video_file_path}')

    output_dir = Path(tempfile.mkdtemp(prefix='jusclipit-audio-'))
    audio_path = output_dir / f'{video_path.stem}.wav'
    _run_cmd([
        'ffmpeg', '-y', '-i', str(video_path), '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', str(audio_path)
    ])
    return str(audio_path)


def _word_timings_from_text(start_time: float, end_time: float, text: str) -> list[WordTiming]:
    words = [w for w in re.findall(r"\b[\w']+\b", text) if w]
    if not words:
        return []
    duration = max(end_time - start_time, 0.01)
    step = duration / len(words)
    return [WordTiming(start_time + i * step, min(end_time, start_time + (i + 1) * step), w) for i, w in enumerate(words)]


def transcribe_audio(audio_file_path: str) -> list[TranscriptSegment]:
    client = _openai_client()
    with open(audio_file_path, 'rb') as audio_file:
        transcript = client.audio.transcriptions.create(
            model='whisper-1',
            file=audio_file,
            response_format='verbose_json',
            timestamp_granularities=['segment', 'word'],
        )

    raw_segments = getattr(transcript, 'segments', None)
    if raw_segments is None and isinstance(transcript, dict):
        raw_segments = transcript.get('segments', [])

    normalized: list[TranscriptSegment] = []
    for seg in raw_segments or []:
        start_time = float(getattr(seg, 'start', seg.get('start', 0.0)))
        end_time = float(getattr(seg, 'end', seg.get('end', start_time)))
        text = str(getattr(seg, 'text', seg.get('text', ''))).strip()
        if not text:
            continue

        raw_words = getattr(seg, 'words', None)
        if raw_words is None and isinstance(seg, dict):
            raw_words = seg.get('words')

        words = [
            WordTiming(
                start_time=float(getattr(word, 'start', word.get('start', start_time))),
                end_time=float(getattr(word, 'end', word.get('end', end_time))),
                word=str(getattr(word, 'word', word.get('word', ''))).strip(),
            )
            for word in (raw_words or [])
        ]
        if not words:
            words = _word_timings_from_text(start_time, end_time, text)
        normalized.append(TranscriptSegment(start_time, end_time, text, words))
    return normalized


def _extract_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(cleaned)


def score_segments_with_gpt(segments: list[TranscriptSegment]) -> list[RankedClip]:
    if not segments:
        return []
    client = _openai_client()
    segment_payload = [{'start_time': s.start_time, 'end_time': s.end_time, 'text': s.text} for s in segments]
    prompt = f"""
You are a short-form viral video editor.
Return JSON only with key clips[]. Each clip includes start_time,end_time,reasoning,suggested_title,suggested_caption,
and scores: emotional_intensity, controversy_tension, story_completeness, hook_strength, relatability (0-100).
Weights: 30%,20%,20%,15%,15%. Max 8 clips.
Transcript:
{json.dumps(segment_payload)}
""".strip()
    response = client.chat.completions.create(
        model='gpt-4o-mini',
        temperature=0.2,
        messages=[{'role': 'system', 'content': 'Return valid JSON only.'}, {'role': 'user', 'content': prompt}],
    )
    parsed = _extract_json(response.choices[0].message.content or '{"clips": []}')

    ranked: list[RankedClip] = []
    for clip in parsed.get('clips', []):
        scores = clip.get('scores', {})
        virality = (
            float(scores.get('emotional_intensity', 0)) * 0.30
            + float(scores.get('controversy_tension', 0)) * 0.20
            + float(scores.get('story_completeness', 0)) * 0.20
            + float(scores.get('hook_strength', 0)) * 0.15
            + float(scores.get('relatability', 0)) * 0.15
        )
        ranked.append(
            RankedClip(
                start_time=float(clip.get('start_time', 0)),
                end_time=float(clip.get('end_time', 0)),
                virality_score=round(virality, 2),
                reasoning=str(clip.get('reasoning', '')).strip(),
                suggested_title=str(clip.get('suggested_title', '')).strip(),
                suggested_caption=str(clip.get('suggested_caption', '')).strip(),
            )
        )
    ranked.sort(key=lambda c: c.virality_score, reverse=True)
    return ranked[:5]


def _audio_energy_series(audio_path: str, clip_start: float, clip_end: float, hop_ms: int = 100) -> tuple[np.ndarray, np.ndarray]:
    with wave.open(audio_path, 'rb') as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if wf.getnchannels() > 1:
            data = data.reshape(-1, wf.getnchannels()).mean(axis=1)

    start = int(max(0, clip_start) * sr)
    end = int(min(len(data) / sr, clip_end) * sr)
    clip = data[start:end] if end > start else np.array([], dtype=np.float32)
    if clip.size == 0:
        return np.array([0.0]), np.array([0.0])

    hop = max(1, int(sr * hop_ms / 1000))
    energies, times = [], []
    for i in range(0, len(clip), hop):
        chunk = clip[i:i + hop]
        rms = float(np.sqrt(np.mean(np.square(chunk))) if chunk.size else 0.0)
        energies.append(rms)
        times.append(clip_start + i / sr)
    return np.array(times), np.array(energies)


def _detect_faces_frame(frame_bgr: np.ndarray, detector: Any) -> list[tuple[float, float, float, float]]:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    result = detector.process(rgb)
    faces: list[tuple[float, float, float, float]] = []
    h, w = frame_bgr.shape[:2]
    if result.detections:
        for det in result.detections:
            box = det.location_data.relative_bounding_box
            x = max(0.0, box.xmin * w)
            y = max(0.0, box.ymin * h)
            bw = min(w - x, box.width * w)
            bh = min(h - y, box.height * h)
            faces.append((x, y, bw, bh))
    return faces


def _is_speaking(t: float, segments: list[TranscriptSegment]) -> bool:
    return any(s.start_time <= t <= s.end_time for s in segments)


def generate_frame_coordinate_map(
    video_path: str,
    start_time: float,
    end_time: float,
    transcript_segments: list[TranscriptSegment],
    audio_path: str,
) -> list[dict[str, float | int | bool]]:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

    times, energies = _audio_energy_series(audio_path, start_time, end_time)
    energy75 = float(np.percentile(energies, 75)) if energies.size else 0.0
    energy90 = float(np.percentile(energies, 90)) if energies.size else 0.0

    mp_face = mp.solutions.face_detection
    map_rows: list[dict[str, float | int | bool]] = []

    base_crop_h = src_h
    base_crop_w = min(src_w, int(base_crop_h * 9 / 16))
    x_center = src_w / 2

    with mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5) as detector:
        sample_interval = max(1, int(fps / 5))
        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps)

        for fidx in range(start_frame, end_frame, sample_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
            ok, frame = cap.read()
            if not ok:
                continue
            t = fidx / fps
            faces = _detect_faces_frame(frame, detector)
            face_count = len(faces)

            speaking = _is_speaking(t, transcript_segments)
            energy = float(energies[np.argmin(np.abs(times - t))]) if energies.size else 0.0
            active_energy_spike = energy >= energy75
            emotional_spike = energy >= energy90

            target_center = src_w / 2
            if faces:
                # choose most prominent face
                faces_sorted = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)
                chosen = faces_sorted[0]
                target_center = chosen[0] + chosen[2] / 2
                if face_count >= 2 and speaking and active_energy_spike:
                    # two active speakers -> widen crop as much as source allows
                    base_crop_w = min(src_w, max(base_crop_w, int(src_h * 0.75)))
                else:
                    base_crop_w = min(src_w, int(src_h * 9 / 16))

            alpha = 0.22  # smooth transition
            x_center = (1 - alpha) * x_center + alpha * target_center

            zoom = 1.08 if emotional_spike else 1.0
            crop_w = int(max(320, min(src_w, base_crop_w / zoom)))
            crop_h = int(max(568, min(src_h, src_h / zoom)))
            x = int(max(0, min(src_w - crop_w, x_center - crop_w / 2)))
            y = int(max(0, min(src_h - crop_h, (src_h - crop_h) / 2)))

            map_rows.append(
                {
                    'frame': int(fidx),
                    'time': round(t, 3),
                    'x': x,
                    'y': y,
                    'w': crop_w,
                    'h': crop_h,
                    'zoom': round(zoom, 3),
                    'speaker_count': face_count,
                    'active_speaker': bool(speaking and active_energy_spike),
                }
            )

    cap.release()
    if not map_rows:
        map_rows.append({'frame': int(start_time * fps), 'time': round(start_time, 3), 'x': 0, 'y': 0, 'w': base_crop_w, 'h': src_h, 'zoom': 1.0, 'speaker_count': 0, 'active_speaker': False})
    return map_rows


def _segments_to_ass(segments: list[TranscriptSegment], clip_start: float, clip_end: float, ass_path: Path) -> None:
    filtered = [s for s in segments if s.end_time > clip_start and s.start_time < clip_end]
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Arial,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,4,0,2,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def fmt_time(seconds: float) -> str:
        c = max(0, int(round(seconds * 100)))
        return f'{c // 360000}:{(c % 360000) // 6000:02d}:{(c % 6000) // 100:02d}.{c % 100:02d}'

    lines = [header]
    for segment in filtered:
        seg_start = max(0.0, segment.start_time - clip_start)
        seg_end = max(seg_start + 0.05, min(clip_end - clip_start, segment.end_time - clip_start))
        words = [w for w in segment.words if w.word.strip()] or _word_timings_from_text(segment.start_time, segment.end_time, segment.text)
        karaoke = []
        for word in words:
            dur_cs = max(5, int(round((min(segment.end_time, word.end_time) - max(segment.start_time, word.start_time)) * 100)))
            karaoke.append(f'{{\\k{dur_cs}}}{word.word}')
        text = '{\\an2\\fad(80,80)}' + (' '.join(karaoke) if karaoke else f'{{\\k50}}{segment.text}')
        lines.append(f'Dialogue: 0,{fmt_time(seg_start)},{fmt_time(seg_end)},TikTok,,0,0,0,,{text}\n')

    ass_path.write_text(''.join(lines), encoding='utf-8')


def _render_dynamic_vertical_core(
    video_path: str,
    start_time: float,
    end_time: float,
    frame_map: list[dict[str, float | int | bool]],
    output_path: str,
) -> None:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (1080, 1920))

    map_by_frame = {int(row['frame']): row for row in frame_map}
    frames_sorted = sorted(map_by_frame.keys())

    start_frame = int(start_time * fps)
    end_frame = int(end_time * fps)
    current_row = map_by_frame.get(frames_sorted[0])
    ptr = 0

    for fidx in range(start_frame, end_frame):
        while ptr + 1 < len(frames_sorted) and frames_sorted[ptr + 1] <= fidx:
            ptr += 1
            current_row = map_by_frame[frames_sorted[ptr]]

        cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
        ok, frame = cap.read()
        if not ok or current_row is None:
            continue

        x, y = int(current_row['x']), int(current_row['y'])
        w, h = int(current_row['w']), int(current_row['h'])
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            continue
        resized = cv2.resize(crop, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)
        writer.write(resized)

    cap.release()
    writer.release()


def _burn_subtitles_and_mux_audio(core_video: str, source_video: str, ass_path: str, start_time: float, duration: float, output_path: str) -> None:
    _run_cmd([
        'ffmpeg', '-y', '-i', core_video, '-ss', f'{start_time:.3f}', '-t', f'{duration:.3f}', '-i', source_video,
        '-vf', f"subtitles='{ass_path}'", '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'libx264', '-preset', 'medium',
        '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path
    ])


def _render_platform_variant(input_video: str, output_path: str, video_bitrate_k: int, maxrate_k: int) -> None:
    _run_cmd([
        'ffmpeg', '-y', '-i', input_video, '-c:v', 'libx264', '-preset', 'medium', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
        '-b:v', f'{video_bitrate_k}k', '-maxrate', f'{maxrate_k}k', '-bufsize', f'{maxrate_k * 2}k',
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path
    ])


def render_vertical_clip(video_path: str, start_time: float, end_time: float, transcript_segments: list[TranscriptSegment]) -> RenderedClipOutput:
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f'Video file not found: {video_path}')

    duration = max(0.1, end_time - start_time)
    out_dir = Path(tempfile.mkdtemp(prefix='jusclipit-render-'))
    audio_path = extract_audio(video_path)

    frame_map = generate_frame_coordinate_map(video_path, start_time, end_time, transcript_segments, audio_path)
    frame_map_path = out_dir / 'frame_coordinate_map.json'
    frame_map_path.write_text(json.dumps(frame_map, indent=2), encoding='utf-8')

    ass_path = out_dir / 'captions.ass'
    _segments_to_ass(transcript_segments, start_time, end_time, ass_path)

    core_vertical = out_dir / 'core_vertical.mp4'
    final_vertical = out_dir / 'final_vertical.mp4'
    _render_dynamic_vertical_core(video_path, start_time, end_time, frame_map, str(core_vertical))
    _burn_subtitles_and_mux_audio(str(core_vertical), video_path, str(ass_path), start_time, duration, str(final_vertical))

    tiktok_path = out_dir / 'clip_tiktok.mp4'
    reels_path = out_dir / 'clip_reels.mp4'
    shorts_path = out_dir / 'clip_shorts.mp4'

    target_bits = 9_500_000 * 8
    tiktok_v_k = max(1200, int((target_bits / max(duration, 1.0) - 160_000) / 1000))
    tiktok_v_k = min(tiktok_v_k, 9000)

    _render_platform_variant(str(final_vertical), str(tiktok_path), tiktok_v_k, max(tiktok_v_k + 500, 1800))
    _render_platform_variant(str(final_vertical), str(reels_path), 7000, 8500)
    _render_platform_variant(str(final_vertical), str(shorts_path), 7500, 9000)

    return RenderedClipOutput(
        tiktok_path=str(tiktok_path),
        reels_path=str(reels_path),
        shorts_path=str(shorts_path),
        final_vertical_path=str(final_vertical),
        frame_coordinate_map_path=str(frame_map_path),
        duration=round(duration, 3),
        resolution='1080x1920',
    )


def run_ai_clipping_pipeline(video_file_path: str) -> list[RankedClip]:
    audio_file_path = extract_audio(video_file_path)
    segments = transcribe_audio(audio_file_path)
    return score_segments_with_gpt(segments)
