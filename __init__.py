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
from logs import messages


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
            
            # 写入面
            if indices:
                # OBJ 索引从 1 开始
                for i in range(0, len(indices) - 2, 3):
                    i0 = indices[i] + 1
                    i1 = indices[i + 1] + 1
                    i2 = indices[i + 2] + 1
                    
                    if has_texcoords and has_normals:
                        # f v/vt/vn v/vt/vn v/vt/vn
                        f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")
                    elif has_texcoords:
                        # f v/vt v/vt v/vt
                        f.write(f"f {i0}/{i0} {i1}/{i1} {i2}/{i2}\n")
                    elif has_normals:
                        # f v//vn v//vn v//vn
                        f.write(f"f {i0}//{i0} {i1}//{i1} {i2}//{i2}\n")
                    else:
                        # f v v v
                        f.write(f"f {i0} {i1} {i2}\n")
            else:
                for i in range(0, len(positions) - 2, 3):
                    i0 = i + 1
                    i1 = i + 2
                    i2 = i + 3
                    
                    if has_texcoords and has_normals:
                        f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")
                    elif has_texcoords:
                        f.write(f"f {i0}/{i0} {i1}/{i1} {i2}/{i2}\n")
                    elif has_normals:
                        f.write(f"f {i0}//{i0} {i1}//{i1} {i2}//{i2}\n")
                    else:
                        f.write(f"f {i0} {i1} {i2}\n")
        
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
            
        
        # 导出 shader 描述信息
        shader_info_file = os.path.join(output_dir, f"shader_info_{program_id_hex}.json")
        with open(shader_info_file, 'w', encoding='utf-8') as f:
            # 过滤掉二进制数据，只保留描述信息
            info = {
                "program_id": program_id,
                "program_id_hex": program_id_hex,
                "event_index": event_index,
                "shaders": {}
            }
            for shader_type in ["vertex", "pixel", "geometry", "hull", "domain", "compute"]:
                if shader_type in program_desc:
                    shader_info = program_desc[shader_type]
                    info["shaders"][shader_type] = {
                        "hash": shader_info.get("hash", ""),
                        "has_source": bool(shader_info.get("source", "")),
                        "has_dxil": bool(shader_info.get("dxil", ""))
                    }
            json.dump(info, f, indent=2, ensure_ascii=False, default=str)
        
        exported_shaders.append({
            "type": "info",
            "file": os.path.basename(shader_info_file)
        })
        
    except Exception as e:
        messages.debug(f"导出 shader 失败 (event {event_index}): {str(e)}")
    
    return exported_shaders


