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

---

### [E003] `Mover not closed` / `Sensor not closed` / `Weapon not closed`

**根因**：缺少对应的 `end_mover` / `end_sensor` / `end_weapon`。

```text
# 错误
mover WSF_AIR_MOVER
   debug
# 缺少 end_mover

# 正确
mover WSF_AIR_MOVER
   debug
end_mover
```

Demo: `../Afsim_demoslists/engage项目汇总.md` line 334-339

---

### [E004] 块嵌套不完整（缺少 `end_xxx`）

**根因**：platform_type / platform / processor 等块没有正确闭合。

```text
# 错误
platform_type MY_TYPE WSF_PLATFORM
   side blue
end_platform_type
platform my_plane MY_TYPE
   side blue
end_platform   # ← 缺少 end_platform

# 正确
platform_type MY_TYPE WSF_PLATFORM
   side blue
end_platform_type

platform my_plane MY_TYPE
   side blue
end_platform
```

---

## 坐标 / 参数格式错误

### [E005] `Invalid position format`

**根因**：坐标格式不正确。AFSIM 要求 `d:m:s N/S e/w`。

```text
# 错误
position 30 120 altitude 10000
position 30.0N 120.0E altitude 10000 ft msl

# 正确
position 30:00:00n 120:00:00e altitude 10000 ft msl
position 30:30:00n 120:30:00e altitude 5000 ft msl
```

Demo: `../Afsim_demoslists/engage项目汇总.md` line 343-350

---

### [E006] 速度单位缺失

**根因**：speed 后缺少单位。

```text
# 错误
speed 300

# 正确
speed 300 kts
speed 150 m/s
speed 0.8 mach
```

---

### [E007] 高度单位缺失或格式错误

**根因**：altitude 后缺少单位或使用了错误单位。

```text
# 错误
altitude 10000
altitude 10000 msl

# 正确
altitude 10000 ft msl
altitude 5000 m agl
```

---

### [E008] 时间单位缺失

**根因**：end_time 等时间参数缺少单位。

```text
# 错误
end_time 30

# 正确
end_time 30 sec
end_time 10 min
end_time 2 hr
```

Demo: `../Afsim_demoslists/engage项目汇总.md` line 353

---

## 命名 / 引用错误

### [E009] `Sensor not found`

**根因**：引用的传感器名称未定义或拼写错误。

检查项：
1. 传感器是否在 platform_type 内的 sensor 块中定义
2. 名称拼写是否完全一致（区分大小写）
3. 传感器基类型是否正确

```text
# 错误：sensor 名称拼写不一致
sensor find WSF_GEOMETRIC_SENSOR
   ...
end_sensor

processor operator WSF_TASK_PROCESSOR
   return StartTracking(TRACK, "DUMMY", PLATFORM.Sensor("findr"), "SEARCH");
   #                       ↑ findr 而非 find
end_processor

# 正确：名称一致
return StartTracking(TRACK, "DUMMY", PLATFORM.Sensor("find"), "SEARCH");
```

---

### [E010] `Weapon not found`

**根因**：weapon 名称未定义或 platform_type 中未声明 weapon。

```text
# 在 platform_type 中定义 weapon
platform_type LAUNCHER_TYPE WSF_PLATFORM
   weapon lrsam LRSAM
     quantity 1
   end_weapon
end_platform_type

# 在 platform 实例中引用
platform launcher1 LAUNCHER_TYPE
   weapon lrsam
end_platform
```

---

### [E011] 引用的 route 不存在

**根因**：`assign_route` 或 platform 内 route 引用的 route 名称未定义。

---

## 注释语法错误

### [E012] 行尾注释

**根因**：AFSIM 不支持行尾注释，注释必须在独立行。

```text
# 错误
position 30:00:00n 120:00:00e altitude 10000 ft msl # 这是注释

# 正确（注释在独立行）
position 30:00:00n 120:00:00e altitude 10000 ft msl
# 这是注释
```

---

## 阵营 / 关系错误

### [E013] 阵营名称不一致

