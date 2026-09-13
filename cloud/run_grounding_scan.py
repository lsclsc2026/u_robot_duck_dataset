#!/usr/bin/env python3
"""Run a reproducible Grounding DINO prompt/threshold scan and build visual reports."""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_PROMPTS = ["yellow rubber duck", "rubber duck", "yellow duck toy"]
COLORS = [(255, 65, 54), (46, 204, 64), (0, 116, 217), (255, 133, 27)]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
        help="Benchmark directory containing grounding_dino/<split>/images",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        required=True,
        help="Local Hugging Face model directory (offline)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for predictions and visual reports",
    )
    parser.add_argument("--split", choices=["calibration", "holdout"], default="calibration")
    parser.add_argument("--prompts", nargs="+", default=DEFAULT_PROMPTS)
    parser.add_argument(
        "--thresholds", nargs="+", type=float, default=[0.15, 0.20, 0.25, 0.30, 0.35]
    )
    parser.add_argument("--text-threshold", type=float, default=0.15)
    parser.add_argument("--visual-threshold", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=0, help="0 means all images")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def post_process(processor, outputs, input_ids, image: Image.Image, box_threshold: float, text_threshold: float):
    kwargs = dict(
        outputs=outputs,
        input_ids=input_ids,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
        target_sizes=[(image.height, image.width)],
    )
    result = processor.post_process_grounded_object_detection(**kwargs)[0]
    labels = result.get("text_labels", result.get("labels", []))
    return result["boxes"].detach().cpu(), result["scores"].detach().cpu(), list(labels)


def draw_overlay(image: Image.Image, boxes, scores, labels, prompt: str) -> Image.Image:
    canvas = image.copy().convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (box, score) in enumerate(zip(boxes, scores)):
        x1, y1, x2, y2 = [float(value) for value in box]
        x1 = min(max(x1, 0.0), float(canvas.width - 1))
        y1 = min(max(y1, 0.0), float(canvas.height - 1))
        x2 = min(max(x2, x1), float(canvas.width - 1))
        y2 = min(max(y2, y1), float(canvas.height - 1))
        color = COLORS[index % len(COLORS)]
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        label = str(labels[index]) if index < len(labels) else prompt
        text = f"{label} {float(score):.3f}"
        left, top, right, bottom = draw.textbbox((x1, y1), text, font=font)
        text_top = max(0.0, y1 - (bottom - top) - 6)
        text_right = min(float(canvas.width - 1), x1 + (right - left) + 6)
        text_bottom = max(text_top, y1)
        draw.rectangle((x1, text_top, text_right, text_bottom), fill=color)
        draw.text((x1 + 3, text_top + 2), text, fill="white", font=font)
    return canvas