def export_mesh_from_buffers(resources_accessor, ibv_resource, vbv_resources, call, output_dir, event_index, call_desc, skeleton_data=None, cbv_resources=None, enable_skinning=True):
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
    """
    try:
        if not ibv_resource or not vbv_resources:
            return None
        
        # 获取绘制调用参数
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
            # 骨骼数据大小为 768 bytes (48 float4, 16 骨骼)
            if skeleton_data is None and cbv_resources:
                for cbv in cbv_resources:
                    cbv_desc = cbv.get_description()
                    cbv_size = cbv_desc.get("size", 0)
                    
                    # 检查是否是骨骼数据 (size == 768)
                    if cbv_size == 768:
                        try:
                            cbv_request = BufferRequest(
                                buffer=cbv,
                                call=call,
                                extract_before=False
                            )
                            cbv_result = resources_accessor.get_buffers_data([cbv_request], timeout=30000)
                            
                            if cbv_request in cbv_result:
                                cbv_data = cbv_result[cbv_request].data
                                skeleton_data = parse_skeleton_data(cbv_data, 0)
                                messages.debug(f"从 CBV 提取骨骼数据: size=768, {len(skeleton_data)} 个 float4")
                                break
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
            
            if indices:
                for i in range(0, len(indices) - 2, 3):
                    i0 = indices[i] + 1
                    i1 = indices[i + 1] + 1
                    i2 = indices[i + 2] + 1
                    
                    if has_texcoords and has_normals:
                        f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")
                    elif has_texcoords:
                        f.write(f"f {i0}/{i0} {i1}/{i1} {i2}/{i2}\n")
                    elif has_normals:
                        f.write(f"f {i0}//{i0} {i1}//{i1} {i2}//{i2}\n")
                    else:
                        f.write(f"f {i0} {i1} {i2}\n")
            else:
                for i in range(0, len(positions) - 2, 3):
                    i0 = i + 1
                    i1 = i + 2
                    i2 = i + 3
                    
                    if has_texcoords and has_normals:
                        f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")
                    elif has_texcoords:
                        f.write(f"f {i0}/{i0} {i1}/{i1} {i2}/{i2}\n")
                    elif has_normals:
                        f.write(f"f {i0}//{i0} {i1}//{i1} {i2}//{i2}\n")
                    else:
                        f.write(f"f {i0} {i1} {i2}\n")
        
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


def run(min_call: "起始事件索引（包含，从1开始）" = 1,
        max_call: "结束事件索引（包含），-1 表示无上限" = -1,
        enable_skinning: "蒙皮计算开关（0=关闭，1=开启）" = 0):
    """
    获取指定索引范围内的事件，导出所有纹理和缓冲区资源
    每个 event 的资源保存在以该 event ID 命名的文件夹下
    
    参数:
        min_call: 起始事件索引（包含，从1开始）
        max_call: 结束事件索引（包含），-1 表示无上限
        enable_skinning: 蒙皮计算开关（0=关闭，1=开启，默认 0）
    """
    
    api_log = plugin_api.get_api_log_accessor()
    resources_accessor = plugin_api.get_resources_accessor()
    
    all_calls = list(common.all_calls_from_node(api_log.get_calls()))
    
    # 筛选事件
    filtered_calls = []
    for call in all_calls:
        desc = call.get_description()
        if not desc.get('is_event', False):
            continue
        filtered_calls.append(call)
    
    # 按索引筛选（min_call 从 1 开始，转换为列表索引需要 -1）
    start_idx = max(0, min_call - 1)  # min_call=1 对应 filtered_calls[0]
    if max_call >= 1:
        filtered_calls = filtered_calls[start_idx:max_call]  # max_call=10 对应 filtered_calls[0:10]
    else:
        filtered_calls = filtered_calls[start_idx:]
    
    # 创建输出目录
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 获取 frame 名称
    frame_name = get_frame_name()
    if frame_name:
        # 清理 frame_name，移除不合法的文件名字符
        safe_frame_name = "".join(c for c in frame_name if c.isalnum() or c in "_-.")
        # 移除可能的扩展名
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
    
    # 输出数据结构
    output_data = {
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filter": {"min_call": min_call, "max_call": max_call},
        "total_count": len(filtered_calls),
        "events": []
    }
    
    total_textures = 0
    total_buffers = 0
    total_meshes = 0
    total_shaders = 0
    
    for idx, call in enumerate(filtered_calls):
        desc = call.get_description()
        call_id = desc.get("id")
        # 事件索引从 min_call 开始（min_call 从 1 开始计数）
        event_index = max(1, min_call) + idx
        
        # 为每个 event 创建单独的文件夹（使用索引命名）
        event_dir = os.path.join(resources_dir, f"g_{event_index}")
        if not os.path.exists(event_dir):
            os.makedirs(event_dir)
        
        # 创建 input 和 output 子文件夹
        input_dir = os.path.join(event_dir, "input")
        output_dir = os.path.join(event_dir, "output")
        if not os.path.exists(input_dir):
            os.makedirs(input_dir)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        event_data = {
            "index": event_index,
            "id": call_id,
            "name": desc.get("name"),
            "exported_textures": [],
            "exported_buffers": [],
            "exported_shaders": [],
            "exported_mesh": None
        }
        
        try:
            bindings = call.get_bindings()
            
            # 收集 IBV、VBV 和 CBV 资源用于生成 mesh（支持蒙皮）
            ibv_resource = None
            vbv_resources = []
            cbv_resources = []  # 用于骨骼数据
            
            # ============ 解析 PS DXBC 纹理绑定，建立 slot -> name 映射 ============
            dxbc_texture_map = {}  # slot_index -> name 映射 (如 0 -> "tBaseMap")
            
            if "execution" in bindings and "program" in bindings["execution"]:
                program = bindings["execution"]["program"]
                program_desc = program.get_description()
                
                # 解析 PS DXBC
                if "pixel" in program_desc:
                    ps_info = program_desc["pixel"]
                    ps_dxbc = ps_info.get("dxbc", "")
                    
                    if ps_dxbc:
                        # 解析 DXBC 中的纹理绑定
                        dxbc_textures = parse_texture_bindings_from_dxbc(ps_dxbc)
                        
                        # 建立 slot_index -> name 映射
                        # slot 格式为 "t0", "t1", "t3" 等，提取数字作为索引
                        for tex in dxbc_textures:
                            slot = tex.get("slot", "")
                            name = tex.get("name", "")
                            if slot.startswith("t") and name:
                                try:
                                    slot_index = int(slot[1:])  # "t0" -> 0
                                    dxbc_texture_map[slot_index] = name
                                except ValueError:
                                    pass
                        
                        if dxbc_texture_map:
                            messages.debug(f"DXBC slot->name 映射: {dxbc_texture_map}")
            
            # ============ 从 PSSetShaderResources 建立 resource_id -> dxbc_name 映射 ============
            resource_id_to_dxbc_name = {}
            
            if dxbc_texture_map:
                # 查找该 event 之前的 PSSetShaderResources 调用
                ps_set_srv_calls = find_ps_set_shader_resources_before_event(all_calls, call)
                
                if ps_set_srv_calls:
                    # 从 PSSetShaderResources 提取 resource_id -> slot 映射
                    resource_id_to_slot = build_resource_id_to_slot_map(ps_set_srv_calls)
                    
                    if resource_id_to_slot:
                        messages.debug(f"PSSetShaderResources resource_id->slot 映射: {resource_id_to_slot}")
                        
                        # 结合两个映射，建立 resource_id -> dxbc_name 映射
                        resource_id_to_dxbc_name = build_resource_id_to_dxbc_name_map(
                            resource_id_to_slot, dxbc_texture_map
                        )
                        
                        if resource_id_to_dxbc_name:
                            messages.debug(f"最终 resource_id->dxbc_name 映射: {resource_id_to_dxbc_name}")
            
            # 收集 inputs 中的资源
            srv_textures_view0 = []
            other_inputs = []
            
            if "inputs" in bindings:
                for res in bindings["inputs"]:
                    res_desc = res.get_description()
                    view_type = res_desc.get("view_type", "")
                    resource_type = res_desc.get("resource_type", "")
                    view_id = res_desc.get("view_id", -1)
                    
                    # 只收集 view_id 为 0 的 SRV 纹理
                    if view_type == "SRV" and resource_type == "texture" and view_id == 0:
                        srv_textures_view0.append(res)
                    else:
                        other_inputs.append(res)
            
            # 导出 SRV 纹理，使用 resource_id -> dxbc_name 映射来命名
            for idx, res in enumerate(srv_textures_view0):
                res_desc = res.get_description()
                res_id = res_desc.get("resource_id")
                res_id_str = str(res_id)
                
                # 优先使用 resource_id -> dxbc_name 映射
                dxbc_name = ""
                dxbc_slot = -1
                
                if res_id in resource_id_to_dxbc_name:
                    dxbc_name = resource_id_to_dxbc_name[res_id]
                    # 反向查找 slot
                    for slot_idx, name in dxbc_texture_map.items():
                        if name == dxbc_name:
                            dxbc_slot = slot_idx
                            break
                    messages.debug(f"资源 {res_id} 通过 PSSetShaderResources 映射到 {dxbc_name} (t{dxbc_slot})")
                
                tex_file = export_texture(
                    resources_accessor, res, call, input_dir, res_id_str, dxbc_name=dxbc_name
                )
                if tex_file:
                    event_data["exported_textures"].append({
                        "type": "input",
                        "resource_id": res_id_str,
                        "dxbc_name": dxbc_name,
                        "dxbc_slot": f"t{dxbc_slot}" if dxbc_slot >= 0 else "",
                        "order_index": idx,
                        "file": f"input/{os.path.basename(tex_file)}"
                    })
                    total_textures += 1
            
            # 处理其他 inputs 资源（非 SRV 纹理）
            for res in other_inputs:
                res_desc = res.get_description()
                res_id = str(res_desc.get("resource_id"))
                resource_type = res_desc.get("resource_type", "")
                view_type = res_desc.get("view_type", "")
                
                if resource_type == "texture":
                    # 非 SRV 的纹理资源
                    tex_file = export_texture(
                        resources_accessor, res, call, input_dir, res_id
                    )
                    if tex_file:
                        event_data["exported_textures"].append({
                            "type": "input",
                            "resource_id": res_id,
                            "file": f"input/{os.path.basename(tex_file)}"
                        })
                        total_textures += 1
                
                elif resource_type == "buffer":
                    # 收集 IBV、VBV 和 CBV 资源
                    if view_type == "IBV":
                        ibv_resource = res
                    elif view_type == "VBV":
                        vbv_resources.append(res)
                    elif view_type == "CBV":
                        cbv_resources.append(res)
                    
                    buf_file = export_buffer(
                        resources_accessor, res, call, input_dir, res_id
                    )
                    if buf_file:
                        event_data["exported_buffers"].append({
                            "type": "input",
                            "resource_id": res_id,
                            "file": f"input/{os.path.basename(buf_file)}"
                        })
                        total_buffers += 1
            
            # 处理 outputs 资源
            if "outputs" in bindings:
                for res in bindings["outputs"]:
                    res_desc = res.get_description()
                    res_id = str(res_desc.get("resource_id"))
                    resource_type = res_desc.get("resource_type")
                    
                    if resource_type == "texture":
                        tex_file = export_texture(
                            resources_accessor, res, call, output_dir, res_id
                        )
                        if tex_file:
                            event_data["exported_textures"].append({
                                "type": "output",
                                "resource_id": res_id,
                                "file": f"output/{os.path.basename(tex_file)}"
                            })
                            total_textures += 1
                    
                    elif resource_type == "buffer":
                        buf_file = export_buffer(
                            resources_accessor, res, call, output_dir, res_id
                        )
                        if buf_file:
                            event_data["exported_buffers"].append({
                                "type": "output",
                                "resource_id": res_id,
                                "file": f"output/{os.path.basename(buf_file)}"
                            })
                            total_buffers += 1
            
            # 导出 Mesh（放在 input 文件夹中，因为是输入几何体）
            # 支持蒙皮计算：传入 CBV 资源用于提取骨骼矩阵数据
            obj_file = None
            
            # 优先使用收集的 IBV 和 VBV 资源生成 mesh（支持蒙皮）
            if ibv_resource and vbv_resources:
                obj_file = export_mesh_from_buffers(
                    resources_accessor, ibv_resource, vbv_resources, call, input_dir, event_index, desc,
                    skeleton_data=None,  # 让函数自动从 CBV 提取
                    cbv_resources=cbv_resources,
                    enable_skinning=(enable_skinning == 1)  # 0=关闭，1=开启
                )
            
            # 如果 IBV/VBV 方式失败，尝试使用 geometry_info
            if not obj_file and "metadata" in bindings and "input_geometry" in bindings["metadata"]:
                geometry_info = bindings["metadata"]["input_geometry"]
                obj_file = export_mesh_to_obj(
                    resources_accessor, call, geometry_info, input_dir, event_index, desc
                )
            
            if obj_file:
                event_data["exported_mesh"] = f"input/{os.path.basename(obj_file)}"
                total_meshes += 1
            
            # 导出 Shader（放在 input 文件夹中）
            if "execution" in bindings and "program" in bindings["execution"]:
                program = bindings["execution"]["program"]
                exported_shaders = export_shaders(program, input_dir, event_index)
                for shader in exported_shaders:
                    event_data["exported_shaders"].append({
                        "type": shader["type"],
                        "file": f"input/{shader['file']}"
                    })
                if exported_shaders:
                    total_shaders += 1
            
            # 保存 event 信息到文件夹内
            event_info_file = os.path.join(event_dir, "_event_info.json")
            with open(event_info_file, 'w', encoding='utf-8') as f:
                json.dump({
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
                }, f, indent=2, ensure_ascii=False, default=str)
                
        except Exception as e:
            event_data["error"] = str(e)
            messages.debug(f"处理 event {call_id} 失败: {str(e)}")
        
        output_data["events"].append(event_data)
    
    # 汇总信息
    output_data["summary"] = {
        "total_events": len(filtered_calls),
        "total_textures": total_textures,
        "total_buffers": total_buffers,
        "total_meshes": total_meshes,
        "total_shaders": total_shaders,
        "resources_dir": resources_dir
    }
    
    # 输出主 JSON 文件
    # output_file = os.path.join(plugin_dir, f"export_{timestamp}.json")
    # try:
    #     with open(output_file, 'w', encoding='utf-8') as f:
    #         json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
    #     messages.debug(f"导出完成:")
    #     messages.debug(f"  - 事件: {len(filtered_calls)}")
    #     messages.debug(f"  - 纹理: {total_textures}")
    #     messages.debug(f"  - 缓冲区: {total_buffers}")
    #     messages.debug(f"  - Mesh: {total_meshes}")
    #     messages.debug(f"  - Shader: {total_shaders}")
    #     messages.debug(f"  - 输出目录: {resources_dir}")
    # except Exception as e:
    #     messages.debug(f"导出失败: {str(e)}")
    
    # node_to_result 返回 List[Dict]，需要展平结果
    results = []
    for call in filtered_calls:
        results.extend(common.node_to_result(call, common.MessageSeverity.INFO))
    return results


def desc():
    return {
        "name": "Easy Output - 资源导出工具",
        "description": "导出每个事件的纹理(DDS)、缓冲区、Mesh(OBJ)和Shader(HLSL)，按事件分文件夹保存，资源按input/output分类。",
        "apis": ["DirectX 11", "DirectX 12"],
        "applicabilities": ["Apilog", "Resources"],
        "plugin_api_version": "1.2"
    }

