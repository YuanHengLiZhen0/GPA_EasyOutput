# Intel GPA Easy Output 插件文档

**创建日期**: 2024年12月27日  
**更新日期**: 2024年12月27日  
**插件路径**: `%USERPROFILE%\Documents\GPA\python_plugins\easy_output`

---

## 概述

Easy Output 是一个用于 Intel Graphics Performance Analyzers (GPA) Frame Analyzer 的 Python 插件，用于批量导出帧分析数据，包括：

- API 调用信息（JSON）
- 纹理资源（DDS）
- 缓冲区资源（BIN）
- 几何数据（OBJ）

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
3. 在api_log 上方的条形框中输入=easy_output(0,-1,0)
4. 回车运行

---

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `min_call` | int | 1 | 起始事件索引（包含，从 1 开始） |
| `max_call` | int | -1 | 结束事件索引（包含），-1 表示无上限 |

### 示例

| 参数设置 | 效果 |
|----------|------|
| `min_call=1, max_call=-1` | 导出所有事件（从第 1 个开始） |
| `min_call=1, max_call=10` | 导出前 10 个事件（索引 1-10） |
| `min_call=101, max_call=200` | 导出第 101-200 个事件 |
| `min_call=51, max_call=-1` | 导出第 51 个事件及之后的所有事件 |

---

## 输出结构

```
easy_output/
├── export_20241227_180000.json          # 主汇总文件
└── resources/
    └── 20241227_180000/
        ├── g_1/                         # 第 1 个事件（索引从 1 开始）
        │   ├── _event_info.json         # 事件详细信息
        │   ├── input/                   # 输入资源文件夹
        │   │   ├── tex_7B.dds           # 输入纹理（ID 123 = 0x7B）
        │   │   ├── buf_1C8_CBV_256bytes.bin  # 输入缓冲区（ID 456 = 0x1C8）
        │   │   ├── buf_1C8_CBV.json     # 缓冲区描述
        │   │   └── mesh.obj             # 几何数据
        │   │
        │   └── output/                  # 输出资源文件夹
        │       ├── tex_315.dds          # 输出纹理（ID 789 = 0x315）
        │       └── buf_65_RTV.bin       # 输出缓冲区（ID 101 = 0x65）
        │
        ├── g_2/                         # 第 2 个事件
        │   ├── input/
        │   │   └── ...
        │   └── output/
        │       └── ...
        │
        └── g_N/                         # 第 N 个事件
            └── ...
```

---

## 导出格式

### 1. 纹理（Textures）

**所有纹理统一导出为 DDS 格式**

#### 支持的纹理格式

| 纹理格式 | DXGI 格式代码 |
|----------|---------------|
| `R8G8B8A8_*` | DXGI_FORMAT_R8G8B8A8_UNORM (28) |
| `B8G8R8A8_*` | DXGI_FORMAT_B8G8R8A8_UNORM (87) |
| `BC1` (DXT1) | DXGI_FORMAT_BC1_UNORM (71) |
| `BC2` (DXT3) | DXGI_FORMAT_BC2_UNORM (74) |
| `BC3` (DXT5) | DXGI_FORMAT_BC3_UNORM (77) |
| `BC4` | DXGI_FORMAT_BC4_UNORM (80) |
| `BC5` | DXGI_FORMAT_BC5_UNORM (83) |
| `BC6H` | DXGI_FORMAT_BC6H_UF16 (95) |
| `BC7` | DXGI_FORMAT_BC7_UNORM (98) |

DDS 文件使用 **DX10 扩展头**，可用以下工具查看：
- Windows: DirectX Texture Tool
- Visual Studio 内置查看器
- GIMP + DDS 插件
- Photoshop + NVIDIA Texture Tools

**文件命名**（资源 ID 使用 16 进制）：
```
tex_{resource_id_hex}.dds
```

**示例**：
```
tex_7B.dds      # 资源 ID 123 (十进制) = 7B (十六进制)
tex_1A4.dds     # 资源 ID 420 (十进制) = 1A4 (十六进制)
```

如果 DDS 保存失败，会回退保存为 RAW 格式：
```
tex_{resource_id_hex}_{width}x{height}_{format}.raw
```

### 2. 缓冲区（Buffers）

每个缓冲区生成两个文件：

- `.bin` - 原始二进制数据
- `.json` - 缓冲区描述信息

**命名规则**（资源 ID 使用 16 进制）：
```
buf_{resource_id_hex}_{view_type}_{size}bytes.bin
buf_{resource_id_hex}_{view_type}.json
```

**示例**：
```
buf_1C8_SRV_1024bytes.bin   # 资源 ID 456 = 1C8 (hex)
buf_1C8_SRV.json
```

### 3. 几何数据（Mesh）

导出为 Wavefront OBJ 格式，保存在 `input/` 文件夹中：

```obj
# Exported from Intel GPA - Call ID: 123
# Vertices: 1500, Indices: 4500

v 0.500000 1.000000 0.000000
v 0.400000 0.900000 0.100000
...

f 1 2 3
f 4 5 6
...
```

**支持**：
- 顶点位置（POSITION）
- 索引缓冲区（16-bit / 32-bit）

---

## JSON 文件结构

### 主汇总文件 (`export_*.json`)

