# 教训索引 | Lesson Index

> 快速定位教训的索引表。**不主动加载**，仅当 errors-ref 命中特定条目时才加载对应教训。

---

## 索引表

|| 教训 ID | 标题 | 关联 errors-ref | 根因分类 |
|---------|------|-----------------|----------|
| L001 | mover 块未闭合 | E003, E004 | CAUSE-A |
| L002 | sensor 块未闭合 | E003, E004 | CAUSE-A |
| L003 | processor 块未闭合 | E003, E004 | CAUSE-A |
| L004 | platform_type 和 platform 块混淆 | E001, E003 | CAUSE-A |
| L005 | 坐标格式错误 | E005 | CAUSE-B |
| L006 | 速度单位缺失 | E006 | CAUSE-B |
| L007 | 时间单位缺失 | E008 | CAUSE-B |
| L008 | 行尾注释 | E012 | CAUSE-B |
| L009 | side 归属混淆 | E013 | CAUSE-C |
| L010 | WSF_GUIDED_MOVER vs WSF_AIR_MOVER | E001 | CAUSE-C |
| L011 | sensor vs radar_signature 混淆 | E009, E010 | CAUSE-C |
| L012 | 缺少基类型 WSF_PLATFORM | E001, E002 | CAUSE-A |
| L013 | optical_signature/radar_signature 基类型处理不一致 | E002 | CAUSE-A |
| L014 | weapon 写在 platform 实例中（而非 platform_type 中）| E019 | CAUSE-A |
| L015 | 输出文件相对路径（相对于启动目录而非文件目录）| E020 | CAUSE-C |

---

## 关键词 → 教训 ID 映射

|| 报错关键词 | 教训 ID |
|-----------|---------|
| `Mover not closed` | L001 |
| `Sensor not closed` | L002 |
| `Processor not closed` | L003 |
| `Unknown command: platform_type` | L004, L012 |
| `Invalid position format` | L005 |
| 行尾 `#` 或 `//` | L008 |
| `side` 不一致 | L009 |
| 导弹不飞 | L010 |
| `Sensor not found` | L011 |
| weapon 在 platform 实例中 | L014 |
| Unable to open.*file | L015 |

---

## 加载规则

1. 仅当 `refs/errors-ref.md` 命中 `[Exxx]` 条目时，才查询本索引
2. 根据关联的教训 ID，加载 `memory/cold/lesson-root-causes.md` 中对应的段落
3. 加载教训后，在本次会话中引用该教训的避坑建议
4. 本次会话结束后，将教训提醒追加到 `memory/hot/session.md`
