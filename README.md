# Intel GPA Easy Output 插件文档

**创建日期**: 2024年12月27日  
**更新日期**: 2026年3月3日  
**插件路径**: `%USERPROFILE%\Documents\GPA\python_plugins\easy_output`

---

## 概述

Easy Output 是一个用于 Intel Graphics Performance Analyzers (GPA) Frame Analyzer 的 Python 插件，用于批量导出帧分析数据，包括：

- API 调用信息（JSON）
- 纹理资源（DDS）
- 缓冲区资源（VBV/IBV）
- 着色器信息（DXBC/HLSL）
- CBV 绑定映射（JSON）
- 几何数据（OBJ，支持蒙皮 + 间接绘制）

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

## 处理流程

`run()` 函数将每个事件的导出拆分为 **10 个 Stage**，每个 Stage 由独立函数实现：

```
Stage 0   _stage_init_session          初始化会话（筛选事件、创建目录）
            │
            ▼  ── 逐事件循环 (_process_single_event) ──
            │
Stage 1   _stage_build_ps_texture_map  解析 PS DXBC + PSSetShaderResources 纹理绑定
Stage 2   _stage_build_vs_cbv_map      解析 VS DXBC + VSSetConstantBuffers CBV 绑定
Stage 3   _stage_classify_inputs       分类输入资源 (SRV 纹理 vs 其他)
Stage 4   _stage_export_textures       导出 SRV 纹理 (DDS)
Stage 5   _stage_export_other_inputs   导出其他输入 + 收集 IBV / VBV / CBV
Stage 6   _stage_export_vbv            合并输出 VBV (vbv.json)
Stage 7   _stage_extract_indirect_args 提取 Indirect Args (DrawIndexedInstancedIndirect)
Stage 8   _stage_export_mesh           导出 Mesh (OBJ，支持蒙皮 + 间接绘制)
Stage 9   _stage_export_event_shaders  导出 Shader (DXBC / HLSL)
Stage 10  _stage_save_event_info       保存事件信息 (_event_info.json)
            │
            ▼  ── 循环结束 ──
            │
          _finalize_export             汇总统计并返回结果
```

---

## 输出结构

```
easy_output/
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

### Stage 1 — 纹理绑定映射 (PSSetShaderResources)

插件通过解析 DXBC 和 `PSSetShaderResources` API 调用来精确映射纹理资源与 Shader 变量名。

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

### Stage 2 — CBV 绑定映射 (VSSetConstantBuffers)

解析 `VSSetConstantBuffers` 调用，结合 VS DXBC 的 cbuffer 绑定信息，建立完整的 CBV 映射。

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

### Stage 4 — 纹理导出 (DDS)

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

### Stage 6 — VBV 缓冲区信息

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

### Stage 7 — DrawIndexedInstancedIndirect 支持

对于 `DrawIndexedInstancedIndirect` 类型的绘制调用：

1. 检测事件名称是否包含 `DrawIndexedInstancedIndirect`
2. 查找 `inputs` 中 `view_type="args"` 的 buffer
3. 从 args buffer 的前 20 字节解析间接参数：

```c
struct D3D11_DRAW_INDEXED_INSTANCED_INDIRECT_ARGS {
    uint IndexCountPerInstance;    // 每实例索引数量
    uint InstanceCount;            // 实例数量
    uint StartIndexLocation;       // 起始索引位置
    int  BaseVertexLocation;       // 基础顶点偏移（有符号）
    uint StartInstanceLocation;    // 起始实例位置
};
```

4. 使用 `StartIndexLocation` 和 `IndexCountPerInstance` 确定索引范围
5. 索引 buffer 范围：`[StartIndexLocation, StartIndexLocation + IndexCountPerInstance)`

**输出示例**（在 `_event_info.json` 中）：

```json
{
  "name": "DrawIndexedInstancedIndirect",
  "indirect_args": {
    "IndexCountPerInstance": 3456,
    "InstanceCount": 1,
    "StartIndexLocation": 0,
    "BaseVertexLocation": 0,
    "StartInstanceLocation": 0
  }
}
```

---

### Stage 8 — 几何数据导出 (OBJ)

导出为 Wavefront OBJ 格式，支持蒙皮变换和间接绘制。

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

### 事件信息文件 (`_event_info.json`)

```json
{
  "index": 51,
  "id": "g_51",
  "name": "DrawIndexedInstanced",
  "arguments": [...],
  "bindings_summary": {
    "inputs_count": 12,
    "outputs_count": 4,
    "has_program": true,
    "has_geometry": true,
    "shaders_exported": 2
  }
}
```

---

## 技术实现

### 核心 API

```python
import plugin_api
from plugin_api.resources import ImageRequest, BufferRequest

