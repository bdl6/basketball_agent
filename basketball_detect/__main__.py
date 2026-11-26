import argparse
from pathlib import Path
import sys

from .config import load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description="篮球进球检测：输入视频，输出完整标注 MP4")
    parser.add_argument("--config", type=Path, help="JSON 配置文件")
    for name in ("video", "model", "output", "font"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps", "dml", "coreml"))
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    parser.add_argument("--coarse-fps", type=float)
    parser.add_argument("--refine-fps", type=float)
    args = vars(parser.parse_args(argv))
    try:
        config = load_config(args.pop("config"), args)
        from .app import run
        result = run(config)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
