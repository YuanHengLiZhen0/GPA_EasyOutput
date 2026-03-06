# Copyright (C) 2024
# Easy Output Plugin for Intel GPA Frame Analyzer
# 用于快速输出帧分析信息到文件

import os
import json
import struct
from datetime import datetime

# 尝试导入 zlib，如果失败则禁用 PNG 支持
try:
    import zlib
    HAS_ZLIB = True
except ImportError:
    HAS_ZLIB = False

from utils import common

# ============== DDS 格式常量 ==============
# 参考: https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide

DDS_MAGIC = 0x20534444  # "DDS "

# DDSD flags
DDSD_CAPS        = 0x1
DDSD_HEIGHT      = 0x2
DDSD_WIDTH       = 0x4
DDSD_PITCH       = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE  = 0x80000
DDSD_DEPTH       = 0x800000

# DDPF flags
DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC      = 0x4
DDPF_RGB         = 0x40

# DDSCAPS
DDSCAPS_COMPLEX  = 0x8
DDSCAPS_TEXTURE  = 0x1000
DDSCAPS_MIPMAP   = 0x400000

# D3D10_RESOURCE_DIMENSION
D3D10_RESOURCE_DIMENSION_TEXTURE2D = 3

# DXGI 格式枚举
DXGI_FORMAT = {
    "R8G8B8A8_UNORM": 28,
    "R8G8B8A8_UNORM_SRGB": 29,
    "R8G8B8A8": 28,
    "B8G8R8A8_UNORM": 87,
    "B8G8R8A8_UNORM_SRGB": 91,
    "B8G8R8A8": 87,
    "B8G8R8X8_UNORM": 88,
    "R16G16B16A16_FLOAT": 10,
    "R32G32B32A32_FLOAT": 2,
    "R10G10B10A2_UNORM": 24,
    "R11G11B10_FLOAT": 26,
    "BC1_UNORM": 71,
    "BC1_UNORM_SRGB": 72,
    "BC1": 71,
    "BC2_UNORM": 74,
    "BC2_UNORM_SRGB": 75,
    "BC2": 74,
    "BC3_UNORM": 77,
    "BC3_UNORM_SRGB": 78,
    "BC3": 77,
    "BC4_UNORM": 80,
    "BC4_SNORM": 81,
    "BC4": 80,
    "BC5_UNORM": 83,
    "BC5_SNORM": 84,
    "BC5": 83,
    "BC6H_UF16": 95,
    "BC6H_SF16": 96,
    "BC6H": 95,
    "BC7_UNORM": 98,
    "BC7_UNORM_SRGB": 99,
    "BC7": 98,
    "R8_UNORM": 61,
    "R8G8_UNORM": 49,
    "R16_FLOAT": 54,
    "R16_UNORM": 56,
    "R32_FLOAT": 41,
    "D24_UNORM_S8_UINT": 45,
    "D32_FLOAT": 40,
}
import plugin_api
import plugin_adapter_interface
from plugin_api.resources import ImageRequest, BufferRequest
from logs import messages as _original_messages


class UTF8Messages:
    """
    包装 messages 对象，确保日志使用 UTF-8 编码写入
    同时写入到独立的 easy_output.log 文件
    """
    def __init__(self, original_messages):
        self._original = original_messages
        self._log_file = None
        self._log_path = None
    
    def _get_log_file(self):
        """获取日志文件句柄，延迟初始化"""
        if self._log_file is None:
            try:
                # 获取插件目录
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                self._log_path = os.path.join(plugin_dir, "easy_output.log")
                self._log_file = open(self._log_path, 'a', encoding='utf-8')
            except Exception:
                pass
        return self._log_file
    
    def _write_to_file(self, msg):
        """写入到文件"""
        try:
            f = self._get_log_file()
            if f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"{timestamp}: {msg}\n")
                f.flush()
        except Exception:
            pass
    
    def debug(self, msg):
        """调试日志 - 仅写入 UTF-8 文件，不调用原始方法避免乱码"""
        self._write_to_file(f"[DEBUG] {msg}")
    
    def info(self, msg):
        """信息日志 - 仅写入 UTF-8 文件"""
        self._write_to_file(f"[INFO] {msg}")
    
    def warning(self, msg):
        """警告日志 - 仅写入 UTF-8 文件"""
        self._write_to_file(f"[WARNING] {msg}")
    
    def error(self, msg):
        """错误日志 - 仅写入 UTF-8 文件"""
        self._write_to_file(f"[ERROR] {msg}")
    
    def __getattr__(self, name):
        """转发其他属性到原始对象"""
        return getattr(self._original, name)


# 使用 UTF-8 包装器替换 messages
messages = UTF8Messages(_original_messages)


def get_frame_name():
    """
    尝试获取当前 frame 的名称
    
    通过 get_frame_metadata() 获取 framename 路径，解析提取最后的名称部分
    
    返回:
        frame 名称字符串，如果获取失败则返回空字符串
    """
    try:
        adapter = plugin_adapter_interface.get_interface()
        
        # 优先使用 get_frame_metadata 获取 framename
        if hasattr(adapter, 'get_frame_metadata'):
            try:
                metadata = adapter.get_frame_metadata()
                
                # 如果是字符串（JSON），尝试解析
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                
                # 获取 framename
                framename = None
                if isinstance(metadata, dict):
                    framename = metadata.get('framename') or metadata.get('frame_name') or metadata.get('name')
                
                if framename:
                    # framename 是路径，提取最后的名称部分
                    # 支持 Windows 和 Unix 路径分隔符
                    if '/' in framename:
                        name = framename.rsplit('/', 1)[-1]
                    elif '\\' in framename:
                        name = framename.rsplit('\\', 1)[-1]
                    else:
                        name = framename
                    
                    # 移除可能的扩展名
                    if name.lower().endswith('.gpa_frame'):
                        name = name[:-10]
                    elif name.lower().endswith('.gpa'):
                        name = name[:-4]
                    
                    messages.debug(f"[Frame] 从 metadata 获取: {framename} -> {name}")
                    return name
                    
            except Exception as e:
                messages.debug(f"[Frame] get_frame_metadata 失败: {str(e)}")
        
    
    except Exception as e:
        messages.debug(f"获取 frame 名称失败: {str(e)}")
    
    return ""


def get_dxgi_format(tex_format):
    """将纹理格式字符串转换为 DXGI 格式值"""
    # 精确匹配优先
    if tex_format in DXGI_FORMAT:
        return DXGI_FORMAT[tex_format]
    
    # 部分匹配
    for key, value in DXGI_FORMAT.items():
        if key in tex_format:
            return value
    
    return 28  # 默认 R8G8B8A8_UNORM


def get_bytes_per_pixel(tex_format):
    """获取每像素字节数（非压缩格式）"""
    if "R32G32B32A32" in tex_format:
        return 16
    elif "R16G16B16A16" in tex_format:
        return 8
    elif "R32G32" in tex_format:
        return 8
    elif "R10G10B10A2" in tex_format or "R11G11B10" in tex_format:
        return 4
    elif "R8G8B8A8" in tex_format or "B8G8R8A8" in tex_format or "B8G8R8X8" in tex_format:
        return 4
    elif "R32" in tex_format or "D32" in tex_format:
        return 4
    elif "D24" in tex_format:
        return 4
    elif "R16G16" in tex_format:
        return 4
    elif "R8G8" in tex_format:
        return 2
    elif "R16" in tex_format:
        return 2
    elif "R8" in tex_format:
        return 1
    return 4  # 默认 4 bytes


def get_bc_block_size(tex_format):
    """获取 BC 压缩格式的块大小（每 4x4 块的字节数）"""
    if "BC1" in tex_format or "BC4" in tex_format:
        return 8
    elif "BC2" in tex_format or "BC3" in tex_format or "BC5" in tex_format:
        return 16
    elif "BC6H" in tex_format or "BC7" in tex_format:
        return 16
    return 0


def is_bc_format(tex_format):
    """判断是否为 BC 压缩格式"""
    return any(bc in tex_format for bc in ["BC1", "BC2", "BC3", "BC4", "BC5", "BC6H", "BC7"])


def flip_image_vertical(raw_data, width, height, tex_format):
    """
    垂直翻转图像数据
    
    参数:
        raw_data: 原始图像数据
        width: 图像宽度
        height: 图像高度
        tex_format: 纹理格式字符串
    
    返回:
        翻转后的图像数据
    """
    data = bytearray(raw_data)
    
    if is_bc_format(tex_format):
        # BC 压缩格式按 4x4 块存储，需要按块行翻转
        block_size = get_bc_block_size(tex_format)
        block_width = (width + 3) // 4
        block_height = (height + 3) // 4
        row_size = block_width * block_size  # 每行块的字节数
        
        flipped = bytearray(len(data))
        
        for y in range(block_height):
            src_offset = y * row_size
            dst_offset = (block_height - 1 - y) * row_size
            
            if src_offset + row_size <= len(data) and dst_offset + row_size <= len(flipped):
                flipped[dst_offset:dst_offset + row_size] = data[src_offset:src_offset + row_size]
        
        return flipped
    else:
        # 非压缩格式按像素行翻转
        bytes_per_pixel = get_bytes_per_pixel(tex_format)
        row_size = width * bytes_per_pixel
        
        flipped = bytearray(len(data))
        
        for y in range(height):
            src_offset = y * row_size
            dst_offset = (height - 1 - y) * row_size
            
            if src_offset + row_size <= len(data) and dst_offset + row_size <= len(flipped):
                flipped[dst_offset:dst_offset + row_size] = data[src_offset:src_offset + row_size]
        
        return flipped


def save_as_dds(raw_data, width, height, tex_format, output_path):
    """
    将纹理数据保存为 DDS 文件
    支持 BC1-BC7 压缩格式和各种非压缩格式
    
    DDS 文件结构:
    - Magic (4 bytes): "DDS "
    - DDS_HEADER (124 bytes)
    - DDS_HEADER_DXT10 (20 bytes, 当使用 DX10 扩展时)
    - Pixel Data
    """
    try:
        dxgi_format = get_dxgi_format(tex_format)
        block_size = get_bc_block_size(tex_format)
        is_compressed = block_size > 0
        
        # 计算 pitch 或 linear size
        if is_compressed:
            # 压缩格式使用 linear size
            block_width = (width + 3) // 4
            block_height = (height + 3) // 4
            pitch_or_linear_size = block_width * block_height * block_size
            flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_LINEARSIZE
        else:
            # 非压缩格式使用 pitch (每行字节数)
            bytes_per_pixel = get_bytes_per_pixel(tex_format)
            pitch_or_linear_size = width * bytes_per_pixel
            flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_PITCH
        
        # ========== DDS_HEADER (124 bytes) ==========
        # 结构偏移量 (相对于 header 起始位置):
        # 0:   dwSize (4) = 124
        # 4:   dwFlags (4)
        # 8:   dwHeight (4)
        # 12:  dwWidth (4)
        # 16:  dwPitchOrLinearSize (4)
        # 20:  dwDepth (4)
        # 24:  dwMipMapCount (4)
        # 28:  dwReserved1[11] (44 bytes)
        # 72:  DDS_PIXELFORMAT (32 bytes)
        #      72: dwSize (4) = 32
        #      76: dwFlags (4)
        #      80: dwFourCC (4)
        #      84: dwRGBBitCount (4)
        #      88: dwRBitMask (4)
        #      92: dwGBitMask (4)
        #      96: dwBBitMask (4)
        #      100: dwABitMask (4)
        # 104: dwCaps (4)
        # 108: dwCaps2 (4)
        # 112: dwCaps3 (4)
        # 116: dwCaps4 (4)
        # 120: dwReserved2 (4)
        
        header = bytearray(124)
        
        # dwSize = 124
        struct.pack_into('<I', header, 0, 124)
        # dwFlags
        struct.pack_into('<I', header, 4, flags)
        # dwHeight
        struct.pack_into('<I', header, 8, height)
        # dwWidth
        struct.pack_into('<I', header, 12, width)
        # dwPitchOrLinearSize
        struct.pack_into('<I', header, 16, pitch_or_linear_size)
        # dwDepth = 1
        struct.pack_into('<I', header, 20, 1)
        # dwMipMapCount = 1
        struct.pack_into('<I', header, 24, 1)
        # dwReserved1[11] = 0 (已经是 0)
        
        # DDS_PIXELFORMAT at offset 72
        # dwSize = 32
        struct.pack_into('<I', header, 72, 32)
        # dwFlags = DDPF_FOURCC (使用 DX10 扩展)
        struct.pack_into('<I', header, 76, DDPF_FOURCC)
        # dwFourCC = "DX10"
        header[80:84] = b'DX10'
        # dwRGBBitCount, masks = 0 (使用 DX10 时不需要)
        
        # dwCaps = DDSCAPS_TEXTURE
        struct.pack_into('<I', header, 104, DDSCAPS_TEXTURE)
        # dwCaps2, dwCaps3, dwCaps4, dwReserved2 = 0 (已经是 0)
        
        # ========== DDS_HEADER_DXT10 (20 bytes) ==========
        # 0:  dxgiFormat (4)
        # 4:  resourceDimension (4) = D3D10_RESOURCE_DIMENSION_TEXTURE2D (3)
        # 8:  miscFlag (4)
        # 12: arraySize (4) = 1
        # 16: miscFlags2 (4)
        
        dx10_header = bytearray(20)
        # dxgiFormat
        struct.pack_into('<I', dx10_header, 0, dxgi_format)
        # resourceDimension = 3 (Texture2D)
        struct.pack_into('<I', dx10_header, 4, D3D10_RESOURCE_DIMENSION_TEXTURE2D)
        # miscFlag = 0
        struct.pack_into('<I', dx10_header, 8, 0)
        # arraySize = 1
        struct.pack_into('<I', dx10_header, 12, 1)
        # miscFlags2 = 0 (DDS_ALPHA_MODE_UNKNOWN)
        struct.pack_into('<I', dx10_header, 16, 0)
        
        # 写入文件
        with open(output_path, 'wb') as f:
            # Magic number "DDS "
            f.write(struct.pack('<I', DDS_MAGIC))
            # DDS_HEADER
            f.write(header)
            # DDS_HEADER_DXT10
            f.write(dx10_header)
            # Pixel data
            f.write(bytes(raw_data))
        
        return True
        
    except Exception as e:
        messages.debug(f"保存 DDS 失败: {str(e)}")
        return False


