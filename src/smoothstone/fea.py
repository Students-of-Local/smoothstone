"""Voxel finite elements for printed parts: hex8 trilinear bricks on a regular grid.

The part is cut into equal cubes. Each cube is one 8-node brick with the same stiffness matrix up to a
scale, so the global matrix is built by stencil (no per-element loops) and solved with conjugate
gradients preconditioned by smoothed aggregation multigrid (pyamg, MIT). The material is transversely
isotropic: one stiffness in the layer plane, another across layers, the build axis set per solve.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp

AXES = "xyz"
CORNERS = np.array([(i, j, k) for k in (0, 1) for j in (0, 1) for i in (0, 1)])  # local node a = i + 2j + 4k


# material

def stiffness(e_xy: float, e_z: float, nu: float, build: int = 2) -> np.ndarray:
    """6x6 stiffness (Voigt: xx yy zz yz xz xy, engineering shear) of a transversely isotropic solid whose
    weak axis (across layers) is `build` (0 x, 1 y, 2 z). Moduli in MPa."""
    s = np.zeros((6, 6))
    s[0, 0] = s[1, 1] = 1 / e_xy
    s[2, 2] = 1 / e_z
    s[0, 1] = s[1, 0] = -nu / e_xy
    s[0, 2] = s[2, 0] = s[1, 2] = s[2, 1] = -nu / e_xy  # nu_31 / E_3 = nu_13 / E_1
    g_z = e_z / (2 * (1 + nu))  # shear across layers follows the Z stiffness (assumption)
    s[3, 3] = s[4, 4] = 1 / g_z
    s[5, 5] = 2 * (1 + nu) / e_xy
    c = np.linalg.inv(s)
    if build == 2:
        return c
    # move the weak axis from z to `build`: permute normal and shear components alike
    order = {0: [2, 0, 1], 1: [0, 2, 1]}[build]  # new axis i takes old axis order[i]
    normal = order
    shear_of = {frozenset((1, 2)): 3, frozenset((0, 2)): 4, frozenset((0, 1)): 5}
    shear = [shear_of[frozenset((order[1], order[2]))], shear_of[frozenset((order[0], order[2]))],
             shear_of[frozenset((order[0], order[1]))]]
    p = normal + shear
    return c[np.ix_(p, p)]


def _bmatrix(xi: float, eta: float, zeta: float, h: float) -> np.ndarray:
    """6 x 24 strain-displacement matrix of a cube of side h at a natural point."""
    b = np.zeros((6, 24))
    for a, (i, j, k) in enumerate(CORNERS):
        si, sj, sk = 2 * i - 1, 2 * j - 1, 2 * k - 1
        dx = si * (1 + sj * eta) * (1 + sk * zeta) / 8 * 2 / h
        dy = sj * (1 + si * xi) * (1 + sk * zeta) / 8 * 2 / h
        dz = sk * (1 + si * xi) * (1 + sj * eta) / 8 * 2 / h
        c = 3 * a
        b[0, c], b[1, c + 1], b[2, c + 2] = dx, dy, dz
        b[3, c + 1], b[3, c + 2] = dz, dy
        b[4, c], b[4, c + 2] = dz, dx
        b[5, c], b[5, c + 1] = dy, dx
    return b


def element_matrix(c: np.ndarray, h: float) -> np.ndarray:
    """24 x 24 stiffness of one brick, 2 x 2 x 2 Gauss points."""
    g = 1 / np.sqrt(3)
    ke = np.zeros((24, 24))
    for xi, eta, zeta in itertools.product((-g, g), repeat=3):
        b = _bmatrix(xi, eta, zeta, h)
        ke += b.T @ c @ b * (h / 2) ** 3
    return ke


# grid

@dataclass
class Grid:
    solid: np.ndarray  # bool (nx, ny, nz), one cube per True
    pitch: float  # mm
    origin: np.ndarray  # mm, corner of cell (0, 0, 0)

    @property
    def shape(self):
        return self.solid.shape

    def cells(self) -> np.ndarray:
        return np.argwhere(self.solid)

    def centers(self, idx: np.ndarray | None = None) -> np.ndarray:
        idx = self.cells() if idx is None else idx
        return self.origin + (idx + 0.5) * self.pitch


def voxelize(mesh, pitch: float) -> Grid:
    """Cells whose centers are inside the mesh, by casting one ray per column along z and counting crossings."""
    lo, hi = mesh.bounds
    n = np.maximum(np.ceil((hi - lo) / pitch).astype(int), 1)
    origin = lo - (n * pitch - (hi - lo)) / 2
    xs = origin[0] + (np.arange(n[0]) + 0.5) * pitch
    ys = origin[1] + (np.arange(n[1]) + 0.5) * pitch
    zs = origin[2] + (np.arange(n[2]) + 0.5) * pitch
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    # a hair off the grid lines, so a ray never runs exactly along an edge of the mesh
    ox = gx.ravel() + pitch * 1.37e-4
    oy = gy.ravel() + pitch * 2.11e-4
    origins = np.column_stack([ox, oy, np.full(ox.size, lo[2] - pitch)])
    dirs = np.tile([0.0, 0.0, 1.0], (ox.size, 1))
    locs, ray, _ = mesh.ray.intersects_location(origins, dirs, multiple_hits=True)
    solid = np.zeros(n, dtype=bool)
    if len(ray):
        order = np.lexsort((locs[:, 2], ray))
        ray, hz = ray[order], locs[order, 2]
        starts = np.searchsorted(ray, np.arange(ox.size))
        ends = np.searchsorted(ray, np.arange(ox.size), side="right")
        for r in np.nonzero(ends > starts)[0]:
            z = np.unique(np.round(hz[starts[r]:ends[r]], 9))
            inside = np.searchsorted(z, zs) % 2 == 1
            solid[r // n[1], r % n[1], :] = inside
    return Grid(solid, float(pitch), origin)


def shell(grid: Grid, wall_mm: float, density: float, exponent: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Per solid cell: the share of it inside the solid skin `wall_mm` deep, and its stiffness weight. The rest is
    infill at `density` (0 to 1), as stiff as density ** exponent of solid (Gibson-Ashby; refs any.infill_exponent).
    The skin is the same depth on every face, top and bottom included (assumption: slicers lay about as many
    solid layers as wall lines)."""
    from scipy.ndimage import distance_transform_edt

    h = grid.pitch
    depth = distance_transform_edt(np.pad(grid.solid, 1), sampling=h)[1:-1, 1:-1, 1:-1][grid.solid]
    wall = np.clip((wall_mm - (depth - h)) / h, 0.0, 1.0)  # a cell spans depth - h to depth below the surface
    return wall, wall + (1 - wall) * density ** exponent


