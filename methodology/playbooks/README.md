# 判断登记

这里登记可检验的说法，到期后用官方数据核对。这是方法库的检验层，步骤与字段见 [guidance-tracking-playbook](../methods/guidance-tracking-playbook.md)。

一家公司一个文件：`<ticker>.yaml`。

## 规则

- 只登记有明确指标、数值或方向，并且有检查日期的说法。
- 自己的判断也要登记（`made_by: self`），否则只会记住说对的。
- 核对结果只说明这条说法是否兑现，不代表方法好坏，也不是投资建议。
- 来自订阅材料的说法，先按 [sources.md](../sources.md) 判断能否入库。