def export_texture(resources_accessor, texture_resource, call, output_dir, res_id, view_type="", dxbc_name=""):
    """
    导出纹理资源为 DDS 文件
    
    参数:
        resources_accessor: 资源访问器
        texture_resource: 纹理资源对象
        call: API 调用对象
        output_dir: 输出目录
        res_id: 资源 ID
        view_type: 视图类型（可选）
        dxbc_name: DXBC 解析出的纹理名称（可选），用于文件命名
    """
    try:
        desc = texture_resource.get_description()
        
        if desc.get("resource_type") != "texture":
            return None
        
        mips = desc.get("mips", [])
        if not mips:
            return None
        
        width = mips[0].get("width", 0)
        height = mips[0].get("height", 0)
        tex_format = desc.get("format", "unknown")
        first_mip = desc.get("first_mip", 0)
        first_slice = desc.get("first_slice", 0)
        
        # 创建图像请求
        image_request = ImageRequest(
            image=texture_resource,
            mip=first_mip,
            slice_=first_slice,
            call=call,
            extract_before=False
        )
        
        # 获取图像数据
        result = resources_accessor.get_images_data([image_request], timeout=30000)
        
        if image_request not in result:
            return None
        
        image_data = result[image_request]
        raw_data = image_data.data
        
        # 将资源 ID 转换为 16 进制
        res_id_hex = format(int(res_id), 'X')
        
        # 生成文件名：如果有 DXBC 名称，则使用 "t_{dxbc_name}_{res_id_hex}.dds" 格式
        if dxbc_name:
            # 清理 dxbc_name，移除不合法的文件名字符
            safe_name = "".join(c for c in dxbc_name if c.isalnum() or c in "_-")
            dds_filename = f"t_{safe_name}_{res_id_hex}.dds"
        else:
            dds_filename = f"tex_{res_id_hex}.dds"
        
        # 所有纹理统一保存为 DDS 格式（不翻转）
        dds_file = os.path.join(output_dir, dds_filename)
        success = save_as_dds(raw_data, width, height, tex_format, dds_file)
        if success:
            return dds_file
        
        # 如果 DDS 保存失败，保存为原始数据文件
        if dxbc_name:
            raw_filename = f"t_{safe_name}_{res_id_hex}_{width}x{height}_{tex_format}.raw"
        else:
            raw_filename = f"tex_{res_id_hex}_{width}x{height}_{tex_format}.raw"
        raw_file = os.path.join(output_dir, raw_filename)
        with open(raw_file, 'wb') as f:
            f.write(bytes(raw_data))
        
        return raw_file
        
    except Exception as e:
        messages.debug(f"导出纹理 {res_id} 失败: {str(e)}")
        return None


def get_vbv_name_by_stride(stride, res_id_hex):
    """
    根据 VBV 的 stride 确定文件名前缀
    stride=8: vbv_bone
    stride=16: vbv_tangent
    stride>=24: vbv_vertex
    """
    if stride == 8:
        return f"vbv_bone_{res_id_hex}"
    elif stride == 16:
        return f"vbv_tangent_{res_id_hex}"
    elif stride >= 24:
        return f"vbv_vertex_{res_id_hex}"
    else:
        return f"vbv_{res_id_hex}"


def parse_skeleton_data(buffer_data, offset=0):
    """
    将缓冲区数据按 float4 解析为 SkeletonData 数组
    
    参数:
        buffer_data: 原始缓冲区数据
        offset: 起始偏移量
    
    返回:
        SkeletonData 数组，每个元素是 (x, y, z, w) 元组
        
    """
    skeleton_data = []
    data_bytes = bytes(buffer_data)
    
    # 每个 float4 = 16 bytes (4 floats * 4 bytes)
    float4_size = 16
    num_float4s = (len(data_bytes) - offset) // float4_size
    
    for i in range(num_float4s):
        base = offset + i * float4_size
        if base + float4_size <= len(data_bytes):
            x, y, z, w = struct.unpack_from('<ffff', data_bytes, base)
            skeleton_data.append((x, y, z, w))
    
    return skeleton_data


def parse_bone_weights_data(buffer_data, num_vertices):
    """
    解析骨骼索引和权重数据 (stride=8 的 VBV)
    
    布局（已修正）:
        ubyte4 bone_weights (4 bytes) - 4 个骨骼权重 (0-255)
        ubyte4 bone_indices (4 bytes) - 4 个骨骼索引
    
    参数:
        buffer_data: 原始缓冲区数据
        num_vertices: 顶点数量
    
    返回:
        (bone_indices_list, bone_weights_list)
        - bone_indices_list: 每个元素是 (i0, i1, i2, i3) 骨骼索引
        - bone_weights_list: 每个元素是 (w0, w1, w2, w3) 归一化权重（和为 1.0）
    """
    bone_indices_list = []
    bone_weights_list = []
    data_bytes = bytes(buffer_data)
    
    stride = 8  # ubyte4 + ubyte4
    
    for i in range(num_vertices):
        base = i * stride
        if base + stride > len(data_bytes):
            break
        
        # 解析骨骼权重 (前 4 bytes)
        w0, w1, w2, w3 = struct.unpack_from('<BBBB', data_bytes, base)
        
        # 解析骨骼索引 (后 4 bytes)
        i0, i1, i2, i3 = struct.unpack_from('<BBBB', data_bytes, base + 4)
        bone_indices_list.append((i0, i1, i2, i3))
        
        # 归一化权重，确保和为 1.0
        # 这与 shader 中 "w3 = 1.0 - w0 - w1 - w2" 的逻辑一致
        total = w0 + w1 + w2 + w3
        if total > 0:
            # 归一化：将 0-255 范围转换为 0-1，并确保和为 1.0
            inv_total = 1.0 / total
            bone_weights_list.append((
                w0 * inv_total,
                w1 * inv_total,
                w2 * inv_total,
                w3 * inv_total
            ))
        else:
            bone_weights_list.append((1.0, 0.0, 0.0, 0.0))  # 默认权重
    
    return bone_indices_list, bone_weights_list


def blend_bone_matrices(weights, indices, skeleton_data):
    """
    混合骨骼矩阵 (对应 shader 中的 BlendBoneMatrices)
    
    参数:
        weights: (w0, w1, w2, w3) 骨骼权重
        indices: (i0, i1, i2, i3) 骨骼索引
        skeleton_data: float4 数组，每个骨骼占 3 个 float4
    
    返回:
        4x3 矩阵，表示为 3 个 float4 的列表 [(r0x,r0y,r0z,r0w), (r1x,r1y,r1z,r1w), (r2x,r2y,r2z,r2w)]
    """
    w0, w1, w2, w3 = weights
    # 计算第四个权重 (shader 中: w3 = 1.0 - w.x - w.y - w.z)
    # 注意：这里输入的 w3 已经是第四个权重了
    
    i0, i1, i2, i3 = indices
    
    # 每个骨骼占 3 行 (idx = indices * 3)
    idx0, idx1, idx2, idx3 = i0 * 3, i1 * 3, i2 * 3, i3 * 3
    
    # 安全获取骨骼数据
    def safe_get(idx):
        if 0 <= idx < len(skeleton_data):
            return skeleton_data[idx]
        return (0.0, 0.0, 0.0, 0.0)
    
    # 混合矩阵的 3 行
    result = []
    for row_offset in range(3):
        r0 = safe_get(idx0 + row_offset)
        r1 = safe_get(idx1 + row_offset)
        r2 = safe_get(idx2 + row_offset)
        r3 = safe_get(idx3 + row_offset)
        
        # 加权混合
        blended = (
            w0 * r0[0] + w1 * r1[0] + w2 * r2[0] + w3 * r3[0],
            w0 * r0[1] + w1 * r1[1] + w2 * r2[1] + w3 * r3[1],
            w0 * r0[2] + w1 * r1[2] + w2 * r2[2] + w3 * r3[2],
            w0 * r0[3] + w1 * r1[3] + w2 * r2[3] + w3 * r3[3]
        )
        result.append(blended)
    
    return result


def skin_position(pos, bone_mat, row_major=True):
    """
    应用蒙皮变换到位置 (对应 shader 中的 SkinPosition)
    
    参数:
        pos: (x, y, z) 原始位置
        bone_mat: 4x3 矩阵 (3 个 float4)
        row_major: True 如果矩阵是行优先存储（默认），False 如果是列优先
    
    返回:
        (x, y, z) 变换后的位置
    """
    px, py, pz = pos
    
    mat0, mat1, mat2 = bone_mat
    
    if row_major:
        # 行优先存储
        # row0 = (m00, m01, m02, tx)
        # row1 = (m10, m11, m12, ty)
        # row2 = (m20, m21, m22, tz)
        x = mat0[0] * px + mat0[1] * py + mat0[2] * pz + mat0[3]
        y = mat1[0] * px + mat1[1] * py + mat1[2] * pz + mat1[3]
        z = mat2[0] * px + mat2[1] * py + mat2[2] * pz + mat2[3]
    else:
        # 列优先存储：col0 = (m00, m10, m20, ?), col1 = (m01, m11, m21, ?), col2 = (m02, m12, m22, ?)
        # 正确的变换：
        # x' = m00*x + m01*y + m02*z + tx
        # y' = m10*x + m11*y + m12*z + ty
        # z' = m20*x + m21*y + m22*z + tz
        x = mat0[0] * px + mat1[0] * py + mat2[0] * pz + mat0[3]
        y = mat0[1] * px + mat1[1] * py + mat2[1] * pz + mat1[3]
        z = mat0[2] * px + mat1[2] * py + mat2[2] * pz + mat2[3]
    
    return (x, y, z)


def skin_normal(normal, bone_mat, row_major=True):
    """
    应用蒙皮变换到法线 (只旋转，不平移)
    
    参数:
        normal: (nx, ny, nz) 原始法线 (0-255 范围)
        bone_mat: 4x3 矩阵 (3 个 float4)
        row_major: True 如果矩阵是行优先存储（默认），False 如果是列优先
    
    返回:
        (nx, ny, nz) 变换后的法线 (0-255 范围)
    """
    # 将 0-255 法线转换为 -1 到 1 范围
    nx = (normal[0] / 255.0) * 2.0 - 1.0
    ny = (normal[1] / 255.0) * 2.0 - 1.0
    nz = (normal[2] / 255.0) * 2.0 - 1.0
    
    mat0, mat1, mat2 = bone_mat
    
    if row_major:
        # 行优先
        tx = mat0[0] * nx + mat0[1] * ny + mat0[2] * nz
        ty = mat1[0] * nx + mat1[1] * ny + mat1[2] * nz
        tz = mat2[0] * nx + mat2[1] * ny + mat2[2] * nz
    else:
        # 列优先：法线变换使用旋转矩阵的转置
        tx = mat0[0] * nx + mat1[0] * ny + mat2[0] * nz
        ty = mat0[1] * nx + mat1[1] * ny + mat2[1] * nz
        tz = mat0[2] * nx + mat1[2] * ny + mat2[2] * nz
    
    # 归一化
    length = (tx*tx + ty*ty + tz*tz) ** 0.5
    if length > 0.0001:
        tx, ty, tz = tx / length, ty / length, tz / length
    
    # 转换回 0-255 范围
    out_nx = (tx + 1.0) * 0.5 * 255.0
    out_ny = (ty + 1.0) * 0.5 * 255.0
    out_nz = (tz + 1.0) * 0.5 * 255.0
    
    return (out_nx, out_ny, out_nz)


def apply_skinning(positions, normals, bone_indices, bone_weights, skeleton_data, row_major=True, output_dir=None, debug_output=False):
    """
    对所有顶点应用蒙皮变换
    
    参数:
        positions: 位置列表 [(x,y,z), ...]
        normals: 法线列表 [(nx,ny,nz), ...] (0-255 范围)
        bone_indices: 骨骼索引列表 [(i0,i1,i2,i3), ...]
        bone_weights: 骨骼权重列表 [(w0,w1,w2,w3), ...]
        skeleton_data: 骨骼矩阵数据 (float4 数组)
        row_major: True 如果矩阵是行优先存储（默认），False 如果是列优先
        output_dir: 输出目录
        debug_output: 是否输出 bone.json 调试文件（默认 False）
    
    返回:
        (skinned_positions, skinned_normals)
    """
    skinned_positions = []
    skinned_normals = []
    
    num_vertices = min(len(positions), len(bone_indices), len(bone_weights))
    
    # 只有当 debug_output=True 且 output_dir 不为空时才收集调试数据
    should_debug = debug_output and output_dir
    bone_debug_data = None
    max_debug_vertices = 10  # 只保存前10个顶点的详细调试数据
    
    if should_debug:
        bone_debug_data = {
            "row_major": row_major,
            "skeleton_data_count": len(skeleton_data),
            "skeleton_data": [{"index": i, "x": s[0], "y": s[1], "z": s[2], "w": s[3]} for i, s in enumerate(skeleton_data[:48])],  # 只保存前48个（16个骨骼）
            "vertices": []
        }
    
    for i in range(num_vertices):
        # 获取当前顶点的骨骼数据
        weights = bone_weights[i]
        indices = bone_indices[i]
        
        # 混合骨骼矩阵
        bone_mat = blend_bone_matrices(weights, indices, skeleton_data)
        
        # 收集调试数据（只保存前几个顶点）
        if should_debug and i < max_debug_vertices:
            i0, i1, i2, i3 = indices
            idx0, idx1, idx2, idx3 = i0 * 3, i1 * 3, i2 * 3, i3 * 3
            
            def safe_get_debug(idx):
                if 0 <= idx < len(skeleton_data):
                    return skeleton_data[idx]
                return (0.0, 0.0, 0.0, 0.0)
            
            vertex_debug = {
                "vertex_index": i,
                "original_position": {"x": positions[i][0], "y": positions[i][1], "z": positions[i][2]},
                "weights": {"w0": weights[0], "w1": weights[1], "w2": weights[2], "w3": weights[3]},
                "indices": {"i0": indices[0], "i1": indices[1], "i2": indices[2], "i3": indices[3]},
                "matrix_indices": {"idx0": idx0, "idx1": idx1, "idx2": idx2, "idx3": idx3},
                "bone_data": {
                    "bone0": [
                        {"row": 0, "data": list(safe_get_debug(idx0))},
                        {"row": 1, "data": list(safe_get_debug(idx0 + 1))},
                        {"row": 2, "data": list(safe_get_debug(idx0 + 2))}
                    ],
                    "bone1": [
                        {"row": 0, "data": list(safe_get_debug(idx1))},
                        {"row": 1, "data": list(safe_get_debug(idx1 + 1))},
                        {"row": 2, "data": list(safe_get_debug(idx1 + 2))}
                    ],
                    "bone2": [
                        {"row": 0, "data": list(safe_get_debug(idx2))},
                        {"row": 1, "data": list(safe_get_debug(idx2 + 1))},
                        {"row": 2, "data": list(safe_get_debug(idx2 + 2))}
                    ],
                    "bone3": [
                        {"row": 0, "data": list(safe_get_debug(idx3))},
                        {"row": 1, "data": list(safe_get_debug(idx3 + 1))},
                        {"row": 2, "data": list(safe_get_debug(idx3 + 2))}
                    ]
                },
                "blended_bone_mat": {
                    "row0": list(bone_mat[0]),
                    "row1": list(bone_mat[1]),
                    "row2": list(bone_mat[2])
                }
            }
            bone_debug_data["vertices"].append(vertex_debug)
        
        # 变换位置
        skinned_pos = skin_position(positions[i], bone_mat, row_major)
        skinned_positions.append(skinned_pos)
        
        # 更新调试数据
        if should_debug and i < max_debug_vertices:
            bone_debug_data["vertices"][-1]["skinned_position"] = {
                "x": skinned_pos[0], "y": skinned_pos[1], "z": skinned_pos[2]
            }
        
        # 变换法线 (如果有)
        if i < len(normals):
            skinned_norm = skin_normal(normals[i], bone_mat, row_major)
            skinned_normals.append(skinned_norm)
            
            # 更新调试数据
            if should_debug and i < max_debug_vertices:
                bone_debug_data["vertices"][-1]["original_normal"] = {
                    "x": normals[i][0], "y": normals[i][1], "z": normals[i][2]
                }
                bone_debug_data["vertices"][-1]["skinned_normal"] = {
                    "x": skinned_norm[0], "y": skinned_norm[1], "z": skinned_norm[2]
                }
    
    # 保存调试数据到 bone.json（仅当 debug_output=True）
    if should_debug and bone_debug_data:
        bone_json_path = os.path.join(output_dir, "bone.json")
        try:
            with open(bone_json_path, 'w', encoding='utf-8') as f:
                json.dump(bone_debug_data, f, indent=2, ensure_ascii=False)
            messages.debug(f"骨骼调试数据已保存到: {bone_json_path}")
        except Exception as e:
            messages.debug(f"保存骨骼调试数据失败: {str(e)}")
    
    # 如果还有剩余位置没有骨骼数据，直接复制
    for i in range(num_vertices, len(positions)):
        skinned_positions.append(positions[i])
    
    for i in range(num_vertices, len(normals)):
        skinned_normals.append(normals[i])
    
    return skinned_positions, skinned_normals


