# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pure planar helpers: wall footprints, join solving, region detection.

Nothing here touches the scene — these are the maths the element builders and
the drawing generators share, testable on their own.

Two solvers live here:

* :func:`join_walls` — where a wall's two ends actually stop, given the other
  walls meeting there. At a corner the wall with the higher material priority
  runs through and the others trim to its face; equal priorities mitre (or
  square off when perpendicular and the corner is a right angle); three or
  more walls at a point leave the butt joint alone.
* :func:`detect_region` — the smallest closed loop around a picked point, from
  the storey's footprints. This is how a room (zone), a ceiling or a slab
  finds its boundary from the walls that already exist, which is what makes
  "pick a point and get the room" work.

Everything is millimetres in world XY.
"""
from __future__ import annotations

import math

#: Endpoints closer than this are the same point (mm).
TOL = 5.0
#: Cross products below this count as parallel/collinear.
PARALLEL_EPS = 1.0e-3
#: A mitre that would extend an end further than this × thickness is refused.
MAX_EXTEND_FACTOR = 10.0
#: |cos| below this counts as a right angle (square corner instead of mitre).
SQUARE_EPS = 0.02
#: Spatial-hash cell for join candidates (mm).
GRID_MM = 4000.0


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _norm(a):
    return math.hypot(a[0], a[1])


def _unit(a):
    n = _norm(a)
    return (0.0, 0.0) if n < 1e-12 else (a[0] / n, a[1] / n)


def area(points) -> float:
    """Signed planar area (positive when the loop runs counter-clockwise)."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def area_m2(points) -> float:
    """Absolute area in square metres."""
    return abs(area(points)) / 1.0e6


