#!/usr/bin/env python3
"""
Workflow Engine — Chain tool calls into multi-step automations.

Workflows are YAML/JSON definitions stored in workflows/ directory.
Each step calls a registered tool, with data flowing between steps
via {{step_id.field}} template references.

Features:
- Sequential and parallel step execution
- Data templating between steps ({{step_id.field}})
- Conditional steps (if: expression)
- Loop steps (for_each: "{{step.items}}")
- Error handling (on_error: skip | stop | continue)
- Cron scheduling via existing cronjob system
- Workflow variables and defaults
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safe expression evaluator for workflow conditions
# ---------------------------------------------------------------------------
import ast
import operator

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b,
    ast.IsNot: lambda a, b: a is not b,
}

_SAFE_NAMES = {
    "True": True,
    "False": False,
    "None": None,
    "len": len,
    "bool": bool,
    "int": int,
    "float": float,
    "str": str,
    "list": list,
    "dict": dict,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "any": any,
    "all": all,
}


def _safe_eval_condition(expr: str):
    """Evaluate a restricted expression for workflow conditions.

    Supported: numbers, strings, booleans, None, comparisons,
    arithmetic, "in" / "not in", "and", "or", calls to whitelisted builtins.
    """
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)


def _eval_node(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Num):  # Python < 3.8 compat
        return node.n
    if isinstance(node, ast.Str):  # Python < 3.8 compat
        return node.s
    if isinstance(node, ast.Name):
        if node.id in _SAFE_NAMES:
            return _SAFE_NAMES[node.id]
        raise NameError(f"Name {node.id!r} is not allowed")
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise TypeError(f"Unsupported binary operator: {op_type.__name__}")
        return _SAFE_OPS[op_type](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise TypeError(f"Unsupported unary operator: {op_type.__name__}")
        return _SAFE_OPS[op_type](_eval_node(node.operand))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in _SAFE_OPS:
                raise TypeError(f"Unsupported comparison: {op_type.__name__}")
            left = _SAFE_OPS[op_type](left, _eval_node(comparator))
        return left
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v) for v in node.values]
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise TypeError(f"Unsupported boolean operator: {op_type.__name__}")
        result = values[0]
        for v in values[1:]:
            result = _SAFE_OPS[op_type](result, v)
        return result
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_NAMES:
            args = [_eval_node(a) for a in node.args]
            kwargs = {kw.arg: _eval_node(kw.value) for kw in node.keywords}
            return _SAFE_NAMES[node.func.id](*args, **kwargs)
        raise TypeError("Only whitelisted function calls are allowed")
    if isinstance(node, ast.List):
        return [_eval_node(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e) for e in node.elts)
    if isinstance(node, ast.Set):
        return {_eval_node(e) for e in node.elts}
    if isinstance(node, ast.Dict):
        return {_eval_node(k): _eval_node(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.IfExp):
        return _eval_node(node.body) if _eval_node(node.test) else _eval_node(node.orelse)
    raise TypeError(f"Unsupported expression type: {type(node).__name__}")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _PROJECT_ROOT / "workflows"

# In-memory cache of running workflow state
_running_workflows: Dict[str, dict] = {}


def _ensure_workflow_dir():
    _WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)


def _list_workflow_files() -> List[Path]:
    _ensure_workflow_dir()
    files = list(_WORKFLOW_DIR.glob("*.json")) + list(_WORKFLOW_DIR.glob("*.yaml")) + list(_WORKFLOW_DIR.glob("*.yml"))
    return sorted(files)


def _load_workflow(name: str) -> Optional[dict]:
    """Load a workflow definition by name."""
    _ensure_workflow_dir()

    # Try JSON first, then YAML
    json_path = _WORKFLOW_DIR / f"{name}.json"
    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))

    for ext in (".yaml", ".yml"):
        yaml_path = _WORKFLOW_DIR / f"{name}{ext}"
        if yaml_path.exists():
            try:
                import yaml
                return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except ImportError:
                # Fallback: parse simple YAML manually or error
                return json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else None

    return None


def _save_workflow(name: str, definition: dict):
    """Save a workflow definition."""
    _ensure_workflow_dir()
    path = _WORKFLOW_DIR / f"{name}.json"
    path.write_text(
        json.dumps(definition, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Template engine — resolve {{step_id.field}} references
# ---------------------------------------------------------------------------
def _resolve_template(template: str, context: dict) -> str:
    """Replace {{step_id.field}} and {{vars.key}} with values from context."""
    if not isinstance(template, str):
        return template

    def _replacer(match):
        ref = match.group(1).strip()
        parts = ref.split(".", 1)

        if len(parts) == 1:
            # Simple reference: {{step_id}} → full output
            return json.dumps(context.get(parts[0], ""))

        section, field = parts

        if section == "vars":
            # Workflow variables
            return str(context.get("vars", {}).get(field, ""))

        # Step output reference
        step_output = context.get(section)
        if step_output is None:
            return match.group(0)  # Leave unresolved

        if isinstance(step_output, dict):
            return str(step_output.get(field, ""))
        return str(step_output)

    return re.sub(r"\{\{(.+?)\}\}", _replacer, template)


def _resolve_args(args: Any, context: dict) -> Any:
    """Recursively resolve template references in args."""
    if isinstance(args, str):
        resolved = _resolve_template(args, context)
        # Try to parse as JSON if the whole string was a template
        if resolved != args:
            try:
                return json.loads(resolved)
            except (json.JSONDecodeError, TypeError):
                pass
        return resolved
    elif isinstance(args, dict):
        return {k: _resolve_args(v, context) for k, v in args.items()}
    elif isinstance(args, list):
        return [_resolve_args(item, context) for item in args]
    return args


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------
def _evaluate_condition(condition: str, context: dict) -> bool:
    """Evaluate a simple condition string against the workflow context."""
    if not condition:
        return True

    # Resolve templates in the condition
    resolved = _resolve_template(condition, context)

    # Safe evaluation — restricted AST-based expression evaluator
    try:
        result = _safe_eval_condition(resolved)
        return bool(result)
    except Exception:
        # If safe eval fails, treat non-empty as True
        return bool(resolved.strip())


# ---------------------------------------------------------------------------
# Step executor
# ---------------------------------------------------------------------------
def _execute_step(step: dict, context: dict) -> dict:
    """Execute a single workflow step. Returns the step result."""
    step_id = step.get("id", f"step_{id(step)}")
    tool_name = step.get("tool", "")
    step_args = step.get("args", {})
    condition = step.get("if")
    on_error = step.get("on_error", "stop")
    for_each = step.get("for_each")

    result = {
        "step_id": step_id,
        "tool": tool_name,
        "status": "pending",
    }

    # Check condition
    if condition and not _evaluate_condition(condition, context):
        result["status"] = "skipped"
        result["reason"] = f"Condition not met: {condition}"
        return result

    # Handle for_each loops
    if for_each:
        items_ref = _resolve_template(for_each, context)
        try:
            items = json.loads(items_ref) if isinstance(items_ref, str) else items_ref
        except (json.JSONDecodeError, TypeError):
            items = []

        if not isinstance(items, list):
            items = [items]

        loop_results = []
        for i, item in enumerate(items):
            loop_context = {**context, "item": item, "index": i}
            resolved_args = _resolve_args(step_args, loop_context)
            try:
                output = registry.dispatch(tool_name, resolved_args)
                try:
                    parsed = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    parsed = {"raw": output}
                loop_results.append(parsed)
            except Exception as e:
                loop_results.append({"error": str(e)})

        result["status"] = "completed"
        result["output"] = loop_results
        result["iterations"] = len(items)
        return result

    # Resolve template references in args
    resolved_args = _resolve_args(step_args, context)

    # Check tool exists
    if tool_name not in registry._tools:
        result["status"] = "error"
        result["error"] = f"Tool '{tool_name}' not found in registry"
        return result

    # Execute
    try:
        output = registry.dispatch(tool_name, resolved_args)
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw": output}

        if "error" in parsed and on_error == "stop":
            result["status"] = "error"
            result["error"] = parsed["error"]
        elif "error" in parsed and on_error == "skip":
            result["status"] = "skipped"
            result["error"] = parsed["error"]
        else:
            result["status"] = "completed"

        result["output"] = parsed

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        if on_error == "skip":
            result["status"] = "skipped"

    return result


# ---------------------------------------------------------------------------
# Workflow runner
# ---------------------------------------------------------------------------
def _run_workflow(definition: dict, input_vars: dict = None) -> dict:
    """Execute a complete workflow definition."""
    wf_name = definition.get("name", "unnamed")
    steps = definition.get("steps", [])
    defaults = definition.get("defaults", {})

    # Build initial context
    context = {
        "vars": {**defaults, **(input_vars or {})},
    }

    run_id = f"wf-{int(time.time())}"
    run_result = {
        "run_id": run_id,
        "workflow": wf_name,
        "status": "running",
        "steps": [],
        "start_time": time.time(),
    }
    _running_workflows[run_id] = run_result

    for step in steps:
        step_id = step.get("id", f"step_{len(run_result['steps'])}")

        # Handle parallel steps
        parallel = step.get("parallel")
        if parallel and isinstance(parallel, list):
            parallel_results = []
            for sub_step in parallel:
                sub_id = sub_step.get("id", f"par_{len(parallel_results)}")
                sub_result = _execute_step(sub_step, context)
                sub_result["step_id"] = sub_id
                parallel_results.append(sub_result)
                # Add output to context
                if sub_result.get("output"):
                    context[sub_id] = sub_result["output"]

            run_result["steps"].append({
                "step_id": step_id,
                "type": "parallel",
                "status": "completed",
                "sub_steps": parallel_results,
            })
            continue

        # Regular step
        step_result = _execute_step(step, context)
        run_result["steps"].append(step_result)

        # Add output to context for next steps
        if step_result.get("output"):
            context[step_id] = step_result["output"]

        # Stop on error (unless step says otherwise)
        if step_result["status"] == "error" and step.get("on_error", "stop") == "stop":
            run_result["status"] = "failed"
            run_result["failed_step"] = step_id
            run_result["end_time"] = time.time()
            _running_workflows.pop(run_id, None)
            return run_result

    run_result["status"] = "completed"
    run_result["end_time"] = time.time()
    run_result["duration_s"] = round(run_result["end_time"] - run_result["start_time"], 2)
    _running_workflows.pop(run_id, None)

    # Include final context (all step outputs) for inspection
    run_result["outputs"] = {
        k: v for k, v in context.items()
        if k != "vars" and isinstance(v, (dict, list, str, int, float, bool))
    }

    return run_result


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------
def workflow_create_handler(args: dict, **kwargs) -> str:
    """Create or update a workflow definition."""
    name = args.get("name", "").strip()
    if not name:
        return json.dumps({"error": "name is required"})

    name = re.sub(r"[^a-z0-9_-]", "_", name.lower())

    steps = args.get("steps")
    if not steps:
        return json.dumps({"error": "steps are required"})

    definition = {
        "name": name,
        "description": args.get("description", ""),
        "defaults": args.get("defaults", {}),
        "steps": steps,
    }

    trigger = args.get("trigger")
    if trigger:
        definition["trigger"] = trigger

    _save_workflow(name, definition)

    return json.dumps({
        "created": True,
        "name": name,
        "steps": len(steps),
        "file": str(_WORKFLOW_DIR / f"{name}.json"),
    }, ensure_ascii=False)


def workflow_run_handler(args: dict, **kwargs) -> str:
    """Run a saved workflow or an inline workflow definition."""
    name = args.get("name", "").strip()
    inline_steps = args.get("steps")
    input_vars = args.get("variables", {})

    if inline_steps:
        # Run inline workflow
        definition = {
            "name": name or "inline",
            "steps": inline_steps,
            "defaults": args.get("defaults", {}),
        }
    elif name:
        definition = _load_workflow(name)
        if not definition:
            return json.dumps({"error": f"Workflow '{name}' not found"})
    else:
        return json.dumps({"error": "Provide 'name' of saved workflow or inline 'steps'"})

    result = _run_workflow(definition, input_vars)

    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


def workflow_list_handler(args: dict, **kwargs) -> str:
    """List all saved workflows."""
    workflows = []
    for path in _list_workflow_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            workflows.append({
                "name": data.get("name", path.stem),
                "description": data.get("description", ""),
                "steps": len(data.get("steps", [])),
                "trigger": data.get("trigger"),
                "file": path.name,
            })
        except Exception:
            workflows.append({"name": path.stem, "error": "failed to parse"})

    return json.dumps({"workflows": workflows, "count": len(workflows)}, ensure_ascii=False)


def workflow_delete_handler(args: dict, **kwargs) -> str:
    """Delete a saved workflow."""
    name = args.get("name", "").strip()
    if not name:
        return json.dumps({"error": "name is required"})

    deleted = False
    for ext in (".json", ".yaml", ".yml"):
        path = _WORKFLOW_DIR / f"{name}{ext}"
        if path.exists():
            path.unlink()
            deleted = True

    if deleted:
        return json.dumps({"deleted": True, "name": name})
    return json.dumps({"error": f"Workflow '{name}' not found"})


def workflow_schedule_handler(args: dict, **kwargs) -> str:
    """Schedule a workflow to run on a cron expression."""
    name = args.get("name", "").strip()
    if not name:
        return json.dumps({"error": "name is required"})

    cron_expr = args.get("cron", "").strip()
    if not cron_expr:
        return json.dumps({"error": "cron expression is required (e.g. '0 8 * * *')"})

    definition = _load_workflow(name)
    if not definition:
        return json.dumps({"error": f"Workflow '{name}' not found"})

    # Update workflow definition with trigger
    definition["trigger"] = cron_expr
    _save_workflow(name, definition)

    # Wire to the cronjob system if available
    try:
        cronjob_tool = registry._tools.get("cronjob")
        if cronjob_tool:
            # Use the cronjob tool to create a scheduled job that runs this workflow
            cron_args = {
                "action": "create",
                "name": f"workflow-{name}",
                "schedule": cron_expr,
                "command": f"Run workflow '{name}' now using workflow_run",
            }
            cronjob_tool.handler(cron_args)
            return json.dumps({
                "scheduled": True,
                "workflow": name,
                "cron": cron_expr,
                "cronjob_name": f"workflow-{name}",
            }, ensure_ascii=False)
    except Exception as e:
        logger.debug("Could not wire to cronjob system: %s", e)

    return json.dumps({
        "scheduled": True,
        "workflow": name,
        "cron": cron_expr,
        "note": "Trigger saved to workflow definition. Cronjob integration unavailable.",
    }, ensure_ascii=False)


def workflow_show_handler(args: dict, **kwargs) -> str:
    """Show the full definition of a saved workflow."""
    name = args.get("name", "").strip()
    if not name:
        return json.dumps({"error": "name is required"})

    definition = _load_workflow(name)
    if not definition:
        return json.dumps({"error": f"Workflow '{name}' not found"})

    return json.dumps(definition, indent=2, ensure_ascii=False)


# ===========================================================================
# Schemas & Registration
# ===========================================================================

WORKFLOW_CREATE_SCHEMA = {
    "name": "workflow_create",
    "description": (
        "Create a multi-step workflow that chains tool calls together. "
        "Each step specifies a tool and args. Use {{step_id.field}} to pass "
        "data between steps. Supports conditions (if:), loops (for_each:), "
        "parallel execution, and error handling."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Workflow name (lowercase, hyphens/underscores).",
            },
            "description": {
                "type": "string",
                "description": "What this workflow does.",
            },
            "steps": {
                "type": "array",
                "description": (
                    "Array of step objects. Each step: "
                    "{id, tool, args, if?, on_error?, for_each?, parallel?}. "
                    "Use {{step_id.field}} in args to reference previous step outputs."
                ),
                "items": {"type": "object"},
            },
            "defaults": {
                "type": "object",
                "description": "Default variable values (accessible via {{vars.key}}).",
            },
            "trigger": {
                "type": "string",
                "description": "Optional cron expression to schedule this workflow.",
            },
        },
        "required": ["name", "steps"],
    },
}

WORKFLOW_RUN_SCHEMA = {
    "name": "workflow_run",
    "description": (
        "Run a saved workflow by name, or execute inline steps directly. "
        "Pass variables to override defaults."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of saved workflow to run.",
            },
            "steps": {
                "type": "array",
                "description": "Inline steps to run (alternative to name).",
                "items": {"type": "object"},
            },
            "variables": {
                "type": "object",
                "description": "Input variables to pass to the workflow.",
            },
            "defaults": {
                "type": "object",
                "description": "Default variable values for inline workflows.",
            },
        },
    },
}

WORKFLOW_LIST_SCHEMA = {
    "name": "workflow_list",
    "description": "List all saved workflows with their step counts and triggers.",
    "parameters": {"type": "object", "properties": {}},
}

WORKFLOW_DELETE_SCHEMA = {
    "name": "workflow_delete",
    "description": "Delete a saved workflow.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workflow name to delete."},
        },
        "required": ["name"],
    },
}

WORKFLOW_SHOW_SCHEMA = {
    "name": "workflow_show",
    "description": "Show the full definition of a saved workflow.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workflow name to show."},
        },
        "required": ["name"],
    },
}

WORKFLOW_SCHEDULE_SCHEMA = {
    "name": "workflow_schedule",
    "description": (
        "Schedule a saved workflow to run automatically on a cron schedule. "
        "Example cron: '0 8 * * *' = every day at 8am, '*/30 * * * *' = every 30 min."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workflow name to schedule."},
            "cron": {"type": "string", "description": "Cron expression (e.g. '0 8 * * *')."},
        },
        "required": ["name", "cron"],
    },
}

for name, schema, handler in [
    ("workflow_create", WORKFLOW_CREATE_SCHEMA, workflow_create_handler),
    ("workflow_run", WORKFLOW_RUN_SCHEMA, workflow_run_handler),
    ("workflow_list", WORKFLOW_LIST_SCHEMA, workflow_list_handler),
    ("workflow_delete", WORKFLOW_DELETE_SCHEMA, workflow_delete_handler),
    ("workflow_show", WORKFLOW_SHOW_SCHEMA, workflow_show_handler),
    ("workflow_schedule", WORKFLOW_SCHEDULE_SCHEMA, workflow_schedule_handler),
]:
    registry.register(
        name=name, toolset="workflows", schema=schema, handler=handler,
    )
