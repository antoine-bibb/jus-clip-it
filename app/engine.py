from __future__ import annotations

from pathlib import Path
import subprocess
import json
import math
from typing import Dict, List, Any, Tuple, Optional
import tempfile
import os
import wave

import numpy as np
import cv2
import whisper


# ----------------------------
# Shell helpers
# ----------------------------
def run(cmd: List[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "Command failed")
    return p.stdout


def ffprobe_duration(path: str) -> float:
    out = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ])
    try:
        return float(out.strip())
    except Exception:
        return 0.0


def ffprobe_dims(path: str) -> Tuple[int, int]:
    out = run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        path
    ]).strip()
    try:
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return (0, 0)


# ----------------------------
# Clip + thumbnail
# ----------------------------
def cut_clip_copy(in_path: str, out_path: str, start: float, duration: float):
    run([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", in_path,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        out_path
    ])


def cut_clip_reencode(in_path: str, out_path: str, start: float, duration: float, vf: str):
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", in_path,
        "-t", f"{duration:.3f}",
    ]
    if vf:
        cmd += ["-vf", vf]

    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        out_path
    ]
    run(cmd)


def make_thumbnail(in_path: str, out_path: str, at_seconds: float = 0.5):
    run([
        "ffmpeg", "-y",
        "-ss", f"{at_seconds:.3f}",
        "-i", in_path,
        "-vframes", "1",
        "-q:v", "2",
        out_path
    ])