def export_buffer(resources_accessor, buffer_resource, call, output_dir, res_id):
    """导出缓冲区资源描述信息（不导出二进制文件）"""
    try:
        desc = buffer_resource.get_description()
        
        if desc.get("resource_type") != "buffer":
            return None
        
        size = desc.get("size", 0)
        stride = desc.get("stride", 0)
        offset = desc.get("offset", 0)
        buf_view_type = desc.get("view_type", "unknown")
        
        # 将资源 ID 转换为 16 进制
        res_id_hex = format(int(res_id), 'X')
        
        # 根据 view_type 和 stride 确定文件名
        if buf_view_type == "VBV":
            # VBV 类型根据 stride 命名: vbv_vertex_XXX, vbv_bone_XXX, vbv_tangent_XXX
            base_name = get_vbv_name_by_stride(stride, res_id_hex)
            info_file = os.path.join(output_dir, f"{base_name}.json")
        elif buf_view_type == "IBV":
            # IBV 类型: ibv_XXX
            info_file = os.path.join(output_dir, f"ibv_{res_id_hex}.json")
        elif buf_view_type == "CBV":
            # IBV 类型: ibv_XXX
            info_file = os.path.join(output_dir, f"cbv_{res_id_hex}.json")
        else:
            # 其他类型
            info_file = os.path.join(output_dir, f"buf_{res_id_hex}_{buf_view_type}.json")
        
        # 准备基础输出数据
        output_info = {
            "resource_id": res_id,
            "resource_id_hex": res_id_hex,
            "size": size,
            "stride": stride,
            "offset": offset,
            "view_type": buf_view_type,
            "description": desc
        }
        
        # 如果 size 是 768，按 float4 提取成 SkeletonData 数组
        if size == 768:
            try:
                # 获取缓冲区数据
                buffer_request = BufferRequest(
                    buffer=buffer_resource,
                    call=call,
                    extract_before=False
                )
                
                buffer_result = resources_accessor.get_buffers_data([buffer_request], timeout=30000)
                
                if buffer_request in buffer_result:
                    buffer_data = buffer_result[buffer_request].data
                    skeleton_data = parse_skeleton_data(buffer_data, 0)
                    
                    output_info["is_skeleton_data"] = True
                    output_info["skeleton_float4_count"] = len(skeleton_data)
                    output_info["skeleton_data"] = skeleton_data
                    
                    messages.debug(f"解析骨骼数据: size=768, {len(skeleton_data)} 个 float4")
            except Exception as e:
                messages.debug(f"解析骨骼数据失败: {str(e)}")
                output_info["skeleton_parse_error"] = str(e)
        
        # 保存描述信息
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(output_info, f, indent=2, ensure_ascii=False, default=str)
        
        return info_file
        
    except Exception as e:
        messages.debug(f"导出缓冲区 {res_id} 失败: {str(e)}")
        return None


def save_as_tga(raw_data, width, height, row_pitch, output_path, tex_format):
    """保存为 TGA 图像格式（不需要 zlib）"""
    try:
        # TGA 文件头 (18 字节)
        header = bytearray(18)
        header[2] = 2  # 未压缩的真彩色图像
        header[12] = width & 0xFF
        header[13] = (width >> 8) & 0xFF
        header[14] = height & 0xFF
        header[15] = (height >> 8) & 0xFF
        header[16] = 32  # 32 位（RGBA）
        header[17] = 0x20  # 从左上角开始
        
        with open(output_path, 'wb') as f:
            f.write(header)
            
            bytes_per_pixel = 4
            for y in range(height):
                row_start = y * row_pitch
                row_end = row_start + width * bytes_per_pixel
                row_data = raw_data[row_start:row_end]
                
                # RGBA -> BGRA (TGA 格式)
                if "R8G8B8A8" in tex_format:
                    converted_row = bytearray(len(row_data))
                    for x in range(width):
                        px = x * 4
                        if px + 3 < len(row_data):
                            converted_row[px] = row_data[px + 2]      # B
                            converted_row[px + 1] = row_data[px + 1]  # G
                            converted_row[px + 2] = row_data[px]      # R
                            converted_row[px + 3] = row_data[px + 3]  # A
                    f.write(bytes(converted_row))
                else:
                    # B8G8R8A8 格式直接写入
                    f.write(bytes(row_data))
        
        return True
                    
    except Exception as e:
        messages.debug(f"保存 TGA 失败: {str(e)}")
        return False


def save_as_png(raw_data, width, height, row_pitch, output_path, tex_format):
    """根据格式和尺寸保存为 PNG 图像（需要 zlib）"""
    if not HAS_ZLIB:
        messages.debug("zlib 模块不可用，无法保存 PNG")
        return False
    
    try:
        # 判断像素格式和字节数
        if "R8G8B8A8" in tex_format or "B8G8R8A8" in tex_format:
            bytes_per_pixel = 4
            color_type = 6  # RGBA
        elif "R8G8B8" in tex_format and "A8" not in tex_format:
            bytes_per_pixel = 3
            color_type = 2  # RGB
        elif "R8" in tex_format or "A8" in tex_format or "L8" in tex_format:
            bytes_per_pixel = 1
            color_type = 0  # Grayscale
        elif "R16G16B16A16" in tex_format:
            bytes_per_pixel = 8
            color_type = 6  # RGBA (16-bit per channel)
        elif "R32G32B32A32" in tex_format:
            # 32位浮点转换为8位
            bytes_per_pixel = 16
            color_type = 6
        else:
            # 不支持的格式
            messages.debug(f"PNG 不支持格式: {tex_format}")
            return False
        
        # PNG 文件签名
        png_signature = b'\x89PNG\r\n\x1a\n'
        
        def make_chunk(chunk_type, data):
            """创建 PNG chunk"""
            chunk_len = struct.pack('>I', len(data))
            chunk_crc = zlib.crc32(chunk_type + data) & 0xffffffff
            chunk_crc = struct.pack('>I', chunk_crc)
            return chunk_len + chunk_type + data + chunk_crc
        
        # IHDR chunk
        bit_depth = 8
        ihdr_data = struct.pack('>IIBBBBB', width, height, bit_depth, color_type, 0, 0, 0)
        ihdr_chunk = make_chunk(b'IHDR', ihdr_data)
        
        # 准备图像数据
        raw_rows = []
        for y in range(height):
            row_start = y * row_pitch
            row_end = row_start + width * bytes_per_pixel
            row_data = bytearray(raw_data[row_start:row_end])
            
            # 格式转换
            if "B8G8R8A8" in tex_format:
                # BGRA -> RGBA
                for x in range(width):
                    px = x * 4
                    if px + 3 < len(row_data):
                        row_data[px], row_data[px + 2] = row_data[px + 2], row_data[px]
            elif "R32G32B32A32" in tex_format and "FLOAT" in tex_format:
                # 32位浮点 -> 8位整数
                new_row = bytearray(width * 4)
                for x in range(width):
                    px = x * 16
                    if px + 15 < len(row_data):
                        r = struct.unpack_from('<f', bytes(row_data), px)[0]
                        g = struct.unpack_from('<f', bytes(row_data), px + 4)[0]
                        b = struct.unpack_from('<f', bytes(row_data), px + 8)[0]
                        a = struct.unpack_from('<f', bytes(row_data), px + 12)[0]
                        new_row[x * 4] = max(0, min(255, int(r * 255)))
                        new_row[x * 4 + 1] = max(0, min(255, int(g * 255)))
                        new_row[x * 4 + 2] = max(0, min(255, int(b * 255)))
                        new_row[x * 4 + 3] = max(0, min(255, int(a * 255)))
                row_data = new_row
            elif "R16G16B16A16" in tex_format:
                # 16位 -> 8位
                new_row = bytearray(width * 4)
                for x in range(width):
                    px = x * 8
                    if px + 7 < len(row_data):
                        r = struct.unpack_from('<H', bytes(row_data), px)[0]
                        g = struct.unpack_from('<H', bytes(row_data), px + 2)[0]
                        b = struct.unpack_from('<H', bytes(row_data), px + 4)[0]
                        a = struct.unpack_from('<H', bytes(row_data), px + 6)[0]
                        new_row[x * 4] = r >> 8
                        new_row[x * 4 + 1] = g >> 8
                        new_row[x * 4 + 2] = b >> 8
                        new_row[x * 4 + 3] = a >> 8
                row_data = new_row
            
            # PNG 每行需要添加 filter byte (0 = None)
            raw_rows.append(b'\x00' + bytes(row_data[:width * min(bytes_per_pixel, 4)]))
        
        # 压缩图像数据
        raw_image_data = b''.join(raw_rows)
        compressed_data = zlib.compress(raw_image_data, 9)
        
        # IDAT chunk
        idat_chunk = make_chunk(b'IDAT', compressed_data)
        
        # IEND chunk
        iend_chunk = make_chunk(b'IEND', b'')
        
        # 写入 PNG 文件
        with open(output_path, 'wb') as f:
            f.write(png_signature)
            f.write(ihdr_chunk)
            f.write(idat_chunk)
            f.write(iend_chunk)
        
        return True
        
    except Exception as e:
        messages.debug(f"保存 PNG 失败: {str(e)}")
        return False


def get_draw_call_params(call_desc):
    """
    从 API 调用描述中提取绘制调用参数
    返回: (index_count, start_index_location, base_vertex_location)
    """
    index_count = 0
    start_index_location = 0
    base_vertex_location = 0
    
    arguments = call_desc.get("arguments", [])
    for arg in arguments:
        arg_name = arg.get("name", "").lower()
        arg_value = arg.get("value", 0)
        
        if arg_name in ["indexcount", "index_count"]:
            index_count = int(arg_value) if arg_value else 0
        elif arg_name in ["startindexlocation", "start_index_location"]:
            start_index_location = int(arg_value) if arg_value else 0
        elif arg_name in ["basevertexlocation", "base_vertex_location"]:
            base_vertex_location = int(arg_value) if arg_value else 0
        elif arg_name in ["vertexcount", "vertex_count"]:
            # 对于 Draw 调用（非 DrawIndexed）
            if index_count == 0:
                index_count = int(arg_value) if arg_value else 0
    
    return index_count, start_index_location, base_vertex_location


def parse_indirect_args_buffer(buffer_data):
    """
    解析 DrawIndexedInstancedIndirect 的 args buffer
    
    Buffer 结构 (20 bytes):
        uint IndexCountPerInstance;    // offset 0,  4 bytes
        uint InstanceCount;            // offset 4,  4 bytes
        uint StartIndexLocation;       // offset 8,  4 bytes
        int  BaseVertexLocation;       // offset 12, 4 bytes (signed)
        uint StartInstanceLocation;    // offset 16, 4 bytes
    
    返回: dict 包含解析后的参数，失败时返回 None
    """
    try:
        data_bytes = bytes(buffer_data)
        
        if len(data_bytes) < 20:
            messages.debug(f"Indirect args buffer 数据不足: {len(data_bytes)} bytes, 需要 20 bytes")
            return None
        
        # 解析 5 个 uint/int 值
        index_count_per_instance = struct.unpack_from('<I', data_bytes, 0)[0]
        instance_count = struct.unpack_from('<I', data_bytes, 4)[0]
        start_index_location = struct.unpack_from('<I', data_bytes, 8)[0]
        base_vertex_location = struct.unpack_from('<i', data_bytes, 12)[0]  # signed int
        start_instance_location = struct.unpack_from('<I', data_bytes, 16)[0]
        
        indirect_args = {
            "IndexCountPerInstance": index_count_per_instance,
            "InstanceCount": instance_count,
            "StartIndexLocation": start_index_location,
            "BaseVertexLocation": base_vertex_location,
            "StartInstanceLocation": start_instance_location
        }
        
        messages.debug(f"解析 Indirect Args: IndexCount={index_count_per_instance}, "
                      f"InstanceCount={instance_count}, StartIndex={start_index_location}, "
                      f"BaseVertex={base_vertex_location}, StartInstance={start_instance_location}")
        
        return indirect_args
        
    except Exception as e:
        messages.debug(f"解析 Indirect args buffer 失败: {str(e)}")
        return None


def find_args_buffer_from_inputs(bindings):
    """
    从 bindings 的 inputs 中查找 view_type 为 "args" 的 buffer
    
    返回: 找到的资源对象，未找到返回 None
    """
    if "inputs" not in bindings:
        return None
    
    for res in bindings["inputs"]:
        res_desc = res.get_description()
        view_type = res_desc.get("view_type", "")
        resource_type = res_desc.get("resource_type", "")
        
        if view_type.lower() == "args" and resource_type == "buffer":
            res_id = res_desc.get("resource_id", 0)
            messages.debug(f"找到 args buffer: resource_id={res_id}, view_type={view_type}")
            return res
    
    return None


