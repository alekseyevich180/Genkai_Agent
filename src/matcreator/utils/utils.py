import os
from contextlib import (
    contextmanager,
)
from functools import (
    wraps,
)
from pathlib import (
    Path,
)
import importlib
import logging

import dflow
from dflow.config import (
    config,
    s3_config,
)
from dflow.plugins import (
    bohrium,
)
from dflow.plugins.dispatcher import (
    DispatcherExecutor,
)
from dflow import (
    InputParameter,
    InputArtifact,
    Inputs,
    OutputParameter,
    OutputArtifact,
    Outputs,
    Step,
    Steps,
    Workflow,
    upload_artifact,
    download_artifact,
    argo_len,
    argo_sequence,
    argo_range,
    LocalArtifact,
    S3Artifact
)
from dflow.python import (
    OP,
    OPIO,
    OPIOSign,
    PythonOPTemplate,
    Artifact,
    Parameter,
    BigParameter,
    Slices,
)

from typing import List, Tuple, Union, Optional, Dict, Any, Callable
import subprocess
import sys
import shlex
import selectors
import time
import traceback
import uuid

logger = logging.getLogger(__name__)


@contextmanager
def set_directory(path: Path):
    """Sets the current working path within the context.

    Parameters
    ----------
    path : Path
        The path to the cwd

    Yields
    ------
    None

    Examples
    --------
    >>> with set_directory("some_path"):
    ...    do_something()
    """
    cwd = Path().absolute()
    path.mkdir(exist_ok=True, parents=True)
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)
        
        
def generate_work_path(create: bool = True) -> str:
	"""Return a unique work dir path and create it by default."""
	calling_function = traceback.extract_stack(limit=2)[-2].name
	current_time = time.strftime("%Y%m%d%H%M%S")
	random_string = str(uuid.uuid4())[:8]
	work_path = f"{current_time}.{calling_function}.{random_string}"
	if create:
		os.makedirs(work_path, exist_ok=True)
	return work_path


BOHRIUM_CONFIG={
      "host":"https://workflows.deepmodeling.com",
      "k8s_api_server":"https://workflows.deepmodeling.com",
      "repo_key": "oss-bohrium",
      "storage_client": "dflow.plugins.bohrium.TiefblueClient",
  }


def bohrium_config_from_dict(
    bohrium_config,
):

    config["host"] = bohrium_config.get("host",BOHRIUM_CONFIG["host"])
    config["k8s_api_server"] = bohrium_config.get("k8s_api_server",BOHRIUM_CONFIG["k8s_api_server"])
    bohrium.config["username"] = bohrium_config["username"]
    if bohrium_config.get("password"):
        bohrium.config["password"] = bohrium_config["password"]
    elif bohrium_config.get("ticket"):
        bohrium.config["ticket"] = bohrium_config["ticket"]
    bohrium.config["project_id"] = str(bohrium_config["project_id"])
    s3_config["repo_key"] = bohrium_config.get("repo_key", BOHRIUM_CONFIG["repo_key"])
    storage_client = bohrium_config.get("storage_client", BOHRIUM_CONFIG["storage_client"])
    module, cls = storage_client.rsplit(".", maxsplit=1)
    module = importlib.import_module(module)
    client = getattr(module, cls)
    s3_config["storage_client"] = client()
    


