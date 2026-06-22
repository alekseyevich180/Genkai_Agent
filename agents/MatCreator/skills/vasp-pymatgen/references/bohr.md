# VASP Bohrium Submission Reference (bohr CLI)

See the `bohrium` skill for general `bohr` CLI usage (login, project ID, machine types, monitoring).
This file covers only **VASP-specific** parameters.

## VASP-specific environment variable

| Variable | Description | Example |
|---|---|---|
| `BOHRIUM_VASP_IMAGE` | Docker image URI for VASP | `registry.dp.tech/dptech/vasp:5.4.4` |

All other Bohrium parameters (`BOHRIUM_PROJECT_ID`, machine type) are general and not VASP-specific.

* Check `BOHRIUM_VASP_IMAGE` and `BOHRIUM_PROJECT_ID` in environment.

## VASP run command

```bash
source /opt/intel/oneapi/setvars.sh && mpirun -np <N_CORES> vasp_std > log 2> err
```

Always match the `<N_CORES>` count to the machine's core count.



## Choosing CPU machines

You can check available machine type using `bohr` CLI

Choose based on system size:
- **Small systems (a few atoms)**: `c16_m32_cpu` is efficient — good balance of cores and memory
- **Medium systems (10-50 atoms)**: `c32_m64_cpu` for better parallelization
- **Large systems or k-point-heavy calculations**: `c32_m64_cpu` or larger if available


In most cases, set `NCORES` in the INCAR to 4 - approx SQRT(number of cores) for optimal performance.


## Single job workflow
Submit — return a Job ID
```bash
bohr job submit \
  --project_id "$BOHRIUM_PROJECT_ID" \
  --job_name "vasp-relax-Al" \
  --machine_type "c32_m64_cpu" \
  --image_address "$BOHRIUM_VASP_IMAGE" \
  --input_directory "./vasp-relax-Al-example" \ 
  --command "source /opt/intel/oneapi/setvars.sh && mpirun -np 32 vasp_std" 
```

Monitor (Download log files for Job IDs )
```bash
bohr job log --job_id "$JOB_ID"
```

Download results
```
bohr job download -j 1234 -j 2345 -o /opt
# Download the out files for Job IDs 1234 and 2345 and save them to the local /opt directory
```

## Bathc job workflow
Create a job group, and then submit jobs to that group. See the `bohrium` skill for more details.

## Handling failed jobs
Check job log with:  
```bash
# Inspect logs
bohr job log --job_id <JOB_ID> 
```
Modify the setting, then simply submit again. 