def is_draw_indexed_instanced_indirect(call_desc):
    """
    检查调用是否为 DrawIndexedInstancedIndirect
    """
    call_name = call_desc.get("name", "")
    return "DrawIndexedInstancedIndirect" in call_name


def decode_ubyte4_normal(nx, ny, nz):
    """
    将 ubyte4 法线保持原始值 (0-255)
    """
    norm_x = nx * 1.0
    norm_y = ny * 1.0
    norm_z = nz * 1.0
    return (norm_x, norm_y, norm_z)


def parse_vertex_data_by_stride(vertex_data, stride, num_vertices):
    """
    根据 stride 解析顶点数据
    
    stride=24 布局:
        float3 POSITION  (offset 0, 12 bytes)
        ubyte4 NORMAL    (offset 12, 4 bytes)
        float2 TEXCOORD  (offset 16, 8 bytes)
    
    stride=28 布局:
        float3 POSITION  (offset 0, 12 bytes)
        ubyte4 COLOR     (offset 12, 4 bytes)
        ubyte4 NORMAL    (offset 16, 4 bytes)
        float2 TEXCOORD0 (offset 20, 8 bytes)
    
    stride=32 布局:
        float3 POSITION  (offset 0, 12 bytes)
        ubyte4 NORMAL    (offset 12, 4 bytes)
        float2 TEXCOORD0 (offset 16, 8 bytes)
        float2 TEXCOORD1 (offset 24, 8 bytes)
    
    stride=36 布局:
        float3 POSITION  (offset 0, 12 bytes)
        ubyte4 COLOR     (offset 12, 4 bytes)
        ubyte4 NORMAL    (offset 16, 4 bytes)
        float2 TEXCOORD0 (offset 20, 8 bytes)
        float2 TEXCOORD1 (offset 28, 8 bytes)
    
    返回: (positions, normals, texcoords)
    """
    positions = []
    normals = []
    texcoords = []
    
    data_bytes = bytes(vertex_data)
    
    for i in range(num_vertices):
        base_offset = i * stride
        
        if base_offset + stride > len(data_bytes):
            break
        
        # 解析 POSITION (float3, offset 0) - 所有格式都相同
        x, y, z = struct.unpack_from('<fff', data_bytes, base_offset)
        positions.append((x, y, z))
        
        # 根据 stride 解析 NORMAL 和 TEXCOORD
        if stride == 24:
            # NORMAL at offset 12, TEXCOORD at offset 16
            nx, ny, nz, nw = struct.unpack_from('<BBBB', data_bytes, base_offset + 12)
            normals.append(decode_ubyte4_normal(nx, ny, nz))
            
            u, v = struct.unpack_from('<ff', data_bytes, base_offset + 16)
            texcoords.append((u, 1.0 - v))
            
        elif stride == 28:
            # COLOR at offset 12 (skip), NORMAL at offset 16, TEXCOORD0 at offset 20
            nx, ny, nz, nw = struct.unpack_from('<BBBB', data_bytes, base_offset + 16)
            normals.append(decode_ubyte4_normal(nx, ny, nz))
            
            u, v = struct.unpack_from('<ff', data_bytes, base_offset + 20)
            texcoords.append((u, 1.0 - v))
            
        elif stride == 32:
            # NORMAL at offset 12, TEXCOORD0 at offset 16, TEXCOORD1 at offset 24
            nx, ny, nz, nw = struct.unpack_from('<BBBB', data_bytes, base_offset + 12)
            normals.append(decode_ubyte4_normal(nx, ny, nz))
            
            # 使用 TEXCOORD0
            u, v = struct.unpack_from('<ff', data_bytes, base_offset + 16)
            texcoords.append((u, 1.0 - v))
            
        elif stride == 36:
            # COLOR at offset 12 (skip), NORMAL at offset 16, TEXCOORD0 at offset 20
            nx, ny, nz, nw = struct.unpack_from('<BBBB', data_bytes, base_offset + 16)
            normals.append(decode_ubyte4_normal(nx, ny, nz))
            
            # 使用 TEXCOORD0
            u, v = struct.unpack_from('<ff', data_bytes, base_offset + 20)
            texcoords.append((u, 1.0 - v))
            
        else:
            # 其他 stride，尝试通用解析
            if stride >= 24:
                # 假设 NORMAL 在 offset 12
                nx, ny, nz, nw = struct.unpack_from('<BBBB', data_bytes, base_offset + 12)
                normals.append(decode_ubyte4_normal(nx, ny, nz))
                
                # 尝试在 offset 16 找 UV
                if stride >= 24:
                    try:
                        u, v = struct.unpack_from('<ff', data_bytes, base_offset + 16)
                        if abs(u) < 100 and abs(v) < 100:
                            texcoords.append((u, 1.0 - v))
                        else:
                            texcoords.append((0.0, 0.0))
                    except:
                        texcoords.append((0.0, 0.0))
    
    return positions, normals, texcoords


def export_mesh_to_obj(resources_accessor, call, geometry_info, output_dir, event_index, call_desc):
    """
    导出几何数据为 OBJ 文件
    根据 IndexCount, StartIndexLocation, BaseVertexLocation 提取正确范围的数据
    支持解析 stride=24/28 的顶点布局（位置、法线、UV）
    文件名格式: g_{event_index}.obj
    """
    try:
        if not geometry_info:
            return None
        
        index_buffer_id = geometry_info.get("index_buffer")
        vertex_buffers = geometry_info.get("vertex_buffers", [])
        
        if not vertex_buffers:
            return None
        
        # 获取绘制调用参数
        index_count, start_index_location, base_vertex_location = get_draw_call_params(call_desc)
        
        all_resources = resources_accessor.get_memory_resources()
        
        # 查找主顶点缓冲区（stride >= 24 的，包含完整顶点数据）
        main_buffer = None
        main_stride = 0
        
        for vb in vertex_buffers:
            buffer_id = str(vb.get("buffer"))
            if buffer_id in all_resources:
                buf = all_resources[buffer_id][0]
                buf_stride = buf.get_description().get("stride", 0)
                # 优先选择 stride >= 24 的缓冲区（包含位置+法线+UV）
                if buf_stride >= 24 and buf_stride > main_stride:
                    main_buffer = buf
                    main_stride = buf_stride
        
        # 如果没有找到 stride >= 24 的，尝试找 POSITION 缓冲区
        if not main_buffer:
            for vb in vertex_buffers:
                buffer_id = str(vb.get("buffer"))
                layout = vb.get("layout", {})
                layout_name = layout.get("name", "").upper()
                
                if "POSITION" in layout_name:
                    if buffer_id in all_resources:
                        main_buffer = all_resources[buffer_id][0]
                        main_stride = main_buffer.get_description().get("stride", 12)
                        break
        
        if not main_buffer:
            return None
        
        buffer_request = BufferRequest(
            buffer=main_buffer,
            call=call,
            extract_before=False
        )
        
        buffer_result = resources_accessor.get_buffers_data([buffer_request], timeout=30000)
        
        if buffer_request not in buffer_result:
            return None
        
        vertex_data = buffer_result[buffer_request].data
        num_vertices = len(vertex_data) // main_stride if main_stride > 0 else 0
        
        # 根据 stride 解析顶点数据
        if main_stride >= 24:
            all_positions, all_normals, all_texcoords = parse_vertex_data_by_stride(
                vertex_data, main_stride, num_vertices
            )
        else:
            # 只有位置数据
            all_positions = []
            all_normals = []
            all_texcoords = []
            data_bytes = bytes(vertex_data)
            for i in range(num_vertices):
                offset = i * main_stride
                if offset + 12 <= len(data_bytes):
                    x, y, z = struct.unpack_from('<fff', data_bytes, offset)
                    all_positions.append((x, y, z))
        
        if not all_positions:
            return None
        
        # 读取索引缓冲区
        all_indices = []
        if index_buffer_id:
            index_buffer_id_str = str(index_buffer_id)
            if index_buffer_id_str in all_resources:
                index_buffer = all_resources[index_buffer_id_str][0]
                
                index_request = BufferRequest(
                    buffer=index_buffer,
                    call=call,
                    extract_before=False
                )
                
                try:
                    index_result = resources_accessor.get_buffers_data([index_request], timeout=30000)
                    
                    if index_request in index_result:
                        index_data = index_result[index_request].data
                        index_desc = index_buffer.get_description()
                        index_stride = index_desc.get("stride", 2)
                        # 如果不是 4 则必为 2
                        if index_stride != 4:
                            index_stride = 2
                        
                        index_bytes = bytes(index_data)
                        if index_stride == 4:
                            num_indices = len(index_bytes) // 4
                            for i in range(num_indices):
                                idx = struct.unpack_from('<I', index_bytes, i * 4)[0]
                                all_indices.append(idx)
                        else:
                            num_indices = len(index_bytes) // 2
                            for i in range(num_indices):
                                idx = struct.unpack_from('<H', index_bytes, i * 2)[0]
                                all_indices.append(idx)
                except Exception as e:
                    messages.debug(f"获取索引缓冲区失败: {str(e)}")
        
        # 根据 StartIndexLocation 和 IndexCount 提取使用的索引
        if all_indices and index_count > 0:
            end_index = start_index_location + index_count
            used_indices = all_indices[start_index_location:end_index]
        elif all_indices:
            used_indices = all_indices
        else:
            used_indices = []
        
        # 应用 BaseVertexLocation 并收集使用的顶点
        has_normals = len(all_normals) > 0
        has_texcoords = len(all_texcoords) > 0
        
        if used_indices:
            # 找出所有使用的顶点索引
            adjusted_indices = [idx + base_vertex_location for idx in used_indices]
            unique_vertex_indices = sorted(set(adjusted_indices))
            
            # 创建旧索引到新索引的映射
            index_map = {old_idx: new_idx for new_idx, old_idx in enumerate(unique_vertex_indices)}
            
            # 提取使用的顶点数据
            positions = []
            normals = []
            texcoords = []
            
            for old_idx in unique_vertex_indices:
                if 0 <= old_idx < len(all_positions):
                    positions.append(all_positions[old_idx])
                else:
                    positions.append((0.0, 0.0, 0.0))
                
                if has_normals and 0 <= old_idx < len(all_normals):
                    normals.append(all_normals[old_idx])
                elif has_normals:
                    normals.append((0.0, 1.0, 0.0))
                
                if has_texcoords and 0 <= old_idx < len(all_texcoords):
                    texcoords.append(all_texcoords[old_idx])
                elif has_texcoords:
                    texcoords.append((0.0, 0.0))
            
            # 重新映射索引
            indices = [index_map.get(idx + base_vertex_location, 0) for idx in used_indices]
        else:
            # 没有索引缓冲区，直接使用顶点
            positions = all_positions
            normals = all_normals
            texcoords = all_texcoords
            indices = []
        
        if not positions:
            return None
        
        # 使用 g_{event_index}.obj 命名
        obj_file = os.path.join(output_dir, f"g_{event_index}.obj")
        
        with open(obj_file, 'w') as f:
            f.write(f"# Exported from Intel GPA\n")
            f.write(f"# Event Index: {event_index}\n")
            f.write(f"# Stride: {main_stride}\n")
            f.write(f"# IndexCount: {index_count}, StartIndexLocation: {start_index_location}, BaseVertexLocation: {base_vertex_location}\n")
            f.write(f"# Vertices: {len(positions)}, Triangles: {len(indices) // 3 if indices else len(positions) // 3}\n")
            f.write(f"# Has Normals: {has_normals}, Has UVs: {has_texcoords}\n\n")
            
            # 写入顶点位置
            for v in positions:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            
            f.write("\n")
            
            # 写入纹理坐标
            if texcoords:
                for uv in texcoords:
                    f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
                f.write("\n")
            
            # 写入法线
            if normals:
                for n in normals:
                    f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
                f.write("\n")
            
            # 写入面 — 交换 i1/i2 将 D3D CW 环绕转为 OBJ CCW 环绕
            if indices:
                for i in range(0, len(indices) - 2, 3):
                    i0 = indices[i] + 1
                    i1 = indices[i + 1] + 1
                    i2 = indices[i + 2] + 1
                    
                    if has_texcoords and has_normals:
                        f.write(f"f {i0}/{i0}/{i0} {i2}/{i2}/{i2} {i1}/{i1}/{i1}\n")
                    elif has_texcoords:
                        f.write(f"f {i0}/{i0} {i2}/{i2} {i1}/{i1}\n")
                    elif has_normals:
                        f.write(f"f {i0}//{i0} {i2}//{i2} {i1}//{i1}\n")
                    else:
                        f.write(f"f {i0} {i2} {i1}\n")
            else:
                for i in range(0, len(positions) - 2, 3):
                    i0 = i + 1
                    i1 = i + 2
                    i2 = i + 3
                    
                    if has_texcoords and has_normals:
                        f.write(f"f {i0}/{i0}/{i0} {i2}/{i2}/{i2} {i1}/{i1}/{i1}\n")
                    elif has_texcoords:
                        f.write(f"f {i0}/{i0} {i2}/{i2} {i1}/{i1}\n")
                    elif has_normals:
                        f.write(f"f {i0}//{i0} {i2}//{i2} {i1}//{i1}\n")
                    else:
                        f.write(f"f {i0} {i2} {i1}\n")
        
        return obj_file
        
    except Exception as e:
        messages.debug(f"导出 mesh 失败 (event {event_index}): {str(e)}")
        return None


def export_shader_il(program, shader_type, il_type, output_dir, program_id_hex):
    """
    尝试导出 shader 的中间语言（DXIL 或 ISA）
    """
    try:
        il_source = program.get_il_source(shader_type, il_type, timeout_ms=30000)
        if il_source:
            # 确定文件扩展名
            ext = ".dxil" if il_type == "dxil" else ".isa"
            prefix = "vs" if shader_type == "vertex" else "ps" if shader_type == "pixel" else shader_type[:2]
            
            il_file = os.path.join(output_dir, f"{prefix}_{program_id_hex}{ext}")
            
            # 判断是文本还是二进制
            if isinstance(il_source, str):
                with open(il_file, 'w', encoding='utf-8') as f:
                    f.write(il_source)
            else:
                with open(il_file, 'wb') as f:
                    f.write(bytes(il_source))
            
            return {"type": f"{shader_type}_{il_type}", "file": os.path.basename(il_file)}
    except Exception as e:
        messages.debug(f"获取 {shader_type} {il_type} 失败: {str(e)}")
    
    return None


