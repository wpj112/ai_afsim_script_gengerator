# AFSIM 报错索引

> 常见报错模式 + 根因 + 修正方案 + Demo 路径。命中后联动激活 `memory/cold/` 中的教训。

> **格式**：`## [Exxx] 报错关键字 → 根因 → 修正方案 → Demo`

---

## 块结构错误

### [E001] `Unknown command: platform_type` 或 `Unknown command: XXX`

**根因**：缺少基类型 `WSF_PLATFORM`。

```text
# 错误
platform_type MY_PLATFORM

# 正确
platform_type MY_PLATFORM WSF_PLATFORM
```

Demo: `../Afsim_demoslists/engage项目汇总.md` line 330

---

### [E002] `Unknown command: radar_signature`

**根因**：缺少基类型 `WSF_RADAR_SIGNATURE`。

```text
# 错误
radar_signature MY_SIGNATURE
  constant 10 m^2

# 正确
radar_signature MY_SIGNATURE WSF_RADAR_SIGNATURE
  constant 10 m^2
end_radar_signature
```

Demo: `../Afsim_demoslists/signature_demos项目汇总.md`
