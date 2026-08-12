# AFSIM Commands Quick Reference

本文档只使用 AFSIM/WSF 的文本块语法。AFSIM 配置块不使用 C/JSON 风格的 `{}` 或 `[]` 包裹；脚本语言自身的 `if`、`for` 等控制结构除外。

## Platform Type

```text
platform_type FIGHTER WSF_PLATFORM
   mover WSF_AIR_MOVER
   end_mover
end_platform_type
```

## Platform Instance

```text
platform blue_fighter_1 FIGHTER
   side blue
   position 38:16:36n 116:19:48w altitude 35000 ft msl
   route
      navigation
         position 38:16:36n 116:19:48w altitude 35000 ft msl
            speed 450 kts
         position 38:24:12n 117:21:12w altitude 35000 ft msl
            speed 450 kts
      end_navigation
   end_route
end_platform
```

相邻航点不能使用完全相同的经纬度。需要平台移动时，航路点必须有有效距离，且空中平台应使用带速度的 `WSF_AIR_MOVER`。

## Sensor

传感器类型和完整参数应以对应的官方文档为准。最小定义形式如下：

```text
sensor SEARCH_RADAR WSF_RADAR_SENSOR
   mode SEARCH_MODE
      frame_time 1.0 sec
   end_mode
end_sensor
```

复杂雷达配置需要继续定义 `beam`、`transmitter`、`receiver` 和天线方向图，不能根据本文件猜测参数。

## Weapon

武器类型必须使用当前 AFSIM 安装和模型库中存在的类型。当前项目在 Linux 镜像中验证的通用骨架是：

```text
weapon BASIC_WEAPON WSF_EXPLICIT_WEAPON
end_weapon
```

具体导弹、炸弹、杀伤模型和挂载方式应优先参考官方文档及已验证 Demo，不要把 `missile`、`AA_MISSILE` 等自然语言名称直接当成 AFSIM 类型。

## Script Processor

```text
processor status_proc WSF_SCRIPT_PROCESSOR
   update_interval 1.0 sec
   script_variables
      int counter = 0;
   end_script_variables
   on_initialize
      counter = 0;
   end_on_initialize
   on_update
      counter = counter + 1;
      print(TIME_NOW, " counter=", counter);
   end_on_update
end_processor
```

`on_initialize` 和 `on_update` 中直接写脚本语句，不再额外套 `script/end_script`。

## Script Interface

```text
script_interface
   debug
end_script_interface
```

## Simulation End

```text
end_time 7200 sec
```

仿真结束使用单行 `end_time`，不要生成 `RUN_SIMULATION` 或 `time { ... }` 形式的配置块。

## Related References

- `commands_reference.md`：项目整理的命令级参考
- `file_structure.md`：脚本整体结构
- `script_syntax_critical.md`：关键语法和已知错误
- `language_grammar.md`：脚本语言控制结构和数据类型
- `examples.md`：完整示例
- `afsimDoc/html/_sources/docs/`：AFSIM 2.9.0 官方源文档
