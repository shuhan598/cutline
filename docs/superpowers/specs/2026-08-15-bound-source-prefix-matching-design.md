# bound_source_name 首段截取设计

## 目标

后端保留完整的 `buffer_realtime.bound_source_name`，算法内部使用第一个英文
连字符前的内容作为标准产品名，映射当前有效订单的 `product_name`。

## 匹配规则

1. 逗号多值记录仍优先整条忽略。
2. 其他记录执行 `bound_source_name.strip().split("-", 1)[0].strip()`。
3. 不根据产品目录执行精确优先或最长前缀选择。
4. 归一化后仍由现有订单索引判断唯一订单；零个或多个当前订单时继续报告
   `order_mapping_not_found` 或 `order_mapping_ambiguous`。
5. 后端请求模型中的原始 `bound_source_name` 不被修改。

## 影响范围

共享归一化函数放在 `app/utils/buffer_binding.py`。Snapshot 订单库存转换和
`MainBufferAggregator` 使用同一函数，保证库存映射与物理 Buffer 聚合一致。
通用 `CurrentOrderIndex` 和 AGV 产品名继续精确匹配。其他订单、断料、溢满
和响应规则不变。

## 验证

- `210R天合代工-背膜下-AUTO` 能映射到 `210R天合代工`。
- 不带连字符的产品名保持原值。
- `Product A-Special-AUTO` 固定截取为 `Product A`，不选择产品目录中的较长名称。
- 不满足 `product_name + "-"` 的相似字符串仍不匹配。
- 完整测试、Pyright、compileall 和 API 冒烟全部通过。

## Git 约束

不执行 `git add`、`git commit` 或 `git push`。
