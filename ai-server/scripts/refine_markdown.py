from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR, get_settings
from llm.mlx_client import MlxQwenClient
from rag.markdown_refiner import refine_markdown_directory, refine_markdown_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refine Docling Markdown files with a local Qwen MLX model.")
    parser.add_argument("--input", help="Single Markdown file to refine.")
    parser.add_argument("--input-dir", default=str(ROOT_DIR / "data/markdown"))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-tokens", type=int, default=2048)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    output_dir = Path(args.output_dir) if args.output_dir else settings.refined_markdown_dir
    model_path = args.model or settings.qwen_model_path
    llm = MlxQwenClient(model_path)

    if args.input:
        results = [refine_markdown_file(Path(args.input), output_dir, llm, max_tokens=args.max_tokens)]
    else:
        results = refine_markdown_directory(Path(args.input_dir), output_dir, llm, max_tokens=args.max_tokens)

    for result in results:
        print(f"{result.input_path} -> {result.output_path} ({result.block_count} block(s))")


if __name__ == "__main__":
    main()

