"""受控写 Tool：创建运营跟进任务草稿。

Tool 只创建 DRAFT，不直接落正式任务；确认由独立 API 完成。
"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from rag_demo.agent.actions import ActionError, create_followup_draft
from rag_demo.agent.tool import ToolResult


class FollowupTaskInput(BaseModel):
    title: str = Field(..., min_length=2, max_length=80, description="任务标题")
    description: str = Field(default="", max_length=1000, description="任务说明")
    owner: str = Field(default="", max_length=40, description="负责人，可为空")
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    due_date: str = Field(default="", max_length=20, description="截止日期，可为空")


@tool(args_schema=FollowupTaskInput)
def prepare_followup_task(
    title: str,
    description: str = "",
    owner: str = "",
    priority: str = "normal",
    due_date: str = "",
) -> dict:
    """创建一条待确认的运营跟进任务草稿；不会直接写入正式任务。"""
    try:
        action = create_followup_draft(
            title=title,
            description=description,
            owner=owner,
            priority=priority,
            due_date=due_date,
        )
        return ToolResult.success(
            action_id=action["action_id"],
            status=action["status"],
            title=action["title"],
            requires_confirmation=True,
            message="已创建待确认的运营跟进任务；用户确认后才会正式写入。",
        ).dump()
    except ActionError as exc:
        return ToolResult.failure(exc.code, exc.message).dump()
