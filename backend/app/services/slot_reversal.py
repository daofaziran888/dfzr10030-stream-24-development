"""槽位更正回退业务规则：冲销对账批的产出、结算、归档与重放核对都收在这里。

背景：数据落盘只有成功回执，错批没有撤销记录。本模块为指标槽位引入
版本化账本与槽位冲销对账批归档：

- 每次发布按请求标识幂等结算，成功回执同步携带实际已生效的槽位；
- 冲销对账批根据已写入的指标值与各槽位有效版本产出，条目指到具体槽位和版本；
- 提交记录不可变落盘（临时文件 + fsync + 原子改名），落库失败不修改持久结果；
- 错批待冲销而更正同时提交时，立即回退优先、更正链接其后，消费方任意时刻
  只能读到一个有来源且已确认的版本，全部版本留档可复查；
- 去重管理依据已结算的冲销对账批确认已撤回的发布标识；
- 重放提交记录可重建槽位清单，并核对原批与更正批的实际写入。
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings

MODULE = "slot_reversal"

# 槽位版本状态
CONFIRMED = "confirmed"  # 已确认：消费方唯一可读的版本
REVERSED = "reversed"  # 已冲销：被对账批撤回，仅用于复查

# 批类型
PUBLISH = "publish"
REVERSAL = "reversal"

# 结算状态
SETTLED = "settled"
DUPLICATE = "duplicate"
WITHDRAWN = "withdrawn"
PENDING = "pending"

STATUS_LABELS = {
    SETTLED: "已结算",
    DUPLICATE: "重复请求",
    WITHDRAWN: "已撤回",
    PENDING: "待冲销",
}
REVERSAL_STATUS_LABELS = {PENDING: "待冲销", SETTLED: "已冲销"}

LIST_FIELDS = ["对账批号", "目标批次", "冲销槽位", "回退条目", "归档序号", "发起原因", "撤销标识", "状态"]
STATUSES = ["待冲销", "已冲销"]


class LedgerError(Exception):
    """请求本身不合法：未知批次、空发布、重复冲销等。"""


class PersistenceError(Exception):
    """落库失败：已持久结果保持不变，调用方可原样重试。"""


@dataclass
class SlotVersion:
    """槽位的一个版本。每个版本都有来源批，状态可复查。"""

    slot: str
    version: int
    value: Any
    source_batch: str
    kind: str  # PUBLISH | REVERSAL
    state: str = CONFIRMED
    reverses: int | None = None  # 冲销版本指向被回退的具体版本
    seq: int = 0


@dataclass
class PublishBatch:
    """一批已结算的指标发布。"""

    batch_id: str
    request_id: str
    entries: dict[str, Any] = field(default_factory=dict)
    writes: dict[str, int] = field(default_factory=dict)  # 槽位 -> 实际写入版本
    seq: int = 0


@dataclass
class ReversalEntry:
    """冲销条目：必须指到具体槽位和版本。"""

    slot: str
    reversed_version: int
    reversed_value: Any
    restored_from_version: int | None
    restored_value: Any
    new_version: int | None  # 回退产生的新版本；仅标记撤回时为 None


@dataclass
class ReversalBatch:
    """槽位冲销对账批：根据已写入的指标值与各槽位有效版本产出。"""

    reversal_id: str
    target_batch_id: str
    reason: str = ""
    entries: list[ReversalEntry] = field(default_factory=list)
    status: str = PENDING
    seq: int = 0


@dataclass
class Receipt:
    """结算回执。成功时同步携带实际已生效的槽位视图。"""

    ok: bool
    status: str  # SETTLED | DUPLICATE | WITHDRAWN
    request_id: str
    batch_id: str | None = None
    effective_slots: dict[str, dict | None] = field(default_factory=dict)
    error: str | None = None

    def as_duplicate(self) -> "Receipt":
        return Receipt(
            ok=self.ok,
            status=DUPLICATE,
            request_id=self.request_id,
            batch_id=self.batch_id,
            effective_slots=dict(self.effective_slots),
            error=self.error,
        )


class ArchiveStorage:
    """槽位更正回退的数据归档。

    commits/ 下是不可变提交记录（一批一文件，临时文件 + fsync + 原子改名）；
    manifest.json 是槽位清单，由重放结果回写，可随时从提交记录重建。
    原子改名之前任何失败都不会修改已持久结果。
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.commits_dir = self.root / "commits"
        self.commits_dir.mkdir(parents=True, exist_ok=True)
        self._fail_next_commits = 0

    def inject_failures(self, count: int = 1) -> None:
        """验收用故障注入：让接下来的 count 次落盘失败。"""
        self._fail_next_commits += count

    def next_seq(self) -> int:
        seqs = [self._seq_of(path) for path in self.commits_dir.glob("*.json")]
        return max(seqs, default=0) + 1

    @staticmethod
    def _seq_of(path: Path) -> int:
        return int(path.name.split("-", 1)[0])

    def commit(self, seq: int, record: dict[str, Any]) -> Path:
        """把一条提交记录不可变落盘；失败时已持久结果保持不变。"""
        if self._fail_next_commits > 0:
            self._fail_next_commits -= 1
            raise PersistenceError(f"注入的落库失败：序号 {seq} 未写入")
        name = f"{seq:06d}-{record['id']}.json"
        final = self.commits_dir / name
        tmp = self.commits_dir / f"{name}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, final)
            self._fsync_dir(self.commits_dir)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise PersistenceError(f"落库失败：{exc}") from exc
        return final

    def load_commits(self) -> list[dict[str, Any]]:
        records = []
        for path in self.commits_dir.glob("*.json"):
            with open(path, encoding="utf-8") as handle:
                records.append(json.load(handle))
        return sorted(records, key=lambda item: item["seq"])

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        final = self.root / "manifest.json"
        tmp = self.root / "manifest.json.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, final)
        self._fsync_dir(self.root)
        return final

    def read_manifest(self) -> dict[str, Any] | None:
        path = self.root / "manifest.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class SlotLedger:
    """指标槽位账本：发布结算、冲销对账、去重判定与重放核对。"""

    def __init__(self, storage: ArchiveStorage):
        self.storage = storage
        self._lock = threading.RLock()
        self._reset()

    @classmethod
    def open(cls, root: str | Path) -> "SlotLedger":
        ledger = cls(ArchiveStorage(root))
        ledger.refresh()
        return ledger

    # ---------------- 内部状态 ----------------

    def _reset(self) -> None:
        self._slots: dict[str, list[SlotVersion]] = {}
        self._batches: dict[str, PublishBatch] = {}
        self._reversals: dict[str, ReversalBatch] = {}
        self._reversal_by_target: dict[str, str] = {}
        self._dedup: dict[str, str] = {}  # 请求标识 -> 发布批次
        self._receipts: dict[str, Receipt] = {}  # 请求标识/对账批号 -> 结算回执
        self._reversal_counter = 0
        self._seq = 0

    # ---------------- 发布结算 ----------------

    def settle_publish(self, request_id: str, entries: dict[str, Any]) -> Receipt:
        """按请求标识幂等结算一批指标值；成功回执同步携带实际已生效的槽位。"""
        request_id = str(request_id).strip()
        if not request_id:
            raise LedgerError("请求标识不能为空")
        if not entries:
            raise LedgerError("发布内容不能为空")
        with self._lock:
            known = self._dedup.get(request_id)
            if known is not None:
                # 并发或重试的重复请求只允许结算一次；已撤回的发布标识直接回绝
                if self._is_withdrawn(known):
                    return Receipt(
                        ok=False, status=WITHDRAWN, request_id=request_id, batch_id=known,
                        error=f"发布 {known} 已被冲销对账批撤回，不允许重复结算")
                return self._receipts[request_id].as_duplicate()
            # 发布次序冲突：错批待冲销而更正同时提交 —— 立即回退优先，更正链接其后
            for reversal in self._conflicting_pending_reversals(set(entries)):
                self._settle_reversal_locked(reversal.reversal_id)
            seq = self.storage.next_seq()
            batch_id = f"PUB-{seq:06d}"
            versions: list[SlotVersion] = []
            writes: dict[str, int] = {}
            effective_slots: dict[str, dict] = {}
            for slot in sorted(entries):
                version = self._next_version(slot)
                versions.append(SlotVersion(
                    slot=slot, version=version, value=entries[slot],
                    source_batch=batch_id, kind=PUBLISH, seq=seq))
                writes[slot] = version
                effective_slots[slot] = {
                    "version": version, "value": entries[slot], "source_batch": batch_id}
            record = {
                "type": PUBLISH, "id": batch_id, "seq": seq, "request_id": request_id,
                "entries": dict(entries), "writes": writes,
                "versions": [asdict(item) for item in versions],
                "effective_slots": effective_slots,
            }
            self.storage.commit(seq, record)  # 落库失败时抛出，内存与磁盘都不变
            batch = PublishBatch(
                batch_id=batch_id, request_id=request_id,
                entries=dict(entries), writes=writes, seq=seq)
            self._apply_publish(batch, versions)
            self._dedup[request_id] = batch_id
            receipt = Receipt(
                ok=True, status=SETTLED, request_id=request_id,
                batch_id=batch_id, effective_slots=effective_slots)
            self._receipts[request_id] = receipt
            return receipt

    # ---------------- 冲销对账 ----------------

    def request_reversal(self, target_batch_id: str, reason: str = "") -> ReversalBatch:
        """登记一笔待冲销对账批；同一目标批次只登记一次。"""
        with self._lock:
            if target_batch_id in self._reversals:
                raise LedgerError("冲销对账批不能被再次冲销")
            if target_batch_id not in self._batches:
                raise LedgerError(f"未知发布批次：{target_batch_id}")
            existing = self._reversal_by_target.get(target_batch_id)
            if existing is not None:
                return self._reversals[existing]
            self._reversal_counter += 1
            reversal_id = f"REV-{self._reversal_counter:04d}"
            reversal = ReversalBatch(
                reversal_id=reversal_id, target_batch_id=target_batch_id, reason=reason)
            self._reversals[reversal_id] = reversal
            self._reversal_by_target[target_batch_id] = reversal_id
            return reversal

    def settle_reversal(self, reversal_id: str) -> Receipt:
        """结算一笔待冲销对账批；重复送达的回执幂等返回。"""
        with self._lock:
            return self._settle_reversal_locked(reversal_id)

    def reverse_batch(self, target_batch_id: str, reason: str = "") -> Receipt:
        """登记并立即结算一笔冲销对账批。"""
        with self._lock:
            reversal = self.request_reversal(target_batch_id, reason)
            return self._settle_reversal_locked(reversal.reversal_id)

    def _settle_reversal_locked(self, reversal_id: str) -> Receipt:
        reversal = self._reversals.get(reversal_id)
        if reversal is None:
            raise LedgerError(f"未知冲销对账批：{reversal_id}")
        if reversal.status == SETTLED:
            return self._receipts[reversal_id].as_duplicate()
        target = self._batches.get(reversal.target_batch_id)
        if target is None:
            raise LedgerError(f"冲销目标 {reversal.target_batch_id} 不是发布批次")
        seq = self.storage.next_seq()
        entries: list[ReversalEntry] = []
        restores: list[SlotVersion] = []
        marks: list[tuple[str, int]] = []
        # 根据已写入的指标值与各槽位当前有效版本产出冲销条目
        for slot in sorted(target.writes):
            version = target.writes[slot]
            written = self._version(slot, version)
            if written.state == REVERSED:
                continue
            effective = self._effective(slot)
            if effective is not None and effective.version == version:
                # 错批仍是有效版本：立即回退到前一个已确认版本（无则置空）
                prior = self._prior_confirmed(slot, version)
                restore = SlotVersion(
                    slot=slot, version=self._next_version(slot),
                    value=prior.value if prior else None,
                    source_batch=reversal_id, kind=REVERSAL, reverses=version, seq=seq)
                restores.append(restore)
                entries.append(ReversalEntry(
                    slot=slot, reversed_version=version, reversed_value=written.value,
                    restored_from_version=prior.version if prior else None,
                    restored_value=prior.value if prior else None,
                    new_version=restore.version))
            else:
                # 错批已被更新版本取代：只标记撤回，不动当前有效值
                entries.append(ReversalEntry(
                    slot=slot, reversed_version=version, reversed_value=written.value,
                    restored_from_version=effective.version if effective else None,
                    restored_value=effective.value if effective else None,
                    new_version=None))
            marks.append((slot, version))
        restore_by_slot = {item.slot: item for item in restores}
        effective_slots: dict[str, dict | None] = {}
        for entry in entries:
            restore = restore_by_slot.get(entry.slot)
            if restore is not None:
                effective_slots[entry.slot] = {
                    "version": restore.version, "value": restore.value,
                    "source_batch": reversal_id}
            else:
                effective = self._effective(entry.slot)
                effective_slots[entry.slot] = (
                    {"version": effective.version, "value": effective.value,
                     "source_batch": effective.source_batch} if effective else None)
        record = {
            "type": REVERSAL, "id": reversal_id, "seq": seq,
            "target_batch_id": reversal.target_batch_id, "reason": reversal.reason,
            "entries": [asdict(item) for item in entries],
            "marks": [list(item) for item in marks],
            "restores": [asdict(item) for item in restores],
            "effective_slots": effective_slots,
        }
        self.storage.commit(seq, record)  # 落库失败时抛出，内存与磁盘都不变
        reversal.entries = entries
        reversal.seq = seq
        self._apply_reversal(reversal, restores, marks)
        receipt = Receipt(
            ok=True, status=SETTLED, request_id=reversal_id,
            batch_id=reversal_id, effective_slots=effective_slots)
        self._receipts[reversal_id] = receipt
        return receipt

    # ---------------- 消费方读取 ----------------

    def read(self, slot: str) -> SlotVersion | None:
        """消费方读取：任意时刻只返回一个有来源且已确认的版本。"""
        with self._lock:
            return self._effective(slot)

    def read_version(self, slot: str, version: int) -> SlotVersion:
        """按相同版本重读历史，供复查与刷新后核对。"""
        with self._lock:
            return self._version(slot, version)

    def slot_history(self, slot: str) -> list[SlotVersion]:
        with self._lock:
            return list(self._slots.get(slot, []))

    def reversal_chain(self, slot: str) -> list[dict[str, Any]]:
        """冲销链：槽位全部版本及其来源，供复查。"""
        with self._lock:
            return [asdict(item) for item in self._slots.get(slot, [])]

    # ---------------- 批次与对账批查询 ----------------

    def get_batch(self, batch_id: str) -> PublishBatch | None:
        with self._lock:
            return self._batches.get(batch_id)

    def get_reversal(self, reversal_id: str) -> ReversalBatch | None:
        with self._lock:
            return self._reversals.get(reversal_id)

    def reversal_for(self, target_batch_id: str) -> ReversalBatch | None:
        with self._lock:
            reversal_id = self._reversal_by_target.get(target_batch_id)
            return self._reversals.get(reversal_id) if reversal_id else None

    def list_reversals(self) -> list[ReversalBatch]:
        with self._lock:
            return [self._reversals[key] for key in sorted(self._reversals)]

    def list_batches(self) -> list[PublishBatch]:
        with self._lock:
            return [self._batches[key] for key in sorted(self._batches)]

    def withdrawn_publishes(self) -> list[str]:
        """已撤回的发布标识：去重管理依据已结算的冲销对账批确认。"""
        with self._lock:
            return sorted(self._withdrawn_ids())

    # ---------------- 刷新与重放 ----------------

    def refresh(self) -> None:
        """刷新：从归档重新加载，之后仍可按相同版本重读。"""
        with self._lock:
            self._reset()
            for record in self.storage.load_commits():
                self._apply_commit(record)

    def replay(self) -> dict[str, Any]:
        """重放提交记录重建账本，把结果回写槽位清单，并核对原批与更正批的实际写入。"""
        with self._lock:
            previous = self.storage.read_manifest()
            self._reset()
            commits = self.storage.load_commits()
            for record in commits:
                self._apply_commit(record)
            report = {
                "replayed_commits": len(commits),
                "batches": self._batch_write_report(),
                "withdrawn": sorted(self._withdrawn_ids()),
                "discrepancies": self._diff_manifest(previous),
            }
            self.storage.write_manifest(self._build_manifest(report))
            return report

    def slot_manifest(self) -> dict[str, Any]:
        """当前槽位清单视图（不落盘）；落盘版本由 replay 回写。"""
        with self._lock:
            return self._build_manifest(replay_report=None)

    # ---------------- 内部：状态应用 ----------------

    def _apply_publish(self, batch: PublishBatch, versions: list[SlotVersion]) -> None:
        self._batches[batch.batch_id] = batch
        for item in versions:
            self._slots.setdefault(item.slot, []).append(item)
        self._seq = max(self._seq, batch.seq)

    def _apply_reversal(
        self,
        reversal: ReversalBatch,
        restores: list[SlotVersion],
        marks: list[tuple[str, int]],
    ) -> None:
        self._reversals[reversal.reversal_id] = reversal
        self._reversal_by_target[reversal.target_batch_id] = reversal.reversal_id
        for slot, version in marks:
            self._version(slot, version).state = REVERSED
        for item in restores:
            self._slots.setdefault(item.slot, []).append(item)
        reversal.status = SETTLED
        self._seq = max(self._seq, reversal.seq)

    def _apply_commit(self, record: dict[str, Any]) -> None:
        self._seq = max(self._seq, int(record["seq"]))
        if record["type"] == PUBLISH:
            versions = [SlotVersion(**item) for item in record["versions"]]
            batch = PublishBatch(
                batch_id=record["id"], request_id=record["request_id"],
                entries=dict(record["entries"]),
                writes={slot: int(ver) for slot, ver in record["writes"].items()},
                seq=int(record["seq"]))
            self._apply_publish(batch, versions)
            self._dedup[batch.request_id] = batch.batch_id
            self._receipts[batch.request_id] = Receipt(
                ok=True, status=SETTLED, request_id=batch.request_id,
                batch_id=batch.batch_id,
                effective_slots={
                    slot: dict(view) if view else None
                    for slot, view in record["effective_slots"].items()})
        elif record["type"] == REVERSAL:
            reversal = ReversalBatch(
                reversal_id=record["id"], target_batch_id=record["target_batch_id"],
                reason=record.get("reason", ""),
                entries=[ReversalEntry(**item) for item in record["entries"]],
                status=SETTLED, seq=int(record["seq"]))
            restores = [SlotVersion(**item) for item in record["restores"]]
            marks = [(slot, int(ver)) for slot, ver in record["marks"]]
            self._apply_reversal(reversal, restores, marks)
            self._reversal_counter = max(
                self._reversal_counter, self._ordinal(reversal.reversal_id))
            self._receipts[reversal.reversal_id] = Receipt(
                ok=True, status=SETTLED, request_id=reversal.reversal_id,
                batch_id=reversal.reversal_id,
                effective_slots={
                    slot: dict(view) if view else None
                    for slot, view in record["effective_slots"].items()})

    # ---------------- 内部：派生状态 ----------------

    def _version(self, slot: str, version: int) -> SlotVersion:
        for item in self._slots.get(slot, []):
            if item.version == version:
                return item
        raise LedgerError(f"槽位 {slot} 不存在版本 {version}")

    def _next_version(self, slot: str) -> int:
        return len(self._slots.get(slot, [])) + 1

    def _effective(self, slot: str) -> SlotVersion | None:
        for item in reversed(self._slots.get(slot, [])):
            if item.state == CONFIRMED:
                return item
        return None

    def _prior_confirmed(self, slot: str, before_version: int) -> SlotVersion | None:
        for item in reversed(self._slots.get(slot, [])):
            if item.version < before_version and item.state == CONFIRMED:
                return item
        return None

    def _is_withdrawn(self, batch_id: str) -> bool:
        return batch_id in self._withdrawn_ids()

    def _withdrawn_ids(self) -> set[str]:
        return {
            item.target_batch_id
            for item in self._reversals.values()
            if item.status == SETTLED
        }

    def _conflicting_pending_reversals(self, slots: set[str]) -> list[ReversalBatch]:
        """待冲销且目标版本仍是槽位有效版本的对账批，与新提交构成发布次序冲突。"""
        conflicts = []
        for reversal in self._reversals.values():
            if reversal.status != PENDING:
                continue
            target = self._batches.get(reversal.target_batch_id)
            if target is None:
                continue
            for slot, version in target.writes.items():
                if slot not in slots:
                    continue
                effective = self._effective(slot)
                if effective is not None and effective.version == version:
                    conflicts.append(reversal)
                    break
        return conflicts

    @staticmethod
    def _ordinal(batch_id: str) -> int:
        try:
            return int(batch_id.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            return 0

    # ---------------- 内部：清单与核对 ----------------

    def _build_manifest(self, replay_report: dict[str, Any] | None) -> dict[str, Any]:
        withdrawn = self._withdrawn_ids()
        return {
            "seq": self._seq,
            "slots": {
                slot: {
                    "effective": asdict(effective) if (effective := self._effective(slot)) else None,
                    "versions": [asdict(item) for item in versions],
                }
                for slot, versions in sorted(self._slots.items())
            },
            "batches": {
                batch_id: {
                    "request_id": batch.request_id,
                    "seq": batch.seq,
                    "withdrawn": batch_id in withdrawn,
                    "writes": dict(batch.writes),
                }
                for batch_id, batch in sorted(self._batches.items())
            },
            "reversal_batches": {
                reversal_id: {
                    "target_batch_id": item.target_batch_id,
                    "reason": item.reason,
                    "status": item.status,
                    "seq": item.seq,
                    "entries": [asdict(entry) for entry in item.entries],
                }
                for reversal_id, item in sorted(self._reversals.items())
            },
            "dedup": dict(sorted(self._dedup.items())),
            "withdrawn_publishes": sorted(withdrawn),
            "replay": replay_report,
        }

    def _batch_write_report(self) -> dict[str, Any]:
        """原批与更正批的实际写入，供对账核对。"""
        report = {}
        for batch_id, batch in sorted(self._batches.items()):
            writes = {}
            for slot, version in sorted(batch.writes.items()):
                written = self._version(slot, version)
                writes[slot] = {
                    "version": version, "value": written.value, "state": written.state}
            report[batch_id] = {
                "request_id": batch.request_id,
                "seq": batch.seq,
                "withdrawn": batch_id in self._withdrawn_ids(),
                "writes": writes,
            }
        return report

    def _diff_manifest(self, previous: dict[str, Any] | None) -> list[str]:
        if previous is None:
            return []
        diffs = []
        old_slots = previous.get("slots", {})
        for slot in sorted(set(old_slots) | set(self._slots)):
            old_effective = old_slots.get(slot, {}).get("effective")
            current = self._effective(slot)
            new_effective = asdict(current) if current else None
            if old_effective != new_effective:
                diffs.append(f"槽位 {slot} 有效版本不一致：清单={old_effective} 重放={new_effective}")
        old_batches = previous.get("batches", {})
        for batch_id, batch in self._batches.items():
            old = old_batches.get(batch_id)
            if old is None:
                continue
            if old.get("writes") != batch.writes:
                diffs.append(
                    f"批次 {batch_id} 实际写入不一致：清单={old.get('writes')} 重放={batch.writes}")
        return diffs


class SlotReversalService:
    """模块门面：把账本操作包装成列表与动作口径，状态流转只允许在这里改。"""

    ACTION_RULES = {"结算冲销": "已冲销"}

    def __init__(self, ledger: SlotLedger | None = None):
        self._ledger = ledger

    @property
    def ledger(self) -> SlotLedger:
        if self._ledger is None:
            self._ledger = SlotLedger.open(settings.slot_archive_dir)
        return self._ledger

    # ---------------- 列表口径 ----------------

    def _catalog_rows(self) -> list[dict[str, Any]]:
        rows = []
        for index, reversal in enumerate(self.ledger.list_reversals(), start=1):
            entries = reversal.entries
            if entries:
                slots = "、".join(sorted({entry.slot for entry in entries}))
            else:
                target = self.ledger.get_batch(reversal.target_batch_id)
                slots = "、".join(sorted(target.writes)) if target else "—"
            status = REVERSAL_STATUS_LABELS.get(reversal.status, reversal.status)
            rows.append({
                "id": index,
                "对账批号": reversal.reversal_id,
                "目标批次": reversal.target_batch_id,
                "冲销槽位": slots or "—",
                "回退条目": len(entries),
                "归档序号": reversal.seq or "—",
                "发起原因": reversal.reason or "—",
                "撤销标识": reversal.target_batch_id if reversal.status == SETTLED else "—",
                "状态": status,
                "status": status,
                "pending": reversal.status != SETTLED,
                "abnormal": False,
            })
        return rows

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._catalog_rows()
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("对账批号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        for row in self._catalog_rows():
            if row["id"] == entry_id:
                reversal = self.ledger.get_reversal(row["对账批号"])
                detail = dict(row)
                detail["冲销条目"] = [asdict(entry) for entry in reversal.entries] if reversal else []
                return detail
        return None

    # ---------------- 业务动作 ----------------

    def publish(self, request_id: str, entries: dict[str, Any]) -> dict[str, Any]:
        """结算一批指标发布，返回回执视图。"""
        receipt = self.ledger.settle_publish(request_id, entries)
        return self._receipt_view(receipt)

    def request_reversal(self, target_batch_id: str, reason: str = "") -> dict[str, Any]:
        reversal = self.ledger.request_reversal(target_batch_id.strip(), reason.strip())
        return self._row_for(reversal.reversal_id)

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        row = self.get_entry(entry_id)
        if row is None:
            return None, f"冲销对账批 {entry_id} 不存在或已归档"
        if action not in self.ACTION_RULES:
            return None, f"动作「{action}」不属于槽位更正回退可执行范围"
        receipt = self.ledger.settle_reversal(row["对账批号"])
        return self.get_entry(entry_id), f"冲销对账批{row['对账批号']}已{action}（{STATUS_LABELS[receipt.status]}）"

    def replay(self) -> dict[str, Any]:
        report = self.ledger.replay()
        return {
            "重放提交数": report["replayed_commits"],
            "已撤回发布": report["withdrawn"],
            "批次写入": report["batches"],
            "不一致": report["discrepancies"],
        }

    # ---------------- 查询视图 ----------------

    def manifest_view(self) -> dict[str, Any]:
        manifest = self.ledger.slot_manifest()
        return {
            "归档序号": manifest["seq"],
            "槽位": manifest["slots"],
            "批次": manifest["batches"],
            "冲销对账批": manifest["reversal_batches"],
            "已撤回发布": manifest["withdrawn_publishes"],
        }

    def slot_rows(self) -> list[dict[str, Any]]:
        rows = []
        manifest = self.ledger.slot_manifest()
        for slot, info in manifest["slots"].items():
            effective = info["effective"]
            versions = info["versions"]
            rows.append({
                "槽位": slot,
                "有效版本": effective["version"] if effective else "—",
                "指标值": effective["value"] if effective else "—",
                "来源批次": effective["source_batch"] if effective else "—",
                "版本数": len(versions),
                "已冲销版本": sum(1 for item in versions if item["state"] == REVERSED),
            })
        return rows

    def slot_chain(self, slot: str) -> list[dict[str, Any]]:
        chain = []
        for item in self.ledger.reversal_chain(slot):
            chain.append({
                "版本": item["version"],
                "指标值": item["value"],
                "来源批次": item["source_batch"],
                "类型": "冲销回退" if item["kind"] == REVERSAL else "发布",
                "状态": "已确认" if item["state"] == CONFIRMED else "已冲销",
                "回退自版本": item["reverses"] if item["reverses"] is not None else "—",
                "归档序号": item["seq"],
            })
        return chain

    def withdrawn_publishes(self) -> list[str]:
        return self.ledger.withdrawn_publishes()

    def stats(self) -> dict[str, int]:
        manifest = self.ledger.slot_manifest()
        reversals = self.ledger.list_reversals()
        return {
            "槽位总数": len(manifest["slots"]),
            "待冲销对账批": sum(1 for item in reversals if item.status == PENDING),
            "已撤回发布": len(manifest["withdrawn_publishes"]),
            "归档提交数": manifest["seq"],
        }

    # ---------------- 内部 ----------------

    def _row_for(self, reversal_id: str) -> dict[str, Any]:
        for row in self._catalog_rows():
            if row["对账批号"] == reversal_id:
                return row
        raise LedgerError(f"未知冲销对账批：{reversal_id}")

    @staticmethod
    def _receipt_view(receipt: Receipt) -> dict[str, Any]:
        return {
            "ok": receipt.ok,
            "回执状态": STATUS_LABELS.get(receipt.status, receipt.status),
            "请求标识": receipt.request_id,
            "批次号": receipt.batch_id,
            "生效槽位": {
                slot: (
                    {"版本": view["version"], "指标值": view["value"], "来源批次": view["source_batch"]}
                    if view else None
                )
                for slot, view in receipt.effective_slots.items()
            },
            "失败原因": receipt.error,
        }


# 路由与去重管理共用的模块级服务；归档目录来自配置，首次使用时才打开。
shared_service = SlotReversalService()
