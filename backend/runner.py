"""Private subprocess entry point. No input data or secrets are logged."""

import json
import sys
import time
from pathlib import Path
from .errors import public_error


def main():
    input_path, output_path, stage_path = map(Path, sys.argv[1:])
    args = json.loads(input_path.read_text(encoding="utf8"))
    for key in ("video_path", "work_dir", "model_path"):
        args[key] = Path(args[key])

    def on_stage(stage):
        status = stage.get("status") if isinstance(stage, dict) else stage
        if status in ("preparing_roi", "analyzing", "rendering"):
            temporary = stage_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(stage, ensure_ascii=False), encoding="utf8")
            temporary.replace(stage_path)
            # The worker acknowledges only after committing the status message.
            while stage_path.exists():
                time.sleep(0.01)

    args["on_stage"] = on_stage
    try:
        operation = args.pop('operation', 'analyze')
        if operation == 'prepare_roi':
            from video_engine.upstream import prepare_roi
            output = prepare_roi(args['video_path'], args['work_dir'], model_path=args['model_path'],
                                 engine_root=args.get('engine_root'), on_progress=on_stage)
        else:
            from agent.graph import execute_job
            output = execute_job(**args)
    except Exception as error:
        output = {"worker_error": public_error(error)}
    output_path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf8")


if __name__ == "__main__":
    main()
