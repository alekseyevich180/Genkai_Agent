If you gonna use dpdispatcher to submit job to Bohrium, you may need to set following variables at `agents/MatCreator/.env`
```env
BOHRIUM_EMAIL="your_email"
BOHRIUM_PASSWORD="your_password"
BOHRIUM_PROJECT_ID="1111"

# Below are some environment variables for debugging and development, you can ignore them if you don't know what they are for.
INFO_DB_PATH="PATH_TO_INFO.db"


# VASP related environment variables
BOHRIUM_VASP_IMAGE="VASP_IMAGE"
BOHRIUM_VASP_MACHINE="c16_m32_cpu"

# DPA related environment variables
DEEPMD_MODEL_PATH="default_model_path"
BOHRIUM_DEEPMD_IMAGE="deepmd_image"
BOHRIUM_DEEPMD_MACHINE="1 * NVIDIA V100_32g"

BOHRIUM_DEEPMD_ASE_IMAGE="deepmd_image_with_ase"
BOHRIUM_DEEPMD_ASE_MACHINE="1 * NVIDIA V100_32g"
```