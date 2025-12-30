# Intel GPA Easy Output 插件文档

**创建日期**: 2024年12月27日  
**更新日期**: 2024年12月30日  
**插件路径**: `%USERPROFILE%\Documents\GPA\python_plugins\easy_output`

---

## 概述

Easy Output 是一个用于 Intel Graphics Performance Analyzers (GPA) Frame Analyzer 的 Python 插件，用于批量导出帧分析数据，包括：

- API 调用信息（JSON）
- 纹理资源（DDS）
- 缓冲区资源（VBV/IBV）
- 着色器信息（DXBC/HLSL）
- CBV 绑定映射（JSON）
- 几何数据（OBJ，支持蒙皮）

---

## 安装

将 `easy_output` 文件夹复制到：
```
%USERPROFILE%\Documents\GPA\python_plugins\
```

---

## 使用方法

### 在 Frame Analyzer 中运行

1. 打开 Intel GPA Frame Analyzer
2. 加载帧捕获文件
3. 在 api_log 上方的条形框中输入 `=easy_output(51, 52, 1)`
4. 回车运行

---

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `min_call` | int | 1 | 起始事件索引（包含，从 1 开始） |
| `max_call` | int | -1 | 结束事件索引（包含），-1 表示无上限 |
| `enable_skinning` | int | 0 | 蒙皮计算开关（0=关闭，1=开启） |

> **注意**：骨骼数据自动从 `cbv_bindings` 中 `dxbc_name` 为 **"Skeleton"** 的条目获取，无需手动指定。

### 示例

| 调用方式 | 效果 |
|----------|------|
| `=easy_output(1, -1, 0)` | 导出所有事件，不启用蒙皮 |
| `=easy_output(1, 10, 0)` | 导出前 10 个事件 |
| `=easy_output(51, 52, 1)` | 导出第 51-52 个事件，启用蒙皮 |
| `=easy_output(101, -1, 1)` | 导出第 101 个事件及之后，启用蒙皮 |

---

## 输出结构

```
easy_output/
├── export_20241230_130000.json          # 主汇总文件
├── easy_output.log                       # 日志文件（UTF-8编码）
└── resources/
    └── {frame_name}_{timestamp}/
        ├── g_51/                         # 第 51 个事件
        │   ├── _event_info.json          # 事件详细信息
        │   ├── g_51.obj                  # 几何数据（支持蒙皮）
        │   │
        │   ├── # 纹理资源
        │   ├── t_tBaseMap_3DD.dds        # 使用 DXBC 变量名命名
        │   ├── t_tMixMap_5BA.dds
        │   ├── t_tNormalMap_5BB.dds
        │   │
        │   ├── # 缓冲区资源
        │   ├── vbv.json                  # VBV 缓冲区信息（合并）
        │   ├── ibv_27A.json              # IBV 索引缓冲区
        │   │
        │   ├── # Shader 资源
        │   ├── vs_15.dxbc                # 顶点着色器
        │   ├── ps_15.dxbc                # 像素着色器
        │   ├── ps_texture_bindings_15.json  # PS 纹理绑定
        │   └── vs_cbv_bindings_15.json   # VS CBV 绑定映射
        │
        └── g_52/                         # 第 52 个事件
            └── ...
```

---

## 核心功能

### 1. 纹理导出（DDS）

所有纹理统一导出为 DDS 格式，使用 DXBC 中的变量名命名。

#### 支持的纹理格式

| 纹理格式 | DXGI 格式代码 |
|----------|---------------|
| `R8G8B8A8_*` | 28 |
| `B8G8R8A8_*` | 87 |
| `BC1` (DXT1) | 71 |
| `BC2` (DXT3) | 74 |
| `BC3` (DXT5) | 77 |
| `BC4` | 80 |
| `BC5` | 83 |
| `BC6H` | 95 |
| `BC7` | 98 |

#### 文件命名

```
t_{dxbc_name}_{resource_id_hex}.dds
```

**示例**：
```
t_tBaseMap_3DD.dds     # tBaseMap 纹理，资源 ID 0x3DD
t_tNormalMap_5BB.dds   # tNormalMap 纹理，资源 ID 0x5BB
```

---

### 2. 纹理名称映射（PSSetShaderResources）

插件通过解析 `PSSetShaderResources` API 调用来精确映射纹理资源与 Shader 中的变量名。

#### 工作流程

