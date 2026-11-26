"""Private subprocess entry point. No input data or secrets are logged."""

import json
import sys
from pathlib import Path
from .errors import public_error


def main():
    input_path, output_path, stage_path = map(Path, sys.argv[1:])
    args = json.loads(input_path.read_text(encoding="utf8"))
    for key in ("video_path", "work_dir", "model_path"):
        args[key] = Path(args[key])

    def on_stage(stage):
        if stage in ("analyzing", "rendering"):
            stage_path.write_text(stage, encoding="utf8")

    args["on_stage"] = on_stage
    try:
        from agent.graph import execute_job

        output = execute_job(**args)
    except Exception as error:
        output = {"worker_error": public_error(error)}
    output_path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf8")


if __name__ == "__main__":
    main()
