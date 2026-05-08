import open3d as o3d

pcd = o3d.io.read_point_cloud("logs/ergoCub_floor0_cafeteria.ply")

#print(pcd)
#print("Has colors:", pcd.has_colors())

o3d.visualization.draw_geometries([pcd])
