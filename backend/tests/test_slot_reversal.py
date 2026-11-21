"""槽位更正回退：发布结算、冲销对账、并发去重、落盘失败与重放核对。

验收场景在 TestAcceptance：交错送达冲销和更正回执，包含一次落盘失败，
核对指标槽位只出现约定的有效值及可查的冲销链。
"""
import threading

import pytest

from app.services.dedup_mgr import DedupMgrService
from app.services.slot_reversal import (
    LedgerError,
    PersistenceError,
    SlotLedger,
    SlotReversalService,
)


def make_ledger(tmp_path):
    return SlotLedger.open(tmp_path / "archive")


class TestPublishSettlement:
    def test_success_returns_effective_slots(self, tmp_path):
        ledger = make_ledger(tmp_path)
        receipt = ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0, "METR-ORDER-COUNT": 10})
        assert receipt.ok and receipt.status == "settled"
        assert receipt.effective_slots["METR-GMV"] == {
            "version": 1, "value": 1800.0, "source_batch": receipt.batch_id}
        head = ledger.read("METR-GMV")
        assert head.value == 1800.0
        assert head.state == "confirmed"
        assert head.source_batch == receipt.batch_id

    def test_empty_request_rejected(self, tmp_path):
        ledger = make_ledger(tmp_path)
        with pytest.raises(LedgerError):
            ledger.settle_publish("", {"METR-GMV": 1.0})
        with pytest.raises(LedgerError):
            ledger.settle_publish("REQ-1", {})


