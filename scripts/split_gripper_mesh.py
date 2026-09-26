from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

root = Path(__file__).resolve().parents[1]
source = root / "simulation" / "dofbot_description" / "meshes" / "link5.STL"
output_dir = source.parent
triangle_dtype = np.dtype(
    [("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")]
)


def find(parent: np.ndarray, node: int) -> int:
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = int(parent[node])
    return node


def union(parent: np.ndarray, sizes: np.ndarray, first: int, second: int) -> None:
    first_root = find(parent, first)
    second_root = find(parent, second)
    if first_root == second_root:
        return
    if sizes[first_root] < sizes[second_root]:
        first_root, second_root = second_root, first_root
    parent[second_root] = first_root
    sizes[first_root] += sizes[second_root]


def write_binary_stl(path: Path, triangles: np.ndarray) -> None:
    header = f"Dofbot split mesh: {path.stem}".encode("ascii")[:80].ljust(80, b" ")
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(struct.pack("<I", len(triangles)))
        triangles.tofile(handle)


with source.open("rb") as handle:
    handle.read(80)
    triangle_count = struct.unpack("<I", handle.read(4))[0]
    triangles = np.fromfile(handle, dtype=triangle_dtype, count=triangle_count)

parents = np.arange(triangle_count)
sizes = np.ones(triangle_count, dtype=int)
vertex_owners: dict[tuple[float, float, float], int] = {}
for triangle_index, vertices in enumerate(triangles["vertices"]):
    for vertex in vertices:
        key = tuple(float(value) for value in np.round(vertex, 7))
        if key in vertex_owners:
            union(parents, sizes, triangle_index, vertex_owners[key])
        else:
            vertex_owners[key] = triangle_index

components: dict[int, list[int]] = {}
for triangle_index in range(triangle_count):
    components.setdefault(find(parents, triangle_index), []).append(triangle_index)

groups: dict[str, list[int]] = {"base": [], "left_finger": [], "right_finger": []}
for indices in components.values():
    vertices = triangles["vertices"][indices].reshape(-1, 3)
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    is_tip_component = minimum[2] >= 0.039 and maximum[2] >= 0.060
    if is_tip_component and maximum[0] <= 0.0025 and minimum[0] < -0.020:
        group = "left_finger"
    elif is_tip_component and minimum[0] >= -0.0025 and maximum[0] > 0.020:
        group = "right_finger"
    else:
        group = "base"
    groups[group].extend(indices)

for group, indices in groups.items():
    output = output_dir / f"link5_{group}.STL"
    selected = triangles[np.asarray(sorted(indices))]
    write_binary_stl(output, selected)
    vertices = selected["vertices"].reshape(-1, 3)
    print(
        f"{output.name}: triangles={len(selected)}, "
        f"min={vertices.min(axis=0).round(5)}, max={vertices.max(axis=0).round(5)}"
    )
