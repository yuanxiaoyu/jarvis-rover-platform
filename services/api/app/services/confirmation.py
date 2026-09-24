from __future__ import annotations

from app.models.assistant import MappingAction


CONFIRMATION_WORDS = frozenset({"确认", "是", "执行", "好的"})
CANCELLATION_WORDS = frozenset({"取消", "否", "不要", "停止操作"})


def is_confirmation(text: str) -> bool:
    return text.strip() in CONFIRMATION_WORDS


def is_cancellation(text: str) -> bool:
    return text.strip() in CANCELLATION_WORDS


def action_label(action: MappingAction) -> str:
    labels = {
        "mapping_start": "开始建图",
        "mapping_pause": "暂停建图",
        "mapping_resume": "恢复建图",
        "mapping_save": "保存地图",
        "mapping_stop": "停止建图",
    }
    return labels[action.type]