def point_in_polygon(point, polygon) -> bool:
    """Ray casting — inside test that works with either winding."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            t = (y - y0) / (y1 - y0) if y1 != y0 else 0.0
            if x < x0 + t * (x1 - x0):
                inside = not inside
    return inside


def clean_polygon(points, tol: float = 1.0) -> list:
    """Drop repeated points and collinear runs (a polygon the solvers trust)."""
    pts = []
    for p in points or ():
        x, y = float(p[0]), float(p[1])
        if not pts or _norm(_sub((x, y), pts[-1])) > tol:
            pts.append((x, y))
    while len(pts) > 1 and _norm(_sub(pts[0], pts[-1])) <= tol:
        pts.pop()
    out = []
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        if abs(_cross(_sub(b, a), _sub(c, b))) > tol * _norm(_sub(c, b)):
            out.append(b)
    return out if len(out) >= 3 else pts


# ---- wall footprints --------------------------------------------------------

def wall_footprint(p0, p1, lo: float, hi: float, start=None, end=None):
    """The 4-corner plan polygon of a wall.

    ``lo``/``hi`` are the signed offsets from the baseline to the two faces
    (along the left normal of ``p0 -> p1``); ``start``/``end`` are ``(u_lo,
    u_hi)`` pairs along the baseline when joins trimmed the ends — without
    them the polygon runs the whole length.
    """
    length = _norm(_sub(p1, p0))
    d = _unit(_sub(p1, p0))
    st = start or (0.0, 0.0)
    en = end or (length, length)
    # Walk the quad: along the lo face from the start end to the end one,
    # then back along the hi face. ``st``/``en`` are (lo_face_u, hi_face_u)
    # at that end — equal unless a mitre swung the two faces apart.
    return [
        _along(p0, d, st[0], lo),          # start, lo face
        _along(p0, d, en[0], lo),          # end,   lo face
        _along(p0, d, en[1], hi),          # end,   hi face
        _along(p0, d, st[1], hi),          # start, hi face
    ]


def _along(p0, d, u: float, off: float):
    """A point ``u`` along the baseline and ``off`` across it (left normal)."""
    nx, ny = -d[1], d[0]
    return (p0[0] + d[0] * u + nx * off, p0[1] + d[1] * u + ny * off)


def wall_frame(p0, p1):
    """``(origin, dir, perp, length)`` of a baseline (dir unit, perp = left)."""
    length = _norm(_sub(p1, p0))
    d = _unit(_sub(p1, p0))
    return (p0, d, (-d[1], d[0]), length)


def side_offsets(params) -> tuple:
    """Signed offsets from the reference line to (near, far) face."""
    t = float(params.get("thickness_mm", 200.0))
    ref = params.get("reference_line", "center")
    if ref == "left":
        near = -t
    elif ref == "right":
        near = 0.0
    else:
        near = -t / 2.0
    if params.get("flip_side"):
        # Mirror the body about the reference line: the wall that stood to
        # the line's left now stands to its right. Swapping the two ends
        # (what this used to do) leaves the same interval — the same body
        # — so the switch did nothing on any wall.
        return (-(near + t), -near)
    return (near, near + t)


def inset_footprint(footprint, amount: float):
    """Shrink a convex footprint by ``amount`` toward its centroid."""
    if amount <= 0:
        return list(footprint)
    cx = sum(p[0] for p in footprint) / len(footprint)
    cy = sum(p[1] for p in footprint) / len(footprint)
    out = []
    for x, y in footprint:
        dx, dy = x - cx, y - cy
        n = math.hypot(dx, dy)
        if n < 1e-9:
            out.append((x, y))
            continue
        k = max((n - amount) / n, 0.05)
        out.append((cx + dx * k, cy + dy * k))
    return out


# ---- wall joins -------------------------------------------------------------

def join_input(wall_id, params, baseline, story_z: float, height_mm: float):
    """One wall as the solver wants it: ends, face offsets, priority, Z range."""
    p0, p1 = baseline
    # Signed, in the wall's own (near, far) order: the solver compares each
    # face's line against its neighbour's, and collapsing the pair with
    # min/max makes a face-referenced wall lose which side it stands on.
    lo, hi = side_offsets(params)
    base = float(story_z) + float(params.get("base_offset_mm", 0.0))
    from core.building import elements as schemas
    return {
        "id": wall_id, "p0": (float(p0[0]), float(p0[1])),
        "p1": (float(p1[0]), float(p1[1])), "lo": lo, "hi": hi,
        "priority": schemas.priority_of(params),
        "z0": base, "z1": base + float(height_mm),
    }


def join_walls(inputs) -> dict:
    """Solve every wall end — ``{wall_id: {"start": (a,b), "end": (a,b),
    "joined": [ids]}}``.

    ``(a, b)`` are the along-baseline positions where each face stops at that
    end; an untouched end is ``(0, 0)`` at the start and ``(L, L)`` at the end,
    so the builder always has a value to use.
    """
    walls = {}
    for w in inputs or ():
        length = _norm(_sub(w["p1"], w["p0"]))
        if length < 10.0:
            continue
        d = _unit(_sub(w["p1"], w["p0"]))
        walls[w["id"]] = {
            "w": w, "len": length, "dir": d,
            "n": (-d[1], d[0]),
            "default": {"start": (0.0, 0.0), "end": (length, length),
                        "joined": []},
        }
    result = {wid: {"start": (0.0, 0.0), "end": (v["len"], v["len"]),
                    "joined": []} for wid, v in walls.items()}
    if not walls:
        return result

    index = _spatial_index(walls)
    for wid, entry in walls.items():
        for at_end in (False, True):
            point = entry["w"]["p1"] if at_end else entry["w"]["p0"]
            partners, hosts = _candidates(entry, at_end, point, walls, index)
            end = _resolve_end(entry, at_end, partners, hosts)
            if end is None:
                continue
            key = "end" if at_end else "start"
            result[wid][key] = end
            for other in partners:
                other_id = other["id"]
                if other_id not in result[wid]["joined"]:
                    result[wid]["joined"].append(other_id)
                if wid not in result[other_id]["joined"]:
                    result[other_id]["joined"].append(wid)
    return result


def _spatial_index(walls):
    """``{(cell_x, cell_y): [wall_id, ...]}`` for candidate lookup."""
    index: dict = {}
    for wid, entry in walls.items():
        w = entry["w"]
        cells = {_cell(w["p0"]), _cell(w["p1"])}
        # Long walls cross cells: sample along the segment.
        length = entry["len"]
        steps = int(length // GRID_MM) + 1
        if steps > 256:                    # pathological: keep ends only
            steps = 2
        for i in range(steps + 1):
            t = i / steps if steps else 0.0
            x = w["p0"][0] + (w["p1"][0] - w["p0"][0]) * t
            y = w["p0"][1] + (w["p1"][1] - w["p0"][1]) * t
            cells.add(_cell((x, y)))
        for cell in cells:
            index.setdefault(cell, []).append(wid)
    return index


def _cell(point):
    return (int(math.floor(point[0] / GRID_MM)),
            int(math.floor(point[1] / GRID_MM)))


def _candidates(entry, at_end, point, walls, index):
    """Walls meeting ``point``: ``(L partners, T hosts)``.

    An **L partner** shares the endpoint. A **T host** runs past the point with
    this wall's end somewhere inside its span (the T-junction case).
    """
    near_ids = set()
    cx, cy = _cell(point)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            near_ids.update(index.get((cx + dx, cy + dy), ()))
    partners, hosts = [], []
    me = entry["w"]
    for wid in near_ids:
        if wid == me["id"]:
            continue
        other = walls[wid]
        # Z overlap: walls on different storeys never join.
        if (other["w"]["z0"] >= me["z1"] - 1e-6
                or other["w"]["z1"] <= me["z0"] + 1e-6):
            continue
        b = other["w"]
        at_b_end = None
        if _norm(_sub(point, b["p0"])) <= TOL:
            at_b_end = False
        elif _norm(_sub(point, b["p1"])) <= TOL:
            at_b_end = True
        if at_b_end is not None:
            partners.append({"id": wid, "at_end": at_b_end, "entry": other})
            continue
        rel = _sub(point, b["p0"])
        t_along = _dot(rel, other["dir"])
        s_across = _dot(rel, other["n"])
        if (TOL < t_along < other["len"] - TOL
                and b["lo"] - TOL <= s_across <= b["hi"] + TOL
                and abs(_cross(entry["dir"], other["dir"])) > PARALLEL_EPS):
            hosts.append({"id": wid, "entry": other})
    return partners, hosts


def _resolve_end(entry, at_end, partners, hosts):
    """The ``(u_lo, u_hi)`` pair where this end stops, or ``None`` untouched."""
    if not partners and not hosts:
        return None
    own = entry
    if hosts:
        # Trim to the face of the highest-priority host (concrete cuts masonry).
        host = max(hosts, key=lambda h: h["entry"]["w"]["priority"])
        return _trim_to_face(own, at_end, host["entry"])
    if len(partners) == 1:
        other = partners[0]["entry"]
        if abs(_cross(own["dir"], other["dir"])) <= PARALLEL_EPS:
            return None                    # collinear: the square butt fits
        if own["w"]["priority"] == other["w"]["priority"]:
            if abs(_dot(own["dir"], other["dir"])) <= SQUARE_EPS:
                # Perpendicular, same priority: square corner, not a mitre.
                if _runs_through(own, other):
                    return _extend_through(own, at_end, other)
                return _trim_to_face(own, at_end, other)
            return _miter(own, at_end, other)
        if own["w"]["priority"] > other["w"]["priority"]:
            return _extend_through(own, at_end, other)
        return _trim_to_face(own, at_end, other)
    # Three or more walls at one point: leave the butt joint alone unless a
    # collinear pair of the others says who owns the corner.
    if any(abs(_cross(own["dir"], p["entry"]["dir"])) <= PARALLEL_EPS
           for p in partners):
        return None
    pair = None
    for i in range(len(partners)):
        for j in range(i + 1, len(partners)):
            a, b = partners[i]["entry"], partners[j]["entry"]
            if abs(_cross(a["dir"], b["dir"])) <= PARALLEL_EPS:
                pair = (a, b)
                break
        if pair:
            break
    if pair is None:
        return None
    other = max(pair, key=lambda e: e["w"]["priority"])
    if other["w"]["priority"] >= own["w"]["priority"]:
        return _trim_to_face(own, at_end, other)
    return None


def _runs_through(own, other) -> bool:
    """The longer wall keeps the corner (tie: smaller id), deterministically."""
    if abs(own["len"] - other["len"]) > TOL:
        return own["len"] > other["len"]
    return str(own["w"]["id"]) < str(other["w"]["id"])


def _body_dir(entry, at_end):
    """Unit direction in which the wall's body leaves this end."""
    d = entry["dir"]
    return (-d[0], -d[1]) if at_end else d


