# Example submission.json for moldyn

```json
{
  "work_base": ".",
  "machine": {
    "batch_type": "Bohrium",
    "context_type": "BohriumContext",
    "local_root": ".",
    "remote_profile": {
      "email": "${BOHRIUM_EMAIL}",
      "password": "${BOHRIUM_PASSWORD}",
      "program_id": ${BOHRIUM_PROJECT_ID},
      "input_data": {
        "job_type": "container",
        "log_file": "log",
        "scass_type": "${BOHRIUM_MAT_MACHINE}",
        "platform": "ali",
        "image_name": "${BOHRIUM_MAT_IMAGE}"
      }
    }
  },
  "resources": {
    "group_size": 4,
    "para_deg": 4,
    "gpu_per_node": 1
  },
  "forward_common_files": [
    "mattersim_moldyn.py",
    "mattersim-v1.0.0-5M.pth"
  ],
  "task_list": [
    {
      "command": "/opt/mattergen/.venv/bin/python $REMOTE_ROOT/mattersim_moldyn.py \
    --stru structure.extxyz \
    --model $REMOTE_ROOT/mattersim-v1.0.0-5M.pth \
    --temp 300 \
    --npt_steps 1000 \
    --nvt_steps 100000 \
    --timestep 2",
      "task_work_path": "<cal_dir>",
      "forward_files": ["stru.extxyz"],
      "backward_files": ["log.npt","log.nvt","md_nvt.xyz","md_npt.xyz","*.traj"]
    },
        {
      "command": "/opt/mattergen/.venv/bin/python $REMOTE_ROOT/mattersim_moldyn.py \
    --stru structure.extxyz \
    --model $REMOTE_ROOT/mattersim-v1.0.0-5M.pth \
    --temp 300 \
    --npt_steps 1000 \
    --nvt_steps 100000 \
    --timestep 2",
      "task_work_path": "<cal_dir>",
      "forward_files": ["stru.extxyz"],
      "backward_files": ["log.npt","log.nvt","md_nvt.xyz","md_npt.xyz","*.traj"]
    }
  ]
}
```

Important options
- `<cal_dir>`: numbered folders that store the structures, for example "1", "2"
- `--stru`: a single structure file for each MD run
- `--model`: a real model path. Bohrium platform root path is `$REMOTE_ROOT`.
- `--temp`: simulation temperature in Kelvin
- `--npt_steps`: number of NPT steps
- `--nvt_steps`: number of NVT steps
- `--timestep`: MD timestep in fs, default `2`