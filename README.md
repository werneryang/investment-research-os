# Investment Research OS 运行档案

本分支由 GitHub Actions 自动维护，只追加、不修改。由 `iros archive save` 写入，结构与项目根目录相同：

- `runs/<run_id>/`：运行清单、结果与复现记录
- `reports/<study_id>/<run_id>/`：完整报告与图表
- `data/`：允许公开再分发的数据集（`archive_data: true`）中，被已归档运行使用的数据版本
- `archive.jsonl`：每次检查的记录；结论未变的运行记为 skipped，不复制文件

在新环境中复现某次运行：

    uv run iros archive restore <本分支的工作树> --with-data
    uv run iros verify <run_id>

未归档数据的可选输入（如 FRED 交叉核验）无法重算，verify 会标为部分复现。