def run_command(
    cmd: Union[List[str], str],
    raise_error: bool = True,
    input: Optional[str] = None,
    try_bash: bool = False,
    login: bool = True,
    interactive: bool = True,
    shell: bool = False,
    print_oe: bool = False,
    stdout=None,
    stderr=None,
    **kwargs,
) -> Tuple[int, str, str]:
    """
    Run shell command in subprocess

    Parameters:
    ----------
    cmd: list of str, or str
        Command to execute
    raise_error: bool
        Wheter to raise an error if the command failed
    input: str, optional
        Input string for the command
    try_bash: bool
        Try to use bash if bash exists, otherwise use sh
    login: bool
        Login mode of bash when try_bash=True
    interactive: bool
        Alias of login
    shell: bool
        Use shell for subprocess.Popen
    print_oe: bool
        Print stdout and stderr at the same time
    **kwargs:
        Arguments in subprocess.Popen

    Raises:
    ------
    AssertionError:
        Raises if the error failed to execute and `raise_error` set to `True`

    Return:
    ------
    return_code: int
        The return code of the command
    out: str
        stdout content of the executed command
    err: str
        stderr content of the executed command
    """
    if print_oe:
        stdout = sys.stdout
        stderr = sys.stderr

    if isinstance(cmd, str):
        if shell:
            cmd = [cmd]
        else:
            cmd = cmd.split()
    elif isinstance(cmd, list):
        cmd = [str(x) for x in cmd]

    if try_bash:
        arg = "-lc" if (login and interactive) else "-c"
        script = "if command -v bash 2>&1 >/dev/null; then bash %s " % arg + \
            shlex.quote(" ".join(cmd)) + "; else " + " ".join(cmd) + "; fi"
        cmd = [script]
        shell = True

    with subprocess.Popen(
        args=cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=shell,
        **kwargs,
    ) as sub:
        if stdout is not None or stderr is not None:
            if input is not None:
                sub.stdin.write(bytes(input, encoding=sys.stdout.encoding))
                sub.stdin.close()
            out = ""
            err = ""
            sel = selectors.DefaultSelector()
            sel.register(sub.stdout, selectors.EVENT_READ)
            sel.register(sub.stderr, selectors.EVENT_READ)
            stdout_eof = False
            stderr_eof = False
            while not (stdout_eof and stderr_eof):
                for key, _ in sel.select():
                    line = key.fileobj.readline().decode(sys.stdout.encoding)
                    if not line:
                        if key.fileobj is sub.stdout:
                            stdout_eof = True
                        if key.fileobj is sub.stderr:
                            stderr_eof = True
                        continue
                    if key.fileobj is sub.stdout:
                        if stdout is not None:
                            stdout.write(line)
                            stdout.flush()
                        out += line
                    else:
                        if stderr is not None:
                            stderr.write(line)
                            stderr.flush()
                        err += line
            sub.wait()
        else:
            out, err = sub.communicate(bytes(
                input, encoding=sys.stdout.encoding) if input else None)
            out = out.decode(sys.stdout.encoding)
            err = err.decode(sys.stdout.encoding)
        return_code = sub.poll()
    if raise_error:
        assert return_code == 0, "Command %s failed: \n%s" % (cmd, err)
    return return_code, out, err


def _is_artifact_type(typ) -> bool:
    """Determine if a type should be treated as Artifact (True) or BigParameter (False).
    
    Args:
        typ: The type to check
        
    Returns:
        True if the type should be an Artifact (Path or List[Path]), False otherwise
    """
    # Handle typing.List, typing.Dict, etc.
    import typing
    
    # Direct Path type
    if typ is Path:
        return True
    
    # Check for List[Path]
    if hasattr(typ, '__origin__'):
        origin = typ.__origin__
        # For List[Path]
        if origin is list:
            args = getattr(typ, '__args__', ())
            if args and args[0] is Path:
                return True
    
    # Everything else (Dict, complex types, etc.) should be BigParameter
    return False


