"""槽位更正回退接口：指标发布结算、冲销对账批、槽位清单与重放核对。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, PageResult
from app.services.slot_reversal import (
    LIST_FIELDS,
    STATUSES,
    LedgerError,
    PersistenceError,
    shared_service as service,
)

router = APIRouter(prefix="/api/slot_reversal", tags=["槽位更正回退"])


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按对账批号检索"),
    status: str | None = Query(default=None, description="待冲销、已冲销"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、对账批号关键字与状态过滤冲销对账批列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="slot_reversal.csv"'})


@router.get("/manifest")
def slot_manifest() -> dict:
    """槽位清单：各槽位有效版本、批次登记与已撤回发布标识。"""
    return service.manifest_view()


@router.get("/slots")
def slot_rows() -> dict:
    """槽位清单的列表形态，供页面表格展示。"""
    return {"items": service.slot_rows(), "stats": service.stats()}


@router.get("/slots/{slot}/chain")
def slot_chain(slot: str) -> dict:
    """冲销链：槽位全部版本及来源，所有变更可复查。"""
    return {"items": service.slot_chain(slot)}


@router.get("/withdrawn")
def withdrawn_publishes() -> dict:
    """已撤回的发布标识：去重管理依据冲销对账批确认。"""
    return {"items": service.withdrawn_publishes()}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单笔冲销对账批明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"冲销对账批 {entry_id} 不存在或已归档")
    return entry


@router.post("/publish", response_model=ActionResult)
def publish(payload: dict[str, object]) -> ActionResult:
    """结算一批指标发布；重复请求只结算一次，成功回执同步携带实际已生效的槽位。"""
    request_id = str(payload.get("请求标识") or "").strip()
    entries = payload.get("指标值")
    if not isinstance(entries, dict) or not entries:
        return ActionResult(ok=False, message="指标值必须是非空的 槽位=值 映射")
    try:
        receipt = service.publish(request_id, entries)
    except LedgerError as exc:
        return ActionResult(ok=False, message=str(exc))
    except PersistenceError as exc:
        return ActionResult(ok=False, message=f"{exc}；持久结果未变，可原样重试")
    if not receipt["ok"]:
        return ActionResult(ok=False, message=receipt["失败原因"] or "结算被拒绝", entry=receipt)
    return ActionResult(ok=True, message=f"发布已结算（{receipt['回执状态']}）", entry=receipt)


@router.post("/reversals", response_model=ActionResult)
def request_reversal(payload: dict[str, object]) -> ActionResult:
    """登记一笔待冲销对账批；条目在结算时根据已写入指标值与各槽位有效版本产出。"""
    target = str(payload.get("目标批次") or "").strip()
    reason = str(payload.get("发起原因") or "").strip()
    try:
        row = service.request_reversal(target, reason)
    except LedgerError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message=f"冲销对账批{row['对账批号']}已登记，待结算", entry=row)


@router.post("/replay", response_model=ActionResult)
def replay() -> ActionResult:
    """重放提交记录，把结果回写槽位清单，并核对原批与更正批的实际写入。"""
    report = service.replay()
    count = len(report["不一致"])
    message = "重放完成，账实一致" if count == 0 else f"重放完成，发现 {count} 处不一致"
    return ActionResult(ok=count == 0, message=message, entry=report)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单笔冲销对账批执行结算冲销；重复送达的回执幂等返回。"""
    try:
        entry, message = service.run_action(entry_id, payload.action.strip())
    except PersistenceError as exc:
        return ActionResult(ok=False, message=f"{exc}；持久结果未变，可原样重试")
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