def parse_texture_bindings_from_dxbc(dxbc_source):
    """
    从 DXBC 反汇编文本中逐行解析 Resource Bindings，
    提取 type 为 texture 的内容
    
    解析格式:
    // Name                                 Type  Format         Dim      HLSL Bind  Count
    // ------------------------------ ---------- ------- ----------- -------------- ------
    // tBaseMap                          texture  float4          2d             t0      1 
    
    返回:
        [{"name": "tBaseMap", "type": "texture", "format": "float4", "dim": "2d", "slot": "t0", "count": 1}]
    """
    import re
    
    textures = []
    
    if not dxbc_source:
        return textures
    
    # 确保是字符串
    if isinstance(dxbc_source, bytes):
        try:
            dxbc_source = dxbc_source.decode('utf-8', errors='ignore')
        except:
            dxbc_source = dxbc_source.decode('latin-1', errors='ignore')
    
    # 逐行解析
    in_bindings_section = False
    header_found = False
    
    lines = dxbc_source.split('\n')
    for line_num, line in enumerate(lines):
        original_line = line
        line = line.strip()
        
        # 检测 Resource Bindings 部分开始
        if "Resource Bindings:" in line:
            in_bindings_section = True
            messages.debug(f"[DXBC 解析] 第 {line_num + 1} 行: 找到 Resource Bindings 部分")
            continue
        
        # 检测表头行
        if in_bindings_section and "Name" in line and "HLSL Bind" in line:
            header_found = True
            messages.debug(f"[DXBC 解析] 第 {line_num + 1} 行: 找到表头")
            continue
        
        # 检测分隔线（跳过）
        if in_bindings_section and "// ---" in line:
            continue
        
        # 检测绑定部分结束
        if in_bindings_section and header_found:
            # 空行或非注释行表示结束
            if not line or (not line.startswith("//")):
                in_bindings_section = False
                continue
            
            # 只处理纯注释空行
            if line == "//":
                in_bindings_section = False
                continue
            
            # 解析资源绑定行
            if line.startswith("//"):
                content = line[2:].strip()
                
                # 使用正则匹配: Name Type Format Dim Bind Count
                # 示例: tBaseMap                          texture  float4          2d             t0      1 
                match = re.match(r'(\S+)\s+(texture|sampler|cbuffer|UAV)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)', content)
                if match:
                    name, res_type, fmt, dim, bind, count = match.groups()
                    
                    # 只提取 texture 类型
                    if res_type == "texture":
                        texture_info = {
                            "name": name,
                            "type": res_type,
                            "format": fmt,
                            "dim": dim,
                            "slot": bind,
                            "count": int(count),
                            "line_number": line_num + 1
                        }
                        textures.append(texture_info)
                        messages.debug(f"[DXBC 解析] 第 {line_num + 1} 行: 找到纹理 {name} -> {bind}")
    
    return textures


def export_shaders(program, output_dir, event_index):
    """
    导出 shader 资源（VS 和 PS）
    包括：HLSL 源码、DXIL、ISA
    
    参数:
        program: Program 对象
        output_dir: 输出目录
        event_index: 事件索引
    
    返回:
        导出的 shader 文件列表
    """
    exported_shaders = []
    
    try:
        program_desc = program.get_description()
        program_id = program_desc.get("id", "unknown")
        program_id_hex = format(int(program_id), 'X') if str(program_id).isdigit() else str(program_id)
        
        # 导出 Vertex Shader (顶点着色器)
        if "vertex" in program_desc:
            vs_info = program_desc["vertex"]
            vs_source = vs_info.get("source", "")
            vs_hash = vs_info.get("hash", "")
            
            if vs_source:
                vs_file = os.path.join(output_dir, f"vs_{program_id_hex}.hlsl")
                with open(vs_file, 'w', encoding='utf-8') as f:
                    f.write(f"//==============================================================================\n")
                    f.write(f"// 顶点着色器 (Vertex Shader)\n")
                    f.write(f"//==============================================================================\n")
                    f.write(f"// 程序 ID: {program_id} (0x{program_id_hex})\n")
                    if vs_hash:
                        f.write(f"// 哈希值: {vs_hash}\n")
                    f.write(f"// 事件索引: {event_index}\n")
                    f.write(f"//\n")
                    f.write(f"// 功能说明:\n")
                    f.write(f"//   顶点着色器负责处理每个顶点的变换，包括:\n")
                    f.write(f"//   - 将顶点从模型空间变换到裁剪空间\n")
                    f.write(f"//   - 计算顶点属性（法线、纹理坐标等）的插值\n")
                    f.write(f"//   - 传递数据给像素着色器\n")
                    f.write(f"//==============================================================================\n\n")
                    f.write(vs_source)
                exported_shaders.append({
                    "type": "vertex",
                    "file": os.path.basename(vs_file)
                })
            
            # 尝试导出 DXBC (DX11)
            vs_dxbc = vs_info.get("dxbc", "")
            if vs_dxbc:
                vs_dxbc_file = os.path.join(output_dir, f"vs_{program_id_hex}.dxbc")
                with open(vs_dxbc_file, 'wb') as f:
                    if isinstance(vs_dxbc, str):
                        f.write(vs_dxbc.encode('latin-1'))
                    else:
                        f.write(bytes(vs_dxbc))
                exported_shaders.append({
                    "type": "vertex_dxbc",
                    "file": os.path.basename(vs_dxbc_file)
                })
                
            
            # 尝试通过 API 获取 DXIL
            dxil_result = export_shader_il(program, "vertex", "dxil", output_dir, program_id_hex)
            if dxil_result:
                exported_shaders.append(dxil_result)
            elif vs_info.get("dxil", ""):
                # 回退：使用描述中的 DXIL
                vs_dxil = vs_info.get("dxil", "")
                vs_dxil_file = os.path.join(output_dir, f"vs_{program_id_hex}.dxil")
                with open(vs_dxil_file, 'wb') as f:
                    if isinstance(vs_dxil, str):
                        f.write(vs_dxil.encode('utf-8'))
                    else:
                        f.write(bytes(vs_dxil))
                exported_shaders.append({
                    "type": "vertex_dxil",
                    "file": os.path.basename(vs_dxil_file)
                })
            
        
        # 导出 Pixel Shader (像素着色器)
        if "pixel" in program_desc:
            ps_info = program_desc["pixel"]
            ps_source = ps_info.get("source", "")
            ps_hash = ps_info.get("hash", "")
            
            if ps_source:
                ps_file = os.path.join(output_dir, f"ps_{program_id_hex}.hlsl")
                with open(ps_file, 'w', encoding='utf-8') as f:
                    f.write(f"//==============================================================================\n")
                    f.write(f"// 像素着色器 (Pixel Shader)\n")
                    f.write(f"//==============================================================================\n")
                    f.write(f"// 程序 ID: {program_id} (0x{program_id_hex})\n")
                    if ps_hash:
                        f.write(f"// 哈希值: {ps_hash}\n")
                    f.write(f"// 事件索引: {event_index}\n")
                    f.write(f"//\n")
                    f.write(f"// 功能说明:\n")
                    f.write(f"//   像素着色器负责计算每个像素的最终颜色，包括:\n")
                    f.write(f"//   - 纹理采样和混合\n")
                    f.write(f"//   - 光照计算\n")
                    f.write(f"//   - 材质效果处理\n")
                    f.write(f"//   - 输出最终像素颜色\n")
                    f.write(f"//==============================================================================\n\n")
                    f.write(ps_source)
                exported_shaders.append({
                    "type": "pixel",
                    "file": os.path.basename(ps_file)
                })
            
            # 尝试导出 DXBC (DX11)
            ps_dxbc = ps_info.get("dxbc", "")
            if ps_dxbc:
                ps_dxbc_file = os.path.join(output_dir, f"ps_{program_id_hex}.dxbc")
                with open(ps_dxbc_file, 'wb') as f:
                    if isinstance(ps_dxbc, str):
                        f.write(ps_dxbc.encode('latin-1'))
                    else:
                        f.write(bytes(ps_dxbc))
                exported_shaders.append({
                    "type": "pixel_dxbc",
                    "file": os.path.basename(ps_dxbc_file)
                })
            
            # 从 PS DXBC 中解析纹理绑定并输出到 JSON
            ps_textures = parse_texture_bindings_from_dxbc(ps_dxbc)
            if ps_textures:
                texture_bindings_file = os.path.join(output_dir, f"ps_texture_bindings_{program_id_hex}.json")
                with open(texture_bindings_file, 'w', encoding='utf-8') as f:
                    texture_bindings_data = {
                        "program_id": program_id,
                        "program_id_hex": program_id_hex,
                        "shader_type": "pixel",
                        "event_index": event_index,
                        "texture_count": len(ps_textures),
                        "textures": ps_textures
                    }
                    json.dump(texture_bindings_data, f, indent=2, ensure_ascii=False)
                exported_shaders.append({
                    "type": "ps_texture_bindings",
                    "file": os.path.basename(texture_bindings_file)
                })
                messages.debug(f"已导出 PS 纹理绑定: {len(ps_textures)} 个纹理")
            
            # 尝试通过 API 获取 DXIL
            dxil_result = export_shader_il(program, "pixel", "dxil", output_dir, program_id_hex)
            if dxil_result:
                exported_shaders.append(dxil_result)
            elif ps_info.get("dxil", ""):
                # 回退：使用描述中的 DXIL
                ps_dxil = ps_info.get("dxil", "")
                ps_dxil_file = os.path.join(output_dir, f"ps_{program_id_hex}.dxil")
                with open(ps_dxil_file, 'wb') as f:
                    if isinstance(ps_dxil, str):
                        f.write(ps_dxil.encode('utf-8'))
                    else:
                        f.write(bytes(ps_dxil))
                exported_shaders.append({
                    "type": "pixel_dxil",
                    "file": os.path.basename(ps_dxil_file)
                })
            
        
        # shader_info 文件已取消输出，shader 信息在 vs/ps dxbc 文件中包含
        
    except Exception as e:
        messages.debug(f"导出 shader 失败 (event {event_index}): {str(e)}")
    
    return exported_shaders