def make_contact_sheet(paths: list[Path], output: Path, columns: int = 4) -> None:
    if not paths:
        return
    thumb_w, thumb_h, caption_h = 360, 203, 22
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + caption_h)), "#101826")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, path in enumerate(paths):
        with Image.open(path) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((thumb_w, thumb_h))
        x = (i % columns) * thumb_w
        y = (i // columns) * (thumb_h + caption_h)
        sheet.paste(thumb, (x, y))
        draw.text((x + 4, y + thumb_h + 4), path.name, fill="white", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=90)


def build_html(output_dir: Path, summary: dict, overlay_paths: dict[str, list[Path]]) -> None:
    rows = []
    for prompt, threshold_data in summary["prompts"].items():
        for threshold, values in threshold_data.items():
            rows.append(
                "<tr>"
                f"<td>{html.escape(prompt)}</td><td>{threshold}</td>"
                f"<td>{values['images_with_detections']}/{summary['image_count']}</td>"
                f"<td>{values['total_detections']}</td>"
                f"<td>{values['max_detections_in_image']}</td>"
                "</tr>"
            )
    galleries = []
    for prompt, paths in overlay_paths.items():
        items = "".join(
            f'<a href="{html.escape(str(path.relative_to(output_dir)))}">'
            f'<img loading="lazy" src="{html.escape(str(path.relative_to(output_dir)))}"></a>'
            for path in paths
        )
        galleries.append(f"<h2>{html.escape(prompt)}</h2><div class='grid'>{items}</div>")
    document = f"""<!doctype html><meta charset="utf-8"><title>Grounding DINO scan</title>
<style>body{{font:15px system-ui;background:#101826;color:#e7edf7;margin:24px}}a{{color:#69b7ff}}
table{{border-collapse:collapse}}td,th{{padding:8px 12px;border:1px solid #526071}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px}}
.grid img{{width:100%;height:auto}}</style>
<h1>Grounding DINO prompt scan</h1>
<p>Split: {summary['split']} · images: {summary['image_count']} · visual threshold: {summary['visual_threshold']}</p>
<p>Detection counts are model outputs, not accuracy. Manually inspect overlays before choosing a prompt/threshold.</p>
<table><tr><th>Prompt</th><th>box threshold</th><th>images detected</th><th>boxes</th><th>max boxes/image</th></tr>
{''.join(rows)}</table>{''.join(galleries)}"""
    (output_dir / "report.html").write_text(document, encoding="utf-8")


def main() -> None:
    args = parse_args()
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    image_dir = args.dataset_root / "grounding_dino" / args.split / "images"
    images = sorted(image_dir.glob("*.jpg"))
    if args.limit:
        images = images[: args.limit]
    if not images:
        raise SystemExit(f"No JPG files found in {image_dir}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise SystemExit(f"Output exists: {args.output_dir}; pass --overwrite")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device(args.device)
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    processor = AutoProcessor.from_pretrained(args.model_dir, local_files_only=True)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(
        args.model_dir, local_files_only=True, torch_dtype=dtype
    ).to(device)
    model.eval()

    min_threshold = min(min(args.thresholds), args.visual_threshold)
    counters = {
        prompt: {
            f"{threshold:.2f}": defaultdict(int) for threshold in args.thresholds
        }
        for prompt in args.prompts
    }
    overlays: dict[str, list[Path]] = {prompt: [] for prompt in args.prompts}
    predictions_path = args.output_dir / "predictions.jsonl"
    start = time.monotonic()
    with predictions_path.open("w", encoding="utf-8") as output:
        for image_number, image_path in enumerate(images, 1):
            with Image.open(image_path) as loaded:
                image = loaded.convert("RGB")
            for prompt in args.prompts:
                inputs = processor(images=image, text=prompt, return_tensors="pt")
                inputs = {key: value.to(device) for key, value in inputs.items()}
                with torch.inference_mode(), torch.autocast(
                    device_type=device.type, dtype=dtype, enabled=device.type == "cuda"
                ):
                    outputs = model(**inputs)
                boxes, scores, labels = post_process(
                    processor,
                    outputs,
                    inputs["input_ids"],
                    image,
                    min_threshold,
                    args.text_threshold,
                )
                record = {
                    "image": image_path.name,
                    "split": args.split,
                    "prompt": prompt,
                    "boxes_xyxy": [[round(float(x), 3) for x in box] for box in boxes],
                    "scores": [round(float(score), 6) for score in scores],
                    "labels": [str(label) for label in labels],
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                for threshold in args.thresholds:
                    count = sum(float(score) >= threshold for score in scores)
                    values = counters[prompt][f"{threshold:.2f}"]
                    values["images_with_detections"] += int(count > 0)
                    values["total_detections"] += count
                    values["max_detections_in_image"] = max(
                        values["max_detections_in_image"], count
                    )
                keep = scores >= args.visual_threshold
                vis_boxes = boxes[keep]
                vis_scores = scores[keep]
                vis_labels = [label for label, selected in zip(labels, keep.tolist()) if selected]
                overlay = draw_overlay(image, vis_boxes, vis_scores, vis_labels, prompt)
                overlay_path = args.output_dir / "overlays" / slugify(prompt) / image_path.name
                overlay_path.parent.mkdir(parents=True, exist_ok=True)
                overlay.save(overlay_path, quality=90)
                overlays[prompt].append(overlay_path)
            print(f"[{image_number:03d}/{len(images):03d}] {image_path.name}", flush=True)

    summary = {
        "schema_version": 1,
        "model_dir": str(args.model_dir),
        "split": args.split,
        "image_count": len(images),
        "prompts": {
            prompt: {threshold: dict(values) for threshold, values in threshold_data.items()}
            for prompt, threshold_data in counters.items()
        },
        "thresholds": args.thresholds,
        "text_threshold": args.text_threshold,
        "visual_threshold": args.visual_threshold,
        "elapsed_sec": round(time.monotonic() - start, 3),
        "device": str(device),
        "torch_version": torch.__version__,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for prompt, paths in overlays.items():
        make_contact_sheet(paths, args.output_dir / f"contact_sheet_{slugify(prompt)}.jpg")
    build_html(args.output_dir, summary, overlays)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {args.output_dir / 'report.html'}")


if __name__ == "__main__":
    main()
