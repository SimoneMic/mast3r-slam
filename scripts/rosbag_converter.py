import os
import numpy as np
import cv2
from bisect import bisect_left

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
#from cv_bridge import CvBridge

import tf2_ros
import rclpy
from rclpy.time import Time

# ==== CONFIG ====
BAG_FOLDER = "/home/user1/rosbags/ergocub_floor0_newmap_0/rosbag2_2025_08_04-15_21_45"
BAG_NAME = "rosbag2_2025_08_04-15_21_45_0.mcap"
BAG_PATH = BAG_FOLDER + "/" + BAG_NAME
OUTPUT_DIR = "/home/user1/mast3r-slam/datasets/rosbags/ergocub_floor0_newmap_0"

RGB_TOPIC = "/camera/rgbd/img"
DEPTH_TOPIC = "/camera/rgbd/depth"
TF_TOPIC = "/tf"
TF_STATIC_TOPIC = "/tf_static"

CAMERA_FRAME = "compensated_realsense_frame"
WORLD_FRAME = "map"

SYNC_TOL = 0.05  # 20 ms

# ==== SETUP ====
os.makedirs(f"{OUTPUT_DIR}/rgb", exist_ok=True)
os.makedirs(f"{OUTPUT_DIR}/depth", exist_ok=True)

rgb_txt = open(f"{OUTPUT_DIR}/rgb.txt", "w")
depth_txt = open(f"{OUTPUT_DIR}/depth.txt", "w")
gt_txt = open(f"{OUTPUT_DIR}/groundtruth.txt", "w")

rgb_txt.write("# timestamp filename\n")
depth_txt.write("# timestamp filename\n")
gt_txt.write("# timestamp tx ty tz qx qy qz qw\n")

# ==== ROSBAG READER ====
storage_options = rosbag2_py.StorageOptions(uri=BAG_PATH, storage_id='mcap')
converter_options = rosbag2_py.ConverterOptions('', '')
reader = rosbag2_py.SequentialReader()
reader.open(storage_options, converter_options)

topic_types = reader.get_all_topics_and_types()
type_map = {t.name: t.type for t in topic_types}

def get_msg(topic, data):
    return deserialize_message(data, get_message(type_map[topic]))

# ==== STORAGE ====
rgb_data = []
depth_data = []
tf_msgs = []
tf_static_msgs = []

# ==== READ ALL ====
while reader.has_next():
    topic, data, t = reader.read_next()
    ts = t * 1e-9

    if topic == RGB_TOPIC:
        msg = get_msg(topic, data)
        rgb_data.append((ts, msg))

    elif topic == DEPTH_TOPIC:
        msg = get_msg(topic, data)
        depth_data.append((ts, msg))

    elif topic == TF_TOPIC:
        msg = get_msg(topic, data)
        tf_msgs.append(msg)

    elif topic == TF_STATIC_TOPIC:
        msg = get_msg(topic, data)
        tf_static_msgs.append(msg)

print(f"Loaded {len(rgb_data)} RGB, {len(depth_data)} depth frames")

# ==== SORT ====
rgb_data.sort(key=lambda x: x[0])
depth_data.sort(key=lambda x: x[0])

depth_times = [d[0] for d in depth_data]

# ==== BUILD TF BUFFER ====
rclpy.init()
node = rclpy.create_node("tf_buffer_node")
tf_buffer = tf2_ros.Buffer(cache_time=rclpy.duration.Duration(seconds=1e4))  # effectively infinite
tf_listener = tf2_ros.TransformListener(tf_buffer, node)

for msg in tf_static_msgs:
    for t in msg.transforms:
        tf_buffer.set_transform_static(t, "static_authority")
for msg in tf_msgs:
    for t in msg.transforms:
        tf_buffer.set_transform(t, "default_authority")

print("TF buffer ready")

# ==== HELPER: FIND CLOSEST DEPTH ====
def find_closest_depth(ts):
    idx = bisect_left(depth_times, ts)
    candidates = []
    if idx < len(depth_times):
        candidates.append(depth_data[idx])
    if idx > 0:
        candidates.append(depth_data[idx - 1])

    if not candidates:
        return None

    best = min(candidates, key=lambda x: abs(x[0] - ts))
    if abs(best[0] - ts) < SYNC_TOL:
        return best
    return None

# ==== MAIN LOOP ====
for i, (ts, rgb_msg) in enumerate(rgb_data):

    depth_match = find_closest_depth(ts)
    if depth_match is None:
        print(f"No depth for RGB at {ts}")
        continue
    print(f"RGB frames: {i} / {len(rgb_data)}")
    print(f"Depth frames: {i} / {len(depth_data)}")

    depth_ts, depth_msg = depth_match

    # ==== TF lookup ====
    try:
        transform = tf_buffer.lookup_transform(
            WORLD_FRAME,
            CAMERA_FRAME,
            Time(seconds=ts)
        )
    except Exception as ex:
        print(f"{ex=}")
        continue

    # ==== SAVE RGB ====
    rgb_img = np.frombuffer(rgb_msg.data, dtype=np.uint8).reshape(rgb_msg.height, rgb_msg.width, 3).copy()
    rgb_name = f"{ts:.6f}.png"
    write_ok = cv2.imwrite(f"{OUTPUT_DIR}/rgb/{rgb_name}", rgb_img)
    if not write_ok:
        print(f"Failed to write {rgb_name}")

    # ==== SAVE DEPTH ====
    depth_img = np.frombuffer(depth_msg.data, dtype=np.float32).reshape(depth_msg.height, depth_msg.width).copy()
    if depth_img.dtype != np.uint16:
        depth_img = (depth_img * 1000).astype(np.uint16)

    depth_name = f"{ts:.6f}.png"
    write_ok = cv2.imwrite(f"{OUTPUT_DIR}/depth/{depth_name}", depth_img)
    if not write_ok:
        print(f"Failed to write {depth_name}")

    # ==== WRITE TXT ====
    rgb_txt.write(f"{ts:.6f} rgb/{rgb_name}\n")
    depth_txt.write(f"{ts:.6f} depth/{depth_name}\n")

    t = transform.transform.translation
    q = transform.transform.rotation

    gt_txt.write(
        f"{ts:.6f} "
        f"{t.x} {t.y} {t.z} "
        f"{q.x} {q.y} {q.z} {q.w}\n"
    )

# ==== CLEANUP ====
rgb_txt.close()
depth_txt.close()
gt_txt.close()

rclpy.shutdown()

print("Done. Dataset ready.")