def _face_line_point(entry, off):
    """A point on the wall's face at signed offset ``off``."""
    p0 = entry["w"]["p0"]
    n = entry["n"]
    return (p0[0] + n[0] * off, p0[1] + n[1] * off)


def _line_param(own, own_off, point, line_dir):
    """Where own's face at ``own_off`` crosses the line (point, line_dir).

    Returns the parameter along own's baseline (0 at ``p0``, positive toward
    ``p1``), or ``None`` when the lines are parallel.
    """
    me = own["w"]
    fd, fn = own["dir"], own["n"]
    px = me["p0"][0] + fn[0] * own_off
    py = me["p0"][1] + fn[1] * own_off
    det = fd[0] * (-line_dir[1]) - fd[1] * (-line_dir[0])
    if abs(det) < 1e-9:
        return None
    rx, ry = point[0] - px, point[1] - py
    return (rx * (-line_dir[1]) - ry * (-line_dir[0])) / det


def _crossings(own, other):
    """Where the other wall's two faces cross own's centreline, sorted."""
    out = []
    for off in (other["w"]["lo"], other["w"]["hi"]):
        u = _line_param(own, 0.0, _face_line_point(other, off), other["dir"])
        if u is not None:
            out.append(u)
    return sorted(out)


def _chosen_face(own, at_end, other, through: bool):
    """The face offset of ``other`` this wall's end should stop at."""
    cross = _crossings(own, other)
    if not cross:
        return other["w"]["lo"]
    length = own["len"]
    if through:
        beyond = ([u for u in cross if u > length + TOL] if at_end
                  else [u for u in cross if u < -TOL])
        if beyond:
            target = max(beyond) if at_end else min(beyond)
            return min((other["w"]["lo"], other["w"]["hi"]),
                       key=lambda off: abs(
                           (_line_param(own, 0.0,
                                        _face_line_point(other, off),
                                        other["dir"]) or 0.0) - target))
        return other["w"]["lo"]
    inside = [u for u in cross if -TOL <= u <= length + TOL]
    if inside:
        target = max(inside) if at_end else min(inside)
    else:
        edge = length if at_end else 0.0
        target = min(cross, key=lambda u: abs(u - edge))
    return min((other["w"]["lo"], other["w"]["hi"]),
               key=lambda off: abs(
                   (_line_param(own, 0.0, _face_line_point(other, off),
                                other["dir"]) or 0.0) - target))


