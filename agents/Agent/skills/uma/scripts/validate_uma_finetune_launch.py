#!/usr/bin/env python3
"""Compose and validate a trusted UMA fine-tuning config without training."""

from __future__ import annotations

import argparse
from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compose a UMA Hydra config and validate launch-critical fields."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("train", "resume"))
    parser.add_argument("--override", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = args.config.resolve()
    if not config.is_file():
        raise SystemExit(f"ERROR: config does not exist: {config}")

    with initialize_config_dir(version_base=None, config_dir=str(config.parent)):
        cfg = compose(config_name=config.stem, overrides=args.override)

    scheduler_mode = OmegaConf.select(cfg, "job.scheduler.mode")
    if scheduler_mode != "LOCAL":
        raise SystemExit(
            f"ERROR: job.scheduler.mode must remain LOCAL under PJM, got {scheduler_mode!r}"
        )

    epochs = OmegaConf.select(cfg, "epochs")
    steps = OmegaConf.select(cfg, "steps")
    if (epochs is None) == (steps is None):
        raise SystemExit("ERROR: exactly one of epochs or steps must be non-null")

    base_model = OmegaConf.select(cfg, "base_model_name")
    device = OmegaConf.select(cfg, "job.device_type")
    run_dir = OmegaConf.select(cfg, "job.run_dir")
    train_tasks = OmegaConf.select(cfg, "train_dataset.dataset_configs")
    val_tasks = OmegaConf.select(cfg, "val_dataset.dataset_configs")
    if args.mode == "train":
        if not base_model:
            raise SystemExit("ERROR: base_model_name is missing")
        if not train_tasks or not val_tasks:
            raise SystemExit("ERROR: train/val dataset configuration is missing")
        train_keys = sorted(train_tasks.keys())
        val_keys = sorted(val_tasks.keys())
        if train_keys != val_keys or len(train_keys) != 1:
            raise SystemExit(
                f"ERROR: expected one matching UMA task, got train={train_keys}, "
                f"val={val_keys}"
            )
    else:
        train_keys = sorted(train_tasks.keys()) if train_tasks else []

    print("UMA fine-tuning Hydra preflight")
    print(f"  config     : {config}")
    print(f"  mode       : {args.mode}")
    print(f"  base_model : {base_model}")
    print(f"  task       : {train_keys}")
    print(f"  device     : {device}")
    print(f"  run_dir    : {run_dir}")
    print(f"  epochs     : {epochs}")
    print(f"  steps      : {steps}")
    print("HYDRA PREFLIGHT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
