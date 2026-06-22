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
    "group_size": 1
  },
  "task_list": [
    {
      "command": "/opt/mattergen/.venv/bin/torchrun --nproc_per_node=1 -m mattersim.training.finetune_mattersim \
                            --load_model_path $REMOTE_ROOT/mattersim-v1.0.0-5M.pth \
                            --train_data_path train.extxyz \
                            --valid_data_path valid.extxyz \
                            --lr 2e-4 \
                            --step_size 20 \
                            --save_checkpoint \
                            --save_path ./results"
      "task_work_path": "<cal_dir>",
      "forward_files": ["train.extxyz","valid.extxyz","mattersim-v1.0.0-5m"],
      "backward_files": ["log","err","results/best_model.pth","results/last_model.pth"]
    }
  ]
}
```


Finetune Parameters:
- `load_model_path`: (str) Path to load the pre-trained model. Bohrium platform root path is `$REMOTE_ROOT`.
- `train_data_path`: (str) Path to the training data file. Supports various file types readable by ASE (e.g., .xyz, .traj, .cif). Default is “./sample.xyz”.
- `valid_data_path`: (str) Path to the validation data file. Default is None.
- `lr`: (float) Learning rate for the optimizer. Default is 2e-4.
- `step_size`: (int) Step size for the learning rate scheduler. Default is 10.
- `save_path`: (str) Path to save the trained model. Default is “./results”.
- `include_stresses`: (bool) Whether to include stresses in the training. Default is False.