def export_mesh_from_buffers(resources_accessor, ibv_resource, vbv_resources, call, output_dir, event_index, call_desc, skeleton_data=None, cbv_resources=None, enable_skinning=True, skeleton_cbv_info=None, indirect_args=None):
    """
    使用 IBV (Index Buffer View) 和 VBV (Vertex Buffer View) 资源生成 mesh
    支持蒙皮计算 (当提供骨骼数据且 enable_skinning=True 时)
    
    参数:
        ibv_resource: IBV 类型的缓冲区资源
        vbv_resources: VBV 类型的缓冲区资源列表
        call: API 调用对象
        output_dir: 输出目录
        event_index: 事件索引
        call_desc: 调用描述
        skeleton_data: 骨骼矩阵数据 (float4 数组)，可选
        cbv_resources: CBV 类型的缓冲区资源列表，用于提取骨骼数据
        skeleton_cbv_info: 骨骼数据的CBV信息 {"resource_id": int, "view_id": int}，从cbv_bindings中获取
        indirect_args: DrawIndexedInstancedIndirect 的参数 (从 args buffer 解析)，可选
                       包含: IndexCountPerInstance, InstanceCount, StartIndexLocation, 
                             BaseVertexLocation, StartInstanceLocation
    """
    try:
        if not ibv_resource or not vbv_resources:
            return None
        
        # 获取绘制调用参数
        # 如果提供了 indirect_args，优先使用 indirect_args 中的参数
        if indirect_args:
            index_count = indirect_args.get("IndexCountPerInstance", 0)
            start_index_location = indirect_args.get("StartIndexLocation", 0)
            base_vertex_location = indirect_args.get("BaseVertexLocation", 0)
            messages.debug(f"使用 Indirect Args: IndexCount={index_count}, StartIndex={start_index_location}, BaseVertex={base_vertex_location}")
        else:
            index_count, start_index_location, base_vertex_location = get_draw_call_params(call_desc)
        
        # ==================== 先读取索引数据，计算实际 vertex_count ====================
        ibv_request = BufferRequest(
            buffer=ibv_resource,
            call=call,
            extract_before=False
        )
        
        ibv_result = resources_accessor.get_buffers_data([ibv_request], timeout=30000)
        
        if ibv_request not in ibv_result:
            return None
        
        index_data = ibv_result[ibv_request].data
        ibv_desc = ibv_resource.get_description()
        index_stride = ibv_desc.get("stride", 2)
        # 如果不是 4 则必为 2
        if index_stride != 4:
            index_stride = 2
        
        all_indices = []
        index_bytes = bytes(index_data)
        
        if index_stride == 4:
            num_indices = len(index_bytes) // 4
            for i in range(num_indices):
                idx = struct.unpack_from('<I', index_bytes, i * 4)[0]
                all_indices.append(idx)
        else:
            num_indices = len(index_bytes) // 2
            for i in range(num_indices):
                idx = struct.unpack_from('<H', index_bytes, i * 2)[0]
                all_indices.append(idx)
        
        # 根据 index_count 和 start_index_location 提取使用的索引
        if all_indices and index_count > 0:
            end_index = start_index_location + index_count
            used_indices = all_indices[start_index_location:end_index]
        elif all_indices:
            used_indices = all_indices
        else:
            used_indices = []
        
        if not used_indices:
            return None
        
            # 计算实际使用的最大顶点索引 (加上 base_vertex_location)
        # 实际顶点索引 = index_buffer[i] + base_vertex_location
        max_vertex_index = max(used_indices) + base_vertex_location
        vertex_count = max_vertex_index + 1
        
        messages.debug(f"索引范围: index_count={index_count}, max_index={max(used_indices)}, base_vertex={base_vertex_location}, vertex_count={vertex_count}")
        
        # ==================== 查找顶点缓冲区 ====================
        # 查找主顶点缓冲区（stride >= 24）和骨骼权重缓冲区（stride = 8）
        main_vbv = None
        main_stride = 0
        bone_vbv = None  # stride=8 的骨骼索引/权重缓冲区
        
        for vbv in vbv_resources:
            vbv_desc = vbv.get_description()
            vbv_stride = vbv_desc.get("stride", 0)
            
            if vbv_stride == 8:
                # 骨骼索引和权重缓冲区
                bone_vbv = vbv
            elif vbv_stride >= 24 and vbv_stride > main_stride:
                main_vbv = vbv
                main_stride = vbv_stride
        
        if not main_vbv:
            # 如果没有 stride >= 24 的，使用第一个非骨骼 VBV
            for vbv in vbv_resources:
                vbv_stride = vbv.get_description().get("stride", 0)
                if vbv_stride != 8:
                    main_vbv = vbv
                    main_stride = vbv_stride
                    break
            
            if not main_vbv:
                return None
        
        # 读取顶点数据
        vbv_request = BufferRequest(
            buffer=main_vbv,
            call=call,
            extract_before=False
        )
        
        vbv_result = resources_accessor.get_buffers_data([vbv_request], timeout=30000)
        
        if vbv_request not in vbv_result:
            return None
        
        vertex_data = vbv_result[vbv_request].data
        buffer_vertex_count = len(vertex_data) // main_stride if main_stride > 0 else 0
        
        # 使用实际需要的顶点数量，不超过缓冲区中的顶点数
        actual_vertex_count = min(vertex_count, buffer_vertex_count)
        messages.debug(f"顶点数量: 需要={vertex_count}, 缓冲区={buffer_vertex_count}, 实际={actual_vertex_count}")
        
        # 解析顶点数据（只解析需要的数量）
        if main_stride >= 24:
            all_positions, all_normals, all_texcoords = parse_vertex_data_by_stride(
                vertex_data, main_stride, actual_vertex_count
            )
        else:
            all_positions = []
            all_normals = []
            all_texcoords = []
            data_bytes = bytes(vertex_data)
            for i in range(actual_vertex_count):
                offset = i * main_stride
                if offset + 12 <= len(data_bytes):
                    x, y, z = struct.unpack_from('<fff', data_bytes, offset)
                    all_positions.append((x, y, z))
        
        if not all_positions:
            return None
        
        # ==================== 蒙皮计算 ====================
        skinning_applied = False
        bone_indices_list = None
        bone_weights_list = None
        
        # 只有当 enable_skinning=True 时才进行蒙皮计算
        if enable_skinning:
            # 尝试从 CBV 获取骨骼矩阵数据
            if skeleton_data is None and cbv_resources:
                target_cbv = None
                
                if skeleton_cbv_info:
                    # 使用 cbv_bindings 中的 Skeleton 信息匹配
                    skeleton_resource_id = skeleton_cbv_info.get("resource_id", -1)
                    skeleton_view_id = skeleton_cbv_info.get("view_id", -1)
                    
                    for cbv in cbv_resources:
                        cbv_desc = cbv.get_description()
                        cbv_res_id = cbv_desc.get("resource_id", -1)
                        cbv_view_id = cbv_desc.get("view_id", -1)
                        
                        if cbv_res_id == skeleton_resource_id and cbv_view_id == skeleton_view_id:
                            target_cbv = cbv
                            messages.debug(f"找到骨骼数据 CBV (Skeleton): resource_id={skeleton_resource_id}, view_id={skeleton_view_id}")
                            break
                    
                    if target_cbv is None:
                        messages.debug(f"警告: 未找到匹配的骨骼数据 CBV (resource_id={skeleton_resource_id}, view_id={skeleton_view_id})")
                else:
                    messages.debug("警告: 未提供 skeleton_cbv_info，无法定位骨骼数据")
                
                # 提取骨骼数据
                if target_cbv:
                    try:
                        cbv_desc = target_cbv.get_description()
                        cbv_size = cbv_desc.get("size", 0)
                        cbv_res_id = cbv_desc.get("resource_id", -1)
                        cbv_request = BufferRequest(
                            buffer=target_cbv,
                            call=call,
                            extract_before=False
                        )
                        cbv_result = resources_accessor.get_buffers_data([cbv_request], timeout=30000)
                        
                        if cbv_request in cbv_result:
                            cbv_data = cbv_result[cbv_request].data
                            skeleton_data = parse_skeleton_data(cbv_data, 0)
                            messages.debug(f"从 CBV 提取骨骼数据: resource_id={cbv_res_id}, size={cbv_size}, {len(skeleton_data)} 个 float4")
                    except Exception as e:
                        messages.debug(f"提取骨骼数据失败: {str(e)}")
            
            # 读取骨骼索引和权重（只读取需要的顶点数量）
            if bone_vbv and skeleton_data:
                try:
                    bone_request = BufferRequest(
                        buffer=bone_vbv,
                        call=call,
                        extract_before=False
                    )
                    bone_result = resources_accessor.get_buffers_data([bone_request], timeout=30000)
                    
                    if bone_request in bone_result:
                        bone_data = bone_result[bone_request].data
                        bone_indices_list, bone_weights_list = parse_bone_weights_data(bone_data, actual_vertex_count)
                        messages.debug(f"解析骨骼权重: {len(bone_indices_list)} 个顶点 (限制到 {actual_vertex_count})")
                except Exception as e:
                    messages.debug(f"读取骨骼权重失败: {str(e)}")
            
            # 应用蒙皮变换
            if skeleton_data and bone_indices_list and bone_weights_list:
                try:
                    all_positions, all_normals = apply_skinning(
                        all_positions, all_normals,
                        bone_indices_list, bone_weights_list,
                        skeleton_data,
                        row_major=True,  # 行优先存储（默认）
                        output_dir=output_dir,
                        debug_output=False  # 设置为 True 可输出 bone.json 调试文件
                    )
                    skinning_applied = True
                    messages.debug(f"蒙皮计算完成: {len(all_positions)} 个顶点")
                except Exception as e:
                    messages.debug(f"蒙皮计算失败: {str(e)}")
        # ==================== 蒙皮计算结束 ====================
        
        has_normals = len(all_normals) > 0
        has_texcoords = len(all_texcoords) > 0
        
        # 应用 BaseVertexLocation 并提取使用的顶点
        adjusted_indices = [idx + base_vertex_location for idx in used_indices]
        unique_vertex_indices = sorted(set(adjusted_indices))
        
        # 过滤超出范围的索引
        valid_vertex_indices = [idx for idx in unique_vertex_indices if 0 <= idx < len(all_positions)]
        
        if not valid_vertex_indices:
            messages.debug(f"没有有效的顶点索引")
            return None
        
        index_map = {old_idx: new_idx for new_idx, old_idx in enumerate(valid_vertex_indices)}
            
        positions = []
        normals = []
        texcoords = []
        
        # 使用 valid_vertex_indices 提取顶点数据（已过滤超出范围的索引）
        for old_idx in valid_vertex_indices:
            positions.append(all_positions[old_idx])
            
            if has_normals and old_idx < len(all_normals):
                normals.append(all_normals[old_idx])
            elif has_normals:
                normals.append((127.5, 127.5, 255.0))  # 默认法线 (0-255 范围)
            
            if has_texcoords and old_idx < len(all_texcoords):
                texcoords.append(all_texcoords[old_idx])
            elif has_texcoords:
                texcoords.append((0.0, 0.0))
        
        # 重新映射索引，跳过无效索引
        indices = []
        for idx in used_indices:
            adjusted_idx = idx + base_vertex_location
            if adjusted_idx in index_map:
                indices.append(index_map[adjusted_idx])
        
        if not positions:
            return None
        
        # 写入 OBJ 文件
        obj_file = os.path.join(output_dir, f"g_{event_index}.obj")
        
        with open(obj_file, 'w') as f:
            f.write(f"# Exported from Intel GPA (IBV/VBV)\n")
            f.write(f"# Event Index: {event_index}\n")
            f.write(f"# Stride: {main_stride}\n")
            f.write(f"# IndexCount: {index_count}, StartIndexLocation: {start_index_location}, BaseVertexLocation: {base_vertex_location}\n")
            f.write(f"# VertexCount: {vertex_count} (max_index={max(used_indices) if used_indices else 0} + base={base_vertex_location} + 1)\n")
            f.write(f"# Exported Vertices: {len(positions)}, Triangles: {len(indices) // 3 if indices else len(positions) // 3}\n")
            f.write(f"# Has Normals: {has_normals}, Has UVs: {has_texcoords}\n")
            f.write(f"# Skinning Applied: {skinning_applied}\n")
            if skinning_applied:
                f.write(f"# Skeleton Data: {len(skeleton_data) if skeleton_data else 0} float4s\n")
            f.write("\n")
            
            for v in positions:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            
            f.write("\n")
            
            if texcoords:
                for uv in texcoords:
                    f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
                f.write("\n")
            
            if normals:
                for n in normals:
                    # 将 0-255 范围转换为 -1 到 1 范围用于 OBJ
                    nx = (n[0] / 255.0) * 2.0 - 1.0
                    ny = (n[1] / 255.0) * 2.0 - 1.0
                    nz = (n[2] / 255.0) * 2.0 - 1.0
                    f.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
                f.write("\n")
            
            # 交换 i1/i2 将 D3D CW 环绕转为 OBJ CCW 环绕
            if indices:
                for i in range(0, len(indices) - 2, 3):
                    i0 = indices[i] + 1
                    i1 = indices[i + 1] + 1
                    i2 = indices[i + 2] + 1
                    
                    if has_texcoords and has_normals:
                        f.write(f"f {i0}/{i0}/{i0} {i2}/{i2}/{i2} {i1}/{i1}/{i1}\n")
                    elif has_texcoords:
                        f.write(f"f {i0}/{i0} {i2}/{i2} {i1}/{i1}\n")
                    elif has_normals:
                        f.write(f"f {i0}//{i0} {i2}//{i2} {i1}//{i1}\n")
                    else:
                        f.write(f"f {i0} {i2} {i1}\n")
            else:
                for i in range(0, len(positions) - 2, 3):
                    i0 = i + 1
                    i1 = i + 2
                    i2 = i + 3
                    
                    if has_texcoords and has_normals:
                        f.write(f"f {i0}/{i0}/{i0} {i2}/{i2}/{i2} {i1}/{i1}/{i1}\n")
                    elif has_texcoords:
                        f.write(f"f {i0}/{i0} {i2}/{i2} {i1}/{i1}\n")
                    elif has_normals:
                        f.write(f"f {i0}//{i0} {i2}//{i2} {i1}//{i1}\n")
                    else:
                        f.write(f"f {i0} {i2} {i1}\n")
        
        return obj_file
        
    except Exception as e:
        messages.debug(f"从 IBV/VBV 导出 mesh 失败 (event {event_index}): {str(e)}")
        return None


def find_ps_set_shader_resources_before_event(all_calls, target_call):
    """
    查找目标event之前、上一个event之后的所有PSSetShaderResources调用
    
    参数:
        all_calls: 所有calls列表
        target_call: 目标event的call对象
    
    返回:
        PSSetShaderResources调用列表
    """
    ps_set_srv_calls = []
    
    # 找到target_call在all_calls中的位置
    target_idx = -1
    for i, c in enumerate(all_calls):
        if c == target_call:
            target_idx = i
            break
    
    if target_idx <= 0:
        return ps_set_srv_calls
    
    # 从target_call往前遍历，直到遇到上一个event
    for i in range(target_idx - 1, -1, -1):
        c = all_calls[i]
        desc = c.get_description()
        name = desc.get('name', '')
        
        if desc.get('is_event', False):
            # 遇到上一个event，停止
            break
        
        if name == 'PSSetShaderResources':
            ps_set_srv_calls.insert(0, c)  # 保持顺序
    
    return ps_set_srv_calls


def build_resource_id_to_slot_map(ps_set_srv_calls):
    """
    从PSSetShaderResources调用中提取ppShaderResourceViews，
    建立 resource_id -> slot_index 的映射
    
    参数:
        ps_set_srv_calls: PSSetShaderResources调用列表
    
    返回:
        dict: resource_id -> slot_index 映射
    """
    resource_id_to_slot = {}
    
    for call in ps_set_srv_calls:
        desc = call.get_description()
        arguments = desc.get('arguments', [])
        
        # 获取 StartSlot 参数
        start_slot = 0
        for arg in arguments:
            if arg.get('name') == 'StartSlot':
                start_slot = arg.get('value', 0)
                break
        
        # 获取 ppShaderResourceViews 参数
        for arg in arguments:
            if arg.get('name') == 'ppShaderResourceViews':
                views = arg.get('value', [])
                if isinstance(views, list):
                    for idx, view in enumerate(views):
                        # view 是 {"name": "ppShaderResourceViews", "type": "uint32_t", "value": 989}
                        if isinstance(view, dict):
                            res_id = view.get('value', 0)
                            if res_id and res_id != 0:
                                slot_index = start_slot + idx
                                resource_id_to_slot[res_id] = slot_index
                break
    
    return resource_id_to_slot


def build_resource_id_to_dxbc_name_map(resource_id_to_slot, dxbc_texture_map):
    """
    结合 resource_id -> slot 和 slot -> dxbc_name 映射，
    建立 resource_id -> dxbc_name 的映射
    
    参数:
        resource_id_to_slot: resource_id -> slot_index 映射
        dxbc_texture_map: slot_index -> dxbc_name 映射
    
    返回:
        dict: resource_id -> dxbc_name 映射
    """
    resource_id_to_name = {}
    
    for res_id, slot_index in resource_id_to_slot.items():
        if slot_index in dxbc_texture_map:
            resource_id_to_name[res_id] = dxbc_texture_map[slot_index]
    
    return resource_id_to_name


def parse_cbuffer_bindings_from_dxbc(dxbc_source):
    """
    从 DXBC 反汇编文本中解析 Resource Bindings，
    提取 type 为 cbuffer 的内容
    
    解析格式:
    // Name                                 Type  Format         Dim      HLSL Bind  Count
    // ------------------------------ ---------- ------- ----------- -------------- ------
    // cbPerFrame                         cbuffer      NA          NA            cb0      1
    
    返回:
        [{"name": "cbPerFrame", "slot": "cb0", "slot_index": 0}]
    """
    import re
    
    cbuffers = []
    
    if not dxbc_source:
        return cbuffers
    
    # 确保是字符串
    if isinstance(dxbc_source, bytes):
        try:
            dxbc_source = dxbc_source.decode('utf-8', errors='ignore')
        except:
            dxbc_source = dxbc_source.decode('latin-1', errors='ignore')
    
    # 逐行解析
    in_bindings_section = False
    header_found = False
    
    lines = dxbc_source.split('\n')
    for line_num, line in enumerate(lines):
        line = line.strip()
        
        # 检测 Resource Bindings 部分开始
        if "Resource Bindings:" in line:
            in_bindings_section = True
            continue
        
        # 检测表头行
        if in_bindings_section and "Name" in line and "HLSL Bind" in line:
            header_found = True
            continue
        
        # 检测分隔线（跳过）
        if in_bindings_section and "// ---" in line:
            continue
        
        # 检测绑定部分结束
        if in_bindings_section and header_found:
            if not line or (not line.startswith("//")):
                in_bindings_section = False
                continue
            
            if line == "//":
                in_bindings_section = False
                continue
            
            # 解析资源绑定行
            if line.startswith("//"):
                content = line[2:].strip()
                
                # 使用正则匹配: Name Type Format Dim Bind Count
                match = re.match(r'(\S+)\s+(texture|sampler|cbuffer|UAV)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)', content)
                if match:
                    name, res_type, fmt, dim, bind, count = match.groups()
                    
                    # 只提取 cbuffer 类型
                    if res_type == "cbuffer":
                        try:
                            # "cb0" -> 0
                            slot_index = int(bind[2:]) if bind.startswith("cb") else -1
                            cbuffer_info = {
                                "name": name,
                                "slot": bind,
                                "slot_index": slot_index
                            }
                            cbuffers.append(cbuffer_info)
                            messages.debug(f"[DXBC 解析] 找到 cbuffer {name} -> {bind}")
                        except ValueError:
                            pass
    
    return cbuffers