def smoothed(grid: Grid, values: np.ndarray) -> np.ndarray:
    """Each cell's value averaged with its solid neighbors in a 3 x 3 x 3 block: takes the edge off a stair step."""
    from scipy.ndimage import uniform_filter

    full = np.zeros(grid.shape)
    full[grid.solid] = values
    total = uniform_filter(full, size=3, mode="constant")
    count = uniform_filter(grid.solid.astype(float), size=3, mode="constant")
    return (total / np.maximum(count, 1e-9))[grid.solid]


# solve

@dataclass
class Model:
    grid: Grid
    weight: np.ndarray  # per solid cell: stiffness scale (1 solid wall, rho^2 infill, mixed at the shell edge)
    c: np.ndarray  # 6 x 6 stiffness of solid printed material, MPa
    nodes: np.ndarray = field(init=False)  # (nn, 3) grid index of each active node
    elem: np.ndarray = field(init=False)  # (ne, 8) node ids

    def __post_init__(self):
        cells = self.grid.cells()
        nx, ny, nz = self.grid.shape
        full = np.full((nx + 1, ny + 1, nz + 1), -1, dtype=np.int64)
        corner = cells[:, None, :] + CORNERS[None, :, :]
        used = np.zeros(full.shape, dtype=bool)
        used[corner[..., 0], corner[..., 1], corner[..., 2]] = True
        self.nodes = np.argwhere(used)
        full[used] = np.arange(len(self.nodes))
        self.full = full
        self.elem = full[corner[..., 0], corner[..., 1], corner[..., 2]]

    @property
    def coords(self) -> np.ndarray:
        return self.grid.origin + self.nodes * self.grid.pitch

    def matrix(self) -> sp.csr_matrix:
        """Global stiffness by stencil: block (a, b) of every element lands on node n_a at offset b - a.
        For a fixed local slot a each element owns a different node, so plain += never collides."""
        ke = element_matrix(self.c, self.grid.pitch)
        nn = len(self.nodes)
        blocks = np.zeros((nn, 27, 3, 3))
        off = lambda d: int((d[0] + 1) + 3 * (d[1] + 1) + 9 * (d[2] + 1))
        w = self.weight[:, None, None]
        for a in range(8):
            na = self.elem[:, a]
            for b in range(8):
                blocks[na, off(CORNERS[b] - CORNERS[a])] += w * ke[3 * a:3 * a + 3, 3 * b:3 * b + 3]
        # columns: the neighbor node at each offset, where one exists
        d = np.array([(i, j, k) for k in (-1, 0, 1) for j in (-1, 0, 1) for i in (-1, 0, 1)])
        nb = self.nodes[:, None, :] + d[None, :, :]
        shape = np.array(self.full.shape)
        ok = np.all((nb >= 0) & (nb < shape), axis=2)
        col = np.full(ok.shape, -1, dtype=np.int64)
        col[ok] = self.full[nb[ok][:, 0], nb[ok][:, 1], nb[ok][:, 2]]
        keep = (col >= 0) & np.any(blocks != 0, axis=(2, 3))
        k = sp.bsr_matrix((blocks[keep], col[keep], np.r_[0, np.cumsum(keep.sum(1))]), shape=(3 * nn, 3 * nn))
        return k.tocsr()

    def solve(self, fixed: np.ndarray, force: np.ndarray, tol: float = 1e-8) -> tuple[np.ndarray, dict]:
        """Displacements (nn, 3) for fixed node ids (all three directions held) and a force array (nn, 3) in N."""
        import pyamg

        t0 = time.time()
        k = self.matrix()
        t1 = time.time()
        nn = len(self.nodes)
        hold = np.zeros(3 * nn, dtype=bool)
        hold[(3 * np.asarray(fixed)[:, None] + np.arange(3)).ravel()] = True
        free = np.nonzero(~hold)[0]
        kff = k[free][:, free].tocsr()
        f = force.ravel()[free]
        x = self.coords - self.coords.mean(0)
        rbm = np.zeros((3 * nn, 6))
        for i in range(3):
            rbm[i::3, i] = 1
        rbm[0::3, 3], rbm[1::3, 3] = -x[:, 1], x[:, 0]
        rbm[1::3, 4], rbm[2::3, 4] = -x[:, 2], x[:, 1]
        rbm[0::3, 5], rbm[2::3, 5] = x[:, 2], -x[:, 0]
        ml = pyamg.smoothed_aggregation_solver(kff, B=rbm[free], max_coarse=500)
        t2 = time.time()
        res: list[float] = []
        uf = ml.solve(f, tol=tol, accel="cg", maxiter=400, residuals=res)
        t3 = time.time()
        u = np.zeros(3 * nn)
        u[free] = uf
        info = {"dofs": int(len(free)), "iterations": len(res) - 1, "residual": float(res[-1] / max(res[0], 1e-30)),
                "assemble_s": round(t1 - t0, 2), "setup_s": round(t2 - t1, 2), "solve_s": round(t3 - t2, 2)}
        return u.reshape(nn, 3), info

    def stress(self, u: np.ndarray) -> np.ndarray:
        """Stress (ne, 6) in solid printed plastic at each cell center, MPa: C times the cell's strain. A wall
        line carries this; infill carries weight times it, spread over the cell."""
        cb = self.c @ _bmatrix(0, 0, 0, self.grid.pitch)  # 6 x 24
        ue = u[self.elem].reshape(len(self.elem), 24)
        return ue @ cb.T


def von_mises(s: np.ndarray) -> np.ndarray:
    xx, yy, zz, yz, xz, xy = s.T
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3 * (yz ** 2 + xz ** 2 + xy ** 2))