```
1. 解析 PS DXBC，获取纹理绑定信息：
   ├── t0 → "tBaseMap"
   ├── t1 → "tMixMap"
   ├── t3 → "tNormalMap"
   └── t6 → "tEmissionMap"

2. 查找 DrawCall 之前的 PSSetShaderResources 调用：
   PSSetShaderResources(StartSlot=0, ppShaderResourceViews=[
       {value: 989},   → slot 0
       {value: 1466},  → slot 1
       {value: 0},     → slot 2 (null)
       {value: 1467},  → slot 3
       ...
   ])

3. 建立 resource_id → dxbc_name 映射：
   ├── 989  → "tBaseMap"   (slot 0)
   ├── 1466 → "tMixMap"    (slot 1)
   └── 1467 → "tNormalMap" (slot 3)

4. 导出纹理时使用 dxbc_name 命名
```

---

### 3. CBV 绑定映射（VSSetConstantBuffers）

插件解析 `VSSetConstantBuffers` 调用，结合 VS DXBC 的 cbuffer 绑定信息，建立完整的 CBV 映射。

#### 输出文件：`vs_cbv_bindings_{program_id_hex}.json`

```json
{
  "program_id": 21,
  "program_id_hex": "15",
  "dxbc_cbuffer_map": {
    "0": "Batch",
    "1": "Shader",
    "2": "Global",
    "3": "Skeleton"
  },
  "cbv_bindings": [
    {
      "slot": "cb0",
      "slot_index": 0,
      "dxbc_name": "Batch",
      "resource_id": 37,
      "resource_id_hex": "25",
      "view_id": 14,
      "view_id_hex": "E",
      "offset": 39680,
      "stride": 0,
      "size": 1280,
      "resource_type": "buffer"
    },
    {
      "slot": "cb3",
      "slot_index": 3,
      "dxbc_name": "Skeleton",
      "resource_id": 37,
      "resource_id_hex": "25",
      "view_id": 2,
      "view_id_hex": "2",
      "offset": 41984,
      "stride": 0,
      "size": 768,
      "resource_type": "buffer"
    }
  ]
}
```

---

### 4. VBV 缓冲区信息

所有 VBV（Vertex Buffer View）资源合并到单个文件：`vbv.json`

```json
{
  "vbv_buffers": [
    {
      "type": "vertex",
      "resource_id": 630,
      "resource_id_hex": "276",
      "view_id": 0,
      "view_type": "VBV",
      "size": 96432,
      "stride": 24,
      "offset": 0,
      "resource_type": "buffer"
    },
    {
      "type": "tangent",
      "resource_id": 631,
      "resource_id_hex": "277",
      "view_id": 0,
      "view_type": "VBV",
      "size": 64288,
      "stride": 16,
      "offset": 0,
      "resource_type": "buffer"
    },
    {
      "type": "bone",
      "resource_id": 632,
      "resource_id_hex": "278",
      "view_id": 0,
      "view_type": "VBV",
      "size": 32144,
      "stride": 8,
      "offset": 0,
      "resource_type": "buffer"
    }
  ]
}
```

**类型判断**（根据 stride）：
- `stride=8` → bone（骨骼索引/权重）
- `stride=16` → tangent（切线）
- `stride>=24` → vertex（顶点位置/法线/UV）

---

### 5. 几何数据导出（OBJ）

导出为 Wavefront OBJ 格式，支持蒙皮变换。

```obj
# Exported from Intel GPA - Call ID: g_51
# Skinning Applied: Yes
# Vertices: 4018, Indices: 21642

v 0.500000 1.000000 0.000000
v 0.400000 0.900000 0.100000
...

vn 0.577350 0.577350 0.577350
vn 0.707107 0.707107 0.000000
...

vt 0.500000 0.750000
vt 0.250000 0.500000
...

f 1/1/1 2/2/2 3/3/3
...
```

#### 蒙皮计算

当 `enable_skinning=1` 时：
1. 自动从 `cbv_bindings` 中找到 `dxbc_name="Skeleton"` 的条目
2. 使用对应的 `resource_id` 和 `view_id` 定位骨骼矩阵数据
3. 对顶点位置和法线应用骨骼矩阵变换
4. 支持最多 4 骨骼混合权重

---

## JSON 文件结构

### 主汇总文件 (`export_*.json`)

```json
{
  "export_time": "2024-12-30 13:00:00",
  "filter": {
    "min_call": 51,
    "max_call": 52
  },
  "total_count": 2,
  "events": [
    {
      "index": 51,
      "id": "g_51",
      "name": "DrawIndexedInstanced",
      "texture_binding_map": [
        {"resource_id": 989, "resource_id_hex": "3DD", "slot": "t0", "slot_index": 0, "dxbc_name": "tBaseMap"}
      ],
      "exported_textures": [...],
      "exported_buffers": [...],
      "exported_shaders": [...],
      "exported_mesh": "g_51.obj"
    }
  ],
  "summary": {
    "total_events": 2,
    "total_textures": 14,
    "total_buffers": 4,
    "total_meshes": 2
  }
}
```

