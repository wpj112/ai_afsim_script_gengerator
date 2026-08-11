# 教训本体 | Lesson Root Causes

> 按根因分类的深度教训。每次报错修正后，如果错误有深层根因，创建对应教训追加到此文件。

---

## 根因分类

| 分类 ID | 分类名称 | 说明 |
|---------|----------|------|
| CAUSE-A | 块结构错误 | `end_*` 缺失、块嵌套错误 |
| CAUSE-B | 参数格式错误 | 坐标格式、单位错误、时间格式 |
| CAUSE-C | 语义理解错误 | 混淆基类型用法、版本兼容性 |

---

## CAUSE-A: 块结构错误

### [L001] mover 块未闭合

**关联报错**：`Mover not closed`, `Unknown command`

**场景**：在 platform_type 中添加 mover 后，忘记写 `end_mover`。

**根因**：块结构是 AFSIM 最核心的语法，块必须成对出现（`mover ... end_mover`）。

**正确模式**：
```text
mover WSF_AIR_MOVER
   debug
   print_route true
end_mover
```

**避坑**：
- 每次写 `mover` 立即写 `end_mover`，再填充内容
- 或复制一个已有的完整 mover 块，再修改内容

---

### [L002] sensor 块未闭合

**关联报错**：`Sensor not closed`, `Unknown command`

**场景**：定义传感器后，忘记 `end_sensor`。

**正确模式**：
```text
sensor find WSF_GEOMETRIC_SENSOR
   ignore_same_side
   frame_time 10 sec
   reports_location
   on
   track_quality 0.5
end_sensor
```

---

### [L003] processor 块未闭合

**关联报错**：`Processor not closed`, `Unknown command`

**正确模式**：
```text
processor operator WSF_TASK_PROCESSOR
   show_state_transitions
   evaluation_interval DETECTED 0.5 sec
   state DETECTED
      next_state TRY_TO_ACQUIRE
         return StartTracking(TRACK, "DUMMY", PLATFORM.Sensor("ttr"), "SEARCH");
      end_next_state
   end_state
end_processor
```

---

### [L004] platform_type 和 platform 块混淆

**关联报错**：`Unknown command`, 各种解析错误

**场景**：
- 在 `platform_type` 块内写 `position`（position 只在 platform 实例中有效）
- 在 `platform` 实例中写 `mover`（mover 只在 platform_type 中有效）

**正确模式**：
- `platform_type` 定义模板：包含 side、icon、mover、sensor、weapon、processor
- `platform` 实例化：包含 side（可覆盖）、position、route

---

## CAUSE-B: 参数格式错误

### [L005] 坐标格式错误

**关联报错**：`Invalid position format`

**场景**：使用了 `30 120` 或 `30.0N 120.0E` 等错误格式。

**正确格式**：
```text
position 30:00:00n 120:00:00e altitude 10000 ft msl
position 30:30:00n 120:30:00e altitude 5000 ft msl
```

格式：`d:m:s N/S e/w`

**避坑**：
- 必须有冒号分隔度分秒
- 必须有 N/S 和 E/W 方向
- altitude 必须指定单位（ft 或 m）和基准（msl 或 agl）

---

### [L006] 速度单位缺失

**关联报错**：Warlock 解析错误

**正确格式**：
```text
speed 300 kts    # 节
speed 150 m/s    # 米每秒
speed 0.8 mach   # 马赫
```

---

### [L007] 时间单位缺失

**关联报错**：Warlock 解析错误

**正确格式**：
```text
end_time 30 sec
end_time 10 min
end_time 2 hr
frame_time 0.01 sec
evaluation_interval DETECTED 0.5 sec
```

---

### [L008] 行尾注释

**关联报错**：解析错误

**场景**：在 AFSIM 中，行尾注释会导致后续内容被当作注释处理。

**避坑**：AFSIM 不支持行尾注释，所有注释必须独立成行。

```text
# 正确：注释在独立行
position 30:00:00n 120:00:00e altitude 10000 ft msl
# 这是注释

# 错误：行尾注释
position 30:00:00n 120:00:00e altitude 10000 ft msl # 这是注释
```