def dflow_remote_execution(
    artifact_inputs: Optional[Dict[str, type]] = None,
    artifact_outputs: Optional[Dict[str, type]] = None,
    parameter_inputs: Optional[Dict[str, type]] = None,
    parameter_outputs: Optional[Dict[str, type]] = None,
    op_name: Optional[str] = None,
):
    """
    Decorator to enable dflow remote execution for a function.
    
    This decorator wraps a function to support both local and remote execution via dflow.
    When mode="debug", the function runs locally. When mode="bohrium" or other remote modes,
    it submits the function as a dflow workflow.
    
    Args:
        artifact_inputs: Dict mapping parameter names to Path type (for file/directory inputs)
        artifact_outputs: Dict mapping return dict keys to Path type (for file/directory outputs)
        parameter_inputs: Dict mapping parameter names to their types (for simple inputs)
        parameter_outputs: Dict mapping return dict keys to their types (for simple outputs)
        op_name: Optional name for the OP class (defaults to function name)
    
    Example:
        @dflow_remote_execution(
            artifact_inputs={"train_data": List[Path], "model_path": Path},
            artifact_outputs={"model": Path, "log": Path},
            parameter_outputs={"message": str}
        )
        def my_training_function(workdir, config, train_data, model_path=None, ...):
            # Function implementation
            return {"model": model_path, "log": log_path, "message": "success"}
    
    Usage:
        # Local execution
        result = my_training_function(workdir, config, train_data, mode="debug")
        
        # Remote execution
        result = my_training_function(workdir, config, train_data, mode="bohrium", 
                                     executor=my_executor, template_config={...})
    """
    artifact_inputs = artifact_inputs or {}
    artifact_outputs = artifact_outputs or {}
    parameter_inputs = parameter_inputs or {}
    parameter_outputs = parameter_outputs or {}
    
    
    def decorator(func: Callable) -> Callable:
        # Create the OP class dynamically
        class DynamicOP(OP):
            @classmethod
            def get_input_sign(cls):
                inputs = {}
                for key, typ in artifact_inputs.items():
                    if _is_artifact_type(typ):
                        inputs[key] = Artifact(typ)
                    else:
                        inputs[key] = BigParameter(typ)
                for key, typ in parameter_inputs.items():
                    inputs[key] = Parameter(typ)
                return OPIOSign(inputs)
            
            @classmethod
            def get_output_sign(cls):
                outputs = {}
                for key, typ in artifact_outputs.items():
                    if _is_artifact_type(typ):
                        outputs[key] = Artifact(typ)
                    else:
                        outputs[key] = BigParameter(typ)
                for key, typ in parameter_outputs.items():
                    outputs[key] = Parameter(typ)
                return OPIOSign(outputs)
            
            @OP.exec_sign_check
            def execute(self, ip: OPIO) -> OPIO:
                # Extract all inputs
                kwargs = {}
                for key in artifact_inputs.keys():
                    kwargs[key] = ip[key]
                for key in parameter_inputs.keys():
                    kwargs[key] = ip[key]
                
                # Call the original function
                result = func(**kwargs)
                
                # Prepare outputs
                op_output = {}
                for key in artifact_outputs.keys():
                    op_output[key] = result[key]
                for key in parameter_outputs.keys():
                    op_output[key] = result[key]
                
                return OPIO(op_output)
        
        # Set a better name for the OP class
        op_class_name = op_name or f"{func.__name__.title().replace('_', '')}OP"
        DynamicOP.__name__ = op_class_name
        caller_module_name = func.__module__
        DynamicOP.__module__ = caller_module_name
        DynamicOP.__qualname__ = op_class_name
        
        # Register the OP class in the decorated function's module namespace.
        # DFlow imports OP classes using "<module>.<class>", so this must match
        # the module where the function is declared (e.g. dpa_tool.train).
        caller_module = sys.modules.get(caller_module_name)
        if caller_module is not None:
            setattr(caller_module, op_class_name, DynamicOP)

        # Keep a fallback registration in this module for compatibility.
        globals()[op_class_name] = DynamicOP
        
        @wraps(func)
        def wrapper(*args,  executor=None, template_config: Optional[Dict[str, Any]] = None, 
                   workflow_name: Optional[str] = None, **kwargs):
            """
            Wrapped function that supports both local and remote execution.
            
            Args:
                mode: Execution mode - "debug" for local, "bohrium" or others for remote
                executor: DFlow executor for remote execution (e.g., DispatcherExecutor)
                template_config: Configuration dict for PythonOPTemplate
                workflow_name: Name for the workflow (auto-generated if not provided)
                **kwargs: All original function parameters
            """
            mode = os.environ.get("DPA_SUBMIT_TYPE", "local")
            # Local execution
            if mode == "local":
                return func(*args, **kwargs)
            
            # Remote execution via dflow
            logger.info(f"Submitting {func.__name__} to dflow in {mode} mode")
            
            # Set dflow mode
            if mode == "bohrium":
                dflow.config["mode"] = "default"
                bohrium_config = {
                    "username": os.environ.get("BOHRIUM_USERNAME"),
                    "password": os.environ.get("BOHRIUM_PASSWORD"),
                    "project_id": int(os.environ.get("BOHRIUM_PROJECT_ID", 0)),
                }
                bohrium_config_from_dict(bohrium_config)
                
                executor = DispatcherExecutor(
                    image_pull_policy="IfNotPresent",
                    machine_dict={
                        "batch_type": "Bohrium",
                        "context_type": "Bohrium",
                        "remote_profile": {
                            "input_data": {
                            "job_type": "container",
                            "platform": "ali",
                            "scass_type": 
                        os.environ["BOHRIUM_DPA_MACHINE"]}}})
                #python_packages =[]
                env_packages = os.environ.get("BOHRIUM_PYTHON_PACKAGES","")
                python_packages = []

                for pkg_name in env_packages.split(","):
                    pkg_name = pkg_name.strip()
                    if pkg_name:
                        try:
                            mod = importlib.import_module(pkg_name)
                            python_packages.append(list(mod.__path__)[0])
                        except ImportError:
                            logging.warning(f"Failed to import package: {pkg_name}")
                
                
                template_config = {
                    "image": os.environ.get("BOHRIUM_DPA_IMAGE"),
                    "python_packages": python_packages,
                }
                
            elif mode == "debug":
                dflow.config["mode"] = mode
                template_config = {}
                executor = None
                
            else:
                raise ValueError(f"Unsupported mode: {mode}")
            # Prepare artifacts and parameters for upload
            artifacts = {}
            parameters = {}
            
            # Match positional args with function signature
            import inspect
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            
            # Build kwargs from args and kwargs
            all_kwargs = dict(zip(param_names, args))
            all_kwargs.update(kwargs)
            
            # Separate artifacts and parameters
            for key, value in all_kwargs.items():
                if key in artifact_inputs:
                    typ = artifact_inputs[key]
                    if _is_artifact_type(typ):
                        # Upload as artifact
                        if isinstance(value, (list, tuple)):
                            artifacts[key] = upload_artifact(value)
                        else:
                            artifacts[key] = upload_artifact(value)
                    else:
                        # Use as big parameter
                        parameters[key] = value
                elif key in parameter_inputs:
                    parameters[key] = value
            
            # Create workflow
            wf_name = workflow_name or f"workflow"
            wf = Workflow(name=wf_name)
            
            # Create template config
            tmpl_config = template_config or {}
            
            step_name = f"{func.__name__.lstrip('_-').replace('_', '-')}-step"
            # Create step
            step = Step(
                name=step_name,
                template=PythonOPTemplate(
                    DynamicOP,
                    **tmpl_config
                ),
                parameters=parameters,
                artifacts=artifacts,
                executor=executor,
            )
            
            wf.add(step)
            
            # Submit workflow
            logger.info(f"Submitting workflow '{wf_name}'")
            wf.submit()
            
            # Wait for completion
            while wf.query_status() in ["Pending", "Running"]:
                time.sleep(5)
            
            status = wf.query_status()
            if status != "Succeeded":
                logger.error(f"Workflow '{wf_name}' failed with status: {status}")
                return {
                    "status": "error",
                    "workflow_id": wf.id,
                    "message": f"Workflow failed with status: {status}",
                }
            
            logger.info(f"Workflow '{wf_name}' completed successfully")
            
            # Download results
            step_info = wf.query()
            try:
                completed_step = step_info.get_step(name=step_name)[0]
            except (IndexError, KeyError):
                logger.warning(f"Could not find '{step_name}' for artifact download")
                return {
                    "status": "error",
                    "workflow_id": wf.id,
                    "message": f"Workflow completed but artifacts not found",
                }
            
            # Create download directory
            download_path = Path(f"./{step_name}_results")
            download_path.mkdir(exist_ok=True)
            download_path=download_path.resolve()
            logger.info(f"Downloading artifacts to: {download_path}")
            
            # Download all artifacts
            result = {}
            for key, typ in artifact_outputs.items():
                try:
                    if _is_artifact_type(typ):
                        artifact_path = download_artifact(
                            artifact=completed_step.outputs.artifacts[key],
                            path=download_path,
                        )
                        result[key] = artifact_path
                    else:
                        # Get from big parameters
                        result[key] = completed_step.outputs.parameters[key].value.recover() if isinstance(completed_step.outputs.parameters[key].value, (dflow.argo_objects.ArgoObjectDict,dflow.argo_objects.ArgoObjectList)) else completed_step.outputs.parameters[key].value
                except Exception as e:
                    logger.error(f"Failed to download output '{key}': {e}")
                    result[key] = None
            
            # Get parameters from output
            for key in parameter_outputs.keys():
                try:
                    result[key] = completed_step.outputs.parameters[key].value.recover() if isinstance(completed_step.outputs.parameters[key].value, (dflow.argo_objects.ArgoObjectDict,dflow.argo_objects.ArgoObjectList)) else completed_step.outputs.parameters[key].value
                except Exception as e:
                    logger.error(f"Failed to get parameter '{key}': {e}")
                    result[key] = None
            
            result["workflow_id"] = wf.id
            #result["status"] = "success"
            
            return result
        
        return wrapper
    
    return decorator


