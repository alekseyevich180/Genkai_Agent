

# Genkai: Un agente para materiales, química y simulación.

<p align="center">
  <img src="https://raw.githubusercontent.com/alekseyevich180/Genkai_Agent/main/genkai-logo.png" alt="Genkai logo theme" width="400">
</p>


## Agente

El Agente es una **plataforma de agentes basada en habilidades** para tareas de ciencia de materiales computacionales, con un enfoque en la generación y aplicación de Campos de Fuerza de Aprendizaje Automático (MLFF). Evolucionará con los usuarios mediante la acumulación de experiencia y la creación de nuevas habilidades.

Este espacio de trabajo ahora incluye una habilidad de modelado orientada a superficies en `agents/Agent/skills/surface-modeling/`. Cubre paisajes de vacantes superficiales de óxidos, paisajes de cobertura de adsorbatos y la colocación de nanoclústeres metálicos en superficies, con verificaciones rápidas de calculadoras simuladas y flujos de trabajo UMA/FAIRChem opcionales para relajación en producción.

Los flujos de trabajo MLIP se exponen como tres habilidades integradas separadas con roles explícitos:

- `agents/Agent/skills/mace/`: cálculos preentrenados de energía, fuerza y relajación con MACE/MACE-MP;
- `agents/Agent/skills/deepmd/`: preparación de conjuntos de datos DeepMD, entrenamiento, continuación de puntos de control, congelación, compresión y pruebas;
- `agents/Agent/skills/uma/`: ajuste fino de tarea única con UMA, reanudación y evaluación de modelos ajustados.

La puerta de preparación de UMA audita etiquetas de energía/fuerza/esfuerzo legibles por ASE y una división de prueba retenida, rechapa superposiciones atómicas severas y fugas entre divisiones, crea ASE-LMDB de entrenamiento/validación, verifica registros de fallos del convertidor, lee el LMDB generado y compone la configuración Hydra `fairchem-core 2.21.0` coincidente en versión antes de la transición para el entrenamiento. Los datos, informes, configuraciones, puntos de control y registros permanecen en el proyecto del solicitante.

### Núcleo de flujo de trabajo orientado a bibliotecas

La API de flujo de trabajo científico estable ahora se encuentra en `src/genkai/`. Proporciona contratos de artefactos/procedencia versionados, manifiestos de ejecución atómicos, validación de DAG consciente de artefactos, fachadas de flujo de trabajo de superficies, límites de preparación/resultados VASP, auditorías de conjuntos de datos ASE y adaptadores separados para MACE, DeepMD y UMA. Los puntos de entrada `paperread.surface` y Agent existentes permanecen disponibles durante la migración.

Inicialice e inspeccione una ejecución de referencia sin conexión:

```bash
genkai-workflow init runs/demo \
  --relations tests/fixtures/paper_to_mlip/minimal_surface_relations.jsonl \
  --mock-labels tests/fixtures/paper_to_mlip/mock_labels.extxyz \
  --base-model-uri file:///path/to/read-only/uma-checkpoint.pt
genkai-workflow inspect --run-root runs/demo
genkai-workflow preflight --run-root runs/demo --target uma --mode dry-run
```

Este flujo de trabajo nunca trata el fixture como evidencia DFT: la verificación previa de producción UMA rechaza sus etiquetas simuladas, mientras que la ejecución de prueba registra una advertencia y no inicia ningún proceso VASP, GPU, PJM, DeepMD, MACE o UMA. Consulte
[`docs/artifact-contracts.md`](docs/artifact-contracts.md) y
[`docs/skill-development.md`](docs/skill-development.md).

Este espacio de trabajo también introduce un flujo de trabajo de lectura de artículos bajo `paperread/`. El kit de herramientas `paperread/surface/` puede ingerir PDF de investigación de superficies o texto JSON, extraer materiales superficiales, parámetros de reacción/material, adsorbatos, sitios activos, defectos, átomos únicos, clústeres y palabras clave de modelado, y luego resumir los resultados para el modelado posterior.

Paperread ahora incluye recopilación de experiencia para investigación de superficies. La información útil o desconocida extraída se acumula por clase de material inorgánico en `paperread/surface/experience/material_classes/`, como `carbon_materials`, `single_atom_catalysts`, `oxides` y `supported_catalysts`, para que los resultados repetidos de lectura de artículos puedan mejorar esquemas, prompts, planificadores y actualizaciones de habilidades posteriores.

