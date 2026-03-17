from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PortSurfaceSpec:
    declared_exports: list[str] = field(default_factory=list)
    extraction_rules: list[str] = field(default_factory=list)
    data_contracts: list[str] = field(default_factory=list)


@dataclass
class PortCompat:
    breaking_rules: list[str] = field(default_factory=list)
    nonbreaking_rules: list[str] = field(default_factory=list)


@dataclass
class PortProof:
    required_checks: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)


@dataclass
class PortApproval:
    breaking_requires_human: bool = True
    approvers: list[str] = field(default_factory=list)


VALID_PORT_DIRECTIONS = frozenset({"none", "export", "import", "bidirectional"})


@dataclass
class Port:
    port_id: str
    neighbor_cell_id: str | None = None
    direction: str = "none"
    surface: PortSurfaceSpec = field(default_factory=PortSurfaceSpec)
    invariants: list[str] = field(default_factory=list)
    compat: PortCompat = field(default_factory=PortCompat)
    proof: PortProof = field(default_factory=PortProof)
    approval: PortApproval = field(default_factory=PortApproval)

    def __post_init__(self) -> None:
        if self.direction not in VALID_PORT_DIRECTIONS:
            raise ValueError(
                f"Invalid port direction '{self.direction}'. "
                f"Must be one of: {sorted(VALID_PORT_DIRECTIONS)}"
            )


@dataclass
class Cell:
    cell_id: str
    paths: list[str]
    summary: str
    invariants: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    neighbors: list[str | None] = field(default_factory=lambda: [None] * 6)
    ports: list[Port | None] = field(default_factory=lambda: [None] * 6)


@dataclass
class ParentGroup:
    parent_id: str
    summary: str
    center_cell_id: str
    children: list[str | None] = field(default_factory=lambda: [None] * 6)
    overrides: dict[str, Any] = field(default_factory=dict)
    invariants: list[str] = field(default_factory=list)
    derived_neighbors: list[str | None] = field(default_factory=lambda: [None] * 6)

    def member_cells(self) -> list[str]:
        members = [self.center_cell_id]
        members.extend(child for child in self.children if child is not None)
        return members


@dataclass
class HexMap:
    version: str
    cells: list[Cell]
    port_types: dict[str, Any] = field(default_factory=dict)
    parent_groups: list[ParentGroup] = field(default_factory=list)
    _cell_index: dict[str, Cell] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._cell_index = {cell.cell_id: cell for cell in self.cells}

    def cell(self, cell_id: str) -> Cell:
        result = self._cell_index.get(cell_id)
        if result is None:
            raise KeyError(f"Unknown cell_id: {cell_id}")
        return result

    def has_cell(self, cell_id: str) -> bool:
        return cell_id in self._cell_index

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_cell_index", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HexMap:
        cells = []
        for cell_data in data.get("cells", []):
            ports = []
            for port_data in cell_data.get("ports", [None] * 6):
                if port_data is None:
                    ports.append(None)
                    continue
                ports.append(
                    Port(
                        port_id=port_data["port_id"],
                        neighbor_cell_id=port_data.get("neighbor_cell_id"),
                        direction=port_data.get("direction", "none"),
                        surface=PortSurfaceSpec(**port_data.get("surface", {})),
                        invariants=port_data.get("invariants", []),
                        compat=PortCompat(**port_data.get("compat", {})),
                        proof=PortProof(**port_data.get("proof", {})),
                        approval=PortApproval(**port_data.get("approval", {})),
                    )
                )
            cells.append(
                Cell(
                    cell_id=cell_data["cell_id"],
                    paths=cell_data.get("paths", []),
                    summary=cell_data.get("summary", ""),
                    invariants=cell_data.get("invariants", []),
                    tests=cell_data.get("tests", []),
                    neighbors=cell_data.get("neighbors", [None] * 6),
                    ports=ports,
                )
            )
        parent_groups = []
        for group_data in data.get("parent_groups", []):
            parent_groups.append(
                ParentGroup(
                    parent_id=group_data["parent_id"],
                    summary=group_data.get("summary", ""),
                    center_cell_id=group_data["center_cell_id"],
                    children=group_data.get("children", [None] * 6),
                    overrides=group_data.get("overrides", {}),
                    invariants=group_data.get("invariants", []),
                    derived_neighbors=group_data.get("derived_neighbors", [None] * 6),
                )
            )
        return cls(
            version=data.get("version", "1"),
            cells=cells,
            port_types=data.get("port_types", {}),
            parent_groups=parent_groups,
        )


@dataclass
class TaskState:
    task_id: str
    patch_sha256: str | None = None
    patch_path: str | None = None
    files_touched: list[str] = field(default_factory=list)
    status: str = "staged"
    active_cell_id: str | None = None
    radius: int | None = None
    port_check: dict[str, Any] = field(default_factory=dict)
    proofs: dict[str, Any] = field(default_factory=dict)
    approvals: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    audit_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


@dataclass
class AuditEvent:
    timestamp: str
    event_type: str
    payload: dict[str, Any]


@dataclass
class AuditRun:
    run_id: str
    command: str
    started_at: str
    status: str = "running"
    active_cell_id: str | None = None
    radius: int | None = None
    allowed_cells: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    port_impacts: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    hashes: dict[str, str] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    events: list[AuditEvent] = field(default_factory=list)
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditRun:
        events = [AuditEvent(**event) for event in data.get("events", [])]
        obj = cls(
            run_id=data["run_id"],
            command=data["command"],
            started_at=data["started_at"],
            status=data.get("status", "running"),
            active_cell_id=data.get("active_cell_id"),
            radius=data.get("radius"),
            allowed_cells=data.get("allowed_cells", []),
            files_touched=data.get("files_touched", []),
            port_impacts=data.get("port_impacts", []),
            obligations=data.get("obligations", []),
            artifacts=data.get("artifacts", []),
            hashes=data.get("hashes", {}),
            decisions=data.get("decisions", []),
            tool_calls=data.get("tool_calls", []),
            metrics=data.get("metrics", {}),
            events=events,
            finished_at=data.get("finished_at"),
        )
        return obj