api_log = plugin_api.get_api_log_accessor()
resources_accessor = plugin_api.get_resources_accessor()

calls = api_log.get_calls()
bindings = call.get_bindings()
# bindings["inputs"]  - 输入资源列表
# bindings["outputs"] - 输出资源列表
# bindings["execution"]["program"] - 着色器程序
```

### Stage 函数一览

| 函数 | Stage | 说明 |
|------|-------|------|
| `_stage_init_session()` | 0 | 初始化会话，筛选事件，创建目录 |
| `_stage_build_ps_texture_map()` | 1 | 解析 PS DXBC + PSSetShaderResources 纹理绑定 |
| `_stage_build_vs_cbv_map()` | 2 | 解析 VS DXBC + VSSetConstantBuffers CBV 绑定 |
| `_stage_classify_inputs()` | 3 | 分类输入资源 (SRV 纹理 vs 其他) |
| `_stage_export_textures()` | 4 | 导出 SRV 纹理 (DDS) |
| `_stage_export_other_inputs()` | 5 | 导出其他输入，收集 IBV / VBV / CBV |
| `_stage_export_vbv()` | 6 | 合并输出 VBV 信息 |
| `_stage_extract_indirect_args()` | 7 | 提取 DrawIndexedInstancedIndirect 参数 |
| `_stage_export_mesh()` | 8 | 导出网格 (OBJ，支持蒙皮 + 间接绘制) |
| `_stage_export_event_shaders()` | 9 | 导出着色器 (DXBC / HLSL) |
| `_stage_save_event_info()` | 10 | 保存 _event_info.json |
| `_process_single_event()` | — | 串联 Stage 1~10 |
| `_finalize_export()` | — | 汇总统计并返回结果 |

### 辅助函数

| 函数 | 说明 |
|------|------|
| `parse_texture_bindings_from_dxbc()` | 从 DXBC 解析纹理绑定 |
| `parse_cbuffer_bindings_from_dxbc()` | 从 DXBC 解析 cbuffer 绑定 |
| `find_ps_set_shader_resources_before_event()` | 查找 PSSetShaderResources 调用 |
| `find_vs_set_constant_buffers_before_event()` | 查找 VSSetConstantBuffers 调用 |
| `build_resource_id_to_slot_map()` | 建立 resource_id → slot 映射 |
| `build_cbv_slot_bindings()` | 建立 CBV slot 绑定列表 |
| `export_mesh_from_buffers()` | 从 IBV/VBV 导出网格（支持蒙皮 + 间接绘制） |
| `apply_skinning()` | 应用骨骼蒙皮变换 |
| `is_draw_indexed_instanced_indirect()` | 检测 DrawIndexedInstancedIndirect 调用 |
| `find_args_buffer_from_inputs()` | 查找 view_type="args" 的 buffer |
| `parse_indirect_args_buffer()` | 解析间接绘制参数结构体 |
| `_get_program_desc()` | 从 bindings 安全获取 program description |

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

### 2026-03-03 v4.0

- **代码架构重构**：将 ~560 行的单体 `run()` 函数拆分为 10 个独立 Stage 函数
  - 每个 Stage 职责单一，命名清晰 (`_stage_*`)
  - `_process_single_event()` 负责串联所有 Stage
  - `_stage_init_session()` 返回 session 上下文字典
  - `_finalize_export()` 统一汇总
- **DrawIndexedInstancedIndirect 支持** (Stage 7):
  - 自动检测 `DrawIndexedInstancedIndirect` 类型的绘制调用
  - 从 `view_type="args"` 的 buffer 中提取间接绘制参数
  - 解析 20 字节的间接参数结构体
  - 使用 `StartIndexLocation` 和 `IndexCountPerInstance` 精确提取索引范围
  - 在 `_event_info.json` 中输出 `indirect_args` 信息

### 2024-12-30 v3.0

- **骨骼数据自动识别**：自动从 `cbv_bindings` 中查找 `dxbc_name="Skeleton"`
- **CBV 绑定映射**：`vs_cbv_bindings_{program_id_hex}.json`
- **VBV 信息合并**：`vbv.json`
- **取消独立 CBV / shader_info / input&output 子文件夹**
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