---

## CAUSE-C: 语义理解错误

### [L009] 混淆 platform_type 中的 side 和 platform 实例中的 side

**关联报错**：平台归属错误、逻辑异常

**场景**：
- platform_type 中写了 `side red`
- platform 实例中又写了 `side blue`
- 导致平台实际归属不确定

**正确理解**：
- platform_type 中的 `side` 是默认值
- platform 实例中的 `side` 可以覆盖，但通常保持一致

**避坑**：同一 platform_type 的所有实例通常属于同一 side。如果需要不同 side，创建不同的 platform_type。

---

### [L010] 混淆 WSF_GUIDED_MOVER 和 WSF_AIR_MOVER

**关联报错**：导弹不按预期飞行

**场景**：把导弹（WSF_GUIDED_MOVER）当成飞机（WSF_AIR_MOVER）处理。

**正确理解**：
- `WSF_AIR_MOVER`：飞机，有 route 引导
- `WSF_GUIDED_MOVER`：导弹/制导弹药，需要目标引导，通常不用 route

**避坑**：查看 `../Afsim_demoslists/air_to_air项目汇总.md` 和 `../Afsim_demoslists/engage项目汇总.md` 中的导弹定义方式。

---

### [L011] 混淆 sensor 和 radar_signature

**关联报错**：`Sensor not found`, 传感器不工作

**场景**：定义了 `radar_signature` 但没有定义 `sensor`。

**正确理解**：
- `radar_signature`：描述目标的雷达反射特性（RCS）
- `sensor`：描述探测设备本身的参数

一个平台可以既有 `radar_signature`（被探测）也有 `sensor`（探测别人）。

---

### [L012] 缺少基类型 WSF_PLATFORM / WSF_RADAR_SIGNATURE 等

**关联报错**：`Unknown command: platform_type`、`Unknown command: radar_signature`

**场景**：定义 platform_type 或 radar_signature 时，忘记写基类型。

**正确理解**：
- AFSIM 的命名对象（platform_type、sensor、weapon、processor、radar_signature 等）都需要一个基类型来指定其行为规范
- 常见基类型：`WSF_PLATFORM`、`WSF_RADAR_SIGNATURE`、`WSF_OPTICAL_SIGNATURE`、`WSF_GEOMETRIC_SENSOR`、`WSF_RADAR_SENSOR`、`WSF_TASK_PROCESSOR`、`WSF_TRACK_PROCESSOR` 等

**正确模式**：
```text
# 错误
platform_type MY_TYPE

# 正确
platform_type MY_TYPE WSF_PLATFORM

# 错误
radar_signature MY_SIGNATURE
  constant 10 m^2

# 正确
radar_signature MY_SIGNATURE WSF_RADAR_SIGNATURE
  constant 10 m^2
end_radar_signature
```

**避坑**：
- 定义任何命名对象时，先确认基类型
- 在 `refs/quick-ref.md` 的「核心基类型速查表」中查找
- 注意：`end_radar_signature` 等块闭合标记也不能省略

---

### [L013] optical_signature / radar_signature 定义时基类型处理不一致

**关联报错**：`Unknown command: optical_signature`

**场景**：
- `complete-ref.md` 中写的是 `optical_signature <name> WSF_OPTICAL_SIGNATURE`（有基类型）
- `base_types` Demo 中直接写 `optical_signature awacs_optical_signature`（无基类型，用 `end_optical_signature` 闭合）

**根因**：两种写法都是合法的 AFSIM 语法，取决于具体场景需求：
- 有基类型 `WSF_OPTICAL_SIGNATURE`：使用预定义的光学特征类
- 无基类型直接写名：自定义光学特征，用 `constant` 等参数定义

**正确模式（自定义方式）**：
```text
optical_signature awacs_optical_signature
   constant 1000 m^2
end_optical_signature
```

**正确模式（使用基类型）**：
```text
optical_signature MY_SIG WSF_OPTICAL_SIGNATURE
   intensity 100
end_optical_signature
```