### Flujo de trabajo de superficies de Paperread

Para artículos de reacciones de superficie, utilice la habilidad unificada `paperread` en lugar de los puntos de entrada independientes más antiguos `ReactionSeek` o `NERRE`. La ruta mantenida es:

```text
Texto de artículo en PDF o JSON
-> extracción paperread/surface
-> tabla de condiciones, tabla de tiempo, relaciones superficiales, resumen, puente ptomodel
-> almacén de experiencia por clase de material
-> almacén de términos desconocidos del lado de la habilidad y registro de parámetros de superficie
```

Ejecute un solo artículo:

```bash
python agents/Agent/skills/paperread/scripts/paperread_tools.py surface-pipeline \
  --input /path/to/paper.pdf \
  --output-dir paperread_output \
  --keep-intermediate \
  --collect-experience
```

Salidas importantes de paperread:

- `*_table.csv`: tabla de condiciones de reacción y material.
- `*_time.csv`: valores de tiempo normalizados.
- `*_surface_relations.jsonl`: materiales estructurados, superficies, adsorbatos,
  sitios activos, defectos, átomos únicos, clústeres, reacciones y señales de modelado.
- `*_summary.txt`: resumen de extracción breve y legible por humanos.
- `*_ptomodel.json`: puente normalizado desde hechos del artículo a entradas de modelado del Agente.
- `paperread/surface/experience/material_classes/*.json`: almacén canónico reutilizable de palabras clave por clase de material.
- `agents/Agent/skills/paperread/experience/surface_parameter_registry.{json,md}`:
  vocabulario reutilizable construido desde el almacén de experiencia canónico.
- `agents/Agent/skills/paperread/experience/unrecognized_surface_terms.jsonl`:
  términos de artículos de superficie no resueltos que pueden requerir actualizaciones de ontología o flujo de trabajo.

Para trabajo por lotes de PDF, mantenga siempre los intermedios:

```bash
python agents/Agent/skills/paperread/scripts/paperread_tools.py surface-pipeline \
  --input /path/to/paper.pdf \
  --output-dir tests/paperread_papers2_experience \
  --keep-intermediate \
  --collect-experience
```

`--keep-intermediate` conserva `*_text.txt`, `*_sections.json`,
`*_conditions_input.json` y `*_relations_input.json`. Estos archivos son el punto de reanudación cuando fallan las llamadas a la API o los límites de tasa interrumpen la extracción; continúe desde el JSON generado en lugar de volver a analizar el PDF.

Estado actual de paperread desde `work_logs/2026-07-08.md`:



## Inicio rápido
### Instalación en Linux

El siguiente proceso de instalación es para Linux y requiere Python 3.12 o superior:

```bash
# 如果尚未安装 uv，请先安装
pipx install uv

# 创建并激活项目虚拟环境
uv venv .venv --python 3.12
source .venv/bin/activate

# 以可编辑模式安装 Agent，并安装测试工具
uv pip install -e .
uv pip install pytest

# 可选：从 GitHub 安装最新 pymatgen
uv pip install "git+https://github.com/materialsproject/pymatgen.git"

# 安装前端依赖
cd web/vite-frontend
npm install
cd ../..
```

### Llamada simple a pymatgen

Después de activar el entorno virtual del proyecto, puede usarlo directamente en Python:

```bash
source .venv/bin/activate
python - <<'PY'
from pymatgen.core import Lattice, Structure

structure = Structure(
    Lattice.cubic(3.5),
    ["Si"],
    [[0, 0, 0]],
)

print(structure.formula)
print(structure.lattice.a)
PY
```

Si necesita leer archivos de estructura como CIF/POSCAR:

```python
from pymatgen.core import Structure

structure = Structure.from_file("structure.cif")
print(structure.composition.reduced_formula)
```

### Configuración

Después de la instalación, indique a la CLI dónde se encuentra la raíz del proyecto:

```bash
# Run from the repo directory
agent init .

# Or specify an absolute path
agent init /path/to/PFD-Agent
```

Esto escribe `~/.agent/config.yaml` con la ruta de `project_root`, para que la
CLI pueda ubicar el directorio `agents/` incluso cuando se instala en site-packages.
También puede configurar la variable de entorno `AGENT` en su lugar.

