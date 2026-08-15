"""定义后端原始请求的数据结构，不在此层推导算法业务语义。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.pending_cutline_schema import PendingCutlinePlan
from app.schemas.request_schema import (
    ActiveCutlineEventRequest,
    validate_confirmed_pending_active_coverage,
)


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
    machine_code: str = Field(
        ...,
        description="机台实时状态使用的 P166 集团编码，对应静态机台 p166_jt_group",
    )
    status: str
    tangent_time: datetime | None
    input_quantity: float = Field(ge=0)
    output_quantity: float = Field(ge=0)


class BackendMachineMaster(_BackendRequestModel):
    machine_code: str = Field(
        ...,
        description="静态机台标准编码，对应 AGV equipmentid，并作为算法内部机台编码",
    )
    p166_jt_group: str = Field(
        ...,
        description="P166 集团机台编码，对应机台实时状态中的 machine_code",
    )
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
    loop_code: str | None = Field(
        default=None,
        description="兼容字段；内部循环由 process_name 重新生成",
    )
    loop_name: str | None = Field(
        default=None,
        description="兼容字段；内部循环由 process_name 重新生成",
    )
    upstream_process_code: str | None
    upstream_process_name: str | None
    downstream_process_code: str | None
    downstream_process_name: str | None


class BackendBufferRealtime(_BackendRequestModel):
    main_id: str | None
    buffer_code: str
    bound_source_name: str = Field(
        ...,
        description="Buffer 当前绑定的产品型号名称，对应当前订单 product_name",
    )
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
    equipmentid: str = Field(
        ...,
        description="AGV 记录中的机台编号，对应静态机台 machine_code",
    )
    equipmentname: str = Field(..., description="AGV 记录中的机台名称")
    linename: str = Field(..., description="机台当前生产的产品型号名称")
    lastlinename: str | None = Field(
        ...,
        description="机台上一生产的产品型号名称，未知时允许为 null 或空值",
    )
    waferspec: str = Field(..., description="机台当前订单的硅片规格")
    createtime: datetime = Field(..., description="AGV 当前绑定记录时间")


class BackendAlgorithmRequest(_BackendRequestModel):
    snapshot_meta: BackendSnapshotMeta
    machine_realtime: list[BackendMachineRealtime]
    machine_master: list[BackendMachineMaster]
    machine_process_times: list[BackendMachineProcessTime]
    workshops: list[BackendWorkshop]
    lines: list[BackendLine] = Field(default_factory=list)
    machine_lines: list[BackendMachineLine] = Field(default_factory=list)
    orders: list[BackendOrder]
    products: list[BackendProduct]
    process_routes: list[BackendProcessRoute]
    buffer_realtime: list[BackendBufferRealtime]
    buffer_master: list[BackendBufferMaster]
    agv_relations: list[BackendAgvRelation]
    pending_cutline_plans: list[PendingCutlinePlan] = Field(
        default_factory=list
    )
    active_cutline_events: list[ActiveCutlineEventRequest] = Field(
        default_factory=list
    )
    return_suggested_event_ids: list[str] = Field(default_factory=list)
    mixed_cutline_event_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "return_suggested_event_ids", "mixed_cutline_event_ids"
    )
    @classmethod
    def validate_persisted_event_ids(cls, value: list[str]) -> list[str]:
        if any(not event_id.strip() for event_id in value):
            raise ValueError("persisted event ids must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("persisted event ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_confirmed_pending_events(self) -> BackendAlgorithmRequest:
        validate_confirmed_pending_active_coverage(
            self.pending_cutline_plans,
            self.active_cutline_events,
        )
        return self