def _stop_faces(own, other, other_off):
    """``(u_lo, u_hi)`` where own's two faces meet the other's face line."""
    lo, hi = own["w"]["lo"], own["w"]["hi"]
    point = _face_line_point(other, other_off)
    u_a = _line_param(own, lo, point, other["dir"])
    u_b = _line_param(own, hi, point, other["dir"])
    if u_a is None or u_b is None:
        return None
    thickness = abs(hi - lo)
    limit = MAX_EXTEND_FACTOR * max(thickness, 1.0) + TOL
    if max(abs(u_a), abs(u_b)) > own["len"] + limit:
        return None
    # Face ORDER, not sorted: the caller reads this pair back by face
    # (``_wall_ends`` maps [0] to the near face and [1] to the far one),
    # and a min/max here silently swaps them at any mitre that extends one
    # face past the other — the joint would be built mirrored.
    return (u_a, u_b)


def _trim_to_face(own, at_end, other):
    """Stop this wall where it first reaches the other one."""
    off = _chosen_face(own, at_end, other, through=False)
    return _stop_faces(own, other, off)


def _extend_through(own, at_end, other):
    """Run this wall past the other, to its farthest face."""
    off = _chosen_face(own, at_end, other, through=True)
    return _stop_faces(own, other, off)


def _miter(own, at_end, other):
    """Mitre two equal-priority walls along the bisector of their corner.

    The mitre line runs through the shared point bisecting the angle between
    the two bodies; each of this wall's faces stops where it meets it. Simple,
    symmetric, and correct for any angle — a right angle never gets here (the
    square-corner rule takes it).
    """
    point = own["w"]["p1"] if at_end else own["w"]["p0"]
    at_b_end = None
    if _norm(_sub(point, other["w"]["p1"])) <= TOL:
        at_b_end = True
    elif _norm(_sub(point, other["w"]["p0"])) <= TOL:
        at_b_end = False
    if at_b_end is None:
        return None
    body_a = _body_dir(own, at_end)
    body_b = _body_dir(other, at_b_end)
    bx, by = body_a[0] + body_b[0], body_a[1] + body_b[1]
    if math.hypot(bx, by) < 1e-9:
        return None
    line_dir = _unit((bx, by))
    u_a = _line_param(own, own["w"]["lo"], point, line_dir)
    u_b = _line_param(own, own["w"]["hi"], point, line_dir)
    if u_a is None or u_b is None:
        return None
    return (u_a, u_b)                 # face order — see _stop_faces