def find_vs_set_constant_buffers_before_event(all_calls, target_call):
    """
    查找目标event之前、上一个event之后的所有VSSetConstantBuffers调用
    
    参数:
        all_calls: 所有calls列表
        target_call: 目标event的call对象
    
    返回:
        VSSetConstantBuffers调用列表
    """
    vs_set_cb_calls = []
    
    # 找到target_call在all_calls中的位置
    target_idx = -1
    for i, c in enumerate(all_calls):
        if c == target_call:
            target_idx = i
            break
    
    if target_idx <= 0:
        messages.debug(f"未找到目标 event 在 all_calls 中的位置")
        return vs_set_cb_calls
    
    # 从target_call往前遍历，直到遇到上一个event
    for i in range(target_idx - 1, -1, -1):
        c = all_calls[i]
        desc = c.get_description()
        name = desc.get('name', '')
        
        if desc.get('is_event', False):
            # 遇到上一个event，停止
            break
        
        if name.startswith('VSSetConstantBuffers'):
            vs_set_cb_calls.insert(0, c)  # 保持顺序
    
    if not vs_set_cb_calls:
        messages.debug(f"未找到 VSSetConstantBuffers 调用（event index: {target_idx}）")
    
    return vs_set_cb_calls


def build_cbv_slot_bindings(vs_set_cb_calls):
    """
    从VSSetConstantBuffers调用中提取ppConstantBuffers，
    建立 slot 绑定列表（按顺序记录）
    
    注意: ppConstantBuffers 中的值是 resource_id
    每个 VSSetConstantBuffers 调用的每个条目只对应一个 slot
    
    参数:
        vs_set_cb_calls: VSSetConstantBuffers调用列表
    
    返回:
        list: [{"slot_index": int, "resource_id": int}, ...]
    """
    slot_bindings = []
    
    for call in vs_set_cb_calls:
        desc = call.get_description()
        arguments = desc.get('arguments', [])
        
        # 获取 StartSlot 参数
        start_slot = 0
        for arg in arguments:
            if arg.get('name') == 'StartSlot':
                start_slot = arg.get('value', 0)
                break
        
        # 获取 ppConstantBuffers 参数（值是 resource_id）
        for arg in arguments:
            if arg.get('name') == 'ppConstantBuffers':
                buffers = arg.get('value', [])
                if isinstance(buffers, list):
                    for idx, buf in enumerate(buffers):
                        if isinstance(buf, dict):
                            resource_id = buf.get('value', 0)
                            if resource_id and resource_id != 0:
                                slot_index = start_slot + idx
                                slot_bindings.append({
                                    "slot_index": slot_index,
                                    "resource_id": resource_id
                                })
                break
    
    return slot_bindings


# =============================================================================
# Stage functions — 每个 Stage 负责 run() 主流程中的一个独立阶段
# =============================================================================

def _stage_init_session(min_call, max_call, enable_skinning):
    """
    Stage 0 — 初始化导出会话
    
    获取 API 访问器，筛选事件列表，创建输出目录。
    返回一个 session 上下文字典，贯穿后续所有 Stage。
    """
    messages.info("=" * 60)
    messages.info("easy_output 插件开始执行")
    messages.info(f"函数: run(min_call={min_call}, max_call={max_call}, enable_skinning={enable_skinning})")
    messages.info("=" * 60)

    api_log = plugin_api.get_api_log_accessor()
    resources_accessor = plugin_api.get_resources_accessor()
    all_calls = list(common.all_calls_from_node(api_log.get_calls()))

    # 筛选事件
    filtered_calls = [c for c in all_calls if c.get_description().get('is_event', False)]

    start_idx = max(0, min_call - 1)
    if max_call >= 1:
        filtered_calls = filtered_calls[start_idx:max_call]
    else:
        filtered_calls = filtered_calls[start_idx:]

    # 输出目录
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    frame_name = get_frame_name()
    if frame_name:
        safe_frame_name = "".join(c for c in frame_name if c.isalnum() or c in "_-.")
        if safe_frame_name.lower().endswith(".gpa_frame"):
            safe_frame_name = safe_frame_name[:-10]
        folder_name = f"{safe_frame_name}_{timestamp}"
        messages.debug(f"Frame 名称: {frame_name} -> 文件夹: {folder_name}")
    else:
        folder_name = timestamp
        messages.debug(f"未获取到 Frame 名称，使用时间戳: {folder_name}")

    resources_dir = os.path.join(plugin_dir, "resources", folder_name)
    if not os.path.exists(resources_dir):
        os.makedirs(resources_dir)

    return {
        "api_log": api_log,
        "resources_accessor": resources_accessor,
        "all_calls": all_calls,
        "filtered_calls": filtered_calls,
        "resources_dir": resources_dir,
        "min_call": min_call,
        "max_call": max_call,
        "enable_skinning": enable_skinning,
        "output_data": {
            "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filter": {"min_call": min_call, "max_call": max_call},
            "total_count": len(filtered_calls),
            "events": []
        },
        "counters": {
            "textures": 0,
            "buffers": 0,
            "meshes": 0,
            "shaders": 0
        }
    }


def _stage_build_ps_texture_map(bindings, all_calls, call):
    """
    Stage 1 — 解析 PS 纹理绑定
    
    1) 从 PS DXBC 解析 slot → name 映射  (如 0 → "tBaseMap")
    2) 从 PSSetShaderResources 解析 resource_id → slot 映射
    3) 合并得到 resource_id → dxbc_name 映射
    
    返回: (dxbc_texture_map, resource_id_to_dxbc_name, texture_binding_list)
    """
    dxbc_texture_map = {}
    resource_id_to_dxbc_name = {}
    texture_binding_list = []

    program_desc = _get_program_desc(bindings)
    if not program_desc:
        return dxbc_texture_map, resource_id_to_dxbc_name, texture_binding_list

    # Step 1: 解析 PS DXBC → slot_index → name
    ps_dxbc = program_desc.get("pixel", {}).get("dxbc", "")
    if ps_dxbc:
        for tex in parse_texture_bindings_from_dxbc(ps_dxbc):
            slot, name = tex.get("slot", ""), tex.get("name", "")
            if slot.startswith("t") and name:
                try:
                    dxbc_texture_map[int(slot[1:])] = name
                except ValueError:
                    pass
        if dxbc_texture_map:
            messages.debug(f"DXBC slot->name 映射: {dxbc_texture_map}")

    if not dxbc_texture_map:
        return dxbc_texture_map, resource_id_to_dxbc_name, texture_binding_list

    # Step 2: PSSetShaderResources → resource_id → slot
    ps_set_srv_calls = find_ps_set_shader_resources_before_event(all_calls, call)
    if not ps_set_srv_calls:
        return dxbc_texture_map, resource_id_to_dxbc_name, texture_binding_list

    resource_id_to_slot = build_resource_id_to_slot_map(ps_set_srv_calls)
    if not resource_id_to_slot:
        return dxbc_texture_map, resource_id_to_dxbc_name, texture_binding_list

    messages.debug(f"PSSetShaderResources resource_id->slot 映射: {resource_id_to_slot}")

    # Step 3: 合并 → resource_id → dxbc_name
    resource_id_to_dxbc_name = build_resource_id_to_dxbc_name_map(
        resource_id_to_slot, dxbc_texture_map
    )
    if resource_id_to_dxbc_name:
        messages.debug(f"最终 resource_id->dxbc_name 映射: {resource_id_to_dxbc_name}")
        for res_id, dxbc_name in resource_id_to_dxbc_name.items():
            slot = resource_id_to_slot.get(res_id, -1)
            texture_binding_list.append({
                "resource_id": res_id,
                "resource_id_hex": f"{res_id:X}",
                "slot": f"t{slot}" if slot >= 0 else "",
                "slot_index": slot,
                "dxbc_name": dxbc_name
            })

    return dxbc_texture_map, resource_id_to_dxbc_name, texture_binding_list


def _stage_build_vs_cbv_map(bindings, all_calls, call, event_dir):
    """
    Stage 2 — 解析 VS CBV 绑定
    
    1) 从 VS DXBC 解析 cbuffer slot → name 映射
    2) 从 VSSetConstantBuffers 解析 slot 绑定
    3) 与 inputs 中的 CBV 详情交叉匹配
    4) 输出 vs_cbv_bindings_{program_id_hex}.json
    5) 查找 Skeleton CBV 信息
    
    返回: (cbv_bindings, skeleton_cbv_info)
    """
    cbv_bindings = []
    skeleton_cbv_info = None

    program_desc = _get_program_desc(bindings)
    if not program_desc:
        return cbv_bindings, skeleton_cbv_info

    vs_info = program_desc.get("vertex", {})
    vs_dxbc = vs_info.get("dxbc", "")
    if not vs_dxbc:
        return cbv_bindings, skeleton_cbv_info

    # Step 1: VS DXBC → slot_index → name
    dxbc_cbuffer_map = {}
    for cb in parse_cbuffer_bindings_from_dxbc(vs_dxbc):
        slot_index = cb.get("slot_index", -1)
        name = cb.get("name", "")
        if slot_index >= 0 and name:
            dxbc_cbuffer_map[slot_index] = name

    if not dxbc_cbuffer_map:
        return cbv_bindings, skeleton_cbv_info
    messages.debug(f"VS DXBC cbuffer slot->name 映射: {dxbc_cbuffer_map}")

    # Step 2: VSSetConstantBuffers → slot 绑定列表
    vs_set_cb_calls = find_vs_set_constant_buffers_before_event(all_calls, call)
    if not vs_set_cb_calls:
        return cbv_bindings, skeleton_cbv_info

    slot_bindings = build_cbv_slot_bindings(vs_set_cb_calls)
    if not slot_bindings:
        return cbv_bindings, skeleton_cbv_info
    messages.debug(f"VSSetConstantBuffers slot绑定: {slot_bindings}")

    # Step 3: 从 inputs 收集 CBV 详情，按 resource_id 分组
    cbv_by_resource_id = {}
    for res in bindings.get("inputs", []):
        res_desc = res.get_description()
        if res_desc.get("view_type") != "CBV":
            continue
        res_id = res_desc.get("resource_id")
        cbv_by_resource_id.setdefault(res_id, []).append({
            "view_id": res_desc.get("view_id", 0),
            "offset": res_desc.get("offset", 0),
            "stride": res_desc.get("stride", 0),
            "size": res_desc.get("size", 0),
            "resource_type": res_desc.get("resource_type", "buffer")
        })
    messages.debug(f"CBV resource_id->详情列表: {cbv_by_resource_id}")

    # Step 4: 合并 slot_bindings + cbv_by_resource_id → cbv_bindings
    consumed = {}  # resource_id → 已消耗的 view 索引
    for binding in slot_bindings:
        slot_index = binding["slot_index"]
        resource_id = binding["resource_id"]
        dxbc_name = dxbc_cbuffer_map.get(slot_index, "")

        cbv_list = cbv_by_resource_id.get(resource_id, [])
        ci = consumed.get(resource_id, 0)
        cbv_detail = cbv_list[ci] if ci < len(cbv_list) else {}
        consumed[resource_id] = ci + 1

        view_id = cbv_detail.get("view_id", 0)
        cbv_bindings.append({
            "slot": f"cb{slot_index}",
            "slot_index": slot_index,
            "dxbc_name": dxbc_name,
            "resource_id": resource_id,
            "resource_id_hex": f"{resource_id:X}" if resource_id else "",
            "view_id": view_id,
            "view_id_hex": f"{view_id:X}" if view_id else "",
            "offset": cbv_detail.get("offset", 0),
            "stride": cbv_detail.get("stride", 0),
            "size": cbv_detail.get("size", 0),
            "resource_type": cbv_detail.get("resource_type", "buffer")
        })

    # Step 5: 输出 JSON
    vs_program_id = vs_info.get("hash", "") or program_desc.get("id", "unknown")
    vs_program_id_hex = f"{vs_program_id:X}" if isinstance(vs_program_id, int) else str(vs_program_id)
    vs_cbv_json_file = os.path.join(event_dir, f"vs_cbv_bindings_{vs_program_id_hex}.json")
    with open(vs_cbv_json_file, 'w', encoding='utf-8') as f:
        json.dump({
            "program_id": vs_program_id,
            "program_id_hex": vs_program_id_hex,
            "dxbc_cbuffer_map": dxbc_cbuffer_map,
            "cbv_bindings": cbv_bindings
        }, f, indent=2, ensure_ascii=False)
    messages.debug(f"VS CBV 绑定映射已保存到: {vs_cbv_json_file}")

    # Step 6: 查找 Skeleton
    for b in cbv_bindings:
        if b.get("dxbc_name") == "Skeleton":
            skeleton_cbv_info = {"resource_id": b["resource_id"], "view_id": b["view_id"]}
            messages.debug(f"找到 Skeleton CBV: resource_id={skeleton_cbv_info['resource_id']}, view_id={skeleton_cbv_info['view_id']}")
            break

    return cbv_bindings, skeleton_cbv_info


def _stage_classify_inputs(bindings):
    """
    Stage 3 — 分类输入资源
    
    将 bindings["inputs"] 分为:
      - srv_textures : view_id==0 的 SRV 纹理（用于 DXBC 命名导出）
      - other_inputs : 其余所有输入资源
    
    返回: (srv_textures, other_inputs)
    """
    srv_textures = []
    other_inputs = []

    for res in bindings.get("inputs", []):
        desc = res.get_description()
        vt = desc.get("view_type", "")
        rt = desc.get("resource_type", "")
        vid = desc.get("view_id", -1)

        if vt == "SRV" and rt == "texture" and vid == 0:
            srv_textures.append(res)
        else:
            other_inputs.append(res)

    return srv_textures, other_inputs