## Requisitos del Frontend Vite

Este proyecto incluye una interfaz de frontend. El frontend depende de `node`, `npm` y el servidor de desarrollo local `vite`.

### Instalar NVM

Use NVM para administrar Node.js.

```bash
# Install nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc

# Verify installation:
nvm --version
```

### Instalar Node.js
```bash
nvm install 22
nvm use 22
nvm alias default 22
```

Verifique la instalación
```bash
node -v
npm -v
```

### Instalar dependencias del frontend

```bash
cd web/vite-frontend
npm install
npm run dev
```

### Flujo de trabajo recomendado: WSL + uv para implementación de entornos virtuales

Recomendamos encarecidamente usar WSL (Windows Subsystem for Linux) con uv para implementar entornos virtuales de desarrollo local. WSL proporciona un entorno Linux nativo integrado de manera fluida con Windows, lo que permite acceder a herramientas de Linux. Como administrador de paquetes de Python rápido y liviano, uv crea entornos aislados para evitar conflictos de dependencias, ideal para aplicaciones de Python como Streamlit.

#### Por qué usar pipx para uv en WSL

En WSL, Python del sistema es administrado por apt y es un componente central del sistema. PEP 668 prohíbe la instalación directa con pip para evitar romper dependencias del sistema. Pipx es ideal para herramientas como uv: crea entornos virtuales aislados para acceso global sin ensuciar Python del sistema.

#### Solución: Instalar uv usando pipx

Como herramienta de línea de comandos, uv puede instalarse mediante pipx, que crea un entorno virtual independiente para uso global. Ejecute estos comandos en la terminal de WSL:

```bash
# 1. Install pipx
sudo apt update && sudo apt install pipx -y

# 2. Initialize pipx (add to system PATH)
pipx ensurepath

# 3. Restart terminal, then install uv
pipx install uv
```

### Ejecución de redes de agentes
#### Configuración de entornos
Antes de la primera ejecución, cree el archivo `agents/Agent/.env` y configure sus credenciales de API del modelo (puede requerirse variables de entorno adicionales para algunas funcionalidades).

```bash
touch agents/Agent/.env
```

Un ejemplo del contenido de `.env`:

```env
LLM_MODEL= "MODEL_TYPE"
GRAPH_AGENT_MODEL="MODEL_TYPE"             # optional; defaults to LLM_MODEL
REVIEW_AGENT_MODEL="MODEL_TYPE"            # optional; defaults to GRAPH_AGENT_MODEL
LLM_API_KEY="API_KEYS"
LLM_BASE_URL="BASE_URL"
KDG_DB_PATH="agents/Agent/.adk/know_do_graph.db"
EMBEDDING_MODEL="EMBEDDING_MODEL_TYPE"
AGENT_AUTO_REVIEW=1
AGENT_REVIEW_TRIGGER_THRESHOLD=20
AGENT_REVIEW_BATCH_SIZE=5
AGENT_REVIEW_STRATEGY=auto             # auto, seed, or global

# SKILL_RELATED_ENV
CGCNN_ROOT=user/cgcnn                         # CGCNN project directory
MATTERGEN_ENV=user/../.mattergen              # MATTERGEN virtual environment
TAVILY_API_KEY=""
BOHRIUM_MAT_IMAGE=""                          # MATTERGEN and MATTERSIM IMAGE
BOHRIUM_MAT_MACHINE=""                        # MATTERGEN and MATTERSIM IMAGE
eval_reference="user/../reference_MP2020correction.gz"
mattersim_model="user/../mattersim-v1.0.0-5M.pth"
mattergen_model="user/../mattergen/checkpoints"
BOHRIUM_VASP_IMAGE=""
BOHRIUM_VASP_MACHINE=""
...
```

Si prefiere modelos LLM diferentes para subagentes, puede anular la configuración predeterminada en el archivo `.env` dentro de los directorios de subagentes. 

#### Inicio de la interfaz Web (recomendado)

La interfaz Web proporciona visualización de gráficos de ejecución, carga y descarga de artefactos, visualización de estructuras de materiales y gráficos científicos. Utilice el siguiente script para iniciar simultáneamente ADK API Server, la capa intermedia FastAPI y el frontend Vite:

```bash
# 激活 .venv 后，在仓库根目录执行
bash start/start_agent.sh
```