# ---- region detection -------------------------------------------------------
# The smallest closed loop around a picked point: this is how a room (zone), a
# ceiling or a slab finds its boundary from the walls that are already there —
# "pick a point inside a room and get the room".

def detect_region(footprints, pick):
    """The smallest closed region containing ``pick``.

    ``footprints`` is a list of closed polygons (wall footprints, column
    sections). Returns ``{"outer": [(x, y)…], "holes": [[…], …]}`` in world
    millimetres, or ``None`` when the pick is inside a solid or nothing
    encloses it.

    The walls are *barriers*: a pick inside one is not a room. The loop is
    found by walking the planar arrangement the polygons cut the plane into —
    implemented here as a flood search over the arrangement's faces, which
    stays exact for the T-junctions and shared corners real walls produce.
    """
    x, y = float(pick[0]), float(pick[1])
    cleaned = [clean_polygon(p, tol=1.0) for p in footprints or ()]
    cleaned = [p for p in cleaned if len(p) >= 3 and abs(area(p)) > 1.0]
    if not cleaned:
        return None
    for poly in cleaned:
        if point_in_polygon((x, y), poly):
            return None                     # inside a wall: not a room

    faces = _planar_faces(cleaned)
    if not faces:
        return None
    containing = []
    for face in faces:
        if face["holes"]:
            if point_in_polygon((x, y), face["outer"]) and not any(
                    point_in_polygon((x, y), h) for h in face["holes"]):
                containing.append(face)
        elif point_in_polygon((x, y), face["outer"]):
            containing.append(face)
    if not containing:
        return None
    best = min(containing, key=lambda f: abs(area(f["outer"])))
    if abs(area(best["outer"])) < 1.0e5:      # under 0.1 m²: noise
        return None
    return {"outer": list(best["outer"]), "holes": [list(h) for h in best["holes"]]}


