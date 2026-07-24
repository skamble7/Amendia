# app/engine/bundle.py
"""PackBundle — the immutable, in-process bundle the compiler needs.

Assembles a pack manifest, its pinned resolution, the parsed BPMN model, the
pinned capability descriptors, and the pinned artifact JSON-schemas into one
value. The engine builds it from registry API responses; tests build it straight
from the seed directory. Either way the compiler consumes the same shape.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from amendia_bpmn import BpmnModel, parse
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest

from app.engine.task_runner import IOSpec, NodeContext, OutputSpec


def _bare(ref: str) -> str:
    """'cap.x@1.0.0' or 'cap.x@^1.0.0' → 'cap.x'."""
    return ref.split("@", 1)[0]


@dataclass
class PackBundle:
    manifest: ProcessPackManifest
    resolution: Dict[str, Any]                 # the registry's pinned resolution sidecar
    bpmn_model: BpmnModel
    descriptors: Dict[str, CapabilityDescriptor]   # capability_id -> pinned descriptor
    schemas: Dict[str, Dict[str, Any]]             # "art.key@x.y.z" -> json_schema
    bpmn_xml: str = ""

    @property
    def pack_key(self) -> str:
        return self.manifest.pack_key

    @property
    def pack_version(self) -> str:
        return self.manifest.version

    @property
    def required_execution_profile(self) -> str:
        """The minimum execution profile this pack needs, pinned in resolution at activation
        (ADR-027 Phase 2.5). Older packs with no pin default to the conservative common_subset."""
        return self.resolution.get("required_execution_profile", "common_subset")

    # ---- resolution helpers ----
    def resolved_binding(self, element_id: str) -> Dict[str, Any]:
        for b in self.resolution.get("bindings", []):
            if b.get("element_id") == element_id:
                return b
        raise KeyError(f"no resolved binding for element '{element_id}'")

    @classmethod
    def from_seed_dir(cls, seed_dir: str | Path) -> "PackBundle":
        """Build a bundle directly from the seed files (test/dev convenience).

        All seed refs are ``@^1.0.0`` against single ``1.0.0`` artifacts, so pinning
        is the trivial ``^1.0.0 → 1.0.0``; this mirrors what the registry's
        activation resolution produces.
        """
        root = Path(seed_dir)
        manifest = ProcessPackManifest.model_validate(json.loads((root / "manifest.json").read_text()))
        bpmn_xml = (root / manifest.process.bpmn_file).read_text()
        bpmn_model, findings = parse(bpmn_xml, manifest.process.process_id)
        # ADR-027: documented/unknown elements are warning/info — reject only on error severity.
        errors = [f for f in findings if f.severity == "error"]
        if errors:
            raise ValueError(f"seed BPMN did not parse cleanly: {[f.code for f in errors]}")

        descriptors: Dict[str, CapabilityDescriptor] = {}
        cap_versions: Dict[str, str] = {}
        for path in sorted((root / "capabilities").glob("*.json")):
            d = CapabilityDescriptor.model_validate(json.loads(path.read_text()))
            descriptors[d.capability_id] = d
            cap_versions[d.capability_id] = d.version

        schemas: Dict[str, Dict[str, Any]] = {}
        art_versions: Dict[str, str] = {}
        for path in sorted((root / "artifact-schemas").glob("*.json")):
            reg = json.loads(path.read_text())
            key, ver = reg["artifact_key"], reg["version"]
            schemas[f"{key}@{ver}"] = reg["json_schema"]
            art_versions[key] = ver

        resolution = _build_resolution(manifest, cap_versions, art_versions)
        return cls(
            manifest=manifest, resolution=resolution, bpmn_model=bpmn_model,
            descriptors=descriptors, schemas=schemas, bpmn_xml=bpmn_xml,
        )


def _build_resolution(manifest: ProcessPackManifest, cap_versions, art_versions) -> Dict[str, Any]:
    def pin_art(ref: str) -> str:
        key = _bare(ref)
        return f"{key}@{art_versions[key]}"

    bindings = []
    for b in manifest.bindings:
        executor = b.executor
        exec_cap = None
        assist = None
        if getattr(executor, "type", None) == "capability":
            cid = _bare(str(executor.capability))
            exec_cap = f"{cid}@{cap_versions[cid]}"
        elif getattr(executor, "type", None) == "human":
            if getattr(executor, "assist_capability", None):
                aid = _bare(str(executor.assist_capability))
                assist = f"{aid}@{cap_versions[aid]}"
        bindings.append({
            "element_id": b.element_id,
            "executor_capability": exec_cap,
            "assist_capability": assist,
            "inputs": [{"name": io.name, "schema": pin_art(str(io.schema_))} for io in b.inputs],
            "outputs": [{"name": io.name, "schema": pin_art(str(io.schema_))} for io in b.outputs],
        })
    return {
        "capabilities": {cid: v for cid, v in cap_versions.items()},
        "artifacts": {k: v for k, v in art_versions.items()},
        "bindings": bindings,
    }


def build_node_contexts(bundle: PackBundle) -> Dict[str, NodeContext]:
    """Assemble a NodeContext per bound BPMN element from manifest + resolution."""
    manifest_bindings = {b.element_id: b for b in bundle.manifest.bindings}
    contexts: Dict[str, NodeContext] = {}
    for element_id, mb in manifest_bindings.items():
        rb = bundle.resolved_binding(element_id)
        executor_type = getattr(mb.executor, "type", "capability")
        # ADR-031: a message binding has no HITL gate; hitl is None → treat as mode "none", no role.
        hitl_mode = "none"
        role = None
        if mb.hitl is not None:
            hitl_mode = mb.hitl.mode.value if hasattr(mb.hitl.mode, "value") else str(mb.hitl.mode)
            role = mb.hitl.role
        message_name = getattr(mb.executor, "message_name", None)

        descriptor = None
        if rb.get("executor_capability"):
            descriptor = bundle.descriptors[_bare(rb["executor_capability"])]
        assist_descriptor = None
        if rb.get("assist_capability"):
            assist_descriptor = bundle.descriptors[_bare(rb["assist_capability"])]

        # ADR-035: the wired error boundary codes attached to this element (catch-all — error_code
        # None — dropped, since it needs no legal-code hint). Threaded into the executor so a real
        # llm/mcp/deep_agent capability can emit/label a modeled business error.
        error_codes = [
            eb.error_code
            for eb in bundle.bpmn_model.error_boundaries.get(element_id, [])
            if eb.error_code
        ]

        # ADR-048: per-input data source from the manifest binding (by-alias dicts, so "from" is preserved).
        input_map = {k: v.model_dump(by_alias=True) for k, v in (getattr(mb, "input_map", None) or {}).items()}
        inputs = [IOSpec(name=io["name"], schema_ref=io["schema"]) for io in rb.get("inputs", [])]
        outputs: List[OutputSpec] = []
        for io in rb.get("outputs", []):
            ref = io["schema"]
            json_schema = bundle.schemas.get(ref)
            if json_schema is None:
                raise KeyError(f"no pinned schema for {ref} (element {element_id})")
            outputs.append(OutputSpec(
                name=io["name"], artifact_key=_bare(ref), schema_ref=ref, json_schema=json_schema,
            ))

        contexts[element_id] = NodeContext(
            element_id=element_id,
            element_kind=mb.element_kind,
            hitl_mode=hitl_mode,
            role=role,
            executor_type=executor_type,
            descriptor=descriptor,
            assist_descriptor=assist_descriptor,
            inputs=inputs,
            outputs=outputs,
            title=element_id,
            message_name=message_name,
            error_codes=error_codes,
            input_map=input_map,
        )
    return contexts