**根因**：platform_type 中的 side 和 platform 实例中的 side 不匹配。

```text
# platform_type 中定义 side
platform_type MY_TYPE WSF_PLATFORM
   side red
end_platform_type

# platform 实例中也可以覆盖，但需一致
platform my_unit MY_TYPE
   side red  # ← 必须是 red
end_platform
```

---

## 逻辑 / 脚本错误

### [E014] `Script syntax error`

**根因**：processor 中的脚本语法错误（括号不匹配、缺少分号等）。

```text
# 错误
if (TRACK.TrackQuality() > 0.65
{  # ← 缺少右括号

# 正确
if (TRACK.TrackQuality() > 0.65)
{
   status = StartTracking(TRACK, "DUMMY", PLATFORM.Sensor("ttr"), "ACQUIRE");
}
```

Demo: `../Afsim_demoslists/engage项目汇总.md` line 60-100

---

### [E015] processor 中使用错误的 API

**根因**：processor 脚本中调用的 API 不存在或参数错误。

常见错误：
- `StartTracking` 拼写错误
- `PLATFORM.Sensor()` 名称与实际定义不一致
- 状态名与 `evaluation_interval` 不匹配

---

## 版本兼容错误

### [E016] `Unknown command: comm_network`

**根因**：`comm_network` 在不同 AFSIM 版本中语法不一致。

**建议**：简单仿真避免使用复杂通信网络功能，专注核心平台运动和传感器仿真。

---

## 追加记录

每次遇到新报错并修正后，将模式追加到此文件末尾：

```markdown
### [Exxx] <报错关键字>

**根因**：<描述>

**修正**：
```text
<修正后的代码>
```

Demo: <相关 Demo 路径>
```

---

### [E017] `Unknown weapon: <name>`

**根因**：weapon 实例中引用的 weapon 类型名称与实际定义的 `weapon XXX WSF_EXPLICIT_WEAPON` 名称不一致，或拼写错误（区分大小写）。

```text
# 错误：weapon 类型定义为 HYPHYP_WEAPON，但引用时拼写成 hyphpyp_missile
   weapon hyphpyp_missile HYPHYP_WEAPON
   end_weapon
   wpn = PLATFORM.Weapon("hyphpyp_missile");  # ← 多打了个 p

# 正确：名称完全一致
   weapon hyphyp_missile HYPHYP_WEAPON
   end_weapon
   wpn = PLATFORM.Weapon("hyphyp_missile");
```

**教训**：定义和引用处的名称必须逐字符完全一致（AFSIM 名称区分大小写）。建议在定义 weapon 时，类型名和实例名统一命名风格。

Demo: `../Afsim_demoslists/new_guidance项目汇总.md` line 1475（weapon 定义）

---

### [E018] `Unknown weapon: <name>` — `launched_platform_type` 前向引用

**根因**：`weapon XXX WSF_EXPLICIT_WEAPON` 中引用了 `launched_platform_type <Y>`，但 `<Y>` 这个 `platform_type` 定义在 `weapon` **之后**（前向引用）。AFSIM 解析器在处理 weapon 时，该 platform_type 尚未注册。

**修正**：将 `launched_platform_type` 引用的 `platform_type` 定义在 `weapon` 定义**之前**。

```text
# 错误：platform_type 在 weapon 之后（前向引用）
weapon HYPHYP_WEAPON WSF_EXPLICIT_WEAPON
   launched_platform_type HYPHYP_MISSILE  # ← HYPHYP_MISSILE 还未定义
end_weapon
platform_type HYPHYP_MISSILE WSF_PLATFORM  # ← 太晚了
end_platform_type

# 正确：platform_type 先定义
platform_type HYPHYP_MISSILE WSF_PLATFORM
end_platform_type
weapon HYPHYP_WEAPON WSF_EXPLICIT_WEAPON
   launched_platform_type HYPHYP_MISSILE  # ← 已在上面定义
end_weapon
```

**教训**：AFSIM 类型定义顺序严格按文件顺序解析。`launched_platform_type`、`sensor`、`radar_signature` 等引用的类型必须在使用前先定义。