def categorize_batch_inputs(
    batch_input_keys: List[str],
    artifact_inputs: Dict[str, type],
    artifact_outputs: Dict[str, type],
    parameter_inputs: Dict[str, type],
    parameter_outputs: Dict[str, type],
) -> Dict[str, List[str]]:
    """
    Helper function to categorize batch input keys into artifacts and parameters.
    
    Args:
        batch_input_keys: List of input keys to categorize
        artifact_inputs: Dict of artifact input specifications
        parameter_inputs: Dict of parameter input specifications
    
    Returns:
        Dict with 'artifacts' and 'parameters' keys containing categorized input keys
    
    Example:
        >>> categorize_batch_inputs(
        ...     ["task_path", "config"],
        ...     artifact_inputs={"task_path": Path},
        ...     parameter_inputs={"config": dict}
        ... )
        {'artifacts': ['task_path'], 'parameters': ['config']}
    """
    categorized = {
        'input_artifact': [],
        'output_artifact': [],
        'input_parameter': [],
        'output_parameter': []
    }
    
    for key in batch_input_keys:
        if key in artifact_inputs:
            categorized['input_artifact'].append(key)
        elif key in artifact_outputs:
            categorized['output_artifact'].append(key)
        elif key in parameter_inputs:
            categorized['input_parameter'].append(key)
        elif key in parameter_outputs:
            categorized['output_parameter'].append(key)
        else:
            logger.warning(f"Batch input key '{key}' not found in artifact_inputs or parameter_inputs")
    
    return categorized