Este script iniciará:

- **ADK API Server**: `http://localhost:8000`
- **Capa intermedia FastAPI**: `http://localhost:8001`
- **Frontend Vite**: `http://localhost:5173`

Los registros se escriben en `logs/{api-server,web-main,vite}.log`. Presione `Ctrl+C` para detener todos los servicios.

Si los servicios fallan al iniciarse, puede ver los registros correspondientes con los siguientes comandos:

```bash
tail -f logs/api-server.log
tail -f logs/web-main.log
tail -f logs/vite.log
```

> El modo de desarrollo no requiere construir el frontend previamente; el servidor de desarrollo Vite se ejecutará directamente y proporcionará recarga en caliente.

![La interfaz web para el Agente]()

#### Modo CLI no interactivo

Ejecute el agente con un solo prompt sin iniciar ningún servidor:

```bash
# Inline prompt
agent run -p "Build a silicon FCC structure"

# Prompt from a file
agent run -f prompt.txt

# Save the answer to a file
agent run -p "Build a silicon FCC structure" -o result.txt

# Full structured JSON output (includes turn count, duration, etc.)
agent run -p "Build a silicon FCC structure" --output-format json -o result.json

# Override the workspace directory
agent run --workspace /data/my_workspace -p "Build a silicon FCC structure"
# or via environment variable
MATCLAW_WORKSPACE=/data/my_workspace agent run -p "Build a silicon FCC structure"
```

Cada ejecución crea un directorio de sesión en `<workspace>/sessions/<session-id>/` donde se guardan cualquier archivo producido por el agente.

#### Servidor web adk predeterminado (estilo antiguo)

```bash
agent web
```
Esto configura la red del Agente a través del servidor `adk web` predeterminado. Puede ajustar el modelo LLM y la configuración de comunicación para los agentes.

El espacio de trabajo predeterminado del agente se encuentra en `agents/Agent/.workspace`, donde se almacenan habilidades, memoria, etc.

### Pruebas automatizadas

Active el entorno virtual y ejecute los siguientes comandos en el directorio raíz del repositorio:

```bash
source .venv/bin/activate
```

Ejecute las pruebas de integridad de importación de módulos idénticas a GitHub Actions:

```bash
python -m pytest tests/test_agent.py -v
```

Ejecute las pruebas de memoria, extracción y flujo de revisión de Know-Do Graph:

```bash
python -m pytest \
  tests/test_kdg_memory.py \
  tests/test_kdg_extractor.py \
  tests/test_kdg_review_pipeline.py \
  tests/test_kdg_auto_review.py \
  -v
```

Ejecute todas las pruebas locales:

```bash
python -m pytest tests -v
```

`tests/test_structure_builder.py` actualmente depende del módulo
`agent.tools.structure_builder`, que ya no existe. Por lo tanto, hasta que se restaure dicho módulo o se elimine esta prueba,
el套件 completo de pruebas no podrá aprobarse por completo. GitHub
Actions en `.github/workflows/test.yml` actualmente solo ejecuta `tests/test_agent.py` en cada envío y solicitud de extracción.

## Habilidades
El Agente sigue un principio de diseño modular: las habilidades son archivos de texto que definen metadatos, procedimientos y flujos de trabajo. Algunas habilidades pueden requerir herramientas especializadas (configuradas por `$PROJECT/agents/Agent/tools.py`), y algunas de ellas, por ejemplo, herramientas para cálculos DFT, pueden alojarse en servidores MCP.

> Los conjuntos de datos computacionales de materiales basados en dominio predeterminados se encuentran en `database/domain_datasets.tar.gz`, los cuales deben descomprimirse para el uso de habilidades de base de datos. (Consulte `tools/database/README.md`)

> Consulte el `README.md` en `skills/$SKILL` si realmente desea usarlos. 


> **Nota — transición de servidores MCP a habilidades:** El Agente está moviendo progresivamente la lógica de herramientas fuera de servidores MCP dedicados hacia habilidades autocontenidas. Una habilidad agrupa sus propias instrucciones de flujo de trabajo, scripts auxiliares y configuración junto con el archivo `.md`, por lo que puede ejecutarse con solo una herramienta de shell/Python de propósito general en lugar de un proceso de servidor en ejecución. Si una capacidad que utilizaba previamente a través de un servidor MCP ya no aparece en `tools/`, consulte `agents/Agent/skills/`: es posible que haya migrado a una habilidad. Los servidores MCP se conservan solo para herramientas que realmente requieren un servicio persistente (por ejemplo, un programador de trabajos remoto o un backend de base de datos).