Demo: `../Afsim_demoslists/engage项目汇总.md` line 4317（LRSAM 先定义）vs line 4386（weapon 后定义）

---

### [E019] `Unknown weapon: <name>` — weapon 写在 `platform` 实例中（而非 `platform_type` 中）

**根因**：weapon 的**挂载位置**错误。将 `weapon <instance> <TYPE>` 写在 `platform` 实例块内，而不是 `platform_type` 定义块内。AFSIM 中，weapon 必须在 `platform_type` 中声明，platform 实例只支持 `add weapon`（新增）或 `edit weapon`（修改继承）语法。

**报错示例**：
```text
# 错误：weapon 写在 platform 实例内（非法语法）
platform red_bomber RED_BOMBER
   side red
   weapon hyphyp_missile HYPHYP_WEAPON   # ← 语法非法
      quantity 4
   end_weapon
end_platform
```

**修正**：将 weapon 声明移到 `platform_type` 中：

```text
# 正确：weapon 在 platform_type 中声明
platform_type RED_BOMBER WSF_PLATFORM
   icon B-52
   side red
   weapon hyphyp_missile HYPHYP_WEAPON
      quantity 4
   end_weapon
end_platform_type

platform red_bomber RED_BOMBER
   side red
end_platform
```

**如需在实例中修改数量**，使用 `edit weapon`：

```text
platform red_bomber RED_BOMBER
   edit weapon hyphyp_missile
      quantity 1
   end_weapon
end_platform
```

**如需在实例中新增 weapon**，使用 `add weapon`：

```text
platform red_bomber RED_BOMBER
   add weapon extra_missile EXTRA_WEAPON
      quantity 2
   end_weapon
end_platform
```

**教训**：AFSIM 中 `platform_type` 定义模板，`platform` 实例化对象。weapon 挂载属于"模板定义"范畴，必须在 `platform_type` 中完成。

Demo: `../Afsim_demoslists/engage项目汇总.md` line 441-456（weapon 在 platform_type 中）；`../Afsim_demoslists/iads_c2_demos项目汇总.md` line 459-471（add weapon）；`../Afsim_demoslists/iads_c2_demos项目汇总.md` line 172-175（edit weapon）

---

### [E020] `Unable to open event_pipe/event_output/log file` — 输出文件路径问题

**根因**：
1. AFSIM 工作目录与仿真文件路径不一致（仿真文件在 `output/staging/`，但 AFSIM 从 `D:/afsim/demos/0DIY/test0526/` 启动）
2. 相对路径 `output/$(CASE).evt` 解析到 AFSIM 的启动目录，而非仿真文件所在目录
3. 输出目录不存在或文件未预先创建

**修正**：使用绝对路径，并确保目录存在：

```text
# 错误：相对路径（依赖 AFSIM 启动目录）
log_file output/$(CASE).log
event_output file output/$(CASE).evt end_event_output

# 正确：使用 AFSIM 启动目录的绝对路径
log_file D:/afsim/demos/0DIY/test0526/output/$(CASE).log
event_output file D:/afsim/demos/0DIY/test0526/output/$(CASE).evt end_event_output
```

**预创建文件**（某些 AFSIM 版本要求文件预先存在）：
```bash
mkdir -p D:/afsim/demos/0DIY/test0526/output
touch D:/afsim/demos/0DIY/test0526/output/air_launched_hypersonic_cruise_missile.evt
touch D:/afsim/demos/0DIY/test0526/output/air_launched_hypersonic_cruise_missile.aer
touch D:/afsim/demos/0DIY/test0526/output/air_launched_hypersonic_cruise_missile.log
```

**教训**：AFSIM 的相对路径始终相对于**进程启动目录**（即 AFSIM 可执行文件运行时的 cwd），而非仿真文件所在目录。跨目录调用时，路径必须用绝对路径。

Demo: `../Afsim_demoslists/engage项目汇总.md`（查看 `event_output` 用法）