# ----------------------------
# Crop filter builder
# ----------------------------
def build_crop_filter(
    in_w: int,
    in_h: int,
    out_aspect: str,
    crop_mode: str,
    crop_x: float,
    crop_y: float,
    crop_w: float,
    crop_h: float,
    out_w: int,
    out_h: int,
) -> str:
    if out_aspect == "9:16":
        target_ar = 9 / 16
    elif out_aspect == "1:1":
        target_ar = 1.0
    elif out_aspect == "16:9":
        target_ar = 16 / 9
    else:
        target_ar = in_w / in_h if in_h else 1.0

    filters: List[str] = []

    if crop_mode in ("center", "left", "right"):
        in_ar = (in_w / in_h) if in_h else 1.0

        if in_ar > target_ar:
            crop_h_px = in_h
            crop_w_px = int(round(in_h * target_ar))
            if crop_mode == "left":
                x = 0
            elif crop_mode == "right":
                x = max(0, in_w - crop_w_px)
            else:
                x = max(0, int(round((in_w - crop_w_px) / 2)))
            y = 0
        else:
            crop_w_px = in_w
            crop_h_px = int(round(in_w / target_ar))
            x = 0
            y = max(0, int(round((in_h - crop_h_px) / 2)))

        filters.append(f"crop={crop_w_px}:{crop_h_px}:{x}:{y}")

    elif crop_mode == "manual":
        cx = max(0.0, min(100.0, float(crop_x)))
        cy = max(0.0, min(100.0, float(crop_y)))
        cw = max(10.0, min(100.0, float(crop_w)))
        ch = max(10.0, min(100.0, float(crop_h)))

        crop_w_px = int(round(in_w * (cw / 100.0)))
        crop_h_px = int(round(in_h * (ch / 100.0)))

        center_x_px = int(round(in_w * (cx / 100.0)))
        center_y_px = int(round(in_h * (cy / 100.0)))

        x = max(0, min(in_w - crop_w_px, center_x_px - crop_w_px // 2))
        y = max(0, min(in_h - crop_h_px, center_y_px - crop_h_px // 2))

        filters.append(f"crop={crop_w_px}:{crop_h_px}:{x}:{y}")

    if out_w > 0 and out_h > 0:
        filters.append(f"scale={out_w}:{out_h}")

    return ",".join(filters) if filters else ""


# ----------------------------
# Audio mux helper
# ----------------------------
def mux_audio_from_source(video_no_audio: str, audio_source: str, out_path: str):
    run([
        "ffmpeg", "-y",
        "-i", video_no_audio,
        "-i", audio_source,
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "160k",
        out_path
    ])


# ----------------------------
# Smart Follow helpers
# ----------------------------
def _load_haar_face_cascades():
    frontal_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    profile_path = cv2.data.haarcascades + "haarcascade_profileface.xml"

    frontal = cv2.CascadeClassifier(frontal_path)
    profile = cv2.CascadeClassifier(profile_path)

    if frontal.empty():
        raise RuntimeError("Could not load OpenCV frontal face cascade.")
    if profile.empty():
        profile = None

    return frontal, profile


def _extract_wav_mono_16k(src_video: str, out_wav: str):
    run([
        "ffmpeg", "-y",
        "-i", src_video,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        out_wav
    ])


def _load_wav_rms_per_frame(wav_path: str, fps: float) -> np.ndarray:
    with wave.open(wav_path, "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if sr <= 0 or fps <= 0:
        return np.zeros(1, dtype=np.float32)

    samples_per_frame = int(sr / fps)
    if samples_per_frame <= 0:
        return np.zeros(1, dtype=np.float32)

    total_frames = max(1, int(len(audio) / samples_per_frame))
    rms = np.zeros(total_frames, dtype=np.float32)

    for i in range(total_frames):
        a = i * samples_per_frame
        b = min(len(audio), a + samples_per_frame)
        chunk = audio[a:b]
        rms[i] = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0

    return rms


def _rms_threshold(rms: np.ndarray) -> float:
    if rms is None or len(rms) == 0:
        return 0.02
    med = float(np.median(rms))
    p90 = float(np.percentile(rms, 90))
    return max(0.015, min(0.08, (med * 2.2 + p90 * 0.25)))


def smart_follow_crop(
    in_clip_path: str,
    out_clip_path: str,
    out_w: int,
    out_h: int,
    target_aspect: str = "9:16",
    sample_fps: int = 10,
    smooth: float = 0.18,
    hold_frames: int = 24,
    mode: str = "speaker",  # "face" or "speaker"
    exclude_right_pct: float = 0.0,  # 0.40 = ignore faces in right 40% of frame
    deadzone_px: int = 28,
    min_switch_frames: int = 16,
    max_move_px_per_sec: int = 320,
    debug: bool = False,
):
    """
    ✅ Stabilized follow:
    - deadzone: won't move unless target shifts enough
    - min_switch_frames: won't switch faces too often
    - max_move_px_per_sec: prevents whip-pans
    - hold_frames: holds target for a bit even if detection flickers
    """

    out_w = (int(out_w) // 2) * 2
    out_h = (int(out_h) // 2) * 2

    cap = cv2.VideoCapture(in_clip_path)
    if not cap.isOpened():
        raise RuntimeError("Could not open clip for smart crop")

    in_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    in_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)

    if in_w <= 0 or in_h <= 0:
        cap.release()
        raise RuntimeError("Invalid input dimensions for smart crop")

    if target_aspect == "9:16":
        target_ar = 9 / 16
    elif target_aspect == "1:1":
        target_ar = 1.0
    elif target_aspect == "16:9":
        target_ar = 16 / 9
    else:
        target_ar = (out_w / out_h) if out_h else (in_w / in_h)

    in_ar = in_w / in_h
    if in_ar > target_ar:
        crop_h = in_h
        crop_w = int(round(in_h * target_ar))
    else:
        crop_w = in_w
        crop_h = int(round(in_w / target_ar))

    tmp_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_video, fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Could not open VideoWriter (mp4v).")

    frontal, profile = _load_haar_face_cascades()
    step = max(1, int(round(fps / max(1, sample_fps))))

    cx_s = in_w / 2.0
    cy_s = in_h / 2.0

    frame_idx = 0
    last_det: Optional[Tuple[float, float]] = None
    hold = 0
    frames_since_switch = 999999

    rms = None
    thr = None
    wav_tmp = None
    if mode == "speaker":
        try:
            wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
            _extract_wav_mono_16k(in_clip_path, wav_tmp)
            rms = _load_wav_rms_per_frame(wav_tmp, fps=fps)
            thr = _rms_threshold(rms)
        except Exception:
            mode = "face"
            rms = None
            thr = None

    detect_target_w = 640
    scale = detect_target_w / in_w if in_w > detect_target_w else 1.0

    prev_gray_full = None

    def _faces_detect(frame_bgr):
        if scale != 1.0:
            small = cv2.resize(frame_bgr, (int(in_w * scale), int(in_h * scale)), interpolation=cv2.INTER_AREA)
        else:
            small = frame_bgr

        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        faces = frontal.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(30, 30))

        if (faces is None or len(faces) == 0) and profile is not None:
            faces_p = profile.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(30, 30))
            gray_flip = cv2.flip(gray, 1)
            faces_pf = profile.detectMultiScale(gray_flip, scaleFactor=1.08, minNeighbors=4, minSize=(30, 30))

            faces_list = []
            if faces_p is not None and len(faces_p) > 0:
                faces_list.extend(list(faces_p))
            if faces_pf is not None and len(faces_pf) > 0:
                for (x, y, w, h) in faces_pf:
                    x_unflip = gray.shape[1] - (x + w)
                    faces_list.append((x_unflip, y, w, h))
            faces = faces_list

        full_faces = []
        if faces is not None and len(faces) > 0:
            for (x, y, w, h) in faces:
                if scale != 1.0:
                    x = x / scale
                    y = y / scale
                    w = w / scale
                    h = h / scale
                full_faces.append((float(x), float(y), float(w), float(h)))

        # ✅ exclude right-side faces (for shared-screen layouts)
        if exclude_right_pct > 0.0:
            cutoff = in_w * (1.0 - exclude_right_pct)
            full_faces = [fb for fb in full_faces if (fb[0] + fb[2] / 2.0) < cutoff]

        return full_faces

    def _mouth_motion_score(gray_full, prev_gray_full, face_box):
        if prev_gray_full is None:
            return 0.0

        x, y, w, h = face_box
        mx0 = int(max(0, x))
        my0 = int(max(0, y + h * 0.55))
        mx1 = int(min(in_w, x + w))
        my1 = int(min(in_h, y + h))

        if mx1 <= mx0 or my1 <= my0:
            return 0.0

        cur = gray_full[my0:my1, mx0:mx1]
        prv = prev_gray_full[my0:my1, mx0:mx1]
        if cur.size == 0 or prv.size == 0:
            return 0.0

        diff = cv2.absdiff(cur, prv)
        return float(np.mean(diff))

    def _pick_face(full_faces, gray_full):
        # biggest face bias + speaker motion bias
        best = None
        best_score = -1e18

        for (x, y, w, h) in full_faces:
            fx = x + w / 2.0
            fy = y + h / 2.0
            area = w * h

            if mode == "speaker" and rms is not None and thr is not None:
                rms_idx = min(len(rms) - 1, frame_idx)
                voiced = rms[rms_idx] >= thr
                mot = _mouth_motion_score(gray_full, prev_gray_full, (x, y, w, h))
                score = (mot * (8.0 if voiced else 2.0)) + (area * 0.00002)
            else:
                score = area

            # stability bias: prefer near current center
            score -= 0.0008 * ((fx - cx_s) ** 2 + (fy - cy_s) ** 2)

            if score > best_score:
                best_score = score
                best = (fx, fy)

        return best

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if frame_idx % step == 0:
                faces = _faces_detect(frame)

                if faces and hold <= 0:
                    candidate = _pick_face(faces, gray_full)

                    # ✅ don’t switch too frequently
                    if candidate and frames_since_switch >= min_switch_frames:
                        last_det = candidate
                        hold = hold_frames
                        frames_since_switch = 0
                else:
                    hold = max(0, hold - 1)

            # ✅ smooth + deadzone + max speed clamp
            if last_det is not None:
                tx, ty = last_det

                dx = tx - cx_s
                dy = ty - cy_s

                # deadzone
                if abs(dx) < deadzone_px:
                    dx = 0.0
                if abs(dy) < deadzone_px:
                    dy = 0.0

                # smooth step
                cx_s = cx_s + smooth * dx
                cy_s = cy_s + smooth * dy

                # clamp movement per second
                max_per_frame = (max_move_px_per_sec / max(1.0, fps))
                cx_s = float(np.clip(cx_s, cx_s - max_per_frame, cx_s + max_per_frame))
                cy_s = float(np.clip(cy_s, cy_s - max_per_frame, cy_s + max_per_frame))

            # crop
            x0 = int(round(cx_s - crop_w / 2.0))
            y0 = int(round(cy_s - crop_h / 2.0))
            x0 = max(0, min(in_w - crop_w, x0))
            y0 = max(0, min(in_h - crop_h, y0))

            cropped = frame[y0:y0 + crop_h, x0:x0 + crop_w]
            resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_AREA)
            writer.write(resized)

            prev_gray_full = gray_full
            frame_idx += 1
            frames_since_switch += 1

    finally:
        cap.release()
        writer.release()
        if wav_tmp and os.path.exists(wav_tmp):
            try:
                os.remove(wav_tmp)
            except Exception:
                pass

    mux_audio_from_source(tmp_video, in_clip_path, out_clip_path)


# ----------------------------
# Job creation
# ----------------------------
def create_job(
    job_dir: Path,
    clip_len: int = 25,
    max_clips: int = 8,
    out_aspect: str = "9:16",
    out_w: int = 1080,
    out_h: int = 1920,
    crop_mode: str = "center",
    crop_x: float = 50.0,
    crop_y: float = 50.0,
    crop_w: float = 56.0,
    crop_h: float = 100.0,

    # follow tuning
    follow_sample_fps: int = 10,
    follow_smooth: float = 0.18,
    follow_hold_frames: int = 24,
    follow_deadzone_px: int = 28,
    follow_min_switch_frames: int = 16,
    follow_max_move_px_per_sec: int = 320,
):
    job_json = job_dir / "job.json"
    in_path = job_dir / "input.mp4"

    dur = ffprobe_duration(str(in_path))
    if dur <= 0:
        raise RuntimeError("Could not read video duration (ffprobe failed)")

    in_w, in_h = ffprobe_dims(str(in_path))

    count = min(max_clips, max(1, int(dur // clip_len)))
    if count == 1:
        starts = [0.0]
    else:
        step = max(1.0, (dur - clip_len) / (count - 1))
        starts = [i * step for i in range(count)]

    do_crop = (crop_mode != "none") or (out_w > 0 and out_h > 0)

    clips = []
    for i, s in enumerate(starts):
        out_mp4 = job_dir / f"clip_{i}.mp4"

        if crop_mode in ("smart", "speaker"):
            # base clip fast copy
            cut_clip_copy(str(in_path), str(out_mp4), s, clip_len)

            tmp_out = job_dir / f"clip_{i}.{crop_mode}.mp4"
            sw = out_w or 1080
            sh = out_h or 1920

            # Optional: for “shared screen on right”, ignore right side
            exclude_right_pct = 0.0
            # If you know your layout usually has browser on right, set 0.40
            # exclude_right_pct = 0.40

            smart_follow_crop(
                in_clip_path=str(out_mp4),
                out_clip_path=str(tmp_out),
                out_w=sw,
                out_h=sh,
                target_aspect=(out_aspect or "9:16"),
                sample_fps=follow_sample_fps,
                smooth=follow_smooth,
                hold_frames=follow_hold_frames,
                mode=("speaker" if crop_mode == "speaker" else "face"),
                exclude_right_pct=exclude_right_pct,
                deadzone_px=follow_deadzone_px,
                min_switch_frames=follow_min_switch_frames,
                max_move_px_per_sec=follow_max_move_px_per_sec,
                debug=False,
            )

            out_mp4.unlink(missing_ok=True)
            tmp_out.rename(out_mp4)

        else:
            if do_crop and in_w > 0 and in_h > 0:
                vf = build_crop_filter(
                    in_w=in_w,
                    in_h=in_h,
                    out_aspect=out_aspect,
                    crop_mode=crop_mode,
                    crop_x=crop_x,
                    crop_y=crop_y,
                    crop_w=crop_w,
                    crop_h=crop_h,
                    out_w=out_w,
                    out_h=out_h,
                )
                cut_clip_reencode(str(in_path), str(out_mp4), s, clip_len, vf=vf)
            else:
                cut_clip_copy(str(in_path), str(out_mp4), s, clip_len)

        thumb = job_dir / f"thumb_{i}.jpg"
        make_thumbnail(str(out_mp4), str(thumb), at_seconds=min(0.5, clip_len / 2))

        clips.append({
            "index": i,
            "start": float(s),
            "end": float(min(dur, s + clip_len)),
            "filename": out_mp4.name,
            "thumb": thumb.name
        })

    job = {
        "status": "done",
        "clip_len": clip_len,
        "max_clips": max_clips,
        "clips_created": len(clips),
        "clips": clips,
        "crop": {
            "out_aspect": out_aspect,
            "out_w": out_w,
            "out_h": out_h,
            "crop_mode": crop_mode,
            "crop_x": crop_x,
            "crop_y": crop_y,
            "crop_w": crop_w,
            "crop_h": crop_h,
        }
    }
    job_json.write_text(json.dumps(job, indent=2), encoding="utf-8")


# ----------------------------
# Job helpers
# ----------------------------
def get_job(job_dir: Path) -> Dict[str, Any]:
    job_json = job_dir / "job.json"
    if not job_json.exists():
        return {"status": "missing"}
    return json.loads(job_json.read_text(encoding="utf-8"))


def list_clips(job_dir: Path) -> List[Dict[str, Any]]:
    job = get_job(job_dir)
    return job.get("clips", [])


def get_clip_paths(job_dir: Path, idx: int) -> Dict[str, Path]:
    return {
        "clip_mp4": job_dir / f"clip_{idx}.mp4",
        "words_json": job_dir / f"clip_{idx}.words.json",
        "srt": job_dir / f"clip_{idx}.srt",
        "thumb": job_dir / f"thumb_{idx}.jpg",
    }


# ----------------------------
# Whisper word timestamps + SRT
# ----------------------------
def transcribe_words_whisper(clip_path: str, model_size: str = "base") -> List[Dict[str, Any]]:
    model = whisper.load_model(model_size)

    result = model.transcribe(
        clip_path,
        word_timestamps=True,
        fp16=False
    )

    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            txt = (w.get("word") or "").strip()
            if not txt:
                continue
            words.append({
                "word": txt,
                "start": float(w.get("start", 0)),
                "end": float(w.get("end", 0))
            })

    srt_lines = []

    def fmt(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t - math.floor(t)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    idx = 1
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        srt_lines.append(str(idx))
        srt_lines.append(f"{fmt(seg['start'])} --> {fmt(seg['end'])}")
        srt_lines.append(text)
        srt_lines.append("")
        idx += 1

    clip_p = Path(clip_path)
    srt_path = clip_p.parent / f"{clip_p.stem}.srt"
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

    return words
