#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX 3D 地形可视化一键生成脚本
功能：自动下载 DEM 数据并生成 3D 地形轨迹图
输入：仅需提供 GPX 文件路径
"""

import os
import sys
import argparse
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
from dotenv import load_dotenv
import math
from PIL import Image, ImageDraw, ImageFont

# 检查必要依赖
try:
    import gpxpy
except ImportError:
    print("错误: 未安装 gpxpy，请运行: pip install gpxpy")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("错误: 未安装 requests，请运行: pip install requests")
    sys.exit(1)

try:
    import rasterio
    from rasterio.windows import Window, from_bounds as window_from_bounds
    from rasterio.warp import transform_bounds, transform
except ImportError:
    print("错误: 未安装 rasterio，请运行: pip install rasterio")
    sys.exit(1)

# Plotly 交互式绘图支持
try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


# OpenGL 渲染支持
try:
    # 延迟导入 glfw 以避免与 Open3D 的 glfw 冲突
    # import glfw 
    from OpenGL.GL import *
    from OpenGL.GLU import *
    from OpenGL.GL.shaders import compileProgram, compileShader
    import importlib.util
    if importlib.util.find_spec("glfw") is not None:
        HAS_OPENGL = True
    else:
        HAS_OPENGL = False
except Exception:
    HAS_OPENGL = False

# 设置中文字体支持
import platform
if platform.system() == 'Windows':
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong']
elif platform.system() == 'Darwin':  # macOS
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC', 'STHeiti']
else:  # Linux
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def get_gpx_bounds(gpx_file):
    """
    解析 GPX 文件并获取边界框 (min_lat, min_lon, max_lat, max_lon)
    """
    try:
        with open(gpx_file, 'r', encoding='utf-8') as f:
            gpx = gpxpy.parse(f)
            
        if not gpx.tracks:
            raise ValueError("GPX 文件中没有轨迹")
            
        bounds = gpx.get_bounds()
        if not bounds:
            raise ValueError("无法获取轨迹边界")
            
        return bounds.min_latitude, bounds.min_longitude, bounds.max_latitude, bounds.max_longitude
        
    except Exception as e:
        print(f"解析 GPX 文件边界出错: {e}")
        sys.exit(1)


def parse_gpx_points(gpx_file):
    """
    使用 gpxpy 解析 GPX 文件，提取轨迹点
    Returns: [(lat, lon, ele), ...]
    """
    try:
        with open(gpx_file, 'r', encoding='utf-8') as f:
            gpx = gpxpy.parse(f)

        track_points = []
        for track in gpx.tracks:
            for segment in track.segments:
                # 计算速度 (如果文件中没有)
                # segment.enrich_points() # gpxpy 可能没有此方法，跳过
                if segment.has_times():
                     for i in range(len(segment.points)):
                        if segment.points[i].speed is None:
                             segment.points[i].speed = segment.get_speed(i)
                for point in segment.points:
                    lat = point.latitude
                    lon = point.longitude
                    ele = float(point.elevation or 0.0)
                    time_val = point.time.timestamp() if point.time else 0.0
                    track_points.append((lat, lon, ele, time_val))
        return track_points
    except Exception as e:
        print(f"解析 GPX 点数据出错: {e}")
        return []


def download_dem(api_key, bounds, output_file, dem_type="SRTMGL1", margin=0.02):
    """
    调用 OpenTopography API 下载 DEM 数据
    """
    min_lat, min_lon, max_lat, max_lon = bounds
    
    # 添加缓冲
    south = min_lat - margin
    north = max_lat + margin
    west = min_lon - margin
    east = max_lon + margin
    
    print(f"轨迹范围: Lat [{min_lat:.4f}, {max_lat:.4f}], Lon [{min_lon:.4f}, {max_lon:.4f}]")
    
    url = "https://portal.opentopography.org/API/globaldem"
    params = {
        'demtype': dem_type,
        'south': south,
        'north': north,
        'west': west,
        'east': east,
        'outputFormat': 'GTiff',
        'API_Key': api_key
    }
    
    print(f"正在下载 DEM 数据 (数据集: {dem_type})...")
    
    try:
        response = requests.get(url, params=params, stream=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if 'text' in content_type or 'html' in content_type:
                print(f"错误: API 返回了文本响应，可能参数有误: \n{response.text}")
                return False

            total_size = int(response.headers.get('content-length', 0))
            
            with open(output_file, 'wb') as f:
                if total_size == 0:
                    f.write(response.content)
                else:
                    downloaded = 0
                    for data in response.iter_content(chunk_size=4096):
                        downloaded += len(data)
                        f.write(data)
                        # 简单的进度显示
                        if total_size > 1024*1024: # > 1MB 才显示进度
                            done = int(50 * downloaded / total_size)
                            sys.stdout.write(f"\r下载进度: [{'=' * done}{' ' * (50 - done)}] {downloaded/1024/1024:.2f} MB")
                            sys.stdout.flush()
            
            if total_size > 1024*1024:
                print() # 换行
            print(f"DEM 下载完成: {output_file}")
            return True
        else:
            print(f"下载失败: HTTP {response.status_code}")
            print(response.text)
            return False
            
    except Exception as e:
        print(f"请求出错: {e}")
        return False


def fetch_osm_pois(bbox):
    """
    从 OpenStreetMap 获取附近的兴趣点 (POI)
    bbox: (min_lon, min_lat, max_lon, max_lat)
    """
    print("正在从 OpenStreetMap 获取周边景点信息...")
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    # 构建查询语句: 查询范围内的山峰、景点、观景台
    # 稍微扩大一点搜索范围 (0.01度)
    margin = 0.01
    s, w, n, e = bbox[1]-margin, bbox[0]-margin, bbox[3]+margin, bbox[2]+margin
    
    overpass_query = f"""
    [out:json][timeout:25];
    (
      node["natural"="peak"]({s},{w},{n},{e});
      node["tourism"="attraction"]({s},{w},{n},{e});
      node["tourism"="viewpoint"]({s},{w},{n},{e});
      node["place"="locality"]({s},{w},{n},{e});
    );
    out body;
    """
    
    try:
        response = requests.get(overpass_url, params={'data': overpass_query})
        if response.status_code == 200:
            data = response.json()
            pois = []
            for element in data.get('elements', []):
                if 'tags' in element and 'name' in element['tags']:
                    name = element['tags']['name']
                    lat = element['lat']
                    lon = element['lon']
                    type_ = element['tags'].get('natural') or element['tags'].get('tourism') or element['tags'].get('place')
                    ele = element['tags'].get('ele', '0')
                    try:
                        ele = float(ele)
                    except:
                        ele = 0
                    pois.append({'name': name, 'lat': lat, 'lon': lon, 'ele': ele, 'type': type_})
            print(f"获取到 {len(pois)} 个兴趣点")
            return pois
        else:
            print(f"OSM 请求失败: {response.status_code}")
            return []
    except Exception as e:
        print(f"获取 POI 出错: {e}")
        return []


def load_dem_window(dem_path, bbox_wgs84, margin_ratio=0.05):
    """
    读取 DEM 指定范围窗口并返回数据与仿射变换
    """
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    # 扩展边界
    lon_pad = (max_lon - min_lon) * margin_ratio
    lat_pad = (max_lat - min_lat) * margin_ratio
    min_lon -= lon_pad
    max_lon += lon_pad
    min_lat -= lat_pad
    max_lat += lat_pad

    with rasterio.open(dem_path) as src:
        # 将 WGS84 边界转换到 DEM 的 CRS
        dem_bounds = transform_bounds("EPSG:4326", src.crs, min_lon, min_lat, max_lon, max_lat, densify_pts=21)
        left, bottom, right, top = dem_bounds

        # 计算窗口
        win = window_from_bounds(left, bottom, right, top, transform=src.transform)
        # 修复 RasterioDeprecationWarning: round_shape is deprecated
        win = win.round_offsets(op='floor')
        win = Window(win.col_off, win.row_off, math.ceil(win.width), math.ceil(win.height))

        # 读取 DEM 数据
        dem = src.read(1, window=win).astype(np.float32)

        # 获取窗口的仿射变换
        win_transform = src.window_transform(win)
        dem_crs = src.crs

    return dem, win_transform, dem_crs


def coords_wgs84_to_dem_crs(lons, lats, dem_crs):
    """将经纬度坐标转换到 DEM 的坐标系"""
    xs, ys = transform("EPSG:4326", dem_crs, lons, lats)
    return np.array(xs), np.array(ys)


def meshgrid_from_affine(transform, width, height):
    """根据仿射变换和尺寸生成 X/Y 网格坐标"""
    a, b, c, d, e, f = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f
    cols = np.arange(width)
    rows = np.arange(height)
    cols_grid, rows_grid = np.meshgrid(cols, rows)
    X = a * cols_grid + b * rows_grid + c
    Y = d * cols_grid + e * rows_grid + f
    return X, Y


def plot_terrain_3d_interactive_plotly(track_points, dem_path, output_file):
    """
    使用 Plotly 生成高性能交互式 3D 地形图
    """
    if not HAS_PLOTLY:
        print("错误: 未安装 plotly，无法生成交互式 HTML。请运行: pip install plotly")
        return

    print("正在生成交互式 3D 地形图 (Plotly)...")
    
    # 提取经纬度
    lats = [pt[0] for pt in track_points]
    lons = [pt[1] for pt in track_points]
    times = [pt[3] for pt in track_points] # 提取时间戳
    
    # 简单的相对时间计算 (从0开始)
    if not times or all(t == 0 for t in times):
        print("警告: GPX 中没有时间数据，将使用模拟时间 (1点/秒)")
        times = [float(i) for i in range(len(track_points))]
    
    t0 = times[0]
    rel_times = np.array([t - t0 for t in times])
    total_duration = rel_times[-1]
    if total_duration == 0: total_duration = 1.0 # 避免除零
    
    # 读取 DEM
    bbox = (min(lons), min(lats), max(lons), max(lats))
    try:
        dem, win_transform, dem_crs = load_dem_window(dem_path, bbox)
    except Exception as e:
        print(f"读取 DEM 失败: {e}")
        return

    h, w = dem.shape
    
    # 生成网格坐标 (用于 Plotly 表面)
    X, Y = meshgrid_from_affine(win_transform, w, h)
    
    # 计算路径坐标 (在 DEM 坐标系中)
    xs, ys = coords_wgs84_to_dem_crs(lons, lats, dem_crs)
    
    # 计算路径高度 (贴地)
    inv_transform = ~win_transform
    cols, rows = inv_transform * (xs, ys)
    rows_idx = np.clip(rows, 0, h - 1).astype(int)
    cols_idx = np.clip(cols, 0, w - 1).astype(int)
    path_z = dem[rows_idx, cols_idx] + 5.0 # 抬高 5 米
    
    # 创建 3D 图形
    fig = go.Figure()
    
    # 添加地形表面
    # Plotly 处理大量点比 Matplotlib 快很多，但过大仍会卡顿，进行适度降采样
    MAX_SIZE = 500 # Plotly 可以处理更大的网格
    stride_row = max(1, h // MAX_SIZE)
    stride_col = max(1, w // MAX_SIZE)
    
    fig.add_trace(go.Surface(
        z=dem[::stride_row, ::stride_col],
        x=X[::stride_row, ::stride_col],
        y=Y[::stride_row, ::stride_col],
        colorscale='Earth',
        showscale=False,
        name='地形',
        opacity=0.9
    ))
    
    # 添加轨迹
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=path_z,
        mode='lines',
        line=dict(color='red', width=4),
        name='轨迹'
    ))
    
    # 添加起点和终点
    fig.add_trace(go.Scatter3d(
        x=[xs[0]], y=[ys[0]], z=[path_z[0]],
        mode='markers',
        marker=dict(size=5, color='green'),
        name='起点'
    ))
    fig.add_trace(go.Scatter3d(
        x=[xs[-1]], y=[ys[-1]], z=[path_z[-1]],
        mode='markers',
        marker=dict(size=5, color='red'),
        name='终点'
    ))
    
    # 设置布局
    fig.update_layout(
        title='3D 地形轨迹图 (交互式)',
        scene=dict(
            aspectmode='data', # 保持真实比例
            xaxis_title='X (m)',
            yaxis_title='Y (m)',
            zaxis_title='Elevation (m)',
            camera=dict(
                eye=dict(x=1.5, y=-1.5, z=0.5) # 初始视角
            )
        ),
        margin=dict(l=0, r=0, b=0, t=50)
    )
    
    fig.write_html(output_file)
    print(f"成功: 交互式网页已保存到 -> {output_file}")
    
    # 尝试自动打开
    try:
        import webbrowser
        webbrowser.open('file://' + os.path.abspath(output_file))
    except:
        pass




def create_text_texture(text, font_path=None, font_size=20):
    """
    创建一个包含文本的 OpenGL 纹理 (黄色气泡风格)
    Returns: texture_id, width, height
    """
    # 尝试加载字体
    font = None
    if font_path:
        try:
            font = ImageFont.truetype(font_path, font_size)
        except:
            pass
    if font is None:
        try:
            # Fallback
            font = ImageFont.load_default()
        except:
            pass

    # 计算文本大小
    if font:
        bbox = font.getbbox(text)
        # bbox: (left, top, right, bottom)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    else:
        text_w, text_h = len(text) * 8, 14
    
    padding_x = 14
    padding_y = 10
    w = text_w + padding_x * 2
    h = text_h + padding_y * 2
    
    # 创建图像 (RGBA)
    image = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 画黄色圆角矩形背景 (气泡)
    # 黄色: (255, 235, 59), Alpha: 230
    draw.rounded_rectangle((0, 0, w, h), radius=8, fill=(255, 235, 59, 230), outline=(255, 255, 255, 255), width=1)
    
    # 画文字 (黑色)
    # 简单的居中计算
    draw.text((padding_x, padding_y - 2), text, font=font, fill=(0, 0, 0, 255))
    
    # 转换为纹理数据
    # 注意：OpenGL纹理默认(0,0)在左下角，而PIL在左上角。
    # 使用 FLIP_TOP_BOTTOM 让数据的第一行对应图片的底部，从而使纹理坐标(0,0)对应图片底部。
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    img_data = image.tobytes()
    
    texture_id = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, texture_id)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, img_data)
    
    return texture_id, w, h

def plot_terrain_3d_opengl(track_points, dem_path):
    """
    使用 OpenGL (PyOpenGL+GLFW) 生成高性能 3D 地形图 (Fixed Pipeline)
    """
    if not HAS_OPENGL:
        print("错误: 未安装 PyOpenGL 或 glfw，无法使用 OpenGL 渲染。")
        return

    import glfw  # 延迟导入，仅在使用 OpenGL 渲染时导入

    print("正在生成 3D 地形图 (OpenGL)...")
    
    lats = [pt[0] for pt in track_points]
    lons = [pt[1] for pt in track_points]
    times = [pt[3] for pt in track_points] # 提取时间戳
    
    # 简单的相对时间计算 (从0开始)
    if not times or all(t == 0 for t in times):
        print("警告: GPX 中没有时间数据，将使用模拟时间 (1点/秒)")
        times = [float(i) for i in range(len(track_points))]
    
    t0 = times[0]
    rel_times = np.array([t - t0 for t in times])
    total_duration = rel_times[-1]
    if total_duration == 0: total_duration = 1.0 # 避免除零
    
    # 读取 DEM
    bbox = (min(lons), min(lats), max(lons), max(lats))
    try:
        dem, win_transform, dem_crs = load_dem_window(dem_path, bbox)
    except Exception as e:
        print(f"读取 DEM 失败: {e}")
        return

    h, w = dem.shape
    # OpenGL DisplayList 也能处理百万级，但为了稳妥先适度降采样
    MAX_SIZE = 500
    stride_row = max(1, h // MAX_SIZE)
    stride_col = max(1, w // MAX_SIZE)
    
    dem_ds = dem[::stride_row, ::stride_col]
    X, Y = meshgrid_from_affine(win_transform, w, h)
    X_ds = X[::stride_row, ::stride_col]
    Y_ds = Y[::stride_row, ::stride_col]
    
    rows, cols = dem_ds.shape
    
    # 归一化/中心化
    # 1. 先计算中心点 (原始坐标)
    center_x = (X_ds.min() + X_ds.max()) / 2
    center_y = (Y_ds.min() + Y_ds.max()) / 2
    z_min = dem_ds.min()
    
    # 2. 坐标转换 (近似米制)
    # 检测是否需要经纬度转米 (简单的启发式: 如果范围很小且是WGS84)
    # rasterio CRS 对象有 is_geographic 属性
    scale_x = 1.0
    scale_y = 1.0
    if dem_crs.is_geographic:
        # 估算纬度用于经度缩放
        lat_mean = (Y_ds.min() + Y_ds.max()) / 2
        scale_y = 111320.0 # 1度纬度 ~ 111.32km
        scale_x = 111320.0 * math.cos(math.radians(lat_mean))
        print(f"应用地理坐标转米制: scale_x={scale_x:.1f}, scale_y={scale_y:.1f}")
        
    X_local = (X_ds - center_x) * scale_x
    Y_local = (Y_ds - center_y) * scale_y
    Z_local = (dem_ds - z_min)
    
    # 3. 整体缩放适应视图 (归一化到 [-100, 100] 盒子)
    range_x = X_local.max() - X_local.min()
    range_y = Y_local.max() - Y_local.min()
    range_z = Z_local.max() - Z_local.min()
    
    max_dim = max(range_x, range_y, range_z)
    if max_dim == 0: max_dim = 1.0
    
    target_size = 200.0
    global_scale = target_size / max_dim
    
    # 垂直夸张
    Z_SCALE_FACTOR = 1.5 
    
    X_ds = X_local * global_scale
    Y_ds = Y_local * global_scale
    Z_ds = Z_local * global_scale * Z_SCALE_FACTOR
    
    # 准备顶点数据 (用于显示列表)
    vertices = np.stack([X_ds, Y_ds, Z_ds], axis=2) # rows x cols x 3
    
    # 轨迹数据处理
    xs, ys = coords_wgs84_to_dem_crs(lons, lats, dem_crs)
    path_points = []
    inv_transform = ~win_transform
    c_path, r_path = inv_transform * (xs, ys)
    r_path = np.clip(r_path, 0, h - 1).astype(int)
    c_path = np.clip(c_path, 0, w - 1).astype(int)
    
    # 采样并应用相同的变换
    path_z_raw = dem[r_path, c_path]
    
    path_x_local = (xs - center_x) * scale_x
    path_y_local = (ys - center_y) * scale_y
    path_z_local = path_z_raw - z_min
    
    path_x_final = path_x_local * global_scale
    path_y_final = path_y_local * global_scale
    path_z_final = path_z_local * global_scale * Z_SCALE_FACTOR + 0.5 # 稍微抬高一点 (相对单位)
    
    path_pts = np.stack([path_x_final, path_y_final, path_z_final], axis=1)

    # 预计算路径每段的前进方向与转弯角（用于导航小窗左转/右转/直行，平滑不跳动）
    LOOK_AHEAD = 5  # 向前看几个点用于判断转弯
    path_dirs = np.zeros((len(path_pts), 3))
    turn_angles = np.zeros(len(path_pts))  # 弧度，正=右转，负=左转
    for i in range(len(path_pts) - 1):
        d = path_pts[i + 1] - path_pts[i]
        L = np.sqrt((d[:2] ** 2).sum())
        if L > 1e-6:
            path_dirs[i] = d / np.linalg.norm(d)
        else:
            path_dirs[i] = path_dirs[i - 1] if i > 0 else np.array([1.0, 0.0, 0.0])
    path_dirs[-1] = path_dirs[-2]
    for i in range(len(path_pts) - 2):
        j = min(i + LOOK_AHEAD, len(path_pts) - 2)
        d1 = (path_pts[i + 1] - path_pts[i])[:2]
        d2 = (path_pts[j + 1] - path_pts[j])[:2]
        n1 = np.linalg.norm(d1)
        n2 = np.linalg.norm(d2)
        if n1 > 1e-6 and n2 > 1e-6:
            d1, d2 = d1 / n1, d2 / n2
            cross = d1[0] * d2[1] - d1[1] * d2[0]
            turn_angles[i] = np.arcsin(np.clip(cross, -1, 1))
        else:
            turn_angles[i] = 0.0
    turn_angles[-2] = turn_angles[-3]
    turn_angles[-1] = turn_angles[-2]

    # 初始化 GLFW
    if not glfw.init():
        print("GLFW 初始化失败")
        return

    # 获取 POI 数据
    # pois = fetch_osm_pois(bbox)
    pois = None
    poi_pts = []
    if pois:
        print("\n=== 周边景点 ===")
        # 计算 POI 在 3D 空间中的坐标
        p_lats = [p['lat'] for p in pois]
        p_lons = [p['lon'] for p in pois]
        p_xs, p_ys = coords_wgs84_to_dem_crs(p_lons, p_lats, dem_crs)
        
        inv_transform = ~win_transform
        c_p, r_p = inv_transform * (p_xs, p_ys)
        
        # 过滤在当前DEM范围内的点
        valid_indices = []
        for i in range(len(pois)):
            r, c = int(r_p[i]), int(c_p[i])
            if 0 <= r < h and 0 <= c < w:
                valid_indices.append(i)
                # 获取该位置的地面高度
                z_ground = dem[r, c]
                # 如果 POI 有 ele 属性且合理，也可以参考，但通常 DEM 地面高度更贴合地形
                # 我们把标记画在地面上方一点
                
                # 转换到局部坐标
                px_local = (p_xs[i] - center_x) * scale_x * global_scale
                py_local = (p_ys[i] - center_y) * scale_y * global_scale
                pz_local = (z_ground - z_min) * global_scale * Z_SCALE_FACTOR
                
                poi_pts.append({
                    'pos': (px_local, py_local, pz_local),
                    'name': pois[i]['name'],
                    'type': pois[i]['type']
                })
                print(f"- {pois[i]['name']} ({pois[i]['type']}): 海拔 {z_ground:.1f}m")
        print("==================\n")

    window = glfw.create_window(1280, 800, "GPX 3D Terrain (OpenGL Native)", None, None)
    if not window:
        glfw.terminate()
        return
        
    glfw.make_context_current(window)
    
    # --- 生成文本纹理 (需在 OpenGL 上下文创建后) ---
    font_path = None
    possible_fonts = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "C:/Windows/Fonts/msyh.ttf",   # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf", # 黑体
        "C:/Windows/Fonts/arial.ttf"
    ]
    for fp in possible_fonts:
        if os.path.exists(fp):
            font_path = fp
            break
            
    if poi_pts:
        print("正在生成景点标签纹理...")
        for poi in poi_pts:
            tid, tw, th = create_text_texture(poi['name'], font_path, font_size=18)
            poi['texture_id'] = tid
            poi['w'] = tw
            poi['h'] = th
    # ----------------------------------------
    
    # 交互状态
    # 现在的场景范围大约是 [-100, 100]，相机距离设为 200-300 比较合适
    state = {
        'dist': 300.0,
        'rot_x': 45.0,
        'rot_z': 0.0,
        'last_x': 0,
        'last_y': 0,
        'dragging': False,
        'z_scale': 1.5,      # 当前高度倍数
        'ui_dragging': False,# 是否正在拖动 Z-Scale UI
        
        # 播放控制
        'playing': False,
        'playback_time': 0.0, # 当前播放时间 (秒)
        'speed_scale': 3.0,   # 缺省 3 倍速，1x ~ 50x
        'speed_dragging': False,
        'progress_dragging': False,
        'last_frame_time': 0.0,
        'smoothed_turn': 0.0,  # 平滑后的转弯角（弧度），用于导航指示
        
        # 小地图范围（以当前点为中心，方圆约 200 米）
        'mini_map_half_extent': 100.0 * global_scale,
    }
    
    # 导航小窗（左上角，行车视角）
    NAV_X, NAV_Y = 20, 20
    NAV_W, NAV_H = 320, 180
    
    # UI 配置（放在导航小窗下方）
    UI_X, UI_Y = 20, NAV_Y + NAV_H + 16
    UI_W, UI_H = 200, 20
    
    # 速度滑杆
    SPEED_UI_Y = UI_Y + 40
    
    # 播放按钮
    PLAY_BTN_Y = SPEED_UI_Y + 40
    PLAY_BTN_W = 60
    
    def mouse_button_callback(window, button, action, mods):
        xpos, ypos = glfw.get_cursor_pos(window)
        win_w, win_h = glfw.get_window_size(window)
        prog_margin_x = 20.0
        prog_width = max(10.0, win_w - prog_margin_x * 2.0)
        prog_height = 10.0
        prog_y = win_h - 30.0
        prog_x = prog_margin_x
        in_z_slider = (UI_X <= xpos <= UI_X + UI_W) and (UI_Y <= ypos <= UI_Y + UI_H)
        in_speed_slider = (UI_X <= xpos <= UI_X + UI_W) and (SPEED_UI_Y <= ypos <= SPEED_UI_Y + UI_H)
        in_play_btn = (UI_X <= xpos <= UI_X + PLAY_BTN_W) and (PLAY_BTN_Y <= ypos <= PLAY_BTN_Y + UI_H)
        in_progress = (prog_x <= xpos <= prog_x + prog_width) and (prog_y <= ypos <= prog_y + prog_height)

        if button == glfw.MOUSE_BUTTON_LEFT:
            if action == glfw.PRESS:
                if in_z_slider:
                    state['ui_dragging'] = True
                    ratio = (xpos - UI_X) / UI_W
                    state['z_scale'] = 1.0 + max(0.0, min(1.0, ratio)) * 4.0
                elif in_speed_slider:
                    state['speed_dragging'] = True
                    ratio = (xpos - UI_X) / UI_W
                    state['speed_scale'] = 1.0 + max(0.0, min(1.0, ratio)) * 49.0 # 1x - 50x
                elif in_progress:
                    state['progress_dragging'] = True
                    ratio = (xpos - prog_x) / prog_width
                    ratio = max(0.0, min(1.0, ratio))
                    state['playback_time'] = ratio * total_duration
                elif in_play_btn:
                    state['playing'] = not state['playing']
                    if state['playing']:
                        state['last_frame_time'] = glfw.get_time()
                        # 如果已经播完，重置
                        if state['playback_time'] >= total_duration:
                            state['playback_time'] = 0.0
                else:
                    state['dragging'] = True
                    state['last_x'], state['last_y'] = xpos, ypos
            elif action == glfw.RELEASE:
                state['dragging'] = False
                state['ui_dragging'] = False
                state['speed_dragging'] = False
                state['progress_dragging'] = False
                
    def cursor_position_callback(window, xpos, ypos):
        if state['ui_dragging']:
            ratio = (xpos - UI_X) / UI_W
            state['z_scale'] = 1.0 + max(0.0, min(1.0, ratio)) * 4.0
        elif state['speed_dragging']:
            ratio = (xpos - UI_X) / UI_W
            state['speed_scale'] = 1.0 + max(0.0, min(1.0, ratio)) * 49.0
        elif state['progress_dragging']:
            win_w, win_h = glfw.get_window_size(window)
            prog_margin_x = 20.0
            prog_width = max(10.0, win_w - prog_margin_x * 2.0)
            prog_x = prog_margin_x
            ratio = (xpos - prog_x) / prog_width
            ratio = max(0.0, min(1.0, ratio))
            state['playback_time'] = ratio * total_duration
        elif state['dragging']:
            dx = xpos - state['last_x']
            dy = ypos - state['last_y']
            state['rot_z'] -= dx * 0.5 # 反向旋转，符合用户习惯
            state['rot_x'] += dy * 0.5
            state['rot_x'] = max(10, min(89, state['rot_x']))
            state['last_x'] = xpos
            state['last_y'] = ypos
            
    def scroll_callback(window, xoffset, yoffset):
        state['dist'] *= (0.9 if yoffset > 0 else 1.1)

    glfw.set_mouse_button_callback(window, mouse_button_callback)
    glfw.set_cursor_pos_callback(window, cursor_position_callback)
    glfw.set_scroll_callback(window, scroll_callback)
    
    # OpenGL 初始化
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_LIGHTING)
    glEnable(GL_LIGHT0)
    
    # 启用颜色追踪，使 glColor() 作用于材质的 Ambient 和 Diffuse
    glEnable(GL_COLOR_MATERIAL)
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
    
    # 自动归一化法线 (防止缩放导致法线错误)
    glEnable(GL_NORMALIZE)
    
    # 设置光照模型
    # 1. 增加全局环境光，确保即使背光面也能看见
    glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (0.5, 0.5, 0.5, 1.0))
    # 2. 启用双面光照，防止法线方向问题导致的面剔除或全黑
    glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, GL_TRUE)
    
    # 设置主光源 (LIGHT0)
    glLightfv(GL_LIGHT0, GL_POSITION, (1.0, 1.0, 1.0, 0.0)) 
    glLightfv(GL_LIGHT0, GL_AMBIENT, (0.3, 0.3, 0.3, 1.0))
    glLightfv(GL_LIGHT0, GL_DIFFUSE, (0.9, 0.9, 0.9, 1.0))
    glLightfv(GL_LIGHT0, GL_SPECULAR, (0.1, 0.1, 0.1, 1.0)) # 降低反光，避免看起来像雪
    
    # 优化: 使用顶点数组代替显示列表，大幅提升加载速度
    print(f"正在准备 OpenGL 顶点数据... 数据范围: X[{X_ds.min():.1f}, {X_ds.max():.1f}] Y[{Y_ds.min():.1f}, {Y_ds.max():.1f}] Z[{Z_ds.min():.1f}, {Z_ds.max():.1f}]")
    
    # 1. 顶点数组
    v_data = np.ascontiguousarray(vertices.reshape(-1, 3), dtype=np.float32)
    
    # 2. 法线数组 (平滑着色)
    print("计算法线...")
    dX_dr, dX_dc = np.gradient(X_ds)
    dY_dr, dY_dc = np.gradient(Y_ds)
    dZ_dr, dZ_dc = np.gradient(Z_ds)
    
    # Tangent vectors
    Tr = np.stack([dX_dr, dY_dr, dZ_dr], axis=2)
    Tc = np.stack([dX_dc, dY_dc, dZ_dc], axis=2)
    
    # Normal = cross(Tr, Tc)
    # 之前使用的是 cross(Tc, Tr) 导致法线向下，这里改为 cross(Tr, Tc) 使法线向上
    normals = np.cross(Tr, Tc)
    norm = np.linalg.norm(normals, axis=2, keepdims=True)
    norm[norm == 0] = 1.0
    normals = normals / norm
    n_data = np.ascontiguousarray(normals.reshape(-1, 3), dtype=np.float32)
    
    # 3. 颜色数组
    z_range = Z_ds.max() - Z_ds.min()
    if z_range == 0: z_range = 1
    h_vals = (Z_ds.flatten() - Z_ds.min()) / z_range
    
    c_data = np.zeros((rows * cols, 3), dtype=np.float32)
    mask_low = h_vals < 0.3
    mask_mid = (h_vals >= 0.3) & (h_vals < 0.7)
    mask_high = h_vals >= 0.7
    
    c_data[mask_low] = [0.1, 0.45, 0.1] # 深绿色
    c_data[mask_mid] = [0.6, 0.5, 0.3]
    c_data[mask_high] = [0.7, 0.7, 0.7]
    c_data = np.ascontiguousarray(c_data, dtype=np.float32)
    
    # 4. 索引数组
    print("生成索引...")
    r_idx = np.arange(rows - 1)
    c_idx = np.arange(cols - 1)
    R_idx, C_idx = np.meshgrid(r_idx, c_idx, indexing='ij')
    
    p00 = R_idx * cols + C_idx
    p10 = (R_idx + 1) * cols + C_idx
    p01 = R_idx * cols + (C_idx + 1)
    p11 = (R_idx + 1) * cols + (C_idx + 1)
    
    # Tri 1: p00 -> p10 -> p01
    t1 = np.stack([p00, p10, p01], axis=2).reshape(-1, 3)
    # Tri 2: p10 -> p11 -> p01
    t2 = np.stack([p10, p11, p01], axis=2).reshape(-1, 3)
    
    indices = np.vstack([t1, t2]).flatten().astype(np.uint32)
    
    print(f"数据准备完成: 顶点数 {len(v_data)}, 三角形数 {len(indices)//3}")
    
    print("\n=== 操作指南 ===")
    print("鼠标左键拖拽: 旋转视角")
    print("鼠标滚轮: 缩放")
    print("点击 Play 按钮: 按 GPX 时间从起点播放，左上角出现行车导航小窗（前方道路+左转/右转/直行），缺省 3 倍速直至终点")
    print("拖动 Speed 滑杆调整播放倍速 (1x-50x)")
    print("关闭窗口退出")
    
    state['last_frame_time'] = glfw.get_time()
    
    while not glfw.window_should_close(window):
        width, height = glfw.get_framebuffer_size(window)
        if height == 0: height = 1
        glViewport(0, 0, width, height)
        
        # 浅蓝色背景
        glClearColor(0.53, 0.81, 0.92, 1.0) 
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, width/height, 1.0, 100000.0)
        
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        
        # 相机位置
        dist = state['dist']
        rot_x = state['rot_x']
        rot_z = state['rot_z']
        
        rad_x = math.radians(rot_x)
        rad_z = math.radians(rot_z)
        
        eye_x = dist * math.cos(rad_x) * math.sin(rad_z)
        eye_y = -dist * math.cos(rad_x) * math.cos(rad_z)
        eye_z = dist * math.sin(rad_x)
        
        gluLookAt(eye_x, eye_y, eye_z, 0, 0, 0, 0, 0, 1)
        
        # 应用 Z 轴缩放
        current_scale = state['z_scale']
        glScalef(1.0, 1.0, current_scale / Z_SCALE_FACTOR)
        
        # 绘制地形
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)
        
        glVertexPointer(3, GL_FLOAT, 0, v_data)
        glNormalPointer(GL_FLOAT, 0, n_data)
        glColorPointer(3, GL_FLOAT, 0, c_data)
        
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, indices)
        
        glDisableClientState(GL_VERTEX_ARRAY)
        glDisableClientState(GL_NORMAL_ARRAY)
        glDisableClientState(GL_COLOR_ARRAY)
        
        # 绘制轨迹
        glDisable(GL_LIGHTING)
        glLineWidth(2.0)
        glColor3f(0.8, 0.8, 0.8) # 银白色
        glBegin(GL_LINE_STRIP)
        for p in path_pts:
            glVertex3fv(p)
        glEnd()
        
        # ----------------------------------------
        # 播放逻辑与光点绘制
        # ----------------------------------------
        current_sys_time = glfw.get_time()
        dt = current_sys_time - state['last_frame_time']
        state['last_frame_time'] = current_sys_time
        
        if state['playing'] and not state.get('progress_dragging', False):
            state['playback_time'] += dt * state['speed_scale']
            if state['playback_time'] >= total_duration:
                state['playback_time'] = total_duration
                state['playing'] = False  # 直到终点后停止
        
        # 计算当前位置
        cur_t = state['playback_time']
        idx = np.searchsorted(rel_times, cur_t, side='right') - 1
        idx = max(0, min(len(path_pts)-2, idx))
        
        t1 = rel_times[idx]
        t2 = rel_times[idx+1]
        if t2 - t1 > 1e-6:
            alpha = (cur_t - t1) / (t2 - t1)
        else:
            alpha = 0.0
            
        p1 = path_pts[idx]
        p2 = path_pts[idx+1]
        cur_pos = p1 + (p2 - p1) * alpha
        
        # 当前前进方向（单位向量）
        cur_forward = path_dirs[idx] if idx < len(path_dirs) else (p2 - p1) / (np.linalg.norm(p2 - p1) + 1e-9)
        # 当前转弯角（插值 + 平滑，避免来回跳）
        raw_turn = (1 - alpha) * turn_angles[idx] + alpha * turn_angles[min(idx + 1, len(turn_angles) - 1)]
        SMOOTH = 0.92
        state['smoothed_turn'] = state['smoothed_turn'] * SMOOTH + raw_turn * (1 - SMOOTH)
        # 无人机视角的“朝向”有较大惯性：只做缓慢插值，短时的小转弯不会立刻改变摄像机朝向
        inst_fwd_xy = cur_forward[:2]
        n_inst = np.linalg.norm(inst_fwd_xy)
        if n_inst < 1e-6:
            inst_fwd_xy = np.array([1.0, 0.0], dtype=float)
        else:
            inst_fwd_xy = inst_fwd_xy / n_inst
        cam_fwd_xy = state.get('cam_forward_xy', inst_fwd_xy)
        BETA = 0.02  # 越小越“钝”，只有持续转弯才逐渐转动摄像机
        cam_fwd_xy = (1.0 - BETA) * cam_fwd_xy + BETA * inst_fwd_xy
        n_cam = np.linalg.norm(cam_fwd_xy)
        if n_cam > 1e-6:
            cam_fwd_xy = cam_fwd_xy / n_cam
        state['cam_forward_xy'] = cam_fwd_xy
        
        # 绘制闪烁蓝点 (球体)
        glEnable(GL_LIGHTING) # 球体需要光照才有立体感
        glPushMatrix()
        glTranslatef(cur_pos[0], cur_pos[1], cur_pos[2])
        
        # 闪烁效果: 大小脉冲
        base_radius = 1.0 # 缩小一半
        pulse = 0.25 * math.sin(current_sys_time * 10) # +/- 0.25
        radius = base_radius + pulse
        
        # 蓝色材质
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, (0.0, 0.5, 1.0, 1.0))
        glMaterialfv(GL_FRONT, GL_SPECULAR, (1.0, 1.0, 1.0, 1.0))
        glMaterialf(GL_FRONT, GL_SHININESS, 50.0)
        # 稍微自发光一点，防止在阴影里太暗
        glMaterialfv(GL_FRONT, GL_EMISSION, (0.0, 0.2, 0.4, 1.0))
        
        quad = gluNewQuadric()
        gluSphere(quad, radius, 16, 16)
        
        glPopMatrix()
        
        # 恢复材质
        glMaterialfv(GL_FRONT, GL_EMISSION, (0.0, 0.0, 0.0, 1.0))
        glDisable(GL_LIGHTING)
        
        # 外圈光晕 (仍然用点或透明球体)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        
        glPushMatrix()
        glTranslatef(cur_pos[0], cur_pos[1], cur_pos[2])
        glColor4f(0.0, 0.5, 1.0, 0.3)
        quad_glow = gluNewQuadric()
        # 光晕球体更大，无光照
        gluSphere(quad_glow, radius * 2.0, 16, 16)
        glPopMatrix()
        
        glDisable(GL_BLEND)
        
        # ----------------------------------------
        
        # 绘制 POI 标记 (省略部分，保持原有逻辑)
        if poi_pts:
             # 1. 3D 标记
            glDisable(GL_TEXTURE_2D)
            for poi in poi_pts:
                px, py, pz = poi['pos']
                glColor3f(1.0, 1.0, 0.0)
                glLineWidth(1.0)
                glBegin(GL_LINES)
                glVertex3f(px, py, pz); glVertex3f(px, py, pz + 15.0)
                glEnd()
                glPointSize(6.0)
                glBegin(GL_POINTS)
                glVertex3f(px, py, pz + 15.0)
                glEnd()

            # 2. 2D 标签
            model_view = glGetDoublev(GL_MODELVIEW_MATRIX)
            projection = glGetDoublev(GL_PROJECTION_MATRIX)
            viewport = glGetIntegerv(GL_VIEWPORT)
            
            glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); glOrtho(0, width, 0, height, -1, 1)
            glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
            
            glDisable(GL_LIGHTING); glDisable(GL_DEPTH_TEST); glEnable(GL_TEXTURE_2D); glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glColor4f(1, 1, 1, 1)
            
            for poi in poi_pts:
                px, py, pz = poi['pos']
                try: sx, sy, sz = gluProject(px, py, pz + 15.0, model_view, projection, viewport)
                except: continue
                if 0.0 <= sz <= 1.0:
                    tid, w, h = poi['texture_id'], poi['w'], poi['h']
                    x_pos, y_pos = sx - w / 2, sy + 8
                    glBindTexture(GL_TEXTURE_2D, tid)
                    glBegin(GL_QUADS)
                    glTexCoord2f(0, 0); glVertex2f(x_pos, y_pos)
                    glTexCoord2f(1, 0); glVertex2f(x_pos + w, y_pos)
                    glTexCoord2f(1, 1); glVertex2f(x_pos + w, y_pos + h)
                    glTexCoord2f(0, 1); glVertex2f(x_pos, y_pos + h)
                    glEnd()
            
            glDisable(GL_BLEND); glDisable(GL_TEXTURE_2D); glEnable(GL_DEPTH_TEST); glEnable(GL_LIGHTING)
            glMatrixMode(GL_PROJECTION); glPopMatrix(); glMatrixMode(GL_MODELVIEW); glPopMatrix()

        glEnable(GL_LIGHTING)
        
        # --- 播放时：左上角导航小窗（俯视轨迹小地图，200m×200m）---
        if state['playing']:
            win_w, win_h = glfw.get_window_size(window)
            scale_x = width / max(1, win_w)
            scale_y = height / max(1, win_h)
            nav_vp_x = int(NAV_X * scale_x)
            nav_vp_y = int(height - (NAV_Y + NAV_H) * scale_y)
            nav_vp_w = int(NAV_W * scale_x)
            nav_vp_h = int(NAV_H * scale_y)
            if nav_vp_w > 0 and nav_vp_h > 0:
                glEnable(GL_SCISSOR_TEST)
                glScissor(nav_vp_x, nav_vp_y, nav_vp_w, nav_vp_h)
                glClearColor(0.1, 0.1, 0.1, 1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                glScissor(nav_vp_x, nav_vp_y, nav_vp_w, nav_vp_h)
                
                glViewport(nav_vp_x, nav_vp_y, nav_vp_w, nav_vp_h)
                glMatrixMode(GL_PROJECTION)
                glLoadIdentity()
                half = state.get('mini_map_half_extent', 100.0)
                cx, cy = float(cur_pos[0]), float(cur_pos[1])
                left, right = cx - half, cx + half
                bottom, top = cy - half, cy + half
                glOrtho(left, right, bottom, top, -1000.0, 1000.0)
                glMatrixMode(GL_MODELVIEW)
                glLoadIdentity()
                
                # 绘制小地图中的地形（带深度和光照）
                glEnable(GL_DEPTH_TEST)
                glEnable(GL_LIGHTING)
                glEnableClientState(GL_VERTEX_ARRAY)
                glEnableClientState(GL_NORMAL_ARRAY)
                glEnableClientState(GL_COLOR_ARRAY)
                glVertexPointer(3, GL_FLOAT, 0, v_data)
                glNormalPointer(GL_FLOAT, 0, n_data)
                glColorPointer(3, GL_FLOAT, 0, c_data)
                glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, indices)
                glDisableClientState(GL_VERTEX_ARRAY)
                glDisableClientState(GL_NORMAL_ARRAY)
                glDisableClientState(GL_COLOR_ARRAY)

                # 轨迹和当前位置覆盖在地形之上
                glDisable(GL_LIGHTING)
                # 为小地图生成更平滑的轨迹点，减小锯齿感（重复平滑两次）
                mini_path_pts = path_pts
                if len(path_pts) >= 3:
                    for _ in range(2):
                        smoothed = np.empty_like(mini_path_pts)
                        smoothed[0] = mini_path_pts[0]
                        smoothed[-1] = mini_path_pts[-1]
                        smoothed[1:-1] = (mini_path_pts[:-2] + 2 * mini_path_pts[1:-1] + mini_path_pts[2:]) / 4.0
                        mini_path_pts = smoothed
                # 开启线条抗锯齿
                glEnable(GL_LINE_SMOOTH)
                glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)
                # 用两层宽线叠加，形成类似“公路”的效果
                glLineWidth(8.0)
                glColor3f(0.8, 0.8, 0.8)
                glBegin(GL_LINE_STRIP)
                for p in mini_path_pts:
                    glVertex3f(p[0], p[1], p[2])
                glEnd()
                glLineWidth(4.0)
                glColor3f(1.0, 1.0, 1.0)
                glBegin(GL_LINE_STRIP)
                for p in mini_path_pts:
                    glVertex3f(p[0], p[1], p[2])
                glEnd()
                glDisable(GL_LINE_SMOOTH)
                glPointSize(6.0)
                glColor3f(0.0, 0.6, 1.0)
                glBegin(GL_POINTS)
                glVertex3f(cur_pos[0], cur_pos[1], cur_pos[2])
                glEnd()
                glEnable(GL_LIGHTING)
                
                glDisable(GL_SCISSOR_TEST)
            
            glViewport(0, 0, width, height)
        
        # --- 绘制 UI (2D 覆盖层) ---
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        # 使用逻辑窗口大小 (匹配鼠标坐标)
        win_w, win_h = glfw.get_window_size(window)
        glOrtho(0, win_w, win_h, 0, -1, 1) # 左上角 (0,0), Y 向下
        
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        
        glDisable(GL_DEPTH_TEST) # 确保 UI 在最上层
        glDisable(GL_LIGHTING)
        
        # 0. 播放时：导航小窗边框
        if state['playing']:
            glColor4f(1, 1, 1, 0.9)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glLineWidth(2.0)
            glBegin(GL_LINE_LOOP)
            glVertex2f(NAV_X, NAV_Y)
            glVertex2f(NAV_X + NAV_W, NAV_Y)
            glVertex2f(NAV_X + NAV_W, NAV_Y + NAV_H)
            glVertex2f(NAV_X, NAV_Y + NAV_H)
            glEnd()
            glDisable(GL_BLEND)
        
        # 1. Z-Scale 滑杆
        glColor3f(0.5, 0.5, 0.5) # 背景
        glBegin(GL_QUADS)
        glVertex2f(UI_X, UI_Y); glVertex2f(UI_X + UI_W, UI_Y)
        glVertex2f(UI_X + UI_W, UI_Y + UI_H); glVertex2f(UI_X, UI_Y + UI_H)
        glEnd()
        
        # 滑块
        ratio = (state['z_scale'] - 1.0) / 4.0
        slider_x = UI_X + ratio * UI_W
        slider_w = 10
        glColor3f(1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        glVertex2f(slider_x - slider_w/2, UI_Y - 2); glVertex2f(slider_x + slider_w/2, UI_Y - 2)
        glVertex2f(slider_x + slider_w/2, UI_Y + UI_H + 2); glVertex2f(slider_x - slider_w/2, UI_Y + UI_H + 2)
        glEnd()
        
        # 2. Speed 滑杆
        glColor3f(0.5, 0.5, 0.5) # 背景
        glBegin(GL_QUADS)
        glVertex2f(UI_X, SPEED_UI_Y); glVertex2f(UI_X + UI_W, SPEED_UI_Y)
        glVertex2f(UI_X + UI_W, SPEED_UI_Y + UI_H); glVertex2f(UI_X, SPEED_UI_Y + UI_H)
        glEnd()
        
        # 滑块
        ratio = (state['speed_scale'] - 1.0) / 49.0
        slider_x = UI_X + ratio * UI_W
        glColor3f(1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        glVertex2f(slider_x - slider_w/2, SPEED_UI_Y - 2); glVertex2f(slider_x + slider_w/2, SPEED_UI_Y - 2)
        glVertex2f(slider_x + slider_w/2, SPEED_UI_Y + UI_H + 2); glVertex2f(slider_x - slider_w/2, SPEED_UI_Y + UI_H + 2)
        glEnd()
        
        # 3. Play/Pause 按钮
        if state['playing']:
            glColor3f(0.8, 0.3, 0.3) # 红色暂停
        else:
            glColor3f(0.3, 0.8, 0.3) # 绿色播放
        glBegin(GL_QUADS)
        glVertex2f(UI_X, PLAY_BTN_Y); glVertex2f(UI_X + PLAY_BTN_W, PLAY_BTN_Y)
        glVertex2f(UI_X + PLAY_BTN_W, PLAY_BTN_Y + UI_H); glVertex2f(UI_X, PLAY_BTN_Y + UI_H)
        glEnd()
        
        win_w, win_h = glfw.get_window_size(window)
        prog_margin_x = 20.0
        prog_width = max(10.0, win_w - prog_margin_x * 2.0)
        prog_height = 10.0
        prog_y = win_h - 30.0
        prog_x = prog_margin_x
        glColor3f(0.3, 0.3, 0.3)
        glBegin(GL_QUADS)
        glVertex2f(prog_x, prog_y)
        glVertex2f(prog_x + prog_width, prog_y)
        glVertex2f(prog_x + prog_width, prog_y + prog_height)
        glVertex2f(prog_x, prog_y + prog_height)
        glEnd()
        if total_duration > 0:
            ratio = max(0.0, min(1.0, state['playback_time'] / total_duration))
            fill_w = prog_width * ratio
            glColor3f(0.2, 0.7, 1.0)
            glBegin(GL_QUADS)
            glVertex2f(prog_x, prog_y)
            glVertex2f(prog_x + fill_w, prog_y)
            glVertex2f(prog_x + fill_w, prog_y + prog_height)
            glVertex2f(prog_x, prog_y + prog_height)
            glEnd()
        
        # 恢复状态
        glEnable(GL_LIGHTING)
        glEnable(GL_DEPTH_TEST)
        
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()
        
        glfw.swap_buffers(window)
        glfw.poll_events()

        
    glfw.terminate()


def plot_terrain_3d_matplotlib(track_points, dem_path, output_file, quality='med', metric=False, project=None):
    """
    使用 Matplotlib 生成静态 3D 地形预览图
    """
    print("正在生成静态预览图 (Matplotlib)...")
    
    lats = [pt[0] for pt in track_points]
    lons = [pt[1] for pt in track_points]
    
    bbox = (min(lons), min(lats), max(lons), max(lats))
    try:
        dem, win_transform, dem_crs = load_dem_window(dem_path, bbox)
    except Exception as e:
        print(f"读取 DEM 失败: {e}")
        return

    h, w = dem.shape
    
    # 根据质量设置降采样
    max_size = {'low': 100, 'med': 200, 'high': 400}[quality]
    stride_row = max(1, h // max_size)
    stride_col = max(1, w // max_size)
    
    dem_display = dem[::stride_row, ::stride_col]
    X, Y = meshgrid_from_affine(win_transform, w, h)
    X_display = X[::stride_row, ::stride_col]
    Y_display = Y[::stride_row, ::stride_col]
    
    # 处理投影/坐标转换
    if project == 'utm':
        try:
            from pyproj import Transformer
            # 简单的 UTM 带号计算 (仅适用于北半球非极地)
            zone = int(lats[0]//10 + 31) # 粗略估计，实际上应该根据经度算: (lon + 180) / 6 + 1
            zone = int((lons[0] + 180) / 6) + 1
            crs_utm = f"EPSG:326{zone}"
            print(f"应用 UTM 投影: {crs_utm}")
            transformer = Transformer.from_crs("EPSG:4326", crs_utm, always_xy=True)
            
            # 转换网格
            X_utm, Y_utm = transformer.transform(X_display.flatten(), Y_display.flatten())
            X_display = X_utm.reshape(X_display.shape)
            Y_display = Y_utm.reshape(Y_display.shape)
            
        except ImportError:
            print("警告: 未安装 pyproj，无法进行 UTM 投影。")
            project = None
            
    elif metric:
        # 简单的米制近似
        lon_correction = math.cos(math.radians(sum(lats)/len(lats)))
        X_display *= 111319.9 * lon_correction
        Y_display *= 111319.9

    # 地形阴影
    try:
        ls = LightSource(azdeg=315, altdeg=45)
        shaded = ls.shade(dem_display, cmap=plt.cm.terrain, vert_exag=1.0, blend_mode='soft')
    except Exception:
        shaded = None

    # 路径坐标
    xs, ys = coords_wgs84_to_dem_crs(lons, lats, dem_crs)
    inv_transform = ~win_transform
    cols, rows = inv_transform * (xs, ys)
    rows = np.clip(rows, 0, h - 1).astype(int)
    cols = np.clip(cols, 0, w - 1).astype(int)
    path_z = dem[rows, cols] + 5.0
    
    # 转换路径坐标
    if project == 'utm':
        xs_utm, ys_utm = transformer.transform(xs, ys)
        xs = xs_utm
        ys = ys_utm
    elif metric:
        xs *= 111319.9 * lon_correction
        ys *= 111319.9

    fig = plt.figure(figsize=(14, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    if shaded is not None:
        ax.plot_surface(X_display, Y_display, dem_display, rstride=1, cstride=1, 
                       facecolors=shaded, linewidth=0, antialiased=False, alpha=0.95)
    else:
        ax.plot_surface(X_display, Y_display, dem_display, rstride=1, cstride=1, 
                       cmap=plt.cm.terrain, linewidth=0, antialiased=False, alpha=0.95)
    
    ax.plot(xs, ys, path_z, color='red', linewidth=2.0, zorder=10)
    
    ax.set_title('3D 地形轨迹图', fontsize=16, fontweight='bold')
    
    # 调整视角
    ax.view_init(elev=30, azim=-60)
    
    # 设置比例
    if project == 'utm' or metric:
        ax.set_box_aspect([1, 1, 0.2]) # Z 轴压缩
        
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    print(f"成功: 静态预览图已保存到 -> {output_file}")
    plt.show()


def main():
    # 1. 优先加载项目根目录的 .env
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    root_env = os.path.join(project_root, '.env')
    
    if os.path.exists(root_env):
        print(f"正在加载环境变量: {root_env}")
        load_dotenv(root_env)
    
    # 2. 尝试加载当前目录或默认位置的 .env
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='GPX 3D 地形可视化一键生成脚本')
    parser.add_argument('gpx_file', help='GPX 文件路径')
    parser.add_argument('--api_key', help='OpenTopography API Key')
    parser.add_argument('--quality', choices=['low', 'med', 'high'], default='med', help='绘制质量 (Matplotlib)')
    parser.add_argument('--metric', action='store_true', help='启用近似米制坐标 (Matplotlib)')
    parser.add_argument('--project', choices=['utm'], help='投影到 UTM 坐标 (Matplotlib)')
    parser.add_argument('--renderer', choices=['matplotlib', 'plotly', 'opengl'], default='opengl', 
                        help='选择渲染器: matplotlib (静态/慢), plotly (网页交互), opengl (高性能原生)')
    
    args = parser.parse_args()
    
    gpx_file = args.gpx_file
    if not os.path.exists(gpx_file):
        print(f"错误: 找不到文件 {gpx_file}")
        sys.exit(1)
        
    base_name = os.path.splitext(os.path.basename(gpx_file))[0]
    dir_name = os.path.dirname(os.path.abspath(gpx_file))
    dem_file = os.path.join(dir_name, f"{base_name}_dem.tif")
    
    # 渲染器回退逻辑
    renderer = args.renderer
            
    if renderer == 'plotly' and not HAS_PLOTLY:
        print("警告: 未安装 Plotly，回退到 Matplotlib。")
        renderer = 'matplotlib'

    out_ext = '.html' if renderer == 'plotly' else '.png'
    out_file = os.path.join(dir_name, f"{base_name}_3d{out_ext}")

    # 1. 检查/下载 DEM (复用)
    dem_exists = os.path.exists(dem_file)
    if dem_exists:
        print(f"发现已存在的 DEM 文件: {dem_file}，跳过下载。")
    else:
        api_key = args.api_key or os.environ.get('OPENTOPOGRAPHY_API_KEY')
        if not api_key:
            print("错误: 本地未找到 DEM 文件，且未提供 OPENTOPOGRAPHY_API_KEY，无法下载。")
            print("请在 .env 文件中配置: OPENTOPOGRAPHY_API_KEY=your_key")
            print("或者作为参数提供: --api_key your_key")
            print("申请免费 API Key: https://portal.opentopography.org/myopentopo")
            sys.exit(1)
            
        print("正在获取 GPX 边界...")
        bounds = get_gpx_bounds(gpx_file)
        success = download_dem(api_key, bounds, dem_file)
        if not success:
            print("DEM 下载失败，程序终止。")
            sys.exit(1)

    # 2. 解析 GPX
    print(f"正在解析 GPX: {gpx_file}")
    track_points = parse_gpx_points(gpx_file)
    if not track_points:
        print("未找到轨迹点，程序终止。")
        sys.exit(1)

    # 3. 绘制
    if renderer == 'plotly':
        plot_terrain_3d_interactive_plotly(track_points, dem_file, out_file)
    elif renderer == 'opengl':
        plot_terrain_3d_opengl(track_points, dem_file)
    else:
        plot_terrain_3d_matplotlib(track_points, dem_file, out_file, 
                                  quality=args.quality, metric=args.metric, project=args.project)


if __name__ == "__main__":
    main()
