from ase import units
from ase.md.langevin import Langevin
from ase.md.nptberendsen import NPTBerendsen
from ase.md.nose_hoover_chain import NoseHooverChainNVT
from ase.io import read, write
from ase.optimize import FIRE
import numpy as np
import time
import torch
from mattersim.forcefield import MatterSimCalculator
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[
        logging.FileHandler("log"),
        logging.StreamHandler()
        ])

parser = argparse.ArgumentParser()
parser.add_argument(
        "-m",
        "--model",
        type=str,
        default='mattersim-v1.0.0-5M.pth',
        help="Model path",
)
parser.add_argument(
        "-d",
        "--device",
        type=str,
        default="cuda",
        help="device type for model",
)
parser.add_argument(
        "-t",
        "--temp",
        type=float,
        default=300.,
        help="Simulation temperature",
)
parser.add_argument(
        "-s",
        "--stru",
        type=str,
        default="structure.extxyz",
        help="Simulation structure",
)
parser.add_argument(
        "--fmax",
        type=float,
        default=0.01,
        help="Force convergence for minimization, eV/A",
)
parser.add_argument(
        "--min_steps",
        type=int,
        default=10000,
        help="Max steps for energy minimization",
)
parser.add_argument(
        "--skip_minimize",
        action="store_true",
        help="Skip energy minimization",
)
parser.add_argument(
        "--npt_steps",
        type=int,
        default=0,
        help="Number of NPT steps",
)
parser.add_argument(
        "--nvt_steps",
        type=int,
        default=50000,
        help="Number of NVT steps",
)
parser.add_argument(
        "--timestep",
        type=int,
        default=2,
        help="MD timestep in fs",
)

args = parser.parse_args()
dict_args = vars(args)

# 计算器设置
device = dict_args["device"]
if device == "cuda" and not torch.cuda.is_available():
    logging.info("CUDA is not available, use CPU instead.")
    device = "cpu"

calculator = MatterSimCalculator(load_path=dict_args["model"], device=device)

# 读取结构
atoms = read(dict_args["stru"], index=0)
atoms.calc = calculator

# 初始能量和力
e0 = atoms.get_potential_energy()
f0 = atoms.get_forces()
logging.info(f"Initial energy: {e0:.8f} eV")
logging.info(f"Initial max force: {np.max(np.linalg.norm(f0, axis=1)):.6f} eV/A")

# 能量最小化
if not dict_args["skip_minimize"]:
    logging.info("#### Start energy minimization...")

    opt = FIRE(atoms, logfile="log.min")
    opt.run(fmax=dict_args["fmax"], steps=dict_args["min_steps"])

    write("minimized.extxyz", atoms)
    write("CONTCAR_min.vasp", atoms, format="vasp", direct=True)

    emin = atoms.get_potential_energy()
    fmin = atoms.get_forces()
    logging.info(f"Minimized energy: {emin:.8f} eV")
    logging.info(f"Minimized max force: {np.max(np.linalg.norm(fmin, axis=1)):.6f} eV/A")
    logging.info(f"Minimized volume: {atoms.get_volume():.6f} A^3")
    logging.info("#### Energy minimization finished.")

# MD 参数
timestep = dict_args["timestep"] * units.fs
dumpfreq = 100
temp = dict_args["temp"]
press = 1

# NPT 模拟
start_time = time.time()
logging.info("#### Start NPT calculation...")
dyn = NPTBerendsen(
    atoms,
    timestep,
    temperature_K=temp,
    pressure=press,
    compressibility_au=80,
    logfile="log.npt",
    loginterval=dumpfreq
)

def write_npt_frame():
    dyn.atoms.write('md_npt.xyz', append=True)

dyn.attach(write_npt_frame, interval=50)

dyn.run(dict_args["npt_steps"])

tmp_time = time.time()
logging.info(f"#### NPT simulation ends after {tmp_time - start_time} s")

# NVT 模拟
logging.info("#### Start NVT calculation...")
dyn = NoseHooverChainNVT(
    atoms,
    timestep,
    temperature_K=temp,
    tdamp=100 * timestep,
    logfile="log.nvt",
    loginterval=dumpfreq,
    trajectory=f"{temp}_nvt.traj"
)

def write_nvt_frame():
    dyn.atoms.write('md_nvt.xyz', append=True)

dyn.attach(write_nvt_frame, interval=50)

dyn.run(dict_args["nvt_steps"])

logging.info(f"#### NVT simulation ends after {time.time() - tmp_time} s")
logging.info(f"MD finished!")

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