def dflow_batch_execution(
    batch_input_key: List[str],  # Which parameter receives the list to batch over (e.g., "structure_paths")
    artifact_inputs: Optional[Dict[str, type]] = None,
    artifact_outputs: Optional[Dict[str, type]] = None,
    parameter_inputs: Optional[Dict[str, type]] = None,
    parameter_outputs: Optional[Dict[str, type]] = None,
    slice_config: Dict[str, Any]= {},
    exec_op_name: Optional[str] = None,
):
    """
    Decorator to enable batched dflow execution with automatic task preparation and slicing.
    
    This decorator wraps a function that processes a single item and automatically:
    1. Prepares task directories locally from batch input
    2. Creates an execution OP from the wrapped function
    3. Submits workflow with slices over all tasks
    4. Downloads and returns results
    
    Args:
        batch_input_key: Name of the parameter that contains the list to batch over (e.g., "structure_paths")
        artifact_inputs: Dict mapping parameter names to types (for file/directory inputs to exec OP)
        artifact_outputs: Dict mapping return dict keys to types (for file/directory outputs from exec OP)
        parameter_inputs: Dict mapping parameter names to their types (for simple inputs to exec OP)
        parameter_outputs: Dict mapping return dict keys to their types (for simple outputs from exec OP)
        exec_op_name: Optional name for the execution OP class
        slice_config: Configuration for slices (group_size, pool_size, etc.)
    
    Example:
        @dflow_batch_execution(
            batch_input_key="structure_paths",
            artifact_inputs={"task_path": Path, "model_path": Path},
            artifact_outputs={"traj": Path, "log": Path},
            parameter_inputs={"config": Dict[str, Any]},
            parameter_outputs={"message": str}
        )
        def run_md_task(task_path, model_path, config):
            # Process single task
            return {"traj": traj_path, "log": log_path, "message": "success"}
        
        # Usage: automatically handles batching
        result = run_md_task(
            structure_paths=[path1, path2, path3],
            model_path=model_path,
            config=config
        )
    """
    artifact_inputs = artifact_inputs or {}
    artifact_outputs = artifact_outputs or {}
    parameter_inputs = parameter_inputs or {}
    parameter_outputs = parameter_outputs or {}
    slice_config = slice_config or {"group_size": 1, "pool_size": 1}
    
    def decorator(func: Callable) -> Callable:
        # Create the execution OP class
        class ExecBatchOP(OP):
            """Execution OP that processes a single task."""
            @classmethod
            def get_input_sign(cls):
                inputs = {}
                for key, typ in artifact_inputs.items():
                    if _is_artifact_type(typ):
                        inputs[key] = Artifact(typ)
                    else:
                        inputs[key] = BigParameter(typ)
                for key, typ in parameter_inputs.items():
                    inputs[key] = Parameter(typ)
                return OPIOSign(inputs)
            
            @classmethod
            def get_output_sign(cls):
                outputs = {}
                for key, typ in artifact_outputs.items():
                    if _is_artifact_type(typ):
                        outputs[key] = Artifact(typ)
                    else:
                        outputs[key] = BigParameter(typ)
                for key, typ in parameter_outputs.items():
                    outputs[key] = Parameter(typ)
                return OPIOSign(outputs)
            
            @OP.exec_sign_check
            def execute(self, ip: OPIO) -> OPIO:
                # Extract all inputs
                kwargs = {}
                for key in artifact_inputs.keys():
                    kwargs[key] = ip[key]
                for key in parameter_inputs.keys():
                    kwargs[key] = ip[key]
                
                # Call the original function
                result = func(**kwargs)
                
                # Prepare outputs
                op_output = {}
                for key in artifact_outputs.keys():
                    op_output[key] = result[key]
                for key in parameter_outputs.keys():
                    op_output[key] = result[key]
                
                return OPIO(op_output)
        
        func_name= f"{func.__name__.lstrip('_-').replace('_', '-')}"
        # Set name for OP class
        exec_class_name = exec_op_name or f"Exec{func_name.title().replace('-', '')}OP"
        ExecBatchOP.__name__ = exec_class_name
        caller_module_name = func.__module__
        ExecBatchOP.__module__ = caller_module_name
        ExecBatchOP.__qualname__ = exec_class_name
        
        # Register in the decorated function's module namespace for dflow import.
        caller_module = sys.modules.get(caller_module_name)
        if caller_module is not None:
            setattr(caller_module, exec_class_name, ExecBatchOP)

        # Keep a fallback registration in this module for compatibility.
        globals()[exec_class_name] = ExecBatchOP
        
        @wraps(func)
        def wrapper(
            *args,
            workflow_name: Optional[str] = None,
            executor: Optional[Any] = None,
            template_config: Optional[Dict[str, Any]] = None,
            **kwargs
        ):
            """
            Wrapped function that submits batched workflow.
            
            Args:
                workflow_name: Name for the workflow
                executor: DFlow executor for remote execution
                template_config: Configuration for PythonOPTemplate
                **kwargs: All function parameters including batch input
            """
            mode = os.environ.get("DPA_SUBMIT_TYPE", "local")
            
            # Match positional args with function signature
            import inspect
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            all_kwargs = dict(zip(param_names, args))
            all_kwargs.update(kwargs)
            
            # Categorize batch inputs into artifacts/parameters for slicing
            categorized_inputs = categorize_batch_inputs(
                batch_input_key,
                artifact_inputs,
                artifact_outputs,
                parameter_inputs,
                parameter_outputs
            )   
            
            if categorized_inputs.get("input_parameter"):
                slice_num=len(all_kwargs[categorized_inputs.get("input_parameter")[0]])
            elif categorized_inputs.get("input_artifact"):
                slice_num=len(all_kwargs[categorized_inputs.get("input_artifact")[0]])
            else:
                raise ValueError("No valid batch input")
            
            # For local mode, process each item sequentially
            if mode == "local":
                batch_keys = categorized_inputs.get("input_parameter", []) + categorized_inputs.get("input_artifact", [])
                for key in batch_keys:
                    if key not in all_kwargs:
                        raise ValueError(f"Missing batch input key: {key}")
                    if len(all_kwargs[key]) != slice_num:
                        raise ValueError(
                            f"Batch input '{key}' length mismatch: expected {slice_num}, got {len(all_kwargs[key])}"
                        )

                results = {}
                for idx in range(slice_num):
                    task_key = f"task_{idx:03d}"
                    task_kwargs = dict(all_kwargs)

                    # Replace batched inputs with a single item for this task.
                    for key in batch_keys:
                        task_kwargs[key] = all_kwargs[key][idx]

                    try:
                        results[task_key] = func(**task_kwargs)
                    except Exception as e:
                        logger.error(
                            f"Local batch task '{task_key}' failed: {e}",
                            exc_info=True,
                        )
                        results[task_key] = {
                            "status": "error",
                            "message": str(e),
                        }

                return {
                    "status": "success",
                    "results": results,
                    "message": f"Processed {slice_num} tasks locally",
                }
            
            # Remote execution via dflow
            logger.info(f"Submitting batched {func.__name__} to dflow in {mode} mode")
            
            
            # Set dflow mode
            if mode == "bohrium":
                dflow.config["mode"] = "default"
                bohrium_config = {
                    "username": os.environ.get("BOHRIUM_USERNAME"),
                    "password": os.environ.get("BOHRIUM_PASSWORD"),
                    "project_id": int(os.environ.get("BOHRIUM_PROJECT_ID", 0)),
                }
                bohrium_config_from_dict(bohrium_config)
                
                executor = DispatcherExecutor(
                    image_pull_policy="IfNotPresent",
                    machine_dict={
                        "batch_type": "Bohrium",
                        "context_type": "Bohrium",
                        "remote_profile": {
                            "input_data": {
                                "job_type": "container",
                                "platform": "ali",
                                "scass_type": os.environ["BOHRIUM_DPA_MACHINE"]
                            }
                        }
                    }
                )
                
                env_packages = os.environ.get("BOHRIUM_PYTHON_PACKAGES", "")
                python_packages = []
                for pkg_name in env_packages.split(","):
                    pkg_name = pkg_name.strip()
                    if pkg_name:
                        try:
                            mod = importlib.import_module(pkg_name)
                            python_packages.append(list(mod.__path__)[0])
                        except ImportError:
                            logging.warning(f"Failed to import package: {pkg_name}")
                
                template_config = {
                    "image": os.environ.get("BOHRIUM_DPA_IMAGE"),
                    "python_packages": python_packages,
                }
                
            elif mode == "debug":
                dflow.config["mode"] = mode
                template_config = template_config or {}
                executor = executor or None
            else:
                raise ValueError(f"Unsupported mode: {mode}")
            
            artifacts = {}
            parameters = {}
            
            # Match positional args with function signature
            import inspect
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            
            # Build kwargs from args and kwargs
            all_kwargs = dict(zip(param_names, args))
            all_kwargs.update(kwargs)
            
            # Separate artifacts and parameters
            for key, value in all_kwargs.items():
                if key in artifact_inputs:
                    typ = artifact_inputs[key]
                    if _is_artifact_type(typ):
                        # Upload as artifact
                        if isinstance(value, (list, tuple)):
                            artifacts[key] = upload_artifact(value)
                        else:
                            artifacts[key] = upload_artifact(value)
                    else:
                        # Use as big parameter
                        parameters[key] = value
                elif key in parameter_inputs:
                    parameters[key] = value
            
            # Create workflow
            wf_name = workflow_name or f"batch-{func_name}"
            wf = Workflow(name=wf_name)
                
            # Create step with slices
            step_name = f"{func_name}-batch"
            step = Step(
                name=step_name,
                template=PythonOPTemplate(
                    ExecBatchOP,
                    slices=Slices(
                        '{{item}}',
                        input_artifact=categorized_inputs.get("input_artifact", None),
                        input_parameter=categorized_inputs.get("input_parameter", None),
                        output_parameter=categorized_inputs.get("output_parameter", None),
                        output_artifact=categorized_inputs.get("output_artifact", None),
                        **slice_config,
                    ),
                    **(template_config or {}),
                ),
                parameters=parameters,
                artifacts=artifacts,
                key="--".join([func_name, "{{item}}"]),
                with_param=argo_range(slice_num),
                executor=executor,
            )
            wf.add(step)
            
            # Submit workflow
            logger.info(f"Submitting workflow '{wf_name}'")
            wf.submit()
            
            # Wait for completion
            while wf.query_status() in ["Pending", "Running"]:
                time.sleep(5)
            
            status = wf.query_status()
            if status != "Succeeded":
                logger.error(f"Workflow '{wf_name}' failed with status: {status}")
                return {
                    "status": "error",
                    "workflow_id": wf.id,
                    "message": f"Workflow failed with status: {status}",
                }
            
            logger.info(f"Workflow '{wf_name}' completed successfully")
            
            # Download results
            step_info = wf.query()
            try:
                completed_step_list = step_info.get_step(name=step_name)
            except (IndexError, KeyError):
                logger.warning(f"Could not find '{step_name}' for artifact download")
                return {
                    "status": "error",
                    "workflow_id": wf.id,
                    "message": "Workflow completed but artifacts not found",
                }
            # Create unique download directory with timestamp + random suffix
            work_dir = Path(generate_work_path())
            download_path = work_dir / f"{func.__name__}_results"
            download_path.mkdir(parents=True, exist_ok=True)
            download_path=download_path.resolve()
            logger.info(f"Downloading artifacts to: {download_path}")
            
            # Download all artifacts
            result = {}
            for idx,completed_step in enumerate(completed_step_list):
                task_key = "task_%03d" % idx
                task_path = download_path / task_key
                task_path.mkdir(exist_ok=True)

                result[task_key]= {}
                for key in artifact_outputs.keys():
                    try:
                        artifact_path = download_artifact(
                            artifact=completed_step.outputs.artifacts[key],
                            path=task_path,
                        )
                        result[task_key][key] = artifact_path
                    except Exception as e:
                        logger.error(f"Failed to download artifact '{key}': {e}")
                        result[task_key][key] = None
            
                # Get parameters from output
                for key in parameter_outputs.keys():
                    try:
                        param_value = completed_step.outputs.parameters[key].value
                        result[task_key][key] = param_value.recover() if isinstance(
                            param_value, (dflow.argo_objects.ArgoObjectDict, dflow.argo_objects.ArgoObjectList)
                        ) else param_value
                    except Exception as e:
                        logger.error(f"Failed to get parameter '{key}': {e}")
                        result[task_key][key] = None
            result["workflow_id"] = wf.id
            result["status"] = "success"
            result["download_path"] = str(download_path.resolve())
            return result
        return wrapper
    return decorator