**避坑**：参考 `../Afsim_demoslists/base_types项目汇总.md` 中的实际写法，当 Demo 无基类型时，skill 文档也不应强制添加基类型。

---

### [L014] weapon 写在 platform 实例中（而非 platform_type 中）

**关联报错**：`Unknown weapon: <name>`

**场景**：在 `platform` 实例块内直接写 `weapon <instance> <TYPE>`，而不是在 `platform_type` 中声明。

**根因**：混淆了 AFSIM 中 `platform_type`（模板定义）和 `platform`（实例化）的职责边界。

**正确理解**：
- `platform_type` 定义模板：包含 side、icon、mover、sensor、**weapon**、processor
- `platform` 实例化：包含 side（可覆盖）、position、route、processor 实例（add/edit）、weapon 修改（edit/add）

**正确模式**：

```text
# 正确：weapon 在 platform_type 中声明
platform_type RED_BOMBER WSF_PLATFORM
   weapon hyphyp_missile HYPHYP_WEAPON
      quantity 4
   end_weapon
end_platform_type

platform red_bomber RED_BOMBER
   side red
end_platform
```

**实例中修改继承的 weapon**：

```text
# 继承 platform_type 中的 weapon，但修改数量
platform red_bomber RED_BOMBER
   edit weapon hyphyp_missile
      quantity 1
   end_weapon
end_platform

# 在实例中新增 weapon
platform red_bomber RED_BOMBER
   add weapon extra_missile EXTRA_WEAPON
      quantity 2
   end_weapon
end_platform
```

**避坑**：
- weapon 声明 = 模板定义 → 属于 `platform_type`
- weapon 数量修改 = 实例调整 → 用 `edit weapon`
- weapon 新增挂载 = 实例扩展 → 用 `add weapon`
- 永远不要在 `platform` 块中直接写 `weapon xxx YYY`（不带 `add`/`edit`）

---

### [L015] 输出文件相对路径（相对于 AFSIM 启动目录，而非文件所在目录）

**关联报错**：`Unable to open event_pipe file`、`Unable to open event_output file`、`Unable to open system log file`

**场景**：仿真文件在 `output/staging/` 目录，但 AFSIM 从 `D:/afsim/demos/0DIY/test0526/` 启动。使用相对路径 `output/$(CASE).log` 导致 AFSIM 在启动目录下找不到文件。

**根因**：AFSIM 的工作目录是**进程启动目录**（AFSIM 可执行文件的 cwd），而不是仿真输入文件所在目录。所有相对路径都相对于启动目录解析。

**正确理解**：
- 仿真文件路径 → 任意（绝对路径引用即可）
- 相对路径的文件输出 → 相对于 AFSIM 启动目录
- 如果两者不在同一目录，使用绝对路径

**正确模式**：

```text
# 使用绝对路径（推荐）
log_file D:/afsim/demos/0DIY/test0526/output/$(CASE).log
event_output file D:/afsim/demos/0DIY/test0526/output/$(CASE).evt end_event_output
event_pipe file D:/afsim/demos/0DIY/test0526/output/$(CASE).aer end_event_pipe
```

**预创建文件**（某些版本要求）：

```bash
mkdir -p D:/afsim/demos/0DIY/test0526/output
touch D:/afsim/demos/0DIY/test0526/output/$(CASE).evt
touch D:/afsim/demos/0DIY/test0526/output/$(CASE).aer
```

**避坑**：
- 跨目录调用时，始终使用绝对路径
- 相对路径依赖 AFSIM 的启动方式（GUI 启动 vs 命令行启动，cwd 可能不同）
- 优先确保输出目录存在（`mkdir -p`）

---

## 追加记录

每次发现新的深层教训，追加到对应分类下：

```markdown
### [Lxxx] <教训标题>

**关联报错**：<相关报错关键字>
**场景**：<什么情况下会犯这个错>
**根因**：<为什么犯错>
**正确模式**：<正确的代码>
**避坑**：<如何避免>
```
