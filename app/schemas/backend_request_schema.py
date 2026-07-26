from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _BackendRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackendSnapshotMeta(_BackendRequestModel):
    run_id: str
    trigger_type: str
    workshop_id: str
    snapshot_time: datetime
    params_version: int
    catalog_version: str
    catalog_loaded_at: datetime
    degraded_flags: list[str]


class BackendMachineRealtime(_BackendRequestModel):
    machine_code: str
    status: str
    tangent_time: datetime | None
    input_quantity: float = Field(ge=0)
    output_quantity: float = Field(ge=0)
    completed_quantity: float = Field(ge=0)


class BackendMachineMaster(_BackendRequestModel):
    machine_code: str
    machine_name: str
    process_code: str
    process_name: str


class BackendMachineProcessTime(_BackendRequestModel):
    machine_code: str
    machine_name: str
    product_code: str
    product_name: str
    proc_seconds: float = Field(gt=0)
    actual_capacity: float = Field(gt=0)


class BackendWorkshop(_BackendRequestModel):
    workshop_code: str
    workshop_name: str | None


class BackendLine(_BackendRequestModel):
    line_code: str
    line_name: str
    wafer_spec: str
    workshop_code: str
    workshop_name: str


class BackendMachineLine(_BackendRequestModel):
    machine_code: str
    machine_name: str
    line_code: str
    line_name: str
    wafer_spec: str


class BackendOrder(_BackendRequestModel):
    order_code: str
    order_status: str
    total_quantity: float = Field(ge=0)
    piece_source: str
    estimated_yield: str
    product_code: str
    product_name: str
    workshop_code: str
    workshop_name: str
    produced_quantity: float = Field(ge=0)
    remaining_quantity: float = Field(ge=0)


class BackendProduct(_BackendRequestModel):
    product_code: str
    product_name: str
    wafer_size: str
    source_grade: str
    material_code: str
    material_name: str


class BackendProcessRoute(_BackendRequestModel):
    process_code: str
    process_name: str
    sequence: int
    cache_type: str
    workshop_code: str
    workshop_name: str
    loop_code: str
    loop_name: str
    upstream_process_code: str | None
    upstream_process_name: str | None
    downstream_process_code: str | None
    downstream_process_name: str | None


class BackendBufferRealtime(_BackendRequestModel):
    main_id: str | None
    buffer_code: str
    bound_source_name: str
    current_quantity: float = Field(ge=0)
    current_utilization_rate: float = Field(ge=0)


class BackendBufferMaster(_BackendRequestModel):
    buffer_code: str
    buffer_name: str
    buffer_type: str
    buffer_type_title: str
    max_capacity: float = Field(gt=0)
    safety_low: float = Field(ge=0)
    served_process_codes: list[str] = Field(min_length=1)
    served_process_names: list[str] = Field(min_length=1)
    loop_code: str
    loop_name: str


class BackendAgvRelation(_BackendRequestModel):
    equipmentid: str
    equipmentname: str
    lastlinecode: str
    lastlinename: str
    waferspec: str
    createtime: datetime


class BackendAlgorithmRequest(_BackendRequestModel):
    snapshot_meta: BackendSnapshotMeta
    machine_realtime: list[BackendMachineRealtime]
    machine_master: list[BackendMachineMaster]
    machine_process_times: list[BackendMachineProcessTime]
    workshops: list[BackendWorkshop]
    lines: list[BackendLine]
    machine_lines: list[BackendMachineLine]
    orders: list[BackendOrder]
    products: list[BackendProduct]
    process_routes: list[BackendProcessRoute]
    buffer_realtime: list[BackendBufferRealtime]
    buffer_master: list[BackendBufferMaster]
    agv_relations: list[BackendAgvRelation]
