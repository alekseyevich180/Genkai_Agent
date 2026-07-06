# VASP + LOBSTER

## Scope

Use this path when the user wants a LOBSTER bonding analysis based on a VASP
static calculation. This is the primary supported workflow of the `lobster`
skill.

## Recommended sequence

```text
prepare VASP static input
-> run VASP
-> confirm WAVECAR and usually CHGCAR exist
-> stage lobsterin + job directory
-> run LOBSTER
-> read ICOHPLIST / lobsterout
```

## INCAR pattern

The template below follows the two user-provided references:

- `wu_icohp.sh`
- `.../2O-Nband345/INCAR`

Use this as the default starting point for LOBSTER-oriented VASP runs:

```text
ISPIN = 1
ENCUT = 400-500
ALGO = Normal
EDIFF = 1E-5
NELM = 300-1000
ISMEAR = 1 or -5
SIGMA = 0.05

IBRION = -1
NSW = 0
ISIF = 2

NPAR = 5-10
LREAL = Auto
NSIM = 1
LPLANE = .TRUE.

IVDW = 12              # if the system requires D3(BJ)-style dispersion in your workflow

LWAVE = .TRUE.
LCHARG = .FALSE.       # switch to .TRUE. if you want CHGCAR retained explicitly
NEDOS = 1000
LORBIT = 12
ISYM = -1
LELF = .FALSE.
LVTOT = .FALSE.
LVHAR = .FALSE.
NBANDS = <explicit, sufficiently large>
```

Interpretation:

- `NSW = 0`, `IBRION = -1`, `ISIF = 2` make this a static single-point run.
- `ISYM = -1` is important for LOBSTER compatibility.
- `LWAVE = .TRUE.` is mandatory because LOBSTER reads the VASP wavefunction.
- `NBANDS` should be set explicitly and large enough for the projection basis.
- `LCHARG = .FALSE.` appeared in both local references. Keep that if the run is
  only for LOBSTER and you do not need the charge density later. If another
  downstream step needs charge density, set `LCHARG = .TRUE.`.

## Skill command

Generate a starter INCAR with the script:

```text
run_skill_script(
  skill_name="lobster",
  script_name="lobster_tools.py",
  args="write_vasp_incar --nbands 346 --output ./INCAR"
)
```

Then stage the LOBSTER run:

```text
run_skill_script(
  skill_name="lobster",
  script_name="lobster_tools.py",
  args="prepare_input --scf_dir ./vasp/scf_001 --basis-functions '{\"Ir\": \"5d 6s 6p\", \"O\": \"2s 2p\"}'"
)
```

## Minimal `lobsterin` pattern

```text
COHPstartEnergy -15.0
COHPendEnergy 5.0
basisSet pbeVaspFit2015
basisfunctions Ir 5d 6s 6p
basisfunctions O 2s 2p
cohpGenerator from 0.1 to 6.0
saveProjectionToFile
```

## Output files to check

- `lobsterout`
- `ICOHPLIST.lobster`
- `COHPCAR.lobster`
- `CHARGE.lobster`
- `GROSSPOP.lobster`

## Common failure modes

- `NBANDS` too small for the chosen basis
- missing `WAVECAR`
- `ISYM` not disabled
- basisfunctions not matching the species in `POSCAR`