def _stage_export_textures(resources_accessor, srv_textures, call, event_dir,
                           resource_id_to_dxbc_name, dxbc_texture_map):
    """
    Stage 4 — 导出 SRV 纹理
    
    使用 resource_id → dxbc_name 映射为纹理文件命名。
    
    返回: (exported_list, count)
    """
    exported = []
    count = 0

    for tex_idx, res in enumerate(srv_textures):
        res_desc = res.get_description()
        res_id = res_desc.get("resource_id")
        res_id_str = str(res_id)

        dxbc_name = ""
        dxbc_slot = -1
        if res_id in resource_id_to_dxbc_name:
            dxbc_name = resource_id_to_dxbc_name[res_id]
            for slot_idx, name in dxbc_texture_map.items():
                if name == dxbc_name:
                    dxbc_slot = slot_idx
                    break
            messages.debug(f"资源 {res_id} 通过 PSSetShaderResources 映射到 {dxbc_name} (t{dxbc_slot})")

        tex_file = export_texture(
            resources_accessor, res, call, event_dir, res_id_str, dxbc_name=dxbc_name
        )
        if tex_file:
            exported.append({
                "type": "input",
                "resource_id": res_id_str,
                "dxbc_name": dxbc_name,
                "dxbc_slot": f"t{dxbc_slot}" if dxbc_slot >= 0 else "",
                "order_index": tex_idx,
                "file": os.path.basename(tex_file)
            })
            count += 1

    return exported, count


def _stage_export_other_inputs(resources_accessor, other_inputs, call, event_dir):
    """
    Stage 5 — 导出非 SRV 输入资源，并收集 IBV / VBV / CBV
    
    返回: (exported_textures, tex_count,
            exported_buffers, buf_count,
            ibv_resource, vbv_resources, cbv_resources)
    """
    exported_textures = []
    exported_buffers = []
    tex_count = 0
    buf_count = 0
    ibv_resource = None
    vbv_resources = []
    cbv_resources = []

    for res in other_inputs:
        res_desc = res.get_description()
        res_id = str(res_desc.get("resource_id"))
        resource_type = res_desc.get("resource_type", "")
        view_type = res_desc.get("view_type", "")

        if resource_type == "texture":
            tex_file = export_texture(resources_accessor, res, call, event_dir, res_id)
            if tex_file:
                exported_textures.append({
                    "type": "input",
                    "resource_id": res_id,
                    "file": os.path.basename(tex_file)
                })
                tex_count += 1

        elif resource_type == "buffer":
            if view_type == "IBV":
                ibv_resource = res
            elif view_type == "VBV":
                vbv_resources.append(res)
                continue
            elif view_type == "CBV":
                cbv_resources.append(res)
                continue

            buf_file = export_buffer(resources_accessor, res, call, event_dir, res_id)
            if buf_file:
                exported_buffers.append({
                    "type": "input",
                    "resource_id": res_id,
                    "file": os.path.basename(buf_file)
                })
                buf_count += 1

    return (exported_textures, tex_count,
            exported_buffers, buf_count,
            ibv_resource, vbv_resources, cbv_resources)


def _stage_export_vbv(vbv_resources, event_dir):
    """
    Stage 6 — 合并输出 VBV 信息到 vbv.json
    
    返回: 导出的 buffer 记录 (dict)，若无 VBV 则返回 None
    """
    if not vbv_resources:
        return None

    VBV_TYPE_BY_STRIDE = {8: "bone", 16: "tangent"}

    vbv_buffers = []
    for res in vbv_resources:
        d = res.get_description()
        stride = d.get("stride", 0)
        res_id = d.get("resource_id", 0)
        vbv_buffers.append({
            "type": VBV_TYPE_BY_STRIDE.get(stride, "vertex"),
            "resource_id": res_id,
            "resource_id_hex": f"{res_id:X}",
            "view_id": d.get("view_id", 0),
            "view_type": d.get("view_type", "VBV"),
            "size": d.get("size", 0),
            "stride": stride,
            "offset": d.get("offset", 0),
            "resource_type": d.get("resource_type", "buffer")
        })

    vbv_json_file = os.path.join(event_dir, "vbv.json")
    with open(vbv_json_file, 'w', encoding='utf-8') as f:
        json.dump({"vbv_buffers": vbv_buffers}, f, indent=2, ensure_ascii=False)

    return {"type": "input", "resource_id": "vbv_combined", "file": "vbv.json"}


def _stage_extract_indirect_args(desc, bindings, resources_accessor, call):
    """
    Stage 7 — 提取 DrawIndexedInstancedIndirect 间接参数
    
    如果当前事件是 DrawIndexedInstancedIndirect，则从 view_type="args" 的
    buffer 中读取 20 字节的间接绘制参数结构体。
    
    返回: indirect_args dict 或 None
    """
    if not is_draw_indexed_instanced_indirect(desc):
        return None

    messages.debug("检测到 DrawIndexedInstancedIndirect 调用")
    args_buffer = find_args_buffer_from_inputs(bindings)
    if not args_buffer:
        messages.debug("未找到 view_type='args' 的 buffer")
        return None

    try:
        args_request = BufferRequest(buffer=args_buffer, call=call, extract_before=False)
        args_result = resources_accessor.get_buffers_data([args_request], timeout=30000)
        if args_request not in args_result:
            messages.debug("读取 args buffer 失败")
            return None

        indirect_args = parse_indirect_args_buffer(args_result[args_request].data)
        if indirect_args:
            messages.debug(f"成功提取 Indirect Args: {indirect_args}")
        return indirect_args
    except Exception as e:
        messages.debug(f"读取 args buffer 异常: {str(e)}")
        return None


def _stage_export_mesh(resources_accessor, ibv_resource, vbv_resources,
                       cbv_resources, call, event_dir, event_index, desc,
                       enable_skinning, skeleton_cbv_info, indirect_args, bindings):
    """
    Stage 8 — 导出网格 (OBJ)
    
    优先使用 IBV + VBV 方式（支持蒙皮和间接绘制），
    失败时回退到 geometry_info 方式。
    
    返回: OBJ 文件名 或 None
    """
    obj_file = None

    if ibv_resource and vbv_resources:
        obj_file = export_mesh_from_buffers(
            resources_accessor, ibv_resource, vbv_resources,
            call, event_dir, event_index, desc,
            skeleton_data=None,
            cbv_resources=cbv_resources,
            enable_skinning=(enable_skinning == 1),
            skeleton_cbv_info=skeleton_cbv_info,
            indirect_args=indirect_args
        )

    if not obj_file and "metadata" in bindings and "input_geometry" in bindings["metadata"]:
        obj_file = export_mesh_to_obj(
            resources_accessor, call, bindings["metadata"]["input_geometry"],
            event_dir, event_index, desc
        )

    return os.path.basename(obj_file) if obj_file else None


def _stage_export_event_shaders(bindings, event_dir, event_index):
    """
    Stage 9 — 导出着色器 (DXBC / HLSL)
    
    返回: (shader_records, count)
    """
    records = []
    if "execution" not in bindings or "program" not in bindings["execution"]:
        return records, 0

    exported = export_shaders(bindings["execution"]["program"], event_dir, event_index)
    for s in exported:
        records.append({"type": s["type"], "file": s["file"]})
    return records, 1 if exported else 0


def _stage_save_event_info(event_dir, event_index, call_id, desc, bindings, event_data):
    """
    Stage 10 — 保存 _event_info.json
    """
    info = {
        "index": event_index,
        "id": call_id,
        "name": desc.get("name"),
        "arguments": desc.get("arguments", []),
        "bindings_summary": {
            "inputs_count": len(bindings.get("inputs", [])),
            "outputs_count": len(bindings.get("outputs", [])),
            "has_program": "program" in bindings.get("execution", {}),
            "has_geometry": "input_geometry" in bindings.get("metadata", {}),
            "shaders_exported": len(event_data.get("exported_shaders", []))
        }
    }
    if "indirect_args" in event_data:
        info["indirect_args"] = event_data["indirect_args"]

    event_info_file = os.path.join(event_dir, "_event_info.json")
    with open(event_info_file, 'w', encoding='utf-8') as f:
        json.dump(info, f, indent=2, ensure_ascii=False, default=str)


def _get_program_desc(bindings):
    """从 bindings 中安全获取 program description"""
    exe = bindings.get("execution", {})
    if "program" not in exe:
        return None
    return exe["program"].get_description()


# =============================================================================
# 单个事件处理 — 串联所有 Stage
# =============================================================================

def _process_single_event(ctx, loop_idx, call):
    """
    处理一个事件的完整导出流程:
    
    Stage 1  解析 PS 纹理绑定
    Stage 2  解析 VS CBV 绑定
    Stage 3  分类输入资源
    Stage 4  导出 SRV 纹理
    Stage 5  导出其他输入资源 (收集 IBV / VBV / CBV)
    Stage 6  合并输出 VBV
    Stage 7  提取 Indirect Args (DrawIndexedInstancedIndirect)
    Stage 8  导出 Mesh
    Stage 9  导出 Shader
    Stage 10 保存 _event_info.json
    """
    desc = call.get_description()
    call_id = desc.get("id")
    event_index = max(1, ctx["min_call"]) + loop_idx

    event_dir = os.path.join(ctx["resources_dir"], f"g_{event_index}")
    if not os.path.exists(event_dir):
        os.makedirs(event_dir)

    event_data = {
        "index": event_index,
        "id": call_id,
        "name": desc.get("name"),
        "texture_binding_map": [],
        "exported_textures": [],
        "exported_buffers": [],
        "exported_shaders": [],
        "exported_mesh": None
    }

    try:
        bindings = call.get_bindings()
        all_calls = ctx["all_calls"]
        resources_accessor = ctx["resources_accessor"]
        enable_skinning = ctx["enable_skinning"]

        # Stage 1: PS 纹理绑定
        dxbc_texture_map, resource_id_to_dxbc_name, texture_binding_list = \
            _stage_build_ps_texture_map(bindings, all_calls, call)
        event_data["texture_binding_map"] = texture_binding_list

        # Stage 2: VS CBV 绑定
        cbv_bindings, skeleton_cbv_info = \
            _stage_build_vs_cbv_map(bindings, all_calls, call, event_dir)

        # Stage 3: 分类输入资源
        srv_textures, other_inputs = _stage_classify_inputs(bindings)

        # Stage 4: 导出 SRV 纹理
        tex_exported, tex_count = _stage_export_textures(
            resources_accessor, srv_textures, call, event_dir,
            resource_id_to_dxbc_name, dxbc_texture_map
        )
        event_data["exported_textures"].extend(tex_exported)
        ctx["counters"]["textures"] += tex_count

        # Stage 5: 导出其他输入 + 收集 IBV/VBV/CBV
        (other_tex, other_tex_cnt,
         other_buf, other_buf_cnt,
         ibv_resource, vbv_resources, cbv_resources) = \
            _stage_export_other_inputs(resources_accessor, other_inputs, call, event_dir)
        event_data["exported_textures"].extend(other_tex)
        event_data["exported_buffers"].extend(other_buf)
        ctx["counters"]["textures"] += other_tex_cnt
        ctx["counters"]["buffers"] += other_buf_cnt

        # Stage 6: 合并 VBV
        vbv_record = _stage_export_vbv(vbv_resources, event_dir)
        if vbv_record:
            event_data["exported_buffers"].append(vbv_record)

        # Stage 7: Indirect Args
        indirect_args = _stage_extract_indirect_args(
            desc, bindings, resources_accessor, call
        )
        if indirect_args:
            event_data["indirect_args"] = indirect_args

        # Stage 8: Mesh
        mesh_file = _stage_export_mesh(
            resources_accessor, ibv_resource, vbv_resources, cbv_resources,
            call, event_dir, event_index, desc,
            enable_skinning, skeleton_cbv_info, indirect_args, bindings
        )
        if mesh_file:
            event_data["exported_mesh"] = mesh_file
            ctx["counters"]["meshes"] += 1

        # Stage 9: Shader
        shader_records, shader_count = _stage_export_event_shaders(
            bindings, event_dir, event_index
        )
        event_data["exported_shaders"] = shader_records
        ctx["counters"]["shaders"] += shader_count

        # Stage 10: 保存事件信息
        _stage_save_event_info(event_dir, event_index, call_id, desc, bindings, event_data)

    except Exception as e:
        event_data["error"] = str(e)
        messages.debug(f"处理 event {call_id} 失败: {str(e)}")

    ctx["output_data"]["events"].append(event_data)


def _finalize_export(ctx):
    """汇总导出统计并返回结果"""
    c = ctx["counters"]
    ctx["output_data"]["summary"] = {
        "total_events": len(ctx["filtered_calls"]),
        "total_textures": c["textures"],
        "total_buffers": c["buffers"],
        "total_meshes": c["meshes"],
        "total_shaders": c["shaders"],
        "resources_dir": ctx["resources_dir"]
    }

    results = []
    for call in ctx["filtered_calls"]:
        results.extend(common.node_to_result(call, common.MessageSeverity.INFO))
    return results


# =============================================================================
# 主入口
# =============================================================================

def run(min_call: "起始事件索引（包含，从1开始）" = 1,
        max_call: "结束事件索引（包含），-1 表示无上限" = -1,
        enable_skinning: "蒙皮计算开关（0=关闭，1=开启）" = 0):
    """
    批量导出帧分析数据的主入口函数。
    
    处理流程:
        Stage 0  初始化会话（筛选事件、创建目录）
        ── 逐事件循环 ──
        Stage 1  解析 PS 纹理绑定 (DXBC + PSSetShaderResources)
        Stage 2  解析 VS CBV 绑定 (DXBC + VSSetConstantBuffers)
        Stage 3  分类输入资源 (SRV 纹理 vs 其他)
        Stage 4  导出 SRV 纹理 (DDS)
        Stage 5  导出其他输入资源 + 收集 IBV / VBV / CBV
        Stage 6  合并输出 VBV (vbv.json)
        Stage 7  提取 Indirect Args (DrawIndexedInstancedIndirect)
        Stage 8  导出 Mesh (OBJ，支持蒙皮 + 间接绘制)
        Stage 9  导出 Shader (DXBC / HLSL)
        Stage 10 保存事件信息 (_event_info.json)
        ── 循环结束 ──
        汇总统计并返回结果
    
    参数:
        min_call: 起始事件索引（包含，从1开始）
        max_call: 结束事件索引（包含），-1 表示无上限
        enable_skinning: 蒙皮计算开关（0=关闭，1=开启，默认 0）
    
    骨骼数据自动从 cbv_bindings 中 dxbc_name 为 "Skeleton" 的条目获取。
    """
    # Stage 0: 初始化
    ctx = _stage_init_session(min_call, max_call, enable_skinning)

    # Stage 1~10: 逐事件处理
    for loop_idx, call in enumerate(ctx["filtered_calls"]):
        _process_single_event(ctx, loop_idx, call)

    # 汇总
    return _finalize_export(ctx)


def desc():
    return {
        "name": "Easy Output - 资源导出工具",
        "description": "导出每个事件的纹理(DDS)、缓冲区、Mesh(OBJ)和Shader(HLSL)，按事件分文件夹保存，资源按input/output分类。",
        "apis": ["DirectX 11", "DirectX 12"],
        "applicabilities": ["Apilog", "Resources"],
        "plugin_api_version": "1.2"
    }

