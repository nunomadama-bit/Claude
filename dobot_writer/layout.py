"""Converte texto em traços (em mm) e coloca-os no espaço de trabalho do robô."""

import math

from .font import CAP_HEIGHT, glyph

LETTER_GAP = 1.5      # espaço entre letras, em unidades da fonte
LINE_PITCH = 10.0     # distância entre linhas, em unidades da fonte

# Alcance aproximado do Dobot Magician no plano XY (raio a partir da base).
REACH_MIN_MM = 150.0
REACH_MAX_MM = 315.0


def text_to_strokes(text, height_mm):
    """Traços em coordenadas de "papel" (mm), x para a direita, y para cima,
    centrados em (0, 0). `height_mm` é a altura de uma letra maiúscula."""
    scale = height_mm / CAP_HEIGHT
    strokes = []
    for line_no, line in enumerate(text.splitlines() or [""]):
        cursor = 0.0
        base_y = -line_no * LINE_PITCH
        for char in line:
            width, glyph_strokes = glyph(char)
            for stroke in glyph_strokes:
                strokes.append([((cursor + x) * scale, (base_y + y) * scale)
                                for x, y in stroke])
            cursor += width + LETTER_GAP
    return center(strokes)


def bounds(strokes):
    xs = [x for s in strokes for x, _ in s]
    ys = [y for s in strokes for _, y in s]
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def center(strokes):
    x0, y0, x1, y1 = bounds(strokes)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [[(x - cx, y - cy) for x, y in s] for s in strokes]


def to_robot(strokes, center_x, center_y, rotation_deg=0.0):
    """Coloca os traços no referencial do robô.

    Olhando para a mesa a partir de trás do robô, X do robô aponta para a
    frente e Y para a esquerda. O texto fica legível dessa posição: o "para
    cima" do texto é +X e o "para a direita" é -Y.
    """
    a = math.radians(rotation_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    placed = []
    for s in strokes:
        pts = []
        for px, py in s:
            rx, ry = px * cos_a - py * sin_a, px * sin_a + py * cos_a
            pts.append((center_x + ry, center_y - rx))
        placed.append(pts)
    return placed


def out_of_reach(robot_strokes):
    """Lista de pontos (x, y) fora do alcance aproximado do braço."""
    bad = []
    for s in robot_strokes:
        for x, y in s:
            r = math.hypot(x, y)
            if r < REACH_MIN_MM or r > REACH_MAX_MM:
                bad.append((x, y))
    return bad


def path_length(strokes):
    return sum(math.dist(a, b) for s in strokes for a, b in zip(s, s[1:]))


def to_svg(strokes, margin=5.0, stroke_width=0.5):
    """SVG simples para pré-visualizar o texto (coordenadas de papel)."""
    x0, y0, x1, y1 = bounds(strokes)
    w, h = x1 - x0 + 2 * margin, y1 - y0 + 2 * margin
    paths = []
    for s in strokes:
        pts = " ".join(f"{x - x0 + margin:.2f},{y1 - y + margin:.2f}" for x, y in s)
        paths.append(f'<polyline points="{pts}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}mm" '
        f'height="{h:.1f}mm" viewBox="0 0 {w:.2f} {h:.2f}">\n'
        f'<g fill="none" stroke="black" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n'
        + "\n".join(paths) + "\n</g>\n</svg>\n"
    )
