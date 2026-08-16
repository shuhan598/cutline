# Buffer 绑定来源格式过滤设计

## 目标

Buffer 实时绑定名称取第一个英文连字符 `-` 之前的产品名；如果该产品名不是“数字开头、随后包含英文字母和汉字，且只由数字/英文字母/汉字组成”的格式，则整条 `buffer_realtime` 记录静默忽略。

## 示例

- 保留：`210R公版-退火下-AUTO`、`210N艺馨-氧化下-AUTO`、`210R公版2-背膜下-AUTO`。
- 忽略：`天合返洗验证-退火下-AUTO`、`210公版-退火下-AUTO`、`210R-退火下-AUTO`、`R210公版-退火下-AUTO`、纯中文或空名称。

## 设计

在 `app.utils.buffer_binding` 增加格式判断和统一忽略谓词。忽略谓词同时覆盖现有逗号多值绑定与新的格式非法绑定。Backend Validator、SnapshotAdapter、MainBufferAggregator 共用该谓词，保证非法行不会进入订单映射、容量/库存聚合、预警或错误列表。

格式正确但找不到唯一当前订单的名称仍保留原有 `order_mapping_not_found` 行为；这与格式非法记录区分开。

## 影响

当前请求中 `天合返洗验证-退火下-AUTO` 的两条记录将被忽略，`31011110` 不再因它们产生订单映射错误。接口 Schema、Response Schema 和多值绑定行为不变。

## 验证

覆盖格式边界、逗号多值兼容、Backend Validator、SnapshotAdapter、MainBufferAggregator 三个入口，并使用当前请求通过 `/cutline/evaluate` 验证过滤后的响应。
