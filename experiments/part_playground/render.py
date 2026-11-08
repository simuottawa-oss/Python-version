"""Small perspective software renderer, shared by Tk and SVG output. No GPU required."""
from html import escape
import math
from pathlib import Path


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def subtract(a, b):
    return tuple(x-y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def unit(a):
    length = math.sqrt(dot(a, a))
    return tuple(x/length for x in a)


class Camera:
    def __init__(self, part):
        self.target = (part.position[0], max(part.size[1]/2, part.position[1]/2), part.position[2])
        self.distance = max(1.5, max(part.size)*5, part.position[1]*2.2)
        self.yaw = 0.65
        self.pitch = 0.33

    def prepare(self, width, height):
        cp = math.cos(self.pitch)
        offset = (self.distance * cp * math.sin(self.yaw),
                  self.distance * math.sin(self.pitch),
                  self.distance * cp * math.cos(self.yaw))
        eye = tuple(a+b for a, b in zip(self.target, offset))
        forward = unit(subtract(self.target, eye))
        right = unit(cross(forward, (0, 1, 0)))
        up = cross(right, forward)
        focal = min(width, height) * 1.05

        def project(point):
            delta = subtract(point, eye)
            depth = dot(delta, forward)
            if depth <= 0.02:
                return None
            return (width/2 + focal*dot(delta, right)/depth,
                    height/2 - focal*dot(delta, up)/depth, depth)

        return project


def scene(part, simulation, camera, width=1000, height=700):
    """Produce backend-independent draw commands; faces sorted far to near."""
    project = camera.prepare(width, height)
    commands = []
    # Grid is a visual reference on the y=0 collision plane. Grid spacing is 0.2m.
    cx, _, cz = part.position
    spacing = max(0.2, max(part.size))
    extent = 8 * spacing
    for n in range(-8, 9):
        offset = n * spacing
        for start, end in [((cx-extent, 0, cz+offset), (cx+extent, 0, cz+offset)),
                           ((cx+offset, 0, cz-extent), (cx+offset, 0, cz+extent))]:
            a, b = project(start), project(end)
            if a and b:
                commands.append(("line", [*a[:2], *b[:2]], "#444444", 1))
    # Vertical line marks release height.
    a, b = project((cx, 0, cz)), project(part.position)
    if a and b:
        commands.append(("line", [*a[:2], *b[:2]], "#777777", 1))
    vertices = part.vertices(simulation.position)
    # CCW winding seen from outside: -Z, +Z, -X, +X, -Y, +Y.
    faces = [(0,3,2,1), (4,5,6,7), (0,4,7,3), (1,2,6,5), (0,1,5,4), (3,7,6,2)]
    light = unit((-0.4, 0.8, 0.6))
    rgb = [int(part.color[i:i+2], 16) for i in (1,3,5)]
    polygons = []
    for face in faces:
        points = [project(vertices[i]) for i in face]
        if any(p is None for p in points):
            continue
        normal = unit(cross(subtract(vertices[face[1]], vertices[face[0]]),
                            subtract(vertices[face[2]], vertices[face[0]])))
        brightness = 0.35 + 0.65*max(0, dot(normal, light))
        color = "#" + "".join(f"{round(c*brightness):02x}" for c in rgb)
        polygons.append((sum(p[2] for p in points)/4,
                         ("polygon", [c for p in points for c in p[:2]], color, "#a7e2ec")))
    commands.extend(command for _, command in sorted(polygons, key=lambda x: -x[0]))
    return commands


def write_svg(path, part, simulation, camera, width=1000, height=700):
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#2e2e33"/>']
    for kind, coords, fill, extra in scene(part, simulation, camera, width, height):
        if kind == "line":
            x1, y1, x2, y2 = coords
            lines.append(f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" stroke="{fill}" stroke-width="{extra}"/>')
        else:
            points = " ".join(f"{coords[i]:.3f},{coords[i+1]:.3f}" for i in range(0,len(coords),2))
            lines.append(f'<polygon points="{points}" fill="{fill}" stroke="{extra}" stroke-width="1"/>')
    label = escape(f"{part.name} | {part.mass:.4g} kg | t={simulation.time:.3f} s | y={simulation.position[1]:.3f} m")
    lines.extend([f'<text x="24" y="36" fill="#eeeeee" font-family="sans-serif" font-size="20">{label}</text>',
                  '<text x="24" y="64" fill="#aaaaaa" font-family="sans-serif" font-size="14">SimuO part · perspective view · grid on floor y=0</text>', '</svg>'])
    Path(path).write_text("\n".join(lines), encoding="utf-8")
