"""Preview by default; --apply removes only demo data older than 90 days."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.db import SessionLocal, engine
from app.demo_retention import expire_demo


async def run(apply=False, loop=False):
    try:
        while True:
            try:
                async with SessionLocal() as session:
                    print(json.dumps(await expire_demo(session, apply=apply)), flush=True)
            except Exception:
                if not loop:
                    raise
                logging.getLogger("app.demo.retention").exception("Demo retention failed; retrying next hour")
            if not loop:
                break
            await asyncio.sleep(3600)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.apply, args.loop))