class TestDedup:
    def test_duplicate_request_settles_once(self, tmp_path):
        ledger = make_ledger(tmp_path)
        first = ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        second = ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        assert second.status == "duplicate"
        assert second.batch_id == first.batch_id
        assert ledger.read("METR-GMV").version == 1
        assert len(ledger.storage.load_commits()) == 1

    def test_concurrent_duplicate_requests_settle_once(self, tmp_path):
        ledger = make_ledger(tmp_path)
        receipts = []

        def worker():
            receipts.append(ledger.settle_publish("REQ-RACE", {"METR-GMV": 1.0}))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(1 for r in receipts if r.status == "settled") == 1
        assert sum(1 for r in receipts if r.status == "duplicate") == 7
        assert ledger.read("METR-GMV").version == 1
        assert len(ledger.storage.load_commits()) == 1

    def test_withdrawn_publish_rejected_by_dedup(self, tmp_path):
        ledger = make_ledger(tmp_path)
        bad = ledger.settle_publish("REQ-BAD", {"METR-GMV": 99999.0})
        ledger.reverse_batch(bad.batch_id)
        replay = ledger.settle_publish("REQ-BAD", {"METR-GMV": 99999.0})
        assert replay.status == "withdrawn"
        assert not replay.ok
        assert ledger.read("METR-GMV").value is None  # 没有重新写入

    def test_dedup_mgr_confirms_withdrawn_via_reversal_batches(self, tmp_path):
        ledger = make_ledger(tmp_path)
        good = ledger.settle_publish("REQ-GOOD", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-BAD", {"METR-GMV": 99999.0})
        service = DedupMgrService()
        assert service.confirm_withdrawn(bad.batch_id, ledger=ledger) is False
        ledger.reverse_batch(bad.batch_id)
        # 去重管理依据槽位冲销对账批确认已撤回的发布标识
        assert service.confirm_withdrawn(bad.batch_id, ledger=ledger) is True
        assert service.confirm_withdrawn(good.batch_id, ledger=ledger) is False


class TestPersistenceFailure:
    def test_failed_publish_commit_leaves_nothing(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        ledger.storage.inject_failures(1)
        with pytest.raises(PersistenceError):
            ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        # 落库失败不能修改持久结果：磁盘与内存都保持原样
        assert ledger.read("METR-GMV").value == 1800.0
        assert ledger.read("METR-GMV").version == 1
        assert len(ledger.storage.load_commits()) == 1
        # 同一请求标识可原样重试并成功
        retry = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        assert retry.status == "settled"
        assert ledger.read("METR-GMV").value == 99999.0

    def test_failed_reversal_commit_leaves_nothing(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        reversal = ledger.request_reversal(bad.batch_id)
        ledger.storage.inject_failures(1)
        with pytest.raises(PersistenceError):
            ledger.settle_reversal(reversal.reversal_id)
        assert ledger.read("METR-GMV").value == 99999.0
        assert ledger.get_reversal(reversal.reversal_id).status == "pending"
        assert len(ledger.storage.load_commits()) == 2
        ledger.settle_reversal(reversal.reversal_id)
        assert ledger.read("METR-GMV").value == 1800.0


class TestReversal:
    def test_entries_point_to_slot_and_version(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0, "METR-ORDER-COUNT": 10})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0, "METR-ORDER-COUNT": 777})
        ledger.reverse_batch(bad.batch_id, reason="错批回退")
        reversal = ledger.reversal_for(bad.batch_id)
        entries = {entry.slot: entry for entry in reversal.entries}
        assert entries["METR-GMV"].reversed_version == 2
        assert entries["METR-GMV"].restored_value == 1800.0
        assert entries["METR-ORDER-COUNT"].reversed_version == 2
        assert entries["METR-ORDER-COUNT"].restored_value == 10

    def test_restores_previous_confirmed_value(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        receipt = ledger.reverse_batch(bad.batch_id)
        assert receipt.status == "settled"
        head = ledger.read("METR-GMV")
        assert head.value == 1800.0
        assert head.kind == "reversal" and head.reverses == 2
        assert ledger.read_version("METR-GMV", 2).state == "reversed"

    def test_tombstone_when_no_prior_value(self, tmp_path):
        ledger = make_ledger(tmp_path)
        bad = ledger.settle_publish("REQ-1", {"METR-UV": 777})
        ledger.reverse_batch(bad.batch_id)
        assert ledger.read("METR-UV").value is None

    def test_superseded_version_marks_only(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        ledger.settle_publish("REQ-3", {"METR-GMV": 1860.5})  # 已取代错批
        ledger.reverse_batch(bad.batch_id)
        head = ledger.read("METR-GMV")
        assert head.value == 1860.5 and head.version == 3
        assert ledger.read_version("METR-GMV", 2).state == "reversed"
        assert len(ledger.slot_history("METR-GMV")) == 3  # 没有产生恢复版本
        entry = ledger.reversal_for(bad.batch_id).entries[0]
        assert entry.new_version is None
        assert entry.reversed_version == 2

    def test_cannot_reverse_unknown_or_reversal_batch(self, tmp_path):
        ledger = make_ledger(tmp_path)
        with pytest.raises(LedgerError):
            ledger.request_reversal("PUB-999999")
        bad = ledger.settle_publish("REQ-1", {"METR-GMV": 1.0})
        receipt = ledger.reverse_batch(bad.batch_id)
        with pytest.raises(LedgerError):
            ledger.request_reversal(receipt.batch_id)

    def test_duplicate_reversal_request_is_idempotent(self, tmp_path):
        ledger = make_ledger(tmp_path)
        bad = ledger.settle_publish("REQ-1", {"METR-GMV": 1.0})
        first = ledger.request_reversal(bad.batch_id)
        second = ledger.request_reversal(bad.batch_id)
        assert first.reversal_id == second.reversal_id


class TestPublishOrderConflict:
    def test_pending_reversal_settles_before_correction(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        reversal = ledger.request_reversal(bad.batch_id)
        assert reversal.status == "pending"
        # 错批待冲销而更正在提交：立即回退优先，更正链接其后
        fix = ledger.settle_publish("REQ-3", {"METR-GMV": 1860.5})
        assert fix.status == "settled"
        settled = ledger.get_reversal(reversal.reversal_id)
        assert settled.status == "settled"
        assert settled.seq < ledger.get_batch(fix.batch_id).seq
        chain = ledger.reversal_chain("METR-GMV")
        assert [(c["version"], c["kind"], c["value"]) for c in chain] == [
            (1, "publish", 1800.0),
            (2, "publish", 99999.0),
            (3, "reversal", 1800.0),
            (4, "publish", 1860.5),
        ]
        assert ledger.read("METR-GMV").value == 1860.5

    def test_interleaved_reversal_and_correction_threads(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        reversal = ledger.request_reversal(bad.batch_id)
        barrier = threading.Barrier(2)
        receipts = {}

        def settle_reversal():
            barrier.wait()
            receipts["reversal"] = ledger.settle_reversal(reversal.reversal_id)

        def publish_correction():
            barrier.wait()
            receipts["correction"] = ledger.settle_publish("REQ-3", {"METR-GMV": 1860.5})

        threads = [threading.Thread(target=settle_reversal),
                   threading.Thread(target=publish_correction)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert receipts["reversal"].status in ("settled", "duplicate")
        assert receipts["correction"].status == "settled"
        # 无论线程先后，消费方只读到一个有来源且已确认的版本
        head = ledger.read("METR-GMV")
        assert head.value == 1860.5
        assert head.state == "confirmed" and head.source_batch
        values = [(c["version"], c["value"], c["state"]) for c in ledger.reversal_chain("METR-GMV")]
        assert values == [
            (1, 1800.0, "confirmed"),
            (2, 99999.0, "reversed"),
            (3, 1800.0, "confirmed"),
            (4, 1860.5, "confirmed"),
        ]


class TestRefreshReplay:
    def test_refresh_rereads_same_versions(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        ledger.reverse_batch(bad.batch_id)
        ledger.refresh()
        assert ledger.read_version("METR-GMV", 1).value == 1800.0
        assert ledger.read_version("METR-GMV", 2).value == 99999.0
        assert ledger.read_version("METR-GMV", 2).state == "reversed"
        assert ledger.read("METR-GMV").value == 1800.0
        # 去重注册表同样恢复：已撤回的发布标识仍被回绝
        replay = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        assert replay.status == "withdrawn"

    def test_replay_writes_report_back_to_manifest(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        bad = ledger.settle_publish("REQ-2", {"METR-GMV": 99999.0})
        ledger.reverse_batch(bad.batch_id)
        fix = ledger.settle_publish("REQ-3", {"METR-GMV": 1860.5})
        report = ledger.replay()
        assert report["replayed_commits"] == 4
        # 核对原批与更正批的实际写入
        writes = report["batches"]
        assert writes[bad.batch_id]["writes"]["METR-GMV"] == {
            "version": 2, "value": 99999.0, "state": "reversed"}
        assert writes[fix.batch_id]["writes"]["METR-GMV"] == {
            "version": 4, "value": 1860.5, "state": "confirmed"}
        assert writes[bad.batch_id]["withdrawn"] is True
        assert writes[fix.batch_id]["withdrawn"] is False
        # 重放结果已回写槽位清单；再次重放与清单账实一致
        ledger.refresh()
        assert ledger.replay()["discrepancies"] == []
        manifest = ledger.storage.read_manifest()
        assert manifest["slots"]["METR-GMV"]["effective"]["value"] == 1860.5
        assert manifest["withdrawn_publishes"] == [bad.batch_id]
        assert manifest["replay"]["replayed_commits"] == 4

    def test_replay_detects_manifest_tampering(self, tmp_path):
        ledger = make_ledger(tmp_path)
        ledger.settle_publish("REQ-1", {"METR-GMV": 1800.0})
        ledger.replay()
        manifest = ledger.storage.read_manifest()
        manifest["slots"]["METR-GMV"]["effective"]["value"] = 12345.0
        ledger.storage.write_manifest(manifest)
        report = ledger.replay()
        assert any("METR-GMV" in item for item in report["discrepancies"])


class TestServiceFacade:
    def test_catalog_and_settle_action(self, tmp_path):
        service = SlotReversalService(make_ledger(tmp_path))
        service.publish("REQ-1", {"METR-GMV": 1800.0})
        bad = service.publish("REQ-2", {"METR-GMV": 99999.0})
        row = service.request_reversal(bad["批次号"], "错批回退")
        assert row["状态"] == "待冲销"
        rows, total = service.list_entries(status="待冲销")
        assert total == 1
        entry, message = service.run_action(rows[0]["id"], "结算冲销")
        assert entry["状态"] == "已冲销"
        assert entry["撤销标识"] == bad["批次号"]
        rows, total = service.list_entries(status="待冲销")
        assert total == 0

    def test_receipt_view_carries_effective_slots(self, tmp_path):
        service = SlotReversalService(make_ledger(tmp_path))
        receipt = service.publish("REQ-1", {"METR-GMV": 1800.0})
        assert receipt["回执状态"] == "已结算"
        assert receipt["生效槽位"]["METR-GMV"]["指标值"] == 1800.0


class TestAcceptance:
    def test_interleaved_receipts_with_one_persistence_failure(self, tmp_path):
        """验收：交错送达冲销和更正回执，包含一次落盘失败。

        核对指标槽位只出现约定的有效值及可查的冲销链。
        """
        ledger = make_ledger(tmp_path)

        # 基线批：约定有效的指标值
        base = ledger.settle_publish("REQ-BASE", {"METR-GMV": 1800.0, "METR-ORDER-COUNT": 10})
        assert base.status == "settled"

        # 错批：误写的指标值
        bad = ledger.settle_publish("REQ-BAD", {"METR-GMV": 99999.0, "METR-UV": 777})
        assert ledger.read("METR-GMV").value == 99999.0

        # 错批待冲销：先登记冲销对账批（尚未结算）
        reversal = ledger.request_reversal(bad.batch_id, reason="错批回退")
        assert reversal.status == "pending"

        # 交错一：更正批恰好也在提交，且首次落盘失败 —— 持久结果与内存都不变
        ledger.storage.inject_failures(1)
        with pytest.raises(PersistenceError):
            ledger.settle_publish("REQ-FIX", {"METR-GMV": 1860.5})
        assert ledger.read("METR-GMV").value == 99999.0
        assert len(ledger.storage.load_commits()) == 2

        # 交错二：更正批重试 —— 立即回退优先结算，更正链接其后
        fix = ledger.settle_publish("REQ-FIX", {"METR-GMV": 1860.5})
        assert fix.status == "settled"
        assert fix.effective_slots["METR-GMV"]["value"] == 1860.5

        # 交错三：冲销回执随后送达 —— 幂等，不重复结算
        late = ledger.settle_reversal(reversal.reversal_id)
        assert late.status == "duplicate"

        # 指标槽位只出现约定的有效值
        assert ledger.read("METR-GMV").value == 1860.5  # 更正值
        assert ledger.read("METR-ORDER-COUNT").value == 10  # 基线值未被波及
        assert ledger.read("METR-UV").value is None  # 错批引入的槽位已置空

        # 可查的冲销链：每个版本有来源、状态与回退指向
        chain = ledger.reversal_chain("METR-GMV")
        assert [(c["version"], c["kind"], c["state"]) for c in chain] == [
            (1, "publish", "confirmed"),
            (2, "publish", "reversed"),
            (3, "reversal", "confirmed"),
            (4, "publish", "confirmed"),
        ]
        assert chain[2]["reverses"] == 2
        assert chain[2]["source_batch"] == reversal.reversal_id
        assert chain[3]["source_batch"] == fix.batch_id

        # 冲销对账批指到具体槽位和版本
        settled = ledger.get_reversal(reversal.reversal_id)
        entries = {entry.slot: entry for entry in settled.entries}
        assert entries["METR-GMV"].reversed_version == 2
        assert entries["METR-GMV"].restored_value == 1800.0
        assert entries["METR-UV"].reversed_version == 1
        assert entries["METR-UV"].restored_value is None

        # 去重管理依据冲销对账批确认已撤回的发布标识
        assert ledger.withdrawn_publishes() == [bad.batch_id]
        replayed_bad = ledger.settle_publish("REQ-BAD", {"METR-GMV": 99999.0, "METR-UV": 777})
        assert replayed_bad.status == "withdrawn"
        assert ledger.read("METR-GMV").value == 1860.5

        # 重复请求只允许结算一次
        again = ledger.settle_publish("REQ-FIX", {"METR-GMV": 1860.5})
        assert again.status == "duplicate"
        assert ledger.read("METR-GMV").version == 4

        # 刷新后仍可按相同版本重读
        ledger.refresh()
        assert ledger.read_version("METR-GMV", 2).value == 99999.0
        assert ledger.read_version("METR-GMV", 2).state == "reversed"
        assert ledger.read("METR-GMV").value == 1860.5

        # 重放结果回写槽位清单，核对原批与更正批的实际写入
        report = ledger.replay()
        assert report["replayed_commits"] == 4
        writes = report["batches"]
        assert writes[bad.batch_id]["writes"]["METR-GMV"] == {
            "version": 2, "value": 99999.0, "state": "reversed"}
        assert writes[fix.batch_id]["writes"]["METR-GMV"] == {
            "version": 4, "value": 1860.5, "state": "confirmed"}
        assert writes[bad.batch_id]["withdrawn"] is True
        ledger.refresh()
        assert ledger.replay()["discrepancies"] == []
        manifest = ledger.storage.read_manifest()
        assert manifest["slots"]["METR-GMV"]["effective"]["value"] == 1860.5
        assert manifest["withdrawn_publishes"] == [bad.batch_id]