###  Configuración del servidor (Opcional)
Por ejemplo, para configurar un servidor `mcp` para el software DFT `ABACUS`, ejecute el script con `uv run`: 

```bash
cd tools/abacus
uv sync 

uv run server.py --port 50001
```
 Es posible que deba configurar variables de entorno específicas para el servidor mcp en `tools/$TOOLNAME/.env`, las cuales se pueden consultar en `tools/$TOOLNAME/README.md`

### Personalizar habilidades

Las habilidades son archivos Markdown con un bloque de frontmatter YAML (que declara `name`, `description`, `tools` y `dependent_skills`) seguido de un cuerpo de instrucciones en texto plano. El cargador activo descubre cualquier directorio del espacio de trabajo que contenga un archivo `SKILL.md`, incluidos directorios anidados como `skills/mattergen/mattergen_generation/SKILL.md`. El Agente carga habilidades desde dos ubicaciones en orden:

1. **Habilidades integradas** — incluidas con el paquete en `agents/Agent/skills/`. Cada habilidad vive en un directorio que contiene un archivo `SKILL.md`.
2. **Capa superpuesta del espacio de trabajo** — sus habilidades personales en `$MATCLAW_WORKSPACE/skills/` (predeterminado a `.workspace/` en la raíz del proyecto). Cualquier habilidad aquí con el mismo nombre anula la versión integrada.

Para personalizar una habilidad manualmente, copie su directorio de habilidad en el directorio `skills/` de su espacio de trabajo y edite el `SKILL.md` contenido. Para agregar una nueva habilidad, cree un nuevo archivo `skills/<name>/SKILL.md` siguiendo el mismo formato de frontmatter.

El agente también puede crear y actualizar habilidades por sí solo. Durante una sesión, el agente de pensamiento puede llamar a herramientas integradas para crear una nueva habilidad, escribir contenido actualizado en una existente o listar qué habilidades están disponibles actualmente, permitiendo que el sistema acumule conocimiento automáticamente con el tiempo.

## Know-Do Graph

El Agente utiliza `know-do-graph` tanto para conocimiento duradero como para memoria de trabajo:

- **Know-Do Graph** almacena capacidades curadas, procedimientos, flujos de trabajo y
  heurísticas destiladas en `agents/Agent/.adk/know_do_graph.db` de forma predeterminada.
- **MemGraph** almacena observaciones de agentes actualizadas con frecuencia como
  nodos `EntryType.memory` y aristas de grafo normales en la misma base de datos SQLite.

Las habilidades y guías se inician como entradas duraderas. Las primeras escrituras del Agente permanecen en
MemGraph; las observaciones exitosas repetidas se destilan posteriormente en heurísticas Know-Do validadas y se vinculan a las capacidades que mejoran. Las bases de datos `skill_graph.db`, `memory_graph.db`, trazas JSON antiguas y datos `MEMORY.md` pueden migrarse
idempotentemente. Consulte [manual.md](manual.md).

## Planificación basada en gráficos

Cuando se le da un objetivo, el agente de pensamiento produce un **grafo de ejecución**: un grafo acíclico dirigido (DAG) donde cada nodo es una acción discreta y cada arista codifica una dependencia.

```
step_download_data ──► step_relax ──► step_postprocess
                   └──► step_static ─►
```

Propiedades clave:

- **Nodos** contienen un `node_id`, una `label` legible por humanos, una descripción de `action` en lenguaje natural y una lista de `suggested_skills`.
- **Aristas** son pares `[predecessor_id, successor_id]`. Un nodo no puede comenzar hasta que todos sus predecesores hayan tenido éxito.
- **Ejecución paralela**: los nodos sin dependencias sin resolver se despachan concurrentemente en una sola tanda.
- **Propagación de fallos**: si un nodo falla, todos sus dependientes transitivos se marcan automáticamente como `blocked`.

El agente valida el grafo en busca de ciclos antes de presentarlo al usuario, luego espera la confirmación explícita antes de transferirlo al agente de ejecución.
