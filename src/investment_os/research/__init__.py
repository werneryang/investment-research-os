"""研究分支。新增分支用 register_branch 注册，并在此导入。"""

from . import rates_curve  # noqa: F401  注册分支
from .base import ResearchResult, StudyInput, get_branch, register_branch

__all__ = ["ResearchResult", "StudyInput", "get_branch", "register_branch"]