```json
{
  "export_time": "2024-12-27 18:00:00",
  "filter": {
    "min_call": 0,
    "max_call": 10
  },
  "total_count": 11,
  "events": [
    {
      "index": 0,
      "id": 123,
      "name": "DrawIndexed",
      "exported_textures": [
        {"type": "input", "resource_id": "123", "file": "input/tex_7B.dds"},
        {"type": "output", "resource_id": "456", "file": "output/tex_1C8.dds"}
      ],
      "exported_buffers": [
        {"type": "input", "resource_id": "789", "file": "input/buf_315_CBV_256bytes.bin"}
      ],
      "exported_mesh": "input/mesh.obj"
    }
  ],
  "summary": {
    "total_events": 11,
    "total_textures": 45,
    "total_buffers": 23,
    "total_meshes": 11,
    "resources_dir": "C:\\Users\\...\\resources\\20241227_180000"
  }
}
```

### 事件信息文件 (`_event_info.json`)

```json
{
  "index": 0,
  "id": 123,
  "name": "DrawIndexed",
  "arguments": [
    {"name": "IndexCount", "type": "UINT", "value": 3600},
    {"name": "StartIndexLocation", "type": "UINT", "value": 0}
  ],
  "bindings_summary": {
    "inputs_count": 5,
    "outputs_count": 2,
    "has_program": true,
    "has_geometry": true
  }
}
```

---

## 技术实现

### 核心 API

```python
import plugin_api

# 获取访问器
api_log = plugin_api.get_api_log_accessor()
resources_accessor = plugin_api.get_resources_accessor()

# 获取所有调用
calls = api_log.get_calls()

# 获取事件绑定
bindings = call.get_bindings()
# bindings["inputs"]  - 输入资源列表
# bindings["outputs"] - 输出资源列表
# bindings["metadata"]["input_geometry"] - 几何数据

# 获取图像数据
from plugin_api.resources import ImageRequest
result = resources_accessor.get_images_data([ImageRequest(...)])

# 获取缓冲区数据
from plugin_api.resources import BufferRequest
result = resources_accessor.get_buffers_data([BufferRequest(...)])
```

### DDS 生成

使用 Python 标准库实现，无需额外依赖：

- `struct` - 二进制打包

DDS 文件结构：
1. Magic Number: `DDS ` (0x20534444)
2. DDS Header (124 bytes)
3. DDS_HEADER_DXT10 (20 bytes) - 用于 BC6H/BC7 等格式
4. Pixel Data

---

## 插件描述信息

```python
def desc():
    return {
        "name": "Easy Output - 资源导出工具",
        "description": "导出每个事件的所有纹理(DDS)、缓冲区(BIN)和Mesh(OBJ)，按事件分文件夹保存，资源按input/output分类。",
        "apis": ["DirectX 11", "DirectX 12"],
        "applicabilities": ["Apilog", "Resources"],
        "plugin_api_version": "1.2"
    }
```

---

## 参考资料

- [Intel GPA 官方文档 - 创建自定义插件](https://www.intel.com/content/www/us/en/docs/gpa/user-guide/2025-1/create-a-custom-plugin-for-graphics-frame-analyzer.html)
- [DDS 文件格式](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide)
- [DXGI 格式枚举](https://learn.microsoft.com/en-us/windows/win32/api/dxgiformat/ne-dxgiformat-dxgi_format)

---

## 更新日志

### 2024-12-27 v1.9

- 支持通过 IBV (Index Buffer View) 和 VBV (Vertex Buffer View) 资源生成 mesh
- 法线值直接从 0-255 映射到 0.0-1.0（不做 SNorm 归一化）
- 优先使用 IBV/VBV 方式，如果失败则回退到 geometry_info 方式

### 2024-12-27 v1.8

- 支持更多顶点布局:
  - stride=32: POSITION + NORMAL + UV0 + UV1
  - stride=36: POSITION + COLOR + NORMAL + UV0 + UV1

### 2024-12-27 v1.7

- OBJ 导出支持解析完整顶点布局:
  - stride=24: POSITION(float3) + NORMAL(ubyte4) + TEXCOORD(float2)
  - stride=28: POSITION(float3) + COLOR(ubyte4) + NORMAL(ubyte4) + TEXCOORD(float2)
- OBJ 文件包含法线(vn)和纹理坐标(vt)
- 法线从 ubyte4 SNorm 格式正确解码

### 2024-12-27 v1.6

- VBV 缓冲区根据 stride 智能命名:
  - stride=8: `bone_vbv_{hex_id}.bin`
  - stride=16: `tangent_vbv_{hex_id}.bin`
  - stride>=24: `vertex_vbv_{hex_id}.bin`
- OBJ 导出根据 IndexCount/StartIndexLocation/BaseVertexLocation 提取正确范围
- OBJ 文件命名改为 `g_{event_index}.obj`

### 2024-12-27 v1.5

- 导出纹理时自动垂直翻转图像（修正Y轴方向）
- 支持 BC 压缩格式和非压缩格式的翻转

### 2024-12-27 v1.4

- `min_call` 索引从 1 开始（而非 0）
- 输出文件夹命名与 `min_call` 索引一致（g_1, g_2, ...）

### 2024-12-27 v1.3

- 资源文件名中的 ID 使用 16 进制格式

### 2024-12-27 v1.2

- 所有纹理统一导出为 DDS 格式
- 资源按 input/output 分类存放到对应子文件夹
- 改进的 DDS 文件生成（支持 DX10 扩展头）

### 2024-12-27 v1.1

- 支持 BC7 等压缩格式直接导出为 DDS
- 添加 zlib 不可用时的 TGA 回退

### 2024-12-27 v1.0

- 初始版本创建
- 支持按事件索引筛选
- 每个事件资源保存在独立文件夹
- 纹理导出为 PNG 格式（支持多种格式转换）
- 缓冲区导出为 BIN + JSON
- 几何数据导出为 OBJ 格式
- 支持 inputs 和 outputs 所有资源导出