def _planar_faces(polygons):
    """Every bounded region the polygons cut the plane into.

    The standard planar-arrangement face extraction: split every edge at each
    crossing first (exact at T-junctions and shared corners), then trace the
    half-edge cycles. A region bounded by more than one outline (a room with a
    free-standing column in it) comes back as a counter-clockwise cycle plus
    the clockwise cycles of the outlines it wraps — the two halves of the same
    face.
    """
    edges, _nodes = _split_edges(polygons)
    if not edges:
        return []
    out: dict = {}
    for a, b in edges:
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)
    for node, nbrs in out.items():
        nbrs.sort(key=lambda q: math.atan2(q[1] - node[1],
                                           q[0] - node[0]))

    def following(he):
        """The next half-edge: most clockwise from the way we came."""
        a, b = he
        nbrs = out.get(b) or ()
        if len(nbrs) < 2 or a not in nbrs:
            return None
        idx = nbrs.index(a)
        nxt = nbrs[(idx - 1) % len(nbrs)]
        return (b, nxt)

    visited: set = set()
    cycles = []
    for he in list(_all_half_edges(edges)):
        if he in visited:
            continue
        cycle = []
        cur = he
        while cur is not None and cur not in visited:
            visited.add(cur)
            cycle.append(cur[0])
            cur = following(cur)
            if cur == he:
                break
        loop = _dedupe_loop(cycle)
        if len(loop) >= 3:
            cycles.append(loop)

    outer_regions = [c for c in cycles if area(c) > 1.0]
    inner_loops = [c for c in cycles if area(c) < -1.0]
    faces = []
    for ring in outer_regions:
        holes = []
        for hole in inner_loops:
            if abs(area(hole)) < abs(area(ring)) and point_in_polygon(
                    hole[0], ring) and not any(
                    point_in_polygon(hole[0], h) for h in holes):
                holes.append(hole)
        faces.append({"outer": ring, "holes": holes})
    return faces


def _all_half_edges(edges):
    for a, b in edges:
        yield (a, b)
        yield (b, a)


def _split_edges(polygons):
    """Every polygon edge split at its crossings; returns ``(edges, nodes)``."""
    raw = []
    for poly in polygons:
        n = len(poly)
        for i in range(n):
            raw.append((tuple(poly[i]), tuple(poly[(i + 1) % n])))
    nodes = {}
    for a, b in raw:
        for p in (a, b):
            nodes.setdefault(_snap_key(p), (float(p[0]), float(p[1])))
    for a, b in raw:
        for c, d in raw:
            hit = _segment_intersection(a, b, c, d)
            if hit is not None:
                nodes.setdefault(_snap_key(hit), (float(hit[0]),
                                                  float(hit[1])))
    edges = set()
    for a, b in raw:
        a2 = nodes.get(_snap_key(a))
        b2 = nodes.get(_snap_key(b))
        if a2 is None or b2 is None or a2 == b2:
            continue
        between = [p for key, p in nodes.items()
                   if p != a2 and p != b2 and _on_segment(p, a2, b2)]
        chain = [a2] + sorted(between, key=lambda p: _dist(a2, p)) + [b2]
        for i in range(len(chain) - 1):
            edges.add((chain[i], chain[i + 1]))
    return edges, nodes


def _snap_key(point):
    return (round(float(point[0]), 3), round(float(point[1]), 3))


def _dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _on_segment(p, a, b, eps: float = 1e-6):
    if abs(_cross(_sub(b, a), _sub(p, a))) > eps * max(_dist(a, b), 1.0):
        return False
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
            and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def _segment_intersection(a, b, c, d):
    """The crossing point of two segments, or ``None`` (parallel/collinear)."""
    r = _sub(b, a)
    s = _sub(d, c)
    denom = _cross(r, s)
    if abs(denom) < 1e-9:
        return None
    t = _cross(_sub(c, a), s) / denom
    u = _cross(_sub(c, a), r) / denom
    if not (-1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9):
        return None
    return (a[0] + r[0] * t, a[1] + r[1] * t)


def _dedupe_loop(cycle):
    """A cycle without consecutive repeats, and without a repeated close."""
    out = []
    for p in cycle:
        if not out or p != out[-1]:
            out.append(p)
    while len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out