### 事件信息文件 (`_event_info.json`)

```json
{
  "index": 51,
  "id": "g_51",
  "name": "DrawIndexedInstanced",
  "texture_binding_map": [
    {"resource_id": 989, "resource_id_hex": "3DD", "slot": "t0", "slot_index": 0, "dxbc_name": "tBaseMap"},
    {"resource_id": 1466, "resource_id_hex": "5BA", "slot": "t1", "slot_index": 1, "dxbc_name": "tMixMap"}
  ],
  "exported_textures": [...],
  "exported_buffers": [...],
  "exported_shaders": [...],
  "exported_mesh": "g_51.obj"
}
```

---

## 技术实现

### 核心 API

```python
import plugin_api
from plugin_api.resources import ImageRequest, BufferRequest

# 获取访问器
api_log = plugin_api.get_api_log_accessor()
resources_accessor = plugin_api.get_resources_accessor()

# 获取所有调用
calls = api_log.get_calls()

# 获取事件绑定
bindings = call.get_bindings()
# bindings["inputs"]  - 输入资源列表
# bindings["outputs"] - 输出资源列表
# bindings["execution"]["program"] - 着色器程序
```

### 关键函数

| 函数 | 说明 |
|------|------|
| `parse_texture_bindings_from_dxbc()` | 从 DXBC 解析纹理绑定 |
| `parse_cbuffer_bindings_from_dxbc()` | 从 DXBC 解析 cbuffer 绑定 |
| `find_ps_set_shader_resources_before_event()` | 查找 PSSetShaderResources 调用 |
| `find_vs_set_constant_buffers_before_event()` | 查找 VSSetConstantBuffers 调用 |
| `build_resource_id_to_slot_map()` | 建立 resource_id → slot 映射 |
| `build_cbv_slot_bindings()` | 建立 CBV slot 绑定列表 |
| `export_mesh_from_buffers()` | 从 IBV/VBV 导出网格（支持蒙皮） |
| `apply_skinning()` | 应用骨骼蒙皮变换 |

---

## 日志

插件日志保存在 `easy_output.log`，使用 UTF-8 编码，中文正常显示。

```
2024-12-30 13:06:13: [INFO] ============================================================
2024-12-30 13:06:13: [INFO] easy_output 插件开始执行
2024-12-30 13:06:13: [INFO] 函数: run(min_call=51, max_call=52, enable_skinning=1)
2024-12-30 13:06:13: [DEBUG] Frame 名称: yysls_2025_10_29__11_44_32
2024-12-30 13:06:13: [DEBUG] DXBC slot->name 映射: {0: 'tBaseMap', 1: 'tMixMap', 3: 'tNormalMap'}
2024-12-30 13:06:13: [DEBUG] 找到 Skeleton CBV: resource_id=37, view_id=2
```

---

## 更新日志

### 2024-12-30 v3.0

- **骨骼数据自动识别**：移除 `skeleton_resource_id` 和 `skeleton_view_id` 参数，自动从 `cbv_bindings` 中查找 `dxbc_name="Skeleton"` 的条目
- **CBV 绑定映射**：新增 `vs_cbv_bindings_{program_id_hex}.json` 文件，包含完整的 CBV 绑定信息
  - 通过 `VSSetConstantBuffers` 解析 slot 绑定
  - 包含 resource_id、view_id、offset、size 等详细信息
- **VBV 信息合并**：所有 VBV 缓冲区信息合并到 `vbv.json`
- **取消独立 CBV 文件**：CBV 信息已整合到 `vs_cbv_bindings` 中
- **取消 input/output 子文件夹**：所有资源直接输出到事件文件夹
- **取消 output 资源导出**：仅导出输入资源
- **取消 shader_info 文件**：shader 信息在 dxbc 文件中
- **日志 UTF-8 编码**：修复中文乱码问题

### 2024-12-28 v2.0

- **纹理名称精确映射**：通过 PSSetShaderResources + DXBC 解析
- **texture_binding_map**：在 JSON 中输出 resource_id → dxbc_name 映射

### 2024-12-27 v1.x

- 初始版本创建
- 支持 DDS 纹理导出
- 支持 OBJ 几何导出
- 支持 IBV/VBV 解析
- 支持蒙皮计算

---

## 参考资料

- [Intel GPA 官方文档 - 创建自定义插件](https://www.intel.com/content/www/us/en/docs/gpa/user-guide/2025-1/create-a-custom-plugin-for-graphics-frame-analyzer.html)
- [DDS 文件格式](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide)
- [DXGI 格式枚举](https://learn.microsoft.com/en-us/windows/win32/api/dxgiformat/ne-dxgiformat-dxgi_format)
