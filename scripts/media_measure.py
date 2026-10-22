"""Замер конвейера видео на ЭТОЙ машине — калибровка юнита signaris-hub-media.

Что меряет (по фазам, строка JSON на фазу): паспорт файла, выгрузка звука
16 кГц, замер шума и тишины, первый проход loudnorm, рендер чистовика с
`-threads 1` и `2` (можно ограничить `--render-seconds`), сборка всех файлов в
один (перекодирование частей + concat), при `--stt-url` — расшифровка первых
кусков через существующую ручку `/transcribe` (RTF и ожидание замка).
Параллельно раз в 0,5 с опрашивается API (`--api-url`) — p95 латентности в
каждой фазе показывает, душит ли рендер прод; и `memory.current` своей
cgroup — пик по фазе (ffmpeg-дети в той же группе).

Запуск на VPS — во ВРЕМЕННОМ юните с окружением боевого воркера, но с запасом
памяти и без MemoryHigh:

    systemd-run --wait --pipe --uid=signaris -p MemoryMax=2G -p CPUWeight=20 -p Nice=10 \\
      -p EnvironmentFile=/opt/signaris-hub-staging/.env \\
      -p WorkingDirectory=/opt/signaris-hub-staging \\
      /opt/signaris-hub-staging/.venv/bin/python scripts/media_measure.py \\
      --api-url http://127.0.0.1:5059/api/env --workdir /tmp/media-measure \\
      --render-seconds 300 /opt/signaris-hub/attachments/<tenant>/<task>/*.mp4

Текст расшифровки не печатается — только длина. Лимиты юнита (`MemoryMax`,
`-threads`) фиксируются ТОЛЬКО по этому замеру (docs/DEPLOY.md §«Конвейер видео»).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.learn_media import mp4_duration_seconds, mp4_has_faststart  # noqa: E402
from app.services.media import chunking, edl, ffmpeg, merge, render, silence  # noqa: E402
from app.services.media.probe import Probe, parse_ffprobe  # noqa: E402

MB = 1024 * 1024
CACHE_HEADROOM_MB = 300


def _cgroup_dir() -> Path | None:
    try:
        line = Path("/proc/self/cgroup").read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    path = Path("/sys/fs/cgroup") / line.split("::", 1)[-1].lstrip("/")
    return path if path.is_dir() else None


class Sampler:
    """Фоновый поток: латентность API и `memory.current` cgroup раз в 0,5 с."""

    def __init__(self, api_url: str | None, cgroup: Path | None) -> None:
        self.api_url = api_url
        self.cgroup = cgroup
        self.latencies: list[float] = []
        self.mem: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        import httpx

        client = httpx.Client(timeout=5)
        while not self._stop.is_set():
            if self.api_url:
                t0 = time.monotonic()
                try:
                    client.get(self.api_url)
                    self.latencies.append((time.monotonic() - t0) * 1000)
                except httpx.HTTPError:
                    self.latencies.append(5000.0)
            if self.cgroup is not None:
                try:
                    self.mem.append(int((self.cgroup / "memory.current").read_text()))
                except (OSError, ValueError):
                    pass
            self._stop.wait(0.5)

    def start(self) -> None:
        self._thread.start()

    def reset(self) -> None:
        self.latencies, self.mem = [], []

    def snapshot(self) -> dict:
        out: dict = {}
        if self.latencies:
            lat = sorted(self.latencies)
            out["api_p50_ms"] = round(lat[len(lat) // 2], 1)
            out["api_p95_ms"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1)
            out["api_max_ms"] = round(lat[-1], 1)
        if self.mem:
            out["mem_peak_mb"] = round(max(self.mem) / MB)
        return out

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


def emit(**row) -> None:
    print(json.dumps(row, ensure_ascii=False))  # noqa: T201 — отчёт в stdout


async def phase(name: str, sampler: Sampler, coro, **extra) -> object:
    sampler.reset()
    t0 = time.monotonic()
    try:
        result = await coro
        emit(phase=name, seconds=round(time.monotonic() - t0, 1), **extra, **sampler.snapshot())
        return result
    except Exception as exc:  # noqa: BLE001 — замер продолжается
        emit(phase=name, seconds=round(time.monotonic() - t0, 1), error=str(exc)[:300], **extra)
        return None


async def measure_file(path: Path, args, sampler: Sampler, bins: tuple[str, str]) -> Probe | None:
    ffbin, probebin = bins
    work = Path(args.workdir) / path.stem
    work.mkdir(parents=True, exist_ok=True)
    name = path.name

    async def do_probe() -> Probe:
        return parse_ffprobe(await ffmpeg.probe_json(path, bin_path=probebin))

    probe = await phase("probe", sampler, do_probe(), file=name)
    if probe is None:
        return None
    emit(
        phase="probe_info",
        file=name,
        duration_sec=round(probe.duration, 1),
        size=list(probe.display_size or ()),
        fps=probe.fps,
        vcodec=probe.vcodec,
        acodec=probe.acodec,
        mb=round((probe.size_bytes or 0) / MB),
    )
    wav = work / "audio16k.wav"
    await phase(
        "extract_wav",
        sampler,
        ffmpeg.run(render.audio16k_args(path, wav), bin_path=ffbin, timeout_sec=3600),
        file=name,
    )
    if not wav.exists():
        return probe

    async def analyze() -> dict:
        nf_log = await ffmpeg.run(
            render.noise_floor_args(wav),
            bin_path=ffbin,
            timeout_sec=3600,
            capture_stderr=True,
            loglevel="info",
        )
        floor = silence.parse_noise_floor(nf_log)
        thr = silence.threshold_db(floor)
        sd_log = await ffmpeg.run(
            render.silencedetect_args(wav, threshold_db=thr, min_pause=1.5),
            bin_path=ffbin,
            timeout_sec=3600,
            capture_stderr=True,
            loglevel="info",
        )
        sil = silence.parse_silencedetect(sd_log, duration=probe.duration)
        removed = edl.compress_pauses(sil, keep=0.7, margin=0.2)
        return {
            "noise_floor_db": floor,
            "threshold_db": thr,
            "pauses": len(sil),
            "silence_sec": round(edl.total(sil), 1),
            "removed_sec": round(edl.total(removed), 1),
            "_removed": removed,
            "_silences": sil,
        }

    analysis = await phase("silence", sampler, analyze(), file=name)
    if analysis is None:
        return probe
    emit(
        phase="silence_info",
        file=name,
        **{k: v for k, v in analysis.items() if not k.startswith("_")},
    )
    removed = analysis["_removed"]
    kept = edl.kept_intervals(removed, probe.duration)
    if args.render_seconds:
        kept = edl.intersect(kept, [(0.0, float(args.render_seconds))])

    async def pass1() -> dict:
        log = await ffmpeg.run(
            render.loudnorm_pass1_args(path, kept, denoise="", i=-16, tp=-1.5, lra=11),
            bin_path=ffbin,
            timeout_sec=3600,
            capture_stderr=True,
            loglevel="info",
        )
        return silence.parse_loudnorm_json(log)

    measured = await phase(
        "loudnorm_pass1", sampler, pass1(), file=name, seconds_in=round(edl.total(kept), 1)
    )
    if measured is None:
        return probe
    emit(phase="loudnorm_info", file=name, **{k: round(v, 2) for k, v in measured.items()})

    for threads in args.threads:
        script = work / f"filters-{threads}.txt"
        script.write_text(
            render.filter_script(
                kept,
                denoise=render.denoise_filter("afftdn"),
                i=-16,
                tp=-1.5,
                lra=11,
                measured=measured,
                fps=min(probe.fps or 30, 30),
                scale_cap=1080,
            )
        )
        out = work / f"clean-{threads}.mp4"

        async def do_render(script=script, out=out, threads=threads) -> dict:
            speeds: list[float] = []

            async def on_progress(p: ffmpeg.Progress) -> None:
                if p.speed:
                    speeds.append(p.speed)

            await ffmpeg.run(
                render.render_args(path, out, script, threads=threads),
                bin_path=ffbin,
                timeout_sec=6 * 3600,
                on_progress=on_progress,
            )
            return {
                "output_sec": round(mp4_duration_seconds(out) or 0, 1),
                "faststart": mp4_has_faststart(out),
                "output_mb": round(out.stat().st_size / MB, 1),
                "speed_median": round(statistics.median(speeds), 2) if speeds else None,
            }

        info = await phase(
            f"render_t{threads}",
            sampler,
            do_render(),
            file=name,
            seconds_in=round(edl.total(kept), 1),
        )
        if info:
            emit(phase=f"render_t{threads}_info", file=name, **info)
        if not args.keep:
            out.unlink(missing_ok=True)
    if args.stt_url:
        await measure_stt(wav, analysis["_silences"], probe.duration, args, sampler, name)
    return probe


async def measure_stt(
    wav: Path, silences, duration: float, args, sampler: Sampler, name: str
) -> None:
    import httpx

    plan = chunking.plan_chunks(duration, silences, target=50, max_len=55, min_len=20)
    plan = plan[: args.stt_chunks]
    emit(phase="stt_plan", file=name, chunks=len(plan), lens=[round(e - s, 1) for s, e in plan])
    with wave.open(str(wav), "rb") as src:
        rate = src.getframerate()
    async with httpx.AsyncClient(timeout=180) as client:
        for i, (blob, (s, e)) in enumerate(
            zip(chunking.read_wav_slices(wav, plan), plan, strict=True)
        ):
            t0 = time.monotonic()
            try:
                resp = await client.post(
                    f"{args.stt_url.rstrip('/')}/transcribe",
                    content=blob,
                    headers={"Content-Type": "audio/wav"},
                )
                text = str(resp.json().get("text") or "")
                status = resp.status_code
            except (httpx.HTTPError, ValueError) as exc:
                text, status = "", f"error:{type(exc).__name__}"
            took = time.monotonic() - t0
            emit(
                phase="stt_chunk",
                file=name,
                i=i,
                audio_sec=round(e - s, 1),
                http=status,
                seconds=round(took, 1),
                rtf=round(took / max(0.1, e - s), 2),
                text_chars=len(text),
                rate=rate,
            )
            await asyncio.sleep(1.0)


async def measure_merge(
    paths: list[Path], probes: list[Probe], args, sampler: Sampler, bins
) -> None:
    ffbin, probebin = bins
    work = Path(args.workdir) / "merge"
    work.mkdir(parents=True, exist_ok=True)
    target = merge.plan_target(probes, fps_cap=30, scale_cap=1080)
    emit(phase="merge_target", w=target.width, h=target.height, fps=target.fps, parts=len(paths))
    parts: list[Path] = []
    for i, (path, probe) in enumerate(zip(paths, probes, strict=True)):
        trim_end = float(args.render_seconds) if args.render_seconds else None
        mode = merge.part_mode(probe, target, trim_end=trim_end)
        dst = work / f"part-{i:02d}.mp4"

        async def do_part(path=path, probe=probe, dst=dst, mode=mode, trim_end=trim_end) -> dict:
            await ffmpeg.run(
                merge.part_args(
                    path, dst, probe, target, mode=mode, trim_end=trim_end, threads=args.threads[0]
                ),
                bin_path=ffbin,
                timeout_sec=6 * 3600,
            )
            return {"mode": mode, "output_mb": round(dst.stat().st_size / MB, 1)}

        info = await phase(
            f"merge_part{i}",
            sampler,
            do_part(),
            file=path.name,
            seconds_in=round(merge.part_duration(probe, trim_end=trim_end), 1),
        )
        if info:
            parts.append(dst)
            emit(phase=f"merge_part{i}_info", file=path.name, **info)
    if len(parts) < 2:
        return
    lst = work / "concat.txt"
    lst.write_text(merge.concat_list(parts))
    out = work / "merged.mp4"

    async def do_concat() -> dict:
        await ffmpeg.run(merge.concat_args(lst, out), bin_path=ffbin, timeout_sec=3600)
        return {
            "output_sec": round(mp4_duration_seconds(out) or 0, 1),
            "faststart": mp4_has_faststart(out),
            "output_mb": round(out.stat().st_size / MB, 1),
        }

    info = await phase("merge_concat", sampler, do_concat())
    if info:
        emit(phase="merge_info", **info)
    if not args.keep:
        for p in [*parts, out]:
            p.unlink(missing_ok=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--workdir", type=Path, default=Path("/tmp/media-measure"))  # noqa: S108
    parser.add_argument("--api-url", default=None, help="например http://127.0.0.1:5059/api/env")
    parser.add_argument("--threads", default="1,2", help="значения -threads для рендера")
    parser.add_argument(
        "--render-seconds",
        type=float,
        default=0.0,
        help="рендерить только первые N секунд (0 = весь файл)",
    )
    parser.add_argument("--stt-url", default=None, help="юнит STT для замера кусков")
    parser.add_argument("--stt-chunks", type=int, default=3)
    parser.add_argument("--skip-merge", action="store_true")
    parser.add_argument("--keep", action="store_true", help="не удалять результаты")
    args = parser.parse_args()
    args.threads = [int(x) for x in args.threads.split(",") if x]
    ffbin, probebin = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffbin or not probebin:
        emit(phase="error", error="ffmpeg/ffprobe не найдены")
        return 1
    cg = _cgroup_dir()
    emit(
        phase="start",
        ffmpeg=ffbin,
        cgroup=str(cg) if cg else None,
        api_url=args.api_url,
        threads=args.threads,
        files=[p.name for p in args.files],
    )
    sampler = Sampler(args.api_url, cg)
    sampler.start()
    sampler.reset()
    await asyncio.sleep(3)
    emit(phase="idle_baseline", **sampler.snapshot())
    probes: list[Probe] = []
    paths: list[Path] = []
    try:
        for path in args.files:
            probe = await measure_file(path, args, sampler, (ffbin, probebin))
            if probe is not None:
                probes.append(probe)
                paths.append(path)
        if len(paths) >= 2 and not args.skip_merge:
            await measure_merge(paths, probes, args, sampler, (ffbin, probebin))
    finally:
        sampler.stop()
    peak_mb = None
    if cg is not None:
        try:
            peak_mb = round(int((cg / "memory.peak").read_text()) / MB)
        except (OSError, ValueError):
            peak_mb = None
    emit(
        phase="summary",
        cgroup_peak_mb=peak_mb,
        recommended_memory_max_mb=(peak_mb + CACHE_HEADROOM_MB) if peak_mb else